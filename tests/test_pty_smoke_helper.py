# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_pty_smoke_helper.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the shared, strictly-bounded, readiness-gated PTY
smoke helper (Issue #33 PTY portability + ready-handshake fix).

``scripts/pty_smoke.py`` replaces three copy-pasted, per-package
``run_pty_command()`` implementations (Debian, RPM, FreeBSD) that shared two
latent bugs:

1. Their read loop checked a ``time.monotonic()`` deadline only *between*
   calls to a blocking ``os.read()`` -- a single call that never returns
   (because the child produces no output and never exits) could hang the
   whole function indefinitely. A real FreeBSD ``workflow_dispatch`` run hit
   exactly this and hung for over an hour before being manually canceled.

2. They wrote the command line to the PTY immediately after ``Popen()``,
   racing PySH's raw line editor's ``tty.setraw(in_fd)`` call -- whose
   default ``TCSAFLUSH`` action discards already-queued input. A real
   FreeBSD run (after fix 1) exposed this: the full interactive banner and
   an empty prompt were captured, but the queued "exit" was never acted on.
   The fix withholds input until PySH's bracketed-paste-enable sequence
   (``\\x1b[?2004h``, emitted only *after* ``setraw()`` has already run) is
   observed on the PTY.

Implementing fix 2 surfaced a third, real discovery while validating it
against a real Debian container: ``docker run -i`` (no ``-t``) leaves
``$TERM`` unset in the child's environment. With ``$TERM`` unset or
``"dumb"``, ``PyShell._should_use_raw_editor()`` (via
``_raw_editor_terminal_capable()``) selects PySH's plain ``input()``
fallback instead of ``RawLineReader`` -- an entirely different code path
that never enters ``read_line()`` and therefore never calls
``_enable_bracketed_paste()`` at all, regardless of any color setting. A
real terminal session always has a real, non-``"dumb"`` ``$TERM``; an
unset one is an artifact of the container invocation, not something a
real user would ever present. The fix sets ``TERM=xterm-256color`` by
default (overridable via the new ``env`` parameter) so the raw editor
path -- and with it, the marker this fix depends on -- is actually
exercised, rather than inheriting whatever the parent shell happens to
have.

These tests exercise the shared helper directly (never via string/grep
inspection for the timeout or ordering behavior itself) using genuinely
non-exiting or deliberately-delayed child processes, and separately confirm
each of the three package smoke scripts was rewired to call the one shared,
readiness-gated implementation rather than carrying its own copy or sending
input unconditionally.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "pty_smoke.py"
DEBIAN_SCRIPT = REPO_ROOT / "scripts" / "smoke_debian_package.sh"
RPM_SCRIPT = REPO_ROOT / "scripts" / "smoke_rpm_package.sh"
FREEBSD_SCRIPT = REPO_ROOT / "scripts" / "smoke_freebsd_package.sh"


def _load_module():
    spec = importlib.util.spec_from_file_location("pty_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # pty_smoke.py combines `from __future__ import annotations` with
    # @dataclasses.dataclass; resolving those string annotations requires
    # the module to already be registered in sys.modules before exec.
    sys.modules["pty_smoke"] = module
    spec.loader.exec_module(module)
    return module


PTY_SMOKE = _load_module()

MARKER = PTY_SMOKE.BRACKETED_PASTE_READY_MARKER
MARKER_HEX = MARKER.hex()


# ------------------------------------------------------- 1. normal exit


def test_normal_exiting_child_returns_promptly() -> None:
    start = time.monotonic()
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", "read x; exit 0"], "hello", timeout=10.0
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert not result.timed_out
    assert result.ok
    assert elapsed < 5.0, f"a promptly-exiting child took {elapsed}s"


# --------------------------------------------- 2/3. real bounded timeout


def test_non_exiting_child_times_out_within_a_short_deterministic_bound() -> None:
    """A child that never reads and never exits must not hang this call.

    This is the exact regression this module fixes: the old bare
    `while time.monotonic() < deadline: os.read(...)` loop could block
    forever inside a single os.read() call. `sleep 60` never touches its
    stdin/stdout/stderr and never exits inside the 1-second budget given
    here, so a correct implementation must return within a few seconds of
    that budget, not minutes or hours.
    """
    start = time.monotonic()
    result = PTY_SMOKE.run_pty_command(["sleep", "60"], "ignored", timeout=1.0)
    elapsed = time.monotonic() - start
    assert result.timed_out
    assert not result.ok
    assert elapsed < 5.0, f"timeout handling itself took {elapsed}s (not bounded)"


def test_timeout_kills_and_reaps_the_child() -> None:
    """The killed child must not become a zombie or keep running.

    returncode is negative (killed by a signal, i.e. SIGKILL = -9) rather
    than None, which is only possible if the process was actually waited
    on (reaped) after being killed -- an un-reaped killed child reports no
    returncode at all.
    """
    result = PTY_SMOKE.run_pty_command(["sleep", "60"], "ignored", timeout=1.0)
    assert result.timed_out
    assert result.returncode is not None
    assert result.returncode < 0, f"expected a negative (killed-by-signal) code, got {result.returncode}"


# ------------------------------------------------- 4. descriptor cleanup


def test_repeated_calls_do_not_leak_file_descriptors() -> None:
    """Neither the master fd nor the slave fd may leak across calls.

    Exercises both the normal-exit and the timeout path repeatedly and
    confirms the process's open-fd count does not grow with the number of
    calls -- a leak would show up as roughly +2 fds per call (PTY master +
    slave) that are never closed.
    """
    proc_fd_dir = Path(f"/proc/{os.getpid()}/fd")
    if not proc_fd_dir.is_dir():
        pytest.skip("/proc/<pid>/fd is not available on this platform")

    before = len(list(proc_fd_dir.iterdir()))
    for _ in range(10):
        PTY_SMOKE.run_pty_command(["bash", "-c", "read x; exit 0"], "hi", timeout=5.0)
    for _ in range(5):
        PTY_SMOKE.run_pty_command(["sleep", "60"], "ignored", timeout=0.3)
    after = len(list(proc_fd_dir.iterdir()))

    assert after - before <= 2, (
        f"open fd count grew by {after - before} across 15 calls "
        f"(before={before}, after={after}) -- possible descriptor leak"
    )


# --------------------------------------------------- 5. output capture


def test_output_is_captured() -> None:
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", "read x; echo captured-output-marker; exit 0"],
        "go",
        timeout=10.0,
    )
    assert "captured-output-marker" in result.output


# ---------------------------------------------- 6. traceback detection


def test_traceback_in_output_is_detected_as_not_ok() -> None:
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", "read x; printf 'Traceback (most recent call last):\\n'; exit 0"],
        "go",
        timeout=10.0,
    )
    assert result.returncode == 0
    assert not result.timed_out
    assert "Traceback" in result.output
    assert not result.ok, "a Traceback in output must never be reported ok=True"


# ------------------------------------------ ready-handshake: 1/2/3. ordering


def test_input_is_withheld_until_marker_observed_not_sent_immediately() -> None:
    """Input must never reach the child before the readiness marker.

    Deterministic by construction, not by timing: the child performs a
    single non-blocking readability check (``select.select(..., timeout=0)``,
    which returns immediately regardless of system load) on its own stdin
    *before it has written the marker at all*. Since ``run_pty_command``
    only ever writes input after observing the marker in its own
    accumulated output, and the child has not yet emitted that marker at
    the moment of this check, no input can possibly be queued yet if the
    ready-gating contract holds -- there is no wall-clock window, no
    ``sleep``, and no scheduler-dependent race: the check either sees
    bytes that were written before this point in the child's own
    execution, or it doesn't, full stop.
    """
    child_script = (
        "import select, sys\n"
        "readable, _, _ = select.select([sys.stdin], [], [], 0)\n"
        "print('PREMARKER_INPUT=' + ('YES' if readable else 'NO'))\n"
        "sys.stdout.write('\\x1b[?2004h')\n"
        "sys.stdout.flush()\n"
        "line = sys.stdin.readline().rstrip('\\n')\n"
        "print('GOT:' + line)\n"
    )
    result = PTY_SMOKE.run_pty_command(
        [sys.executable, "-c", child_script], "hello", timeout=5.0, ready_marker=MARKER
    )
    assert result.ready
    assert result.input_sent
    assert result.ok
    assert "PREMARKER_INPUT=NO" in result.output, (
        "input reached the child before it could emit the marker -- "
        f"ready-gating did not withhold it: {result.output!r}"
    )
    assert "PREMARKER_INPUT=YES" not in result.output
    assert "GOT:hello" in result.output


# ----------------------------------------- ready-handshake: 3. output preserved


def test_output_before_marker_is_still_captured() -> None:
    script = "printf 'preamble-line\\n'; printf '\\x1b[?2004h'; read x; exit 0"
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", script], "hello", timeout=5.0, ready_marker=MARKER
    )
    assert result.ready
    assert "preamble-line" in result.output


