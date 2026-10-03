# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/execution.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deterministic fault injection and descriptor/child accounting for shell execution tests.

Only structured, known-safe cases run here (see ``engines.PipelineCase``); arbitrary
fuzz bytes never reach these destructive paths.
"""
from __future__ import annotations

import contextlib
import errno
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from tests.fuzz_support import fdprobe

_REAL = {name: getattr(os, name) for name in ("fork", "pipe", "dup", "dup2", "open")}
_ERRNO = {"fork": errno.EAGAIN, "pipe": errno.EMFILE, "dup": errno.EMFILE,
          "dup2": errno.EBADF, "open": errno.EMFILE}


class FaultInjector:
    """Raise one ``OSError`` at the ``index``-th call of one ``os`` operation.

    Counting starts when the injector is entered, so only calls made by the code
    under test are numbered. Forked children inherit the wrapper and its counter.
    Every successful ``fork`` is recorded in ``child_pids``.
    """

    def __init__(self, fault: tuple[str, int] | None) -> None:
        self.fault = fault
        self.calls = {name: 0 for name in _REAL}
        self.child_pids: list[int] = []
        self.fired = False

    def _wrap(self, name: str):
        real = _REAL[name]

        def wrapper(*args, **kwargs):
            index = self.calls[name]
            self.calls[name] += 1
            if self.fault == (name, index):
                self.fired = True
                raise OSError(_ERRNO[name], f"injected {name} failure")
            result = real(*args, **kwargs)
            if name == "fork" and result:
                self.child_pids.append(result)
            return result

        return wrapper

    @contextlib.contextmanager
    def active(self) -> Iterator[FaultInjector]:
        with contextlib.ExitStack() as stack:
            for name in _REAL:
                stack.enter_context(mock.patch.object(os, name, self._wrap(name)))
            yield self


def stdio_identity() -> dict[int, tuple[int, int]]:
    """``(st_dev, st_ino)`` of fds 0-2, to prove standard descriptors were restored."""
    identity = {}
    for fd in (0, 1, 2):
        info = os.fstat(fd)
        identity[fd] = (info.st_dev, info.st_ino)
    return identity


def unreaped_child() -> int | None:
    """Reap and return one leftover child pid (zombie or still running), else ``None``."""
    try:
        pid, _status = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        return None
    return pid or -1


def prepare_workdir(root: Path) -> Path:
    """Create the controlled files the structured cases refer to."""
    work = root / "work"
    work.mkdir()
    (work / "in.txt").write_text("input\n", encoding="utf-8")
    return work


def make_failing_tempfile(*_args: object, **_kwargs: object):
    raise OSError(errno.EMFILE, "injected TemporaryFile failure")


def patch_tempfile():
    return mock.patch.object(tempfile, "TemporaryFile", make_failing_tempfile)


__all__ = ["FaultInjector", "fdprobe"]
