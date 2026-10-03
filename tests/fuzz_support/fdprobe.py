# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/fdprobe.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Portable descriptor-leak probe: a bounded ``os.fstat`` scan (Issue #49).

Uses only ``os.fstat`` and ``resource.RLIMIT_NOFILE``; it never reads
``/proc/self/fd`` or ``/dev/fd``. On FreeBSD ``/dev/fd`` lists only 0-2 unless
``fdescfs`` is mounted, so a leak check built on it can pass vacuously; the scan
here observes the descriptor table itself on Linux and FreeBSD alike.

Semantics (platform contract, ``docs/compatibility/platform-tiers.md``):

* ``EBADF`` means "closed"; any other ``OSError`` is a probe failure
  (:class:`ProbeFailure`) and is never converted to "no descriptors open".
* If the soft limit cannot be read, the probe raises :class:`ProbeUnavailable`;
  that is a distinct outcome and must not be treated as "no leak".
* Scan range is ``0 .. min(soft RLIMIT_NOFILE, SCAN_CAP) - 1``. ``SCAN_CAP`` is
  4096: descriptors are allocated lowest-first, and the repository's tests
  keep at most a few dozen descriptors open, so a leaked descriptor always lands
  far below the cap, while an unlimited or huge ``RLIMIT_NOFILE`` cannot cause
  a huge scan. An open descriptor numbered at or above the cap is outside the
  evidence boundary (stated, not hidden).
"""
from __future__ import annotations

import contextlib
import errno
import os
import stat
from collections.abc import Iterator

try:  # POSIX only; absence is reported as "unavailable", never as success
    import resource
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None  # type: ignore[assignment]

SCAN_CAP = 4096


class ProbeUnavailable(RuntimeError):
    """Deterministic probing is impossible here; never equivalent to "no leak"."""


class ProbeFailure(RuntimeError):
    """The probe itself failed unexpectedly (a harness defect)."""


def scan_limit(cap: int = SCAN_CAP) -> int:
    """Return the exclusive upper bound of the scan: ``min(soft NOFILE, cap)``."""
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise ValueError("cap must be a positive integer")
    if resource is None:
        raise ProbeUnavailable("the resource module is unavailable")
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError) as error:
        raise ProbeUnavailable(f"cannot read RLIMIT_NOFILE: {error}") from error
    if soft == resource.RLIM_INFINITY:
        return cap
    return min(int(soft), cap)


def open_fds(limit: int | None = None) -> frozenset[int]:
    """Return the exact set of open descriptors in ``0 .. limit - 1``."""
    bound = scan_limit() if limit is None else limit
    found: set[int] = set()
    for fd in range(bound):
        try:
            os.fstat(fd)
        except OSError as error:
            if error.errno == errno.EBADF:
                continue
            raise ProbeFailure(f"fstat({fd}) failed unexpectedly: {error}") from error
        found.add(fd)
    return frozenset(found)


def describe(fd: int) -> str:
    """Short, stable description of one descriptor for failure messages."""
    try:
        info = os.fstat(fd)
    except OSError as error:
        return f"fd {fd}: closed ({error.errno})"
    kind = (
        "fifo" if stat.S_ISFIFO(info.st_mode) else
        "regular" if stat.S_ISREG(info.st_mode) else
        "socket" if stat.S_ISSOCK(info.st_mode) else
        "chr" if stat.S_ISCHR(info.st_mode) else
        "dir" if stat.S_ISDIR(info.st_mode) else "other"
    )
    return f"fd {fd}: {kind} inheritable={os.get_inheritable(fd)}"


def inheritable_fds(fds: frozenset[int]) -> frozenset[int]:
    """Subset of ``fds`` that a child would inherit across ``exec``."""
    return frozenset(fd for fd in fds if os.get_inheritable(fd))


@contextlib.contextmanager
def no_fd_growth(label: str = "operation") -> Iterator[None]:
    """Assert the open-descriptor set is unchanged after the block (even on error)."""
    before = open_fds()
    try:
        yield
    finally:
        after = open_fds()
        leaked = sorted(after - before)
        closed = sorted(before - after)
        if leaked or closed:
            details = ", ".join(describe(fd) for fd in leaked) or "-"
            raise AssertionError(
                f"{label}: descriptor set changed; leaked={leaked} ({details}); closed={closed}"
            )
