# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fd_robustness.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 3: portable descriptor, redirection, and pipeline robustness.

Acceptance evidence uses only ``tests/fuzz_support/fdprobe.py`` (bounded
``os.fstat`` scan + ``RLIMIT_NOFILE``); it never reads ``/proc/self/fd`` or
``/dev/fd``. Failures are injected deterministically at a chosen call of
``os.fork/pipe/dup/dup2/open``; real descriptors are never exhausted except in
one bounded child with a lowered *soft* limit.
"""
from __future__ import annotations

import errno
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

import pytest

from pysh.config.startup import NO_RC_STARTUP_POLICY
from pysh.core.shell import PyShell, _redirect_standard_fds
from pysh.parsing.redirection import RedirectionSpec, parse_redirections
from tests.fuzz_support import engines, fdprobe
from tests.fuzz_support.execution import (
    FaultInjector,
    patch_tempfile,
    prepare_workdir,
    stdio_identity,
    unreaped_child,
)
from tests.fuzz_support.repro import PropertyFailure, Reproduction, traceback_fingerprint

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
PY = str(Path(sys.executable).resolve())


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = prepare_workdir(tmp_path)
    monkeypatch.chdir(directory)
    monkeypatch.setenv("HOME", str(tmp_path))
    return directory


@pytest.fixture
def shell(work: Path) -> PyShell:
    return PyShell(startup_policy=NO_RC_STARTUP_POLICY)


def _healthy(shell: PyShell, capfd: pytest.CaptureFixture[str]) -> None:
    """A simple controlled operation still works: stdio restored, no broken pipeline state."""
    capfd.readouterr()
    assert shell.execute("echo healthy | cat") == 0
    assert capfd.readouterr().out == "healthy\n"


# --- the probe itself -------------------------------------------------------------------


def test_probe_sees_a_new_descriptor_and_its_closure(tmp_path: Path) -> None:
    before = fdprobe.open_fds()
    fd = os.open(tmp_path / "probe.txt", os.O_CREAT | os.O_WRONLY)
    try:
        assert fd in fdprobe.open_fds()
        assert fdprobe.open_fds() - before == {fd}
    finally:
        os.close(fd)
    assert fd not in fdprobe.open_fds() and fdprobe.open_fds() == before


def test_probe_sees_both_pipe_descriptors_and_their_closure() -> None:
    before = fdprobe.open_fds()
    read_fd, write_fd = os.pipe()
    try:
        assert fdprobe.open_fds() - before == {read_fd, write_fd}
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert fdprobe.open_fds() == before


def test_probe_does_not_assume_stdio_is_the_only_open_set(tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    try:
        observed = fdprobe.open_fds()
        assert {read_fd, write_fd} <= observed
        assert observed - {0, 1, 2}  # something beyond stdio is open
        assert {0, 1, 2} <= observed  # pytest keeps stdio open; the probe must report it
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_scan_cap_and_rlimit_behavior_are_deterministic() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    assert fdprobe.scan_limit() == (fdprobe.SCAN_CAP if soft == resource.RLIM_INFINITY
                                    else min(soft, fdprobe.SCAN_CAP))
    assert fdprobe.scan_limit(8) == min(8, soft if soft != resource.RLIM_INFINITY else 8)
    assert fdprobe.scan_limit() == fdprobe.scan_limit()
    with pytest.raises(ValueError):
        fdprobe.scan_limit(0)
    lowered = max(fdprobe.open_fds()) + 8
    resource.setrlimit(resource.RLIMIT_NOFILE, (lowered, hard))
    try:
        assert fdprobe.scan_limit() == min(lowered, fdprobe.SCAN_CAP)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    read_fd, write_fd = os.pipe()
    try:  # a descriptor beyond an explicit bound is outside the stated evidence boundary
        assert write_fd not in fdprobe.open_fds(limit=min(read_fd, write_fd))
        assert read_fd in fdprobe.open_fds(limit=max(read_fd, write_fd) + 1)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_unavailable_or_failing_probe_is_never_a_passing_check(monkeypatch) -> None:
    monkeypatch.setattr(fdprobe, "resource", None)
    with pytest.raises(fdprobe.ProbeUnavailable):
        fdprobe.open_fds()
    with pytest.raises(fdprobe.ProbeUnavailable):  # and the context manager cannot pass silently
        with fdprobe.no_fd_growth("x"):
            pass
    monkeypatch.undo()

    def broken(_fd: int):
        raise OSError(errno.EIO, "io")

    monkeypatch.setattr(os, "fstat", broken)
    with pytest.raises(fdprobe.ProbeFailure):
        fdprobe.open_fds(limit=4)


def test_no_fd_growth_reports_a_leak_even_when_the_block_raises(tmp_path: Path) -> None:
    leaked: list[int] = []
    with pytest.raises(AssertionError, match="leaked="):
        with fdprobe.no_fd_growth("leaky"):
            leaked.append(os.open(tmp_path / "leak", os.O_CREAT | os.O_WRONLY))
    os.close(leaked[0])


# --- pipeline: pipe() succeeds, fork() fails (finding F2) --------------------------------------


@pytest.mark.parametrize("fail_at", [0, 1, 2])
def test_pipe_then_fork_failure_leaks_no_descriptor_and_no_child(
    shell: PyShell, capfd: pytest.CaptureFixture[str], fail_at: int
) -> None:
    identity = stdio_identity()
    injector = FaultInjector(("fork", fail_at))
    before = fdprobe.open_fds()
    with injector.active():
        status = shell.execute("echo hi | cat | cat")
    after = fdprobe.open_fds()
    err = capfd.readouterr().err
    leftover = unreaped_child()
    assert injector.fired
    assert status == 1 and "injected fork failure" in err
    assert after == before, f"leaked descriptors: {[fdprobe.describe(fd) for fd in sorted(after - before)]}"
    assert leftover is None, f"child {leftover} was left unreaped"
    assert stdio_identity() == identity
    _healthy(shell, capfd)


@pytest.mark.parametrize("fail_at", [0, 1])
def test_pipe_creation_failure_in_a_pipeline_is_contained(
    shell: PyShell, capfd: pytest.CaptureFixture[str], fail_at: int
) -> None:
    injector = FaultInjector(("pipe", fail_at))
    before = fdprobe.open_fds()
    with injector.active():
        status = shell.execute("echo hi | cat | cat")
    err = capfd.readouterr().err
    assert injector.fired and status == 1 and "injected pipe failure" in err
    assert fdprobe.open_fds() == before
    assert unreaped_child() is None
    _healthy(shell, capfd)


# --- redirection: partial os.dup failure (finding F3) -------------------------------------------


@pytest.mark.parametrize("fail_at", [0, 1, 2, 3, 4, 5])
def test_partial_dup_failure_is_rolled_back(work: Path, fail_at: int) -> None:
    _clean, spec = parse_redirections("true > out.txt")
    identity = stdio_identity()
    injector = FaultInjector(("dup", fail_at))
    before = fdprobe.open_fds()
    with injector.active(), pytest.raises(OSError, match="injected dup failure"):
        with _redirect_standard_fds(spec):
            pytest.fail("the context body must not run after a failed setup")
    assert injector.fired
    assert fdprobe.open_fds() == before, "partial setup was not rolled back"
    assert stdio_identity() == identity


def test_partial_dup_failure_through_the_shell_keeps_the_session_usable(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    for fail_at in (0, 1, 2):
        injector = FaultInjector(("dup", fail_at))
        before = fdprobe.open_fds()
        with injector.active():
            status = shell.execute("pwd > out.txt")
        assert injector.fired and status == 1
        assert capfd.readouterr().err.count("injected dup failure") == 1
        assert fdprobe.open_fds() == before
        _healthy(shell, capfd)


# --- other reachable failure paths -----------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pwd > missing-dir/out.txt",  # builtin: open() fails after the saved dups exist
        "cat < missing.txt",  # external: stdin open fails
        "cat > missing-dir/out.txt",  # external: stdout open fails
        "pwd > out.txt < missing.txt",  # a target opened, then a later action fails
        "cat < missing.txt | cat",  # failing redirection inside a pipeline stage
    ],
)
def test_unopenable_redirection_targets_fail_deterministically_without_leaks(
    shell: PyShell, capfd: pytest.CaptureFixture[str], command: str
) -> None:
    identity = stdio_identity()
    before = fdprobe.open_fds()
    status = shell.execute(command)
    err = capfd.readouterr().err
    assert "pysh:" in err or "No such file" in err  # a diagnostic is always emitted
    if "|" not in command:
        assert status != 0
    # A pipeline reports its last stage (no pipefail), so only the diagnostic is pinned there.
    assert fdprobe.open_fds() == before
    assert unreaped_child() is None
    assert stdio_identity() == identity
    _healthy(shell, capfd)


@pytest.mark.parametrize(("operation", "fail_at"), [("dup2", 0), ("dup2", 1), ("open", 0)])
def test_dup2_and_open_failures_during_redirection_setup_roll_back(
    shell: PyShell, capfd: pytest.CaptureFixture[str], operation: str, fail_at: int
) -> None:
    identity = stdio_identity()
    injector = FaultInjector((operation, fail_at))
    before = fdprobe.open_fds()
    with injector.active():
        status = shell.execute("pwd > out.txt 2>&1")
    capfd.readouterr()
    assert injector.fired and status != 0
    assert fdprobe.open_fds() == before, (operation, fail_at)
    assert unreaped_child() is None
    assert stdio_identity() == identity, (operation, fail_at)
    _healthy(shell, capfd)


@pytest.mark.parametrize("fail_at", [2, 3, 4])
def test_dup2_failure_while_restoring_stdio_still_closes_every_saved_duplicate(
    work: Path, fail_at: int
) -> None:
    # Calls 0-1 set up ``> out.txt 2>&1``; calls 2-4 restore fds 0-2. A failed restore cannot
    # be undone, but nothing may leak and the failure must surface. The test repairs stdio itself.
    _clean, spec = parse_redirections("true > out.txt 2>&1")
    guard = {fd: os.dup(fd) for fd in (0, 1, 2)}
    before = fdprobe.open_fds()
    injector = FaultInjector(("dup2", fail_at))
    try:
        with injector.active(), pytest.raises(OSError, match="injected dup2 failure"):
            with _redirect_standard_fds(spec):
                pass
    finally:
        for fd, saved in guard.items():
            os.dup2(saved, fd)
    after = fdprobe.open_fds()
    for saved in guard.values():
        os.close(saved)
    assert after == before | set(guard.values()), "saved duplicates leaked while restoring"


def test_heredoc_setup_failure_is_contained(shell: PyShell, capfd: pytest.CaptureFixture[str]) -> None:
    identity = stdio_identity()
    before = fdprobe.open_fds()
    with patch_tempfile():
        status = shell.execute("pwd <<< hi")
    err = capfd.readouterr().err
    assert status == 1 and "injected TemporaryFile failure" in err
    assert fdprobe.open_fds() == before and stdio_identity() == identity
    _healthy(shell, capfd)


# --- child descriptor inheritance ---------------------------------------------------------------


def _expected_child_fds() -> set[int]:
    """fds 0-2 plus whatever pytest's own parent legitimately passed down as inheritable."""
    return {0, 1, 2} | set(fdprobe.inheritable_fds(fdprobe.open_fds()))


