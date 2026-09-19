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

The one property every caller depends on: this never blocks indefinitely.
Every read of the PTY master is gated by ``select.select()`` on a shrinking
remaining-time budget, so a child that produces no output and never exits
cannot hang this process -- it is killed, reaped, and a deterministic
timeout result is returned instead. (Issue #33: a bare
``while time.monotonic() < deadline: os.read(master_fd, ...)`` loop -- the
pattern this module replaces -- checks the deadline only *between* calls;
the blocking ``os.read()`` call itself has no timeout, and once entered
cannot be interrupted by that check. That gap did not matter on the
platforms where the child reliably closed the PTY promptly, but a real
FreeBSD `workflow_dispatch` run hung for over an hour at exactly this call
when it did not.)

No third-party dependencies (no pexpect); no threads used to implement the
timeout -- select() on the file descriptor is the only synchronization
primitive.
"""
from __future__ import annotations

import dataclasses
import os
import pty
import select
import subprocess
import sys
import time

DEFAULT_TIMEOUT = 10.0


@dataclasses.dataclass
class PtyResult:
    """The deterministic outcome of one bounded PTY session."""

    returncode: int | None
    output: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return (
            not self.timed_out
            and self.returncode == 0
            and "Traceback" not in self.output
        )


def run_pty_command(
    argv: list[str], input_line: str, timeout: float = DEFAULT_TIMEOUT
) -> PtyResult:
    """Run *argv* under a real PTY, send *input_line*, and return within
    *timeout* seconds no matter what the child does.

    On a normal exit, the child closes its end of the PTY, ``os.read()``
    eventually returns ``b""`` (EOF), and the loop ends promptly. On a
    stuck or non-exiting child, the absolute deadline expires, the child is
    killed and reaped, and the result reports ``timed_out=True`` -- this
    function itself never raises `subprocess.TimeoutExpired` and never
    blocks past *timeout* plus a bounded child-teardown grace period.
    """
    deadline = time.monotonic() + timeout
    master_fd, slave_fd = pty.openpty()
    proc: subprocess.Popen[bytes] | None = None
    output = b""
    timed_out = False
    drained_after_exit = False

    try:
        proc = subprocess.Popen(
            argv, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True
        )
        os.close(slave_fd)
        slave_fd = -1

        os.write(master_fd, (input_line + "\n").encode())

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break

            exited = proc.poll() is not None
            # A short grace window drains any final buffered output once
            # the child has exited, instead of waiting out the full
            # remaining budget merely to confirm there is nothing left.
            wait_for = min(remaining, 0.5) if exited else remaining

            readable, _, _ = select.select([master_fd], [], [], wait_for)
            if readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                continue

            if exited:
                if drained_after_exit:
                    break
                drained_after_exit = True
                continue
            # Nothing readable yet and the child hasn't exited: loop back
            # to re-check the deadline and exit status.
    finally:
        if slave_fd != -1:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        if proc is not None and proc.poll() is None:
            timed_out = True
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
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
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: pty_smoke.py TIMEOUT_SECONDS INPUT_LINE PROGRAM [ARGS...]",
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

    result = run_pty_command(program_argv, input_line, timeout=timeout)
    print(
        f"PTY interactive {input_line!r}: rc={result.returncode} "
        f"timed_out={result.timed_out}"
    )

    if result.timed_out:
        print(
            f"PTY FAIL: {input_line!r} did not exit within {timeout:.0f}s "
            f"(process killed); output={result.output!r}",
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
