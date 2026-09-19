# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_pty_smoke_helper.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the shared, strictly-bounded PTY smoke helper
(Issue #33 PTY portability fix).

``scripts/pty_smoke.py`` replaces three copy-pasted, per-package
``run_pty_command()`` implementations (Debian, RPM, FreeBSD) that shared a
latent bug: their read loop checked a ``time.monotonic()`` deadline only
*between* calls to a blocking ``os.read()`` -- a single call that never
returns (because the child produces no output and never exits) could hang
the whole function indefinitely. A real FreeBSD ``workflow_dispatch`` run
hit exactly this and hung for over an hour before being manually canceled.

These tests exercise the shared helper directly (never via string/grep
inspection for the timeout behavior itself) using genuinely non-exiting
child processes, and separately confirm each of the three package smoke
scripts was rewired to call the one shared implementation rather than
carrying its own copy.
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


# ------------------------------------- 7/8/9. package smoke scripts rewired


def test_debian_smoke_uses_the_shared_pty_helper() -> None:
    text = DEBIAN_SCRIPT.read_text(encoding="utf-8")
    assert "/pysh-pty-smoke.py" in text
    assert "pty_smoke.py:/pysh-pty-smoke.py:ro" in text
    assert "python3 /pysh-pty-smoke.py 10 exit /usr/bin/pysh" in text
    assert "python3 /pysh-pty-smoke.py 10 quit /usr/bin/pysh" in text


def test_rpm_smoke_uses_the_shared_pty_helper() -> None:
    text = RPM_SCRIPT.read_text(encoding="utf-8")
    assert "/pysh-pty-smoke.py" in text
    assert "pty_smoke.py:/pysh-pty-smoke.py:ro" in text
    assert "python3 /pysh-pty-smoke.py 10 exit /usr/bin/pysh" in text
    assert "python3 /pysh-pty-smoke.py 10 quit /usr/bin/pysh" in text


def test_freebsd_smoke_uses_the_shared_pty_helper() -> None:
    text = FREEBSD_SCRIPT.read_text(encoding="utf-8")
    assert 'python3.13 "${REPO_ROOT}/scripts/pty_smoke.py" 10 exit /usr/local/bin/pysh' in text
    assert 'python3.13 "${REPO_ROOT}/scripts/pty_smoke.py" 10 quit /usr/local/bin/pysh' in text


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