@pytest.mark.parametrize(
    "template",
    [
        '{py} {script}',
        '{py} {script} > child.json',
        'echo ignored | {py} {script}',
        '{py} {script} | cat',
        '{py} {script} <<< input',
        '{py} {script} < in.txt',
        '{py} {script} 2>&1',
    ],
)
def test_external_children_do_not_inherit_internal_descriptors(
    shell: PyShell, capfd: pytest.CaptureFixture[str], work: Path, template: str
) -> None:
    command = template.format(py=f'"{PY}"', script=f'"{FIXTURES / "fd_child.py"}"')
    capfd.readouterr()
    assert shell.execute(command) == 0
    out = (work / "child.json").read_text() if "child.json" in command else capfd.readouterr().out
    reported = set(json.loads(out.strip().splitlines()[-1]))
    allowed = _expected_child_fds()
    assert reported <= allowed, (
        f"child inherited unexpected descriptors {sorted(reported - allowed)} "
        f"(allowed {sorted(allowed)})")
    # every template redirects or pipes stdio but never closes it
    assert reported >= {0, 1, 2}


# --- repeated stability --------------------------------------------------------------------------


def test_repeated_pipelines_cause_no_descriptor_growth(shell: PyShell, capfd: pytest.CaptureFixture[str]) -> None:
    shell.execute("echo warm | cat")  # allow lazy one-time allocations before the baseline
    capfd.readouterr()
    baseline = fdprobe.open_fds()
    for iteration in range(30):
        assert shell.execute("echo hi | cat | cat") == 0
        assert fdprobe.open_fds() == baseline, f"descriptor set changed after iteration {iteration}"
    assert unreaped_child() is None
    assert capfd.readouterr().out == "hi\n" * 30