# ------------------------------------- ready-handshake: 4. marker split across reads


def test_marker_split_across_multiple_reads_is_still_detected() -> None:
    """The marker bytes may arrive in separate os.read() chunks; detection
    must check the full accumulated buffer, not just the latest chunk."""
    script = "printf '\\x1b[?'; sleep 0.15; printf '2004h'; read x; printf 'GOT:%s\\n' \"$x\"; exit 0"
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", script], "world", timeout=5.0, ready_marker=MARKER
    )
    assert result.ready
    assert result.input_sent
    assert "GOT:world" in result.output


# --------------------------------- ready-handshake: 5. marker never arrives


def test_marker_never_arriving_times_out_without_ever_sending_input() -> None:
    start = time.monotonic()
    result = PTY_SMOKE.run_pty_command(
        ["sleep", "60"], "ignored", timeout=1.0, ready_marker=MARKER
    )
    elapsed = time.monotonic() - start
    assert result.timed_out
    assert not result.ready
    assert not result.input_sent
    assert not result.ok
    assert elapsed < 5.0, f"marker-never-arrives case took {elapsed}s (not bounded)"


# ------------------------- ready-handshake: 6. marker arrives, child ignores command


def test_marker_arrives_but_child_ignores_command_times_out_after_sending() -> None:
    script = "printf '\\x1b[?2004h'; sleep 60"
    start = time.monotonic()
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", script], "ignored", timeout=1.0, ready_marker=MARKER
    )
    elapsed = time.monotonic() - start
    assert result.timed_out
    assert result.ready
    assert result.input_sent
    assert not result.ok
    assert elapsed < 5.0, f"post-readiness hang case took {elapsed}s (not bounded)"


