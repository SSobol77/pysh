# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_job_control.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Job-control tests (Issue #11).

Coverage:
A. Parser/background operator — split_chain recognises & correctly.
B. JobTable pure unit tests — deterministic table semantics.
C. Shell integration (non-PTY) — background execution and job builtins.
D. Builtin error paths — jobs/fg/bg with bad arguments.
E. Regression guard — existing operators, redirection and signal tests pass.
"""
from __future__ import annotations

import os
import signal
import sys
import time

import pytest

from pysh.core.jobs import (
    JobStatus,
    JobTable,
    _raw_to_exit,
    has_job_control,
    has_tcsetpgrp,
    make_child_preexec,
    open_tty,
    reset_child_job_control_signals,
    sigtstp_exit_status,
    sigtstp_number,
    tcsetpgrp_safely,
)
from pysh.parsing.ast import ChainOp
from pysh.parsing.errors import ParseError
from pysh.parsing.grammar import split_chain

# ---------------------------------------------------------------------------
# A. Parser / background operator
# ---------------------------------------------------------------------------


class TestBackgroundOperatorParsing:
    """split_chain recognises & as a background operator in all expected forms."""

    def test_echo_hi_background(self) -> None:
        chain = split_chain("echo hi &")
        assert len(chain) == 1
        assert chain[0].command == "echo hi"
        assert chain[0].operator is ChainOp.BACKGROUND

    def test_background_then_next_command(self) -> None:
        chain = split_chain("sleep 5 & echo next")
        assert len(chain) == 2
        assert chain[0].command == "sleep 5"
        assert chain[0].operator is ChainOp.BACKGROUND
        assert chain[1].command == "echo next"
        assert chain[1].operator is None

    def test_quoted_ampersand_is_literal(self) -> None:
        chain = split_chain('echo "&"')
        assert len(chain) == 1
        assert chain[0].command == 'echo "&"'
        assert chain[0].operator is None

    def test_single_quoted_ampersand_is_literal(self) -> None:
        chain = split_chain("echo '&'")
        assert len(chain) == 1
        assert chain[0].command == "echo '&'"
        assert chain[0].operator is None

    def test_double_ampersand_is_and(self) -> None:
        chain = split_chain("echo hi && echo ok")
        assert len(chain) == 2
        assert chain[0].operator is ChainOp.AND
        assert chain[1].operator is None

    def test_amp_redirect_is_not_background(self) -> None:
        """&> is a redirection; the & is NOT a chain operator."""
        chain = split_chain("echo hi &> out.txt")
        assert len(chain) == 1
        assert "&>" in chain[0].command
        assert chain[0].operator is None

    def test_amp_append_redirect_is_not_background(self) -> None:
        chain = split_chain("echo hi &>> out.txt")
        assert len(chain) == 1
        assert chain[0].operator is None

    def test_bare_ampersand_is_parse_error(self) -> None:
        with pytest.raises(ParseError):
            split_chain("&")

    def test_bare_ampersand_at_start_is_parse_error(self) -> None:
        with pytest.raises(ParseError):
            split_chain("& echo something")

    def test_background_after_semicolon(self) -> None:
        chain = split_chain("echo a; sleep 1 &")
        assert len(chain) == 2
        assert chain[0].command == "echo a"
        assert chain[0].operator is ChainOp.SEMI
        assert chain[1].command == "sleep 1"
        assert chain[1].operator is ChainOp.BACKGROUND

    def test_pipeline_background(self) -> None:
        chain = split_chain("ls | grep py &")
        assert len(chain) == 1
        assert chain[0].command == "ls | grep py"
        assert chain[0].operator is ChainOp.BACKGROUND


# ---------------------------------------------------------------------------
# B. JobTable pure unit tests
# ---------------------------------------------------------------------------


class TestJobTableAllocatesIds:
    def test_first_job_gets_id_one(self) -> None:
        jt = JobTable()
        job = jt.add_job(1234, "sleep 5", [1234], background=True)
        assert job.job_id == 1

    def test_ids_are_monotonically_increasing(self) -> None:
        jt = JobTable()
        ids = [jt.add_job(1000 + i, f"cmd{i}", [1000 + i], background=True).job_id for i in range(5)]
        assert ids == [1, 2, 3, 4, 5]

    def test_new_job_is_current(self) -> None:
        jt = JobTable()
        jt.add_job(100, "first", [100], background=True)
        j2 = jt.add_job(200, "second", [200], background=True)
        cur = jt.get_current_job()
        assert cur is not None
        assert cur.job_id == j2.job_id

    def test_get_job_by_id(self) -> None:
        jt = JobTable()
        added = jt.add_job(111, "test cmd", [111], background=True)
        retrieved = jt.get_job(added.job_id)
        assert retrieved is not None
        assert retrieved.command_text == "test cmd"

    def test_get_job_missing_returns_none(self) -> None:
        jt = JobTable()
        assert jt.get_job(999) is None


class TestJobTableStatusTransitions:
    def test_mark_running(self) -> None:
        jt = JobTable()
        job = jt.add_job(1, "cmd", [1], background=True)
        jt.mark_stopped(job.job_id)
        assert jt.get_job(job.job_id).status == JobStatus.STOPPED  # type: ignore[union-attr]
        jt.mark_running(job.job_id)
        assert jt.get_job(job.job_id).status == JobStatus.RUNNING  # type: ignore[union-attr]

    def test_mark_stopped(self) -> None:
        jt = JobTable()
        job = jt.add_job(1, "cmd", [1], background=True)
        jt.mark_stopped(job.job_id)
        assert jt.get_job(job.job_id).status == JobStatus.STOPPED  # type: ignore[union-attr]

    def test_mark_done(self) -> None:
        jt = JobTable()
        job = jt.add_job(1, "cmd", [1], background=True)
        jt.mark_done(job.job_id, 42)
        retrieved = jt.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.status == JobStatus.DONE
        assert retrieved.last_status == 42

    def test_mark_terminated(self) -> None:
        jt = JobTable()
        job = jt.add_job(1, "cmd", [1], background=True)
        jt.mark_terminated(job.job_id, 137)
        retrieved = jt.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.status == JobStatus.TERMINATED
        assert retrieved.last_status == 137


class TestJobTableGetCurrentJob:
    def test_no_jobs_returns_none(self) -> None:
        jt = JobTable()
        assert jt.get_current_job() is None

    def test_current_job_tracks_most_recent_alive(self) -> None:
        jt = JobTable()
        j1 = jt.add_job(1, "cmd1", [1], background=True)
        j2 = jt.add_job(2, "cmd2", [2], background=True)
        assert jt.get_current_job().job_id == j2.job_id  # type: ignore[union-attr]
        jt.mark_done(j2.job_id, 0)
        assert jt.get_current_job().job_id == j1.job_id  # type: ignore[union-attr]

    def test_current_job_skips_done(self) -> None:
        jt = JobTable()
        jt.add_job(1, "cmd1", [1], background=True)
        j2 = jt.add_job(2, "cmd2", [2], background=True)
        jt.mark_done(j2.job_id, 0)
        cur = jt.get_current_job()
        assert cur is not None
        assert cur.job_id == 1


class TestJobTableFormatJobs:
    def test_empty_table_is_empty_string(self) -> None:
        jt = JobTable()
        assert jt.format_jobs() == ""

    def test_one_running_job_format(self) -> None:
        jt = JobTable()
        jt.add_job(1, "sleep 10", [1], background=True)
        output = jt.format_jobs()
        assert "[1]" in output
        assert "Running" in output
        assert "sleep 10" in output

    def test_stopped_job_format(self) -> None:
        jt = JobTable()
        job = jt.add_job(2, "vim", [2], background=False)
        jt.mark_stopped(job.job_id)
        output = jt.format_jobs()
        assert "Stopped" in output
        assert "vim" in output

    def test_current_job_marked_with_plus(self) -> None:
        jt = JobTable()
        jt.add_job(1, "first", [1], background=True)
        jt.add_job(2, "second", [2], background=True)
        output = jt.format_jobs()
        lines = output.splitlines()
        assert any("+" in ln and "second" in ln for ln in lines)

    def test_non_current_job_marked_with_space(self) -> None:
        jt = JobTable()
        jt.add_job(1, "first", [1], background=True)
        jt.add_job(2, "second", [2], background=True)
        output = jt.format_jobs()
        lines = output.splitlines()
        # First job should NOT have "+" marker
        first_line = next(ln for ln in lines if "first" in ln)
        assert "+" not in first_line


class TestJobTableRemoveDone:
    def test_remove_done_removes_completed_jobs(self) -> None:
        jt = JobTable()
        j1 = jt.add_job(1, "cmd1", [1], background=True)
        j2 = jt.add_job(2, "cmd2", [2], background=True)
        jt.mark_done(j1.job_id, 0)
        removed = jt.remove_done()
        assert len(removed) == 1
        assert removed[0].job_id == j1.job_id
        assert jt.get_job(j1.job_id) is None
        assert jt.get_job(j2.job_id) is not None

    def test_remove_done_on_empty_returns_empty(self) -> None:
        jt = JobTable()
        assert jt.remove_done() == []


# ---------------------------------------------------------------------------
# C. Shell integration (non-PTY) — background execution and job builtins
# ---------------------------------------------------------------------------


class TestBackgroundExecution:
    def test_background_sleep_returns_zero_immediately(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute(f"{sys.executable} -c 'import time; time.sleep(0.1)' &")
        assert status == 0

    def test_background_command_completes_without_blocking(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        start = time.monotonic()
        shell.execute(f"{sys.executable} -c 'import time; time.sleep(0.2)' &")
        elapsed = time.monotonic() - start
        assert elapsed < 0.15, f"Background command blocked for {elapsed:.3f}s"

    def test_background_registers_in_job_table(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'import time; time.sleep(0.1)' &")
        assert not shell.job_table.is_empty()

    def test_background_job_has_correct_command_text(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        cmd = f"{sys.executable} -c 'import time; time.sleep(0.1)'"
        shell.execute(f"{cmd} &")
        jobs = shell.job_table.all_jobs()
        assert len(jobs) == 1
        assert jobs[0].command_text == cmd

    def test_background_then_foreground_command(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute(
            f"{sys.executable} -c 'import time; time.sleep(0.1)' & echo done"
        )
        assert status == 0

    def test_false_background_eventually_marks_done(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'raise SystemExit(1)' &")
        # Wait for child to exit then reap
        time.sleep(0.15)
        shell._reap_and_notify_jobs()
        jobs = shell.job_table.all_jobs()
        assert len(jobs) > 0
        assert jobs[0].status == JobStatus.DONE
        assert jobs[0].last_status == 1


class TestJobsBuiltin:
    def test_jobs_with_no_jobs_returns_zero(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("jobs")
        assert status == 0

    def test_jobs_lists_running_job(self, capsys: pytest.CaptureFixture[str]) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'import time; time.sleep(0.3)' &")
        shell.execute("jobs")
        out = capsys.readouterr().out
        assert "[1]" in out

    def test_jobs_shows_done_then_removes(self, capsys: pytest.CaptureFixture[str]) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'raise SystemExit(0)' &")
        time.sleep(0.1)
        shell._reap_and_notify_jobs()
        shell.execute("jobs")
        # After jobs display, done jobs should be removed.
        assert shell.job_table.is_empty()


class TestFgBuiltin:
    def test_fg_no_jobs_returns_one(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("fg")
        assert status == 1

    def test_fg_unknown_numeric_job_id_returns_one(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("fg 999")
        assert status == 1  # runtime error: no such job

    def test_fg_percent_job_id_format(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("fg %999")
        assert status == 1  # %N is accepted; job not found → 1


class TestBgBuiltin:
    def test_bg_no_jobs_returns_one(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("bg")
        assert status == 1

    def test_bg_unknown_numeric_job_id_returns_one(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute("bg 999")
        assert status == 1  # runtime error: no such job

    def test_bg_running_job_not_stopped_returns_one(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'import time; time.sleep(0.5)' &")
        status = shell.execute("bg 1")
        assert status == 1  # job is Running, not Stopped


# ---------------------------------------------------------------------------
# D. Capability probes and helpers
# ---------------------------------------------------------------------------


class TestJobControlHelpers:
    def test_has_job_control_returns_bool(self) -> None:
        result = has_job_control()
        assert isinstance(result, bool)

    def test_has_tcsetpgrp_returns_bool(self) -> None:
        result = has_tcsetpgrp()
        assert isinstance(result, bool)

    def test_sigtstp_number_is_positive(self) -> None:
        n = sigtstp_number()
        assert n > 0

    def test_sigtstp_exit_status_is_128_plus_sigtstp(self) -> None:
        assert sigtstp_exit_status() == 128 + sigtstp_number()

    def test_raw_to_exit_normal(self) -> None:
        # Simulate a raw status for exit(7): WIFEXITED + WEXITSTATUS
        # On Linux, normal exit: raw_status = (exit_code << 8)
        raw = 7 << 8
        result = _raw_to_exit(raw)
        assert result == 7

    def test_raw_to_exit_signal(self) -> None:
        # Simulate signal kill: raw_status = signum (for SIGTERM=15)
        raw = signal.SIGTERM  # lower bits = signal number
        result = _raw_to_exit(raw)
        assert result == 128 + int(signal.SIGTERM)

    def test_open_tty_returns_none_or_int(self) -> None:
        fd = open_tty()
        if fd is not None:
            assert isinstance(fd, int)
            os.close(fd)

    def test_make_child_preexec_is_callable(self) -> None:
        assert callable(make_child_preexec)

    def test_reset_child_job_control_signals_resets_terminal_stop_signals(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reset: list[int] = []

        def fake_signal(sig: signal.Signals, handler: signal.Handlers) -> None:
            assert handler is signal.SIG_DFL
            reset.append(int(sig))

        monkeypatch.setattr(signal, "signal", fake_signal)
        reset_child_job_control_signals()

        assert int(signal.SIGINT) in reset
        assert int(signal.SIGQUIT) in reset
        assert int(signal.SIGTSTP) in reset
        assert int(signal.SIGTTIN) in reset
        assert int(signal.SIGTTOU) in reset

    def test_tcsetpgrp_safely_ignores_terminal_stop_signals(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[int, signal.Handlers]] = []
        tcsetpgrp_calls: list[tuple[int, int]] = []

        def fake_getsignal(sig: signal.Signals) -> signal.Handlers:
            return signal.SIG_DFL

        def fake_signal(sig: signal.Signals, handler: signal.Handlers) -> None:
            calls.append((int(sig), handler))

        def fake_tcsetpgrp(fd: int, pgid: int) -> None:
            tcsetpgrp_calls.append((fd, pgid))

        monkeypatch.setattr(signal, "getsignal", fake_getsignal)
        monkeypatch.setattr(signal, "signal", fake_signal)
        monkeypatch.setattr(os, "tcsetpgrp", fake_tcsetpgrp)
        monkeypatch.setattr(os, "tcgetpgrp", lambda fd: 1234)

        assert tcsetpgrp_safely(7, 99)
        assert tcsetpgrp_calls == [(7, 99)]
        assert (int(signal.SIGTTIN), signal.SIG_IGN) in calls
        assert (int(signal.SIGTTOU), signal.SIG_IGN) in calls
        assert calls[-2:] == [
            (int(signal.SIGTTOU), signal.SIG_DFL),
            (int(signal.SIGTTIN), signal.SIG_DFL),
        ]


# ---------------------------------------------------------------------------
# E. Regression guard — existing behavior unchanged
# ---------------------------------------------------------------------------


class TestRegressionOperators:
    """Existing && || ; | operators still work after Issue #11 changes."""

    def test_and_operator(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        assert shell.execute("true && true") == 0
        assert shell.execute("false && true") == 1

    def test_or_operator(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        assert shell.execute("false || true") == 0
        assert shell.execute("true || false") == 0

    def test_semicolon_chain(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        assert shell.execute("true; false") == 1

    def test_exit_status_propagation(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'raise SystemExit(7)'")
        assert shell.last_status == 7

    def test_amp_redirection_still_works(self) -> None:
        import tempfile

        from pysh.core.shell import PyShell
        shell = PyShell()
        with tempfile.NamedTemporaryFile(delete=True, suffix=".txt") as tmp:
            status = shell.execute(f"echo hello &> {tmp.name}")
            assert status == 0

    def test_dollar_question_propagates(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'raise SystemExit(42)'")
        assert shell.last_status == 42


class TestRegressionSignals:
    """Signal behavior from Issue #6 is unchanged."""

    def test_sigint_child_gives_130(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute(
            f"{sys.executable} -c 'import signal,os; os.kill(os.getpid(), signal.SIGINT)'"
        )
        assert status == 130

    def test_sigterm_child_gives_143(self) -> None:
        from pysh.core.shell import PyShell
        shell = PyShell()
        status = shell.execute(
            f"{sys.executable} -c 'import signal,os; os.kill(os.getpid(), signal.SIGTERM)'"
        )
        assert status == 143


class TestRegressionBuiltins:
    """Existing builtins still dispatch correctly."""

    def test_cd_and_pwd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pysh.core.shell import PyShell

        monkeypatch.chdir("/")
        shell = PyShell()
        status = shell.execute("cd /tmp && pwd")
        assert status == 0

    def test_jobs_fg_bg_in_builtins_set(self) -> None:
        from pysh.core.shell import PyShell
        assert "jobs" in PyShell.BUILTINS
        assert "fg" in PyShell.BUILTINS
        assert "bg" in PyShell.BUILTINS
