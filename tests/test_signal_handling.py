# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_signal_handling.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Signal-handling architecture tests (Issue #6).

Covers:
A. Pure helper tests (returncode_to_exit_status, keyboard_interrupt_status,
   signal_name, is_signal_returncode).
B. External command signal mapping via deterministic local subprocesses.
C. Shell integration: signal mapping sets last_status correctly.
D. Python runtime: KeyboardInterrupt in py-builtin code maps to 130.
E. Secure runner: existing terminal restoration tests still pass (covered
   by test_secure_runner.py); this file adds only the signal-status helper check.

Line editor Ctrl+C:
  The reader raises KeyboardInterrupt when Ctrl+C is pressed (Key.CTRL_C in
  reader._handle_event).  The finally block in read_line restores terminal
  state.  Full PTY validation is manual (see docs/architecture/signal-handling.md).
"""
from __future__ import annotations

import signal
import subprocess
import sys

from pysh.core.signals import (
    is_signal_returncode,
    keyboard_interrupt_status,
    returncode_to_exit_status,
    signal_name,
)

# ---------------------------------------------------------------------------
# A. Pure helper unit tests
# ---------------------------------------------------------------------------


class TestReturnCodeToExitStatus:
    def test_zero(self) -> None:
        assert returncode_to_exit_status(0) == 0

    def test_positive_7(self) -> None:
        assert returncode_to_exit_status(7) == 7

    def test_positive_1(self) -> None:
        assert returncode_to_exit_status(1) == 1

    def test_positive_127(self) -> None:
        assert returncode_to_exit_status(127) == 127

    def test_sigint(self) -> None:
        assert returncode_to_exit_status(-signal.SIGINT) == 130

    def test_sigterm(self) -> None:
        assert returncode_to_exit_status(-signal.SIGTERM) == 143

    def test_arbitrary_negative(self) -> None:
        # -9 (SIGKILL) → 137
        assert returncode_to_exit_status(-9) == 137


class TestKeyboardInterruptStatus:
    def test_value(self) -> None:
        assert keyboard_interrupt_status() == 130

    def test_matches_sigint_formula(self) -> None:
        assert keyboard_interrupt_status() == 128 + signal.SIGINT


class TestSignalName:
    def test_sigint_name(self) -> None:
        assert signal_name(signal.SIGINT) == "SIGINT"

    def test_sigterm_name(self) -> None:
        assert signal_name(signal.SIGTERM) == "SIGTERM"

    def test_deterministic_repeated_call(self) -> None:
        assert signal_name(signal.SIGINT) == signal_name(signal.SIGINT)

    def test_unknown_signum_fallback(self) -> None:
        # Signal 99 is not defined on Linux; fallback must be deterministic.
        name = signal_name(99)
        assert "99" in name


class TestIsSignalReturncode:
    def test_zero_not_signal(self) -> None:
        assert not is_signal_returncode(0)

    def test_positive_not_signal(self) -> None:
        assert not is_signal_returncode(1)
        assert not is_signal_returncode(127)

    def test_negative_is_signal(self) -> None:
        assert is_signal_returncode(-signal.SIGINT)
        assert is_signal_returncode(-signal.SIGTERM)
        assert is_signal_returncode(-9)


# ---------------------------------------------------------------------------
# B. External command signal mapping
# ---------------------------------------------------------------------------


class TestExternalCommandSignalMapping:
    """Subprocess is killed by a signal; returncode_to_exit_status maps correctly."""

    def test_child_killed_by_sigint(self) -> None:
        """Process that kills itself with SIGINT produces exit status 130."""
        proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-c",
                "import signal, os; os.kill(os.getpid(), signal.SIGINT)",
            ],
        )
        rc = proc.wait()
        assert returncode_to_exit_status(rc) == 130

    def test_child_killed_by_sigterm(self) -> None:
        """Process that kills itself with SIGTERM produces exit status 143."""
        proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-c",
                "import signal, os; os.kill(os.getpid(), signal.SIGTERM)",
            ],
        )
        rc = proc.wait()
        assert returncode_to_exit_status(rc) == 143

    def test_child_normal_exit_code_passes_through(self) -> None:
        """Normal exit code is not affected by returncode_to_exit_status."""
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", "raise SystemExit(42)"],
        )
        rc = proc.wait()
        assert returncode_to_exit_status(rc) == 42


# ---------------------------------------------------------------------------
# C. Shell integration: signal-mapped returncode sets last_status
# ---------------------------------------------------------------------------


class TestShellSignalIntegration:
    """Shell._run_external applies returncode_to_exit_status to child exit codes."""

    def test_normal_exit_zero(self) -> None:
        from pysh.core.shell import PyShell

        shell = PyShell()
        status = shell.execute(f"{sys.executable} -c 'raise SystemExit(0)'")
        assert status == 0

    def test_normal_exit_7(self) -> None:
        from pysh.core.shell import PyShell

        shell = PyShell()
        status = shell.execute(f"{sys.executable} -c 'raise SystemExit(7)'")
        assert status == 7

    def test_signal_killed_child_maps_to_128_plus_signum(self) -> None:
        """Child killed by SIGTERM: shell maps to 143 (128 + 15)."""
        from pysh.core.shell import PyShell

        shell = PyShell()
        status = shell.execute(
            f"{sys.executable} -c "
            f"'import signal, os; os.kill(os.getpid(), signal.SIGTERM)'"
        )
        assert status == 143

    def test_last_status_after_signal_killed(self) -> None:
        """$? after signal-terminated command reflects 128 + signum."""
        from pysh.core.shell import PyShell

        shell = PyShell()
        shell.execute(
            f"{sys.executable} -c "
            f"'import signal, os; os.kill(os.getpid(), signal.SIGTERM)'"
        )
        assert shell.last_status == 143


# ---------------------------------------------------------------------------
# D. Python runtime: KeyboardInterrupt → 130
# ---------------------------------------------------------------------------


class TestPythonRuntimeKeyboardInterrupt:
    """KeyboardInterrupt in py-builtin execution maps deterministically to 130."""

    def test_raise_keyboard_interrupt_returns_130(self) -> None:
        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("raise KeyboardInterrupt()")
        assert status == 130

    def test_shell_py_builtin_keyboard_interrupt(self) -> None:
        """py <code> that raises KeyboardInterrupt sets last_status to 130."""
        from pysh.core.shell import PyShell

        shell = PyShell()
        status = shell.execute("py raise KeyboardInterrupt()")
        assert status == 130

    def test_normal_python_exception_still_returns_1(self) -> None:
        """Ordinary Python exceptions still return exit status 1."""
        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("raise ValueError('boom')")
        assert status == 1


# ---------------------------------------------------------------------------
# E. Secure runner: _status_to_returncode consistency with returncode_to_exit_status
# ---------------------------------------------------------------------------


class TestSecureRunnerStatusConsistency:
    """_status_to_returncode (waitpid raw) and returncode_to_exit_status are consistent."""

    def test_secure_runner_exited_normally(self) -> None:
        """SecureRunner._status_to_returncode returns the child exit code on normal exit."""
        import os

        from pysh.security.secure_runner import SecureRunner

        # Simulate os.waitpid raw status for normal exit(0): os.W_OK=0
        # Use os.waitpid on a real child to get a real raw status value.
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        _, raw_status = os.waitpid(pid, 0)
        result = SecureRunner._status_to_returncode(raw_status)
        assert result == 0

    def test_secure_runner_signal_termination(self) -> None:
        """SecureRunner._status_to_returncode maps signal-terminated child to 128+signum."""
        import os

        from pysh.security.secure_runner import SecureRunner

        # Fork a child that kills itself with SIGTERM.
        pid = os.fork()
        if pid == 0:
            os.kill(os.getpid(), signal.SIGTERM)
            os._exit(0)  # should not reach here
        _, raw_status = os.waitpid(pid, 0)
        result = SecureRunner._status_to_returncode(raw_status)
        assert result == 143  # 128 + 15