# ------------------------------ ready-handshake: 7. normal ready->command->exit


def test_normal_ready_then_command_then_exit_is_ok() -> None:
    script = "printf '\\x1b[?2004h'; read x; exit 0"
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", script], "exit", timeout=5.0, ready_marker=MARKER
    )
    assert result.ready
    assert result.input_sent
    assert result.ok


# --------------------------- ready-handshake: single absolute deadline


def test_single_absolute_deadline_covers_readiness_wait_and_execution() -> None:
    """A slow-to-become-ready child must not get a second, separate budget
    after the marker finally appears -- one deadline covers everything."""
    script = "sleep 0.8; printf '\\x1b[?2004h'; sleep 60"
    start = time.monotonic()
    result = PTY_SMOKE.run_pty_command(
        ["bash", "-c", script], "ignored", timeout=1.0, ready_marker=MARKER
    )
    elapsed = time.monotonic() - start
    assert result.ready
    assert result.timed_out
    assert elapsed < 1.5, (
        f"took {elapsed}s -- readiness must not reset the deadline "
        "(0.8s readiness delay + a fresh 1.0s budget would be ~1.8s+)"
    )


# ------------------------------ TERM defaulting (real pysh, no Docker needed)


def _local_pysh_binary() -> Path | None:
    candidate = Path(sys.executable).parent / "pysh"
    return candidate if candidate.is_file() else None


requires_local_pysh = pytest.mark.skipif(
    _local_pysh_binary() is None,
    reason="the project's own venv pysh binary is not available",
)


