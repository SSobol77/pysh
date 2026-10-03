# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_contained_pipeline_groups.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Process-group correctness of pipelines inside and outside a substitution containment domain.

Invariant: a normal shell gives each pipeline its own process group (the first stage's
pid) and uses it for job records, terminal handover and group signals. In a contained
domain the stages stay in the domain's existing group, so no pipeline group exists and
no stage pid may be used as a group id.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import pytest

from pysh.config.startup import NO_RC_STARTUP_POLICY
from pysh.core import shell as shell_module
from pysh.core.shell import PyShell

PY = sys.executable
def slow_stage(marker: Path) -> str:
    """A stage that installs the default SIGINT handler (the runner may start us with SIGINT
    ignored), announces readiness through ``marker``, then sleeps."""
    return (
        f'{PY} -c "import signal, time, pathlib; '
        "signal.signal(signal.SIGINT, signal.default_int_handler); "
        f"pathlib.Path('{marker}').touch(); time.sleep(30)\""
    )


def wait_for(*markers: Path, seconds: float = 20.0) -> None:
    import time

    deadline = time.monotonic() + seconds
    while not all(m.exists() for m in markers):
        assert time.monotonic() < deadline, "the stages never became ready"
        time.sleep(0.01)


PROBE = f"{PY} -c 'import os; print(os.getpid(), os.getpgrp())'"


@pytest.fixture
def make_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    def build(*, contained: bool) -> PyShell:
        shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
        shell._descendants_contained = contained
        return shell

    return build


