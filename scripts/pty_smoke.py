#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/pty_smoke.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Shared, stdlib-only, strictly-bounded genuine-PTY smoke helper.

Used by scripts/smoke_debian_package.sh, scripts/smoke_rpm_package.sh, and
scripts/smoke_freebsd_package.sh to drive a real interactive pseudo-terminal
session against an installed ``pysh`` binary and prove it exits
deterministically for ``exit``/``quit`` -- on Linux (Debian, Fedora/RPM) and
on FreeBSD alike.

Two properties every caller depends on:

1. This never blocks indefinitely. Every read of the PTY master is gated by
   ``select.select()`` on a shrinking remaining-time budget, so a child that
   produces no output and never exits cannot hang this process -- it is
   killed, reaped, and a deterministic timeout result is returned instead.
   (Issue #33: a bare ``while time.monotonic() < deadline: os.read(...)``
   loop -- the pattern this module replaces -- checks the deadline only
   *between* calls; the blocking ``os.read()`` call itself has no timeout.
   That gap did not matter on platforms where the child reliably closed the
   PTY promptly, but a real FreeBSD `workflow_dispatch` run hung for over an
   hour at exactly this call when it did not.)

2. Input is not written until the child has *proven* it is ready to read it
   (``ready_marker``), when the caller supplies one. PySH's raw line editor
   calls ``tty.setraw(in_fd)`` -- whose default ``termios.TCSAFLUSH`` action
   discards any input already queued on the terminal -- before it emits the
   bracketed-paste-enable sequence (``\\x1b[?2004h``). Writing the command
   line immediately after ``Popen()`` (the old behavior) races that
   ``setraw()`` call: on a sufficiently slow or differently-scheduled
   startup, the queued command is silently discarded by TCSAFLUSH, and the
   child then waits forever at an empty prompt for input that already came
   and went. Waiting to observe the bracketed-paste-enable marker -- which
   PySH only emits *after* ``setraw()`` has already run -- proves the raw
   terminal transition is over and input written after it cannot be
   flushed away by it.

No third-party dependencies (no pexpect); no threads and no ``time.sleep()``
used for synchronization -- ``select()`` on the file descriptor, gated by one
absolute deadline covering the whole interaction (readiness wait *and*
command execution), is the only synchronization primitive.
"""
from __future__ import annotations

import dataclasses
import errno
import os
import pty
import select
import subprocess
import sys
import time

DEFAULT_TIMEOUT = 10.0

# PySH's raw line editor (src/pysh/editor/lineedit/reader.py) emits this
# immediately after tty.setraw(in_fd) succeeds, so observing it on the PTY
# proves the raw-mode transition (and its TCSAFLUSH input flush) has already
# happened -- input written after this point cannot be discarded by it.
BRACKETED_PASTE_READY_MARKER = b"\x1b[?2004h"

# A capable TERM is required to exercise PySH's default raw-editor path.
# With TERM unset or "dumb", PyShell._should_use_raw_editor() falls back
# to input() instead of RawLineReader. Because the bracketed-paste ready
# marker is emitted by RawLineReader, that fallback would make the marker
# unavailable even though stdin/stdout are attached to a genuine PTY.
#
# Disposable Docker environments may leave TERM unset, unlike a normal
# interactive terminal session, so provide a conservative terminal type
# only when the caller did not already define TERM.
DEFAULT_TERM = "xterm-256color"


@dataclasses.dataclass
class PtyResult:
    """The deterministic outcome of one bounded, optionally readiness-gated
    PTY session."""

    returncode: int | None
    output: str
    timed_out: bool
    ready: bool
    input_sent: bool

    @property
    def ok(self) -> bool:
        return (
            self.ready
            and self.input_sent
            and not self.timed_out
            and self.returncode == 0
            and "Traceback" not in self.output
        )


def _is_expected_pty_hangup(exc: OSError) -> bool:
    """Return whether *exc* is the platform's PTY-master hangup signal.

    POSIX PTY implementations report closure of the last slave descriptor
    either as an empty read or as ``EIO`` from the master.  Other errors are
    genuine harness failures and must not be silently reclassified as EOF.
    """
    return exc.errno == errno.EIO


def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort terminate *proc* and collect its process-table entry."""
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _wait_until_deadline(proc: subprocess.Popen[bytes], deadline: float) -> bool:
    """Wait for *proc* within *deadline* and report actual deadline expiry.

    The deadline is the original session deadline.  In particular, reaching
    PTY EOF/hangup never grants the child a fresh timeout budget.
    """
    if proc.poll() is not None:
        return False

    remaining = deadline - time.monotonic()
    if remaining > 0:
        try:
            proc.wait(timeout=remaining)
            return False
        except subprocess.TimeoutExpired:
            pass

    _kill_and_reap(proc)
    return True


def run_pty_command(
    argv: list[str],
    input_line: str,
    timeout: float = DEFAULT_TIMEOUT,
    ready_marker: bytes | None = None,
    env: dict[str, str] | None = None,
) -> PtyResult:
    """Run *argv* under a real PTY and return within *timeout* seconds no
    matter what the child does.

    *env* defaults to the current process environment with ``TERM`` forced
    to :data:`DEFAULT_TERM` when not already set by the caller -- a real
    terminal session always has some real ``TERM`` value, and with it
    missing or ``"dumb"`` PySH's editor selection falls back to
    ``input()`` instead of entering its raw line editor at all, so the
    bracketed-paste ready marker (which only the raw editor emits) would
    never appear even though stdin/stdout are attached to a genuine PTY.
    Pass an explicit *env* to override this, e.g. for a test that
    deliberately exercises PySH's ``input()`` fallback path.

    If *ready_marker* is ``None`` (the default), *input_line* is written
    immediately after the child is spawned, matching the simple
    fire-and-forget behavior earlier versions of this helper always used --
    suitable for a plain child that does not itself renegotiate terminal
    modes.

    If *ready_marker* is given, *input_line* is withheld until those exact
    bytes have appeared somewhere in the PTY output accumulated so far (the
    check runs against the full accumulated buffer, so a marker split
    across two separate reads is still detected once both arrive). All
    output preceding the marker is still captured in ``PtyResult.output``.
    If the marker never appears before the deadline, the command is never
    sent (``input_sent`` stays ``False``), the child is killed/reaped, and
    the result reports ``timed_out=True, ready=False``.

    Exactly one absolute deadline covers both the readiness wait and the
    post-input execution -- there is no separate budget reset after the
    marker is observed or after input is sent.

    On a normal exit, the child closes its end of the PTY. Depending on the
    host PTY implementation, ``os.read()`` then returns ``b""`` or raises
    ``EIO``. Both mean hangup, after which the child is given only the
    remaining portion of the original deadline to exit. On a stuck or
    non-exiting child, that absolute deadline expires, the child is killed
    and reaped, and the result reports ``timed_out=True`` -- this function
    itself never raises `subprocess.TimeoutExpired` and never blocks past
    *timeout* plus a bounded child-teardown grace period. Unexpected PTY I/O
    errors are surfaced to the caller after deterministic child cleanup.
    """
    child_env = dict(os.environ) if env is None else dict(env)
    child_env.setdefault("TERM", DEFAULT_TERM)

    deadline = time.monotonic() + timeout
    master_fd, slave_fd = pty.openpty()
    proc: subprocess.Popen[bytes] | None = None
    output = b""
    timed_out = False
    drained_after_exit = False
    ready = ready_marker is None
    input_sent = False

    try:
        proc = subprocess.Popen(
            argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=child_env,
        )
        os.close(slave_fd)
        slave_fd = -1

        if ready_marker is None:
            os.write(master_fd, (input_line + "\n").encode())
            input_sent = True

        while True:
            remaining = deadline - time.monotonic()
            exited = proc.poll() is not None
            if remaining <= 0:
                break

            # A short grace window drains any final buffered output once
            # the child has exited, instead of waiting out the full
            # remaining budget merely to confirm there is nothing left.
            wait_for = min(remaining, 0.5) if exited else remaining

            readable, _, _ = select.select([master_fd], [], [], wait_for)
            if readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if _is_expected_pty_hangup(exc):
                        break
                    raise
                if not chunk:
                    break
                output += chunk

                if not ready and ready_marker is not None and ready_marker in output:
                    ready = True

                if ready and not input_sent:
                    os.write(master_fd, (input_line + "\n").encode())
                    input_sent = True

                continue

            if exited:
                if drained_after_exit:
                    break
                drained_after_exit = True
                continue
            # Nothing readable yet and the child hasn't exited: loop back
            # to re-check the deadline and exit status.
        timed_out = _wait_until_deadline(proc, deadline)
    except BaseException:
        if proc is not None:
            _kill_and_reap(proc)
        raise
    finally:
        if slave_fd != -1:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass

    returncode = proc.returncode if proc is not None else None
    return PtyResult(
        returncode=returncode,
        output=output.decode(errors="replace"),
        timed_out=timed_out,
        ready=ready,
        input_sent=input_sent,
    )


def main(argv: list[str]) -> int:
    ready_marker: bytes | None = None
    if argv[:1] == ["--ready-marker-hex"]:
        if len(argv) < 2:
            print("pty_smoke.py: --ready-marker-hex requires a value", file=sys.stderr)
            return 2
        try:
            ready_marker = bytes.fromhex(argv[1])
        except ValueError:
            print(f"pty_smoke.py: invalid --ready-marker-hex value: {argv[1]!r}", file=sys.stderr)
            return 2
        argv = argv[2:]

    if len(argv) < 3:
        print(
            "usage: pty_smoke.py [--ready-marker-hex HEX] "
            "TIMEOUT_SECONDS INPUT_LINE PROGRAM [ARGS...]",
            file=sys.stderr,
        )
        return 2

    try:
        timeout = float(argv[0])
    except ValueError:
        print(f"pty_smoke.py: TIMEOUT_SECONDS must be numeric, got {argv[0]!r}", file=sys.stderr)
        return 2

    input_line = argv[1]
    program_argv = argv[2:]

    result = run_pty_command(program_argv, input_line, timeout=timeout, ready_marker=ready_marker)
    print(
        f"PTY interactive {input_line!r}: rc={result.returncode} "
        f"ready={result.ready} input_sent={result.input_sent} "
        f"timed_out={result.timed_out}"
    )

    if not result.ready:
        print(
            f"PTY FAIL: editor readiness marker not observed within {timeout:.0f}s "
            f"(command never sent, process killed); output={result.output!r}",
            file=sys.stderr,
        )
        return 1
    if result.timed_out:
        print(
            f"PTY FAIL: command sent after readiness but shell did not exit "
            f"within {timeout:.0f}s (process killed); output={result.output!r}",
            file=sys.stderr,
        )
        return 1
    if result.returncode != 0:
        print(
            f"PTY FAIL: {input_line!r} exited {result.returncode}; "
            f"output={result.output!r}",
            file=sys.stderr,
        )
        return 1
    if "Traceback" in result.output:
        print(
            f"PTY FAIL: {input_line!r} produced a traceback; "
            f"output={result.output!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