@requires_local_pysh
def test_default_term_makes_the_ready_marker_appear_for_real_pysh() -> None:
    """A missing TERM would select PySH's input() fallback instead of the
    raw editor, so the bracketed-paste readiness marker would never be
    emitted. The PTY helper supplies a capable TERM when the environment
    does not.

    Uses the project's own installed dev-venv ``pysh`` directly (no
    Docker) as a real, non-mocked interactive target -- the same binary
    exercised by the Debian/RPM/FreeBSD package smokes, just reached a
    different way.
    """
    pysh_bin = _local_pysh_binary()
    assert pysh_bin is not None

    # With TERM forced empty, PySH selects its input() fallback instead of
    # the raw editor, so the marker never appears -- this is the exact gap
    # the default closes. TERM is set to "" (not merely omitted) so
    # run_pty_command's own setdefault("TERM", ...) does not silently
    # refill it for this deliberately-bare-environment case.
    bare_env = {**os.environ, "TERM": ""}
    result_no_term = PTY_SMOKE.run_pty_command(
        [str(pysh_bin)], "exit", timeout=3.0, ready_marker=MARKER, env=bare_env
    )
    assert not result_no_term.ready

    # The helper's own default (TERM not specified at all) must make the
    # marker appear and let a real interactive session complete cleanly.
    result_default = PTY_SMOKE.run_pty_command(
        [str(pysh_bin)], "exit", timeout=5.0, ready_marker=MARKER
    )
    assert result_default.ready
    assert result_default.input_sent
    assert result_default.ok


# ------------------------------------------------------- CLI entrypoint