def test_repeated_redirections_cause_no_descriptor_growth(
    shell: PyShell, capfd: pytest.CaptureFixture[str], work: Path
) -> None:
    commands = [
        "echo out > o.txt",
        "echo more >> o.txt",
        "cat < in.txt > copy.txt",
        "cat missing.txt 2> e.txt",
        "cat missing.txt > both.txt 2>&1",
        "pwd 2>&1 > p.txt",
        "cat <<< heredoc-string > h.txt",
    ]
    for command in commands:  # warm-up
        shell.execute(command)
    capfd.readouterr()
    baseline = fdprobe.open_fds()
    for iteration in range(15):
        for command in commands:
            shell.execute(command)
        assert fdprobe.open_fds() == baseline, f"descriptor set changed after iteration {iteration}"
    assert unreaped_child() is None
    assert (work / "o.txt").read_text().startswith("out\nmore\n")


# --- low RLIMIT_NOFILE (one bounded child; the parent's limits are untouched) ---------------------


def test_low_soft_nofile_limit_in_a_child_fails_the_pipeline_cleanly(tmp_path: Path) -> None:
    soft_before = resource.getrlimit(resource.RLIMIT_NOFILE)
    done = subprocess.run(  # noqa: S603 - fixed interpreter and repository fixture
        [PY, str(FIXTURES / "fd_limit_child.py"), "echo a | cat | cat", "echo healthy | cat"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
        env={"PYTHONPATH": f"{REPO / 'src'}:{REPO}", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stderr.strip().splitlines()[-1])
    assert report["status"] != 0, "the pipeline cannot succeed with one free descriptor"
    assert report["after"] == report["before"], "descriptors leaked under EMFILE"
    assert report["health"] == 0, "the shell was left unusable"
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == soft_before


# --- structured, deterministic execution cases (replayable) ---------------------------------------


@pytest.mark.parametrize("seed", [1, 2])
def test_structured_pipeline_cases_with_injected_failures_are_contained(
    seed: int, shell: PyShell, capfd: pytest.CaptureFixture[str], work: Path
) -> None:
    for iteration in range(14):
        case = engines.pipeline_case_at(seed, iteration)
        identity = stdio_identity()
        injector = FaultInjector(case.fault)
        before = fdprobe.open_fds()
        try:
            with injector.active():
                shell.execute(case.command)
            capfd.readouterr()
            problems = []
            if fdprobe.open_fds() != before:
                problems.append("descriptor leak")
            leftover = unreaped_child()
            if leftover is not None:
                problems.append(f"unreaped child {leftover}")
            if stdio_identity() != identity:
                problems.append("stdio not restored")
            if problems:
                raise AssertionError("; ".join(problems))
            _healthy(shell, capfd)
        except AssertionError as error:
            raise PropertyFailure(Reproduction(
                "core.shell.pipeline", "execution_robustness", case.command,
                "generated:pipeline", seed, iteration, engines.GENERATOR_VERSION,
                f"fault={case.fault!r}: {error}", exception_type=type(error).__name__,
                exception_message=str(error), traceback_fingerprint=traceback_fingerprint(error),
            )) from error


def test_structured_cases_are_deterministic_and_bounded() -> None:
    for iteration in range(60):
        case = engines.pipeline_case_at(5, iteration)
        assert case == engines.pipeline_case_at(5, iteration)
        assert 1 <= len(case.stages) <= 4 and all(s in engines.SAFE_STAGES for s in case.stages)
        if case.fault is not None:
            operation, index = case.fault
            assert 0 <= index < engines.FAULT_OPERATIONS[operation]
    assert any(engines.pipeline_case_at(5, i).fault is None for i in range(60))
    assert RedirectionSpec().is_empty()
