# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/core/jobs.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Job control module for PySH (Issue #11).

Defines the job table, job status model, and POSIX job-control helpers used
by the interactive shell.

Rules:
- Standard library only.  No pysh implementation imports.
- No terminal I/O at import time.
- No subprocess calls at import time.
- No signal registration at import time.
- No config loading.
- All public functions are pure and deterministic where possible.
"""
from __future__ import annotations

import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    """Current lifecycle state of a PySH job."""

    RUNNING = "Running"
    STOPPED = "Stopped"
    DONE = "Done"
    TERMINATED = "Terminated"


# ---------------------------------------------------------------------------
# Job record
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """A background or suspended job tracked by the shell.

    ``pids`` is the list of process IDs in this job (one for simple commands,
    multiple for pipelines).  All processes share ``pgid``.
    ``last_status`` is the PySH exit status of the last completed/stopped step.
    """

    job_id: int
    pgid: int
    command_text: str
    pids: list[int] = field(default_factory=list)
    status: JobStatus = JobStatus.RUNNING
    last_status: int = 0
    background: bool = True

    def is_alive(self) -> bool:
        """Return True when the job may still have running processes."""
        return self.status in (JobStatus.RUNNING, JobStatus.STOPPED)


# ---------------------------------------------------------------------------
# Job table
# ---------------------------------------------------------------------------


class JobTable:
    """In-process job table for PySH job control.

    Job IDs are monotonically increasing positive integers.
    The current job is the most recently added alive job.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._next_id: int = 1
        self._current_job_id: int | None = None

    # ---------------------------------------------------------------- mutation

    def add_job(
        self,
        pgid: int,
        command_text: str,
        pids: list[int],
        *,
        background: bool,
    ) -> Job:
        """Add a new job and return it.  The new job becomes the current job."""
        job_id = self._next_id
        self._next_id += 1
        job = Job(
            job_id=job_id,
            pgid=pgid,
            command_text=command_text,
            pids=list(pids),
            status=JobStatus.RUNNING,
            background=background,
        )
        self._jobs[job_id] = job
        self._current_job_id = job_id
        return job

    def mark_running(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.RUNNING

    def mark_stopped(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.STOPPED

    def mark_done(self, job_id: int, last_status: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.DONE
            job.last_status = last_status

    def mark_terminated(self, job_id: int, last_status: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.TERMINATED
            job.last_status = last_status

    # ---------------------------------------------------------------- queries

    def get_job(self, job_id: int) -> Job | None:
        """Return the job with ``job_id``, or None."""
        return self._jobs.get(job_id)

    def get_current_job(self) -> Job | None:
        """Return the current (most recently added alive) job, or None."""
        if self._current_job_id is not None:
            job = self._jobs.get(self._current_job_id)
            if job is not None and job.is_alive():
                return job
        # Fall back to the most recently added alive job.
        for job_id in sorted(self._jobs.keys(), reverse=True):
            job = self._jobs[job_id]
            if job.is_alive():
                return job
        return None

    def all_jobs(self) -> list[Job]:
        """Return all tracked jobs in job-id order."""
        return sorted(self._jobs.values(), key=lambda j: j.job_id)

    def is_empty(self) -> bool:
        return len(self._jobs) == 0

    # ---------------------------------------------------------------- lifecycle

    def remove_done(self) -> list[Job]:
        """Remove and return Done/Terminated jobs."""
        done = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.DONE, JobStatus.TERMINATED)
        ]
        for j in done:
            del self._jobs[j.job_id]
        if self._current_job_id not in self._jobs:
            self._current_job_id = None
        return done

    def reap_background_jobs(self) -> list[tuple[Job, int]]:
        """Non-blocking check for completed background jobs.

        Calls ``os.waitpid`` with ``WNOHANG`` for each running job's pids.
        Returns a list of ``(job, exit_status)`` for jobs that have now
        transitioned to Done.  Does not remove them from the table.
        """
        reaped: list[tuple[Job, int]] = []
        wnohang = getattr(os, "WNOHANG", 1)
        wuntraced = getattr(os, "WUNTRACED", 2)
        flags = wnohang | wuntraced

        for job in list(self._jobs.values()):
            if job.status != JobStatus.RUNNING:
                continue

            alive_pids: list[int] = []
            last_exit = job.last_status
            stopped = False

            for pid in job.pids:
                try:
                    res_pid, raw = os.waitpid(pid, flags)
                except ChildProcessError:
                    # Already reaped.
                    continue
                except OSError:
                    alive_pids.append(pid)
                    continue

                if res_pid == 0:
                    alive_pids.append(pid)
                    continue

                if _wifstopped(raw):
                    stopped = True
                    alive_pids.append(pid)
                else:
                    last_exit = _raw_to_exit(raw)

            if stopped:
                job.status = JobStatus.STOPPED
                job.pids = alive_pids
                continue

            job.pids = alive_pids
            if not alive_pids:
                job.status = JobStatus.DONE
                job.last_status = last_exit
                reaped.append((job, last_exit))

        return reaped

    # ---------------------------------------------------------------- display

    def format_jobs(self) -> str:
        """Return a deterministic multi-line job listing string.

        Format per line::

            [N]+ Status      command_text
            [N]  Status      command_text
        """
        lines: list[str] = []
        for job in self.all_jobs():
            current = "+" if job.job_id == self._current_job_id else " "
            lines.append(
                f"[{job.job_id}]{current} {job.status.value:<12}{job.command_text}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Platform capability probes
# ---------------------------------------------------------------------------


def has_job_control() -> bool:
    """Return True when POSIX process-group APIs are available."""
    return hasattr(os, "setpgid") and hasattr(os, "getpgrp")


def has_tcsetpgrp() -> bool:
    """Return True when terminal process-group APIs are available."""
    return hasattr(os, "tcsetpgrp") and hasattr(os, "tcgetpgrp")


def open_tty() -> int | None:
    """Open /dev/tty for job control.  Return an fd or None on failure.

    The fd is opened with O_CLOEXEC so children do not inherit it.
    """
    try:
        return os.open("/dev/tty", os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None


def _job_control_signals() -> tuple[signal.Signals, ...]:
    """Return child job-control signals that must use default disposition."""
    names = ("SIGINT", "SIGQUIT", "SIGTSTP", "SIGTTIN", "SIGTTOU", "SIGCHLD")
    found: list[signal.Signals] = []
    for name in names:
        sig = getattr(signal, name, None)
        if sig is not None:
            found.append(sig)
    return tuple(found)


def reset_child_job_control_signals() -> None:
    """Reset inherited shell signal dispositions in a child before exec."""
    for sig in _job_control_signals():
        try:
            signal.signal(sig, signal.SIG_DFL)
        except OSError:
            pass


@contextmanager
def _ignore_terminal_stop_signals() -> Iterator[None]:
    """Ignore SIGTTIN/SIGTTOU while the shell changes terminal ownership."""
    saved: list[tuple[signal.Signals, signal.Handlers]] = []
    for name in ("SIGTTIN", "SIGTTOU"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous = signal.getsignal(sig)
            signal.signal(sig, signal.SIG_IGN)
        except OSError:
            continue
        saved.append((sig, previous))
    try:
        yield
    finally:
        for sig, previous in reversed(saved):
            try:
                signal.signal(sig, previous)
            except OSError:
                pass


def tcsetpgrp_safely(tty_fd: int, pgid: int) -> bool:
    """Set terminal foreground process group without stopping the shell.

    POSIX terminals can deliver SIGTTOU/SIGTTIN to background process groups
    that manipulate terminal foreground ownership.  PySH must ignore those
    signals only around tcsetpgrp, then restore the previous dispositions.
    """
    if not has_tcsetpgrp():
        return False
    try:
        with _ignore_terminal_stop_signals():
            os.tcsetpgrp(tty_fd, pgid)
    except OSError:
        return False
    return True


def sigtstp_number() -> int:
    """Return the SIGTSTP signal number (platform-portable)."""
    return int(signal.SIGTSTP)


def sigtstp_exit_status() -> int:
    """Return the PySH exit status for a SIGTSTP-stopped foreground job (148)."""
    return 128 + sigtstp_number()


# ---------------------------------------------------------------------------
# Raw waitpid status helpers
# ---------------------------------------------------------------------------


def _wifstopped(raw: int) -> bool:
    if hasattr(os, "WIFSTOPPED"):
        return bool(os.WIFSTOPPED(raw))
    return False


def _raw_to_exit(raw: int) -> int:
    """Convert os.waitpid raw status to a PySH exit status integer."""
    if hasattr(os, "WIFEXITED") and os.WIFEXITED(raw):
        return os.WEXITSTATUS(raw)
    if hasattr(os, "WIFSIGNALED") and os.WIFSIGNALED(raw):
        return 128 + os.WTERMSIG(raw)
    return 1


# ---------------------------------------------------------------------------
# Child preexec helper
# ---------------------------------------------------------------------------


def make_child_preexec() -> None:
    """Callable passed as subprocess preexec_fn for external commands.

    Puts the child in a new process group and resets signal dispositions
    so the child receives SIGTSTP / SIGINT / SIGQUIT from the terminal.
    This function runs *in the child* after fork but before exec.
    """
    os.setpgrp()
    reset_child_job_control_signals()