def _run_cli(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_cli_passes_for_a_normally_exiting_command() -> None:
    result = _run_cli("10", "hello", "bash", "-c", "read x; exit 0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rc=0" in result.stdout


def test_cli_fails_deterministically_for_a_hanging_command() -> None:
    start = time.monotonic()
    result = _run_cli("1", "ignored", "sleep", "60", timeout=10.0)
    elapsed = time.monotonic() - start
    assert result.returncode == 1
    assert "PTY FAIL" in result.stderr
    assert "did not exit within" in result.stderr
    assert elapsed < 8.0, f"CLI took {elapsed}s to report a 1s timeout"


def test_cli_rejects_missing_arguments() -> None:
    result = _run_cli()
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_cli_ready_marker_gates_input_and_reports_distinct_diagnostics() -> None:
    """The CLI must distinguish 'marker never observed' from 'command sent
    but shell did not exit' -- these are different failure classes."""
    never_ready = _run_cli(
        "--ready-marker-hex", MARKER_HEX, "1", "ignored", "sleep", "60", timeout=10.0
    )
    assert never_ready.returncode == 1
    assert "ready=False" in never_ready.stdout
    assert "input_sent=False" in never_ready.stdout
    assert "readiness marker not observed" in never_ready.stderr
    assert "command sent after readiness" not in never_ready.stderr

    ready_but_hangs = _run_cli(
        "--ready-marker-hex",
        MARKER_HEX,
        "1",
        "ignored",
        "bash",
        "-c",
        "printf '\\x1b[?2004h'; sleep 60",
        timeout=10.0,
    )
    assert ready_but_hangs.returncode == 1
    assert "ready=True" in ready_but_hangs.stdout
    assert "input_sent=True" in ready_but_hangs.stdout
    assert "command sent after readiness but shell did not exit" in ready_but_hangs.stderr
    assert "readiness marker not observed" not in ready_but_hangs.stderr


def test_cli_ready_marker_normal_success() -> None:
    result = _run_cli(
        "--ready-marker-hex",
        MARKER_HEX,
        "10",
        "hello",
        "bash",
        "-c",
        "printf '\\x1b[?2004h'; read x; exit 0",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ready=True" in result.stdout
    assert "input_sent=True" in result.stdout


# ------------------------------------- 7/8/9. package smoke scripts rewired


def test_debian_smoke_uses_the_shared_pty_helper() -> None:
    text = DEBIAN_SCRIPT.read_text(encoding="utf-8")
    assert "/pysh-pty-smoke.py" in text
    assert "pty_smoke.py:/pysh-pty-smoke.py:ro" in text
    assert f"--ready-marker-hex {MARKER_HEX} 10 exit /usr/bin/pysh" in text
    assert f"--ready-marker-hex {MARKER_HEX} 10 quit /usr/bin/pysh" in text


def test_rpm_smoke_uses_the_shared_pty_helper() -> None:
    text = RPM_SCRIPT.read_text(encoding="utf-8")
    assert "/pysh-pty-smoke.py" in text
    assert "pty_smoke.py:/pysh-pty-smoke.py:ro" in text
    assert f"--ready-marker-hex {MARKER_HEX} 10 exit /usr/bin/pysh" in text
    assert f"--ready-marker-hex {MARKER_HEX} 10 quit /usr/bin/pysh" in text


def test_freebsd_smoke_uses_the_shared_pty_helper() -> None:
    text = FREEBSD_SCRIPT.read_text(encoding="utf-8")
    assert '"${REPO_ROOT}/scripts/pty_smoke.py" --ready-marker-hex' in text
    assert f"--ready-marker-hex {MARKER_HEX}" in text
    assert "10 exit /usr/local/bin/pysh" in text
    assert "10 quit /usr/local/bin/pysh" in text


# --------------------------------- 10. no copied blocking read loop remains


def test_no_package_smoke_script_carries_its_own_pty_driver() -> None:
    """Only scripts/pty_smoke.py may define run_pty_command; every package
    smoke script must call the shared implementation, never redefine it."""
    for script in (DEBIAN_SCRIPT, RPM_SCRIPT, FREEBSD_SCRIPT):
        text = script.read_text(encoding="utf-8")
        assert "def run_pty_command" not in text, f"{script.name} still defines its own PTY driver"
        assert "import pty" not in text, f"{script.name} still embeds a PTY driver import"


# ---------------------------------------- 11. FreeBSD contract preserved


def test_freebsd_smoke_contract_still_requires_genuine_pty() -> None:
    text = FREEBSD_SCRIPT.read_text(encoding="utf-8")
    assert "real interactive PTY smoke (genuine pseudo-terminal)" in text
    assert "PTY interactive smoke PASSED" in text
    # The non-TTY batch check must remain explicitly distinguished from
    # the genuine PTY check, as before.
    assert "NOT a PTY test" in text


# ---------------------------- 12/13. readiness contract, all three scripts


def _pty_smoke_section(text: str) -> str:
    start = text.index("--- real interactive PTY smoke (genuine pseudo-terminal) ---")
    end = text.index("PTY interactive smoke PASSED")
    return text[start:end]


def test_all_three_package_smokes_use_the_ready_marker_contract() -> None:
    """Debian, RPM, and FreeBSD must all use the identical readiness
    contract -- no FreeBSD-specific handling, no script left ungated."""
    for script in (DEBIAN_SCRIPT, RPM_SCRIPT, FREEBSD_SCRIPT):
        section = _pty_smoke_section(script.read_text(encoding="utf-8"))
        assert f"--ready-marker-hex {MARKER_HEX}" in section, (
            f"{script.name}'s PTY smoke section is missing the shared "
            "readiness marker contract"
        )
        # Both exit and quit calls must be gated, not just one of them.
        assert section.count(f"--ready-marker-hex {MARKER_HEX}") == 2, (
            f"{script.name} must gate both the exit and quit PTY calls"
        )


def test_no_package_smoke_sends_input_before_the_ready_flag_is_present() -> None:
    """Every '... 10 exit ...' / '... 10 quit ...' invocation in the PTY
    smoke section must be preceded by --ready-marker-hex on the same call
    -- there must be no bare, ungated invocation anywhere."""
    for script in (DEBIAN_SCRIPT, RPM_SCRIPT, FREEBSD_SCRIPT):
        section = _pty_smoke_section(script.read_text(encoding="utf-8"))
        for target in ("exit /usr/bin/pysh", "quit /usr/bin/pysh",
                       "exit /usr/local/bin/pysh", "quit /usr/local/bin/pysh"):
            if target not in section:
                continue
            call_start = section.rindex("python3", 0, section.index(target))
            call_text = section[call_start : section.index(target) + len(target)]
            assert "--ready-marker-hex" in call_text, (
                f"{script.name}: found an ungated PTY call: {call_text!r}"
            )


# ------------------------------------- 14. no sleep-based synchronization


def test_no_package_smoke_uses_sleep_for_pty_synchronization() -> None:
    """The whole point of the ready-marker protocol is to avoid guessing
    a fixed delay -- no script may reach for sleep as a substitute."""
    for script in (DEBIAN_SCRIPT, RPM_SCRIPT, FREEBSD_SCRIPT):
        section = _pty_smoke_section(script.read_text(encoding="utf-8"))
        assert "sleep" not in section, f"{script.name} uses sleep-based PTY synchronization"


def test_pty_smoke_helper_itself_uses_no_time_sleep() -> None:
    """The module docstring legitimately *names* time.sleep() while
    explaining why it is not used; scope the check to the actual code."""
    text = SCRIPT.read_text(encoding="utf-8")
    code_start = text.index('from __future__ import annotations')
    code = text[code_start:]
    assert "time.sleep(" not in code