class Spies:
    """Record every group-level operation the parent shell performs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.killpg: list[tuple[int, int]] = []
        self.kill: list[tuple[int, int]] = []
        self.tcsetpgrp: list[int] = []
        self.add_job: list[int] = []
        real_killpg, real_kill = os.killpg, os.kill

        def killpg(pgid: int, sig: int) -> None:
            self.killpg.append((pgid, int(sig)))
            real_killpg(pgid, sig)

        def kill(pid: int, sig: int) -> None:
            self.kill.append((pid, int(sig)))
            real_kill(pid, sig)

        monkeypatch.setattr(shell_module.os, "killpg", killpg)
        monkeypatch.setattr(shell_module.os, "kill", kill)
        monkeypatch.setattr(
            shell_module, "tcsetpgrp_safely", lambda fd, pgid: self.tcsetpgrp.append(pgid) or True
        )


def _reap_all() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _probe_ids(out: str) -> tuple[int, int]:
    pid, pgid = out.split()[:2]
    return int(pid), int(pgid)


def test_contained_foreground_pipeline_uses_no_invalid_group_id(make_shell, monkeypatch, capfd) -> None:
    spies = Spies(monkeypatch)
    shell = make_shell(contained=True)
    shell._tty_fd = 99  # even with a terminal descriptor present, no handover may happen
    jobs_before = len(shell.job_table.all_jobs())
    capfd.readouterr()
    assert shell.execute(f"{PROBE} | cat") == 0
    pid, pgid = _probe_ids(capfd.readouterr().out)
    assert pgid == os.getpgrp() != pid  # the stage stayed in the existing (domain) group
    assert spies.killpg == [] and spies.tcsetpgrp == []
    assert len(shell.job_table.all_jobs()) == jobs_before


def test_contained_pipeline_cancellation_never_targets_a_group(
    make_shell, monkeypatch, capfd, tmp_path: Path
) -> None:
    spies = Spies(monkeypatch)
    shell = make_shell(contained=True)
    real_waitpid = os.waitpid
    state = {"raised": False}

    def waitpid(pid: int, flags: int):
        if not state["raised"] and pid > 0 and flags == 0:
            state["raised"] = True
            wait_for(tmp_path / "ready1", tmp_path / "ready2")  # signal only once both stages run
            raise KeyboardInterrupt
        return real_waitpid(pid, flags)

    monkeypatch.setattr(shell_module.os, "waitpid", waitpid)
    status = shell.execute(f"{slow_stage(tmp_path / 'ready1')} | {slow_stage(tmp_path / 'ready2')}")
    assert status == 130
    assert spies.killpg == []  # no group id was invented
    signalled = {pid for pid, sig in spies.kill if sig == signal.SIGINT}
    assert len(signalled) == 2  # exactly the two forked stages were interrupted individually
    assert os.getpgid(0) == os.getpgrp()
    _reap_all()


def test_contained_background_pipeline_and_command_store_no_job_record(make_shell, monkeypatch, capfd) -> None:
    spies = Spies(monkeypatch)
    shell = make_shell(contained=True)
    recorded: list[int] = []
    real_add = shell.job_table.add_job
    monkeypatch.setattr(
        shell.job_table, "add_job",
        lambda pgid, *a, **k: recorded.append(pgid) or real_add(pgid, *a, **k),
    )
    capfd.readouterr()
    assert shell.execute("true | true &") == 0
    assert shell.execute("true &") == 0
    assert recorded == []
    assert spies.killpg == [] and spies.tcsetpgrp == []
    assert "[" not in capfd.readouterr().out  # no fake job notice either
    _reap_all()


def test_ordinary_pipeline_keeps_its_own_process_group(make_shell, monkeypatch, capfd) -> None:
    shell = make_shell(contained=False)
    capfd.readouterr()
    assert shell.execute(f"{PROBE} | cat") == 0
    pid, pgid = _probe_ids(capfd.readouterr().out)
    assert pgid == pid != os.getpgrp()  # the pipeline owns a group whose id is its first stage


def test_ordinary_background_pipeline_still_registers_a_job_with_the_first_stage_group(
    make_shell, monkeypatch, capfd
) -> None:
    shell = make_shell(contained=False)
    recorded: list[tuple[int, list[int]]] = []
    real_add = shell.job_table.add_job

    def add_job(pgid, command, pids, **kw):
        recorded.append((pgid, list(pids)))
        return real_add(pgid, command, pids, **kw)

    monkeypatch.setattr(shell.job_table, "add_job", add_job)
    assert shell.execute("true | true &") == 0
    assert len(recorded) == 1 and recorded[0][0] == recorded[0][1][0]
    assert "[" in capfd.readouterr().out
    _reap_all()


def test_ordinary_pipeline_interrupt_still_signals_the_pipeline_group(
    make_shell, monkeypatch, tmp_path: Path
) -> None:
    spies = Spies(monkeypatch)
    shell = make_shell(contained=False)
    real_waitpid = os.waitpid
    state = {"raised": False}

    def waitpid(pid: int, flags: int):
        if not state["raised"] and pid > 0 and flags == 0:
            state["raised"] = True
            wait_for(tmp_path / "ready1", tmp_path / "ready2")  # signal only once both stages run
            raise KeyboardInterrupt
        return real_waitpid(pid, flags)

    monkeypatch.setattr(shell_module.os, "waitpid", waitpid)
    assert shell.execute(f"{slow_stage(tmp_path / 'ready1')} | {slow_stage(tmp_path / 'ready2')}") == 130
    assert len(spies.killpg) == 1 and spies.killpg[0][1] == signal.SIGINT
    assert [pid for pid, _ in spies.kill] == []  # per-process signalling is the contained path only
    _reap_all()


def test_the_contained_flag_is_still_granted_only_by_the_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSH_SUBSTITUTION_DEPTH", "3")
    assert PyShell(startup_policy=NO_RC_STARTUP_POLICY)._descendants_contained is False


# --- PTY helper: a group-owning child is never reaped before its group is swept ----------------


def _pty_helper():
    from tests.differential import pty_lab

    return pty_lab.load_pty_helper()


def test_controlling_tty_mode_does_not_poll_the_leader_before_the_sweep(monkeypatch) -> None:
    helper = _pty_helper()
    polls_before_sweep: list[int] = []
    state = {"swept": False}
    real_popen = helper.subprocess.Popen

    class SpyPopen(real_popen):
        def poll(self):
            if not state["swept"]:
                polls_before_sweep.append(self.pid)  # poll() would reap the zombie leader
            return super().poll()

    real_sweep = helper._sweep_group_and_reap

    def sweep(proc):
        state["swept"] = True
        return real_sweep(proc)

    monkeypatch.setattr(helper.subprocess, "Popen", SpyPopen)
    monkeypatch.setattr(helper, "_sweep_group_and_reap", sweep)
    result = helper.run_pty_command(
        [PY, "-c", "print('done')"], "", timeout=20.0, input_bytes=b"", controlling_tty=True,
    )
    assert state["swept"] and result.returncode == 0 and "done" in result.output
    assert polls_before_sweep == []


def test_exited_noreap_treats_an_already_reaped_child_as_exited(monkeypatch) -> None:
    helper = _pty_helper()

    class Gone:
        pid = 1
        returncode = None

    def raise_child_process_error(*_args):
        raise ChildProcessError

    monkeypatch.setattr(helper.os, "waitid", raise_child_process_error)
    assert helper._exited_noreap(Gone()) is True

    class Reaped(Gone):
        returncode = 0

    assert helper._exited_noreap(Reaped()) is True  # decided without any system call
