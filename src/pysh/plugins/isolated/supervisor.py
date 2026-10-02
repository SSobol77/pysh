# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/supervisor.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Parent-side supervision primitives for governed isolated plugins (Issue #53).

Two narrow, dependency-free primitives:

* :class:`WallClockWatchdog` - an independent total-lifetime deadline on
  ``time.monotonic()``, run on one small daemon thread. It needs no signal,
  no process-global timer and no child cooperation, and it is cancelled
  deterministically (``cancel()`` joins the thread).
* :class:`ConcurrencyGovernor` - a lock-protected counter of simultaneously
  active runtimes per key, with immediate fail-closed acquisition (no queue,
  no waiting) and idempotent permits.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pysh.plugins.isolated.errors import ResourcePolicyError

__all__ = [
    "DEFAULT_CONCURRENCY_GOVERNOR",
    "ConcurrencyGovernor",
    "ConcurrencyPermit",
    "WallClockWatchdog",
]


class WallClockWatchdog:
    """Fire ``on_expire`` once when ``time.monotonic()`` reaches ``deadline``.

    ``cancel()`` is idempotent, safe from any thread (including the watchdog's
    own callback), and joins the thread unless called from it. After
    ``cancel()`` returns, ``on_expire`` will not *start*; a callback already
    running is not interrupted.
    """

    THREAD_NAME = "pysh-isolated-watchdog"

    def __init__(self, deadline: float, on_expire: Callable[[], None]) -> None:
        self._deadline = deadline
        self._on_expire = on_expire
        self._cancelled = threading.Event()
        self._gate = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=self.THREAD_NAME, daemon=True)

    def start(self) -> None:
        """Start the watchdog thread."""
        self._thread.start()

    @property
    def alive(self) -> bool:
        """Return whether the watchdog thread is still running."""
        return self._thread.is_alive()

    def cancel(self) -> None:
        """Cancel the deadline and release the thread."""
        self._cancelled.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join()

    def _run(self) -> None:
        while not self._cancelled.is_set():
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                break
            self._cancelled.wait(remaining)
        with self._gate:
            if self._cancelled.is_set():
                return
        self._on_expire()


class ConcurrencyPermit:
    """One acquired slot; ``release()`` is idempotent and thread-safe."""

    __slots__ = ("_governor", "_key", "_released")

    def __init__(self, governor: ConcurrencyGovernor, key: str) -> None:
        self._governor = governor
        self._key = key
        self._released = False

    def release(self) -> None:
        """Return the slot exactly once."""
        self._governor._release(self, self._key)  # noqa: SLF001 - same module, narrow seam


class ConcurrencyGovernor:
    """Count active runtimes per key; refuse immediately beyond the limit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}

    def acquire(self, key: str, limit: int) -> ConcurrencyPermit:
        """Take a slot or raise ``ResourcePolicyError``; never blocks or queues."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ResourcePolicyError("concurrency limit must be a positive integer")
        with self._lock:
            active = self._active.get(key, 0)
            if active >= limit:
                raise ResourcePolicyError(
                    f"concurrency limit of {limit} active runtime(s) reached"
                )
            self._active[key] = active + 1
        return ConcurrencyPermit(self, key)

    def active(self, key: str) -> int:
        """Return the number of active permits for ``key``."""
        with self._lock:
            return self._active.get(key, 0)

    def total_active(self) -> int:
        """Return the number of active permits across all keys."""
        with self._lock:
            return sum(self._active.values())

    def _release(self, permit: ConcurrencyPermit, key: str) -> None:
        with self._lock:
            if permit._released:  # noqa: SLF001
                return
            permit._released = True  # noqa: SLF001
            remaining = self._active.get(key, 0) - 1
            if remaining > 0:
                self._active[key] = remaining
            else:
                self._active.pop(key, None)


#: Process-wide governor used by runtimes unless one is injected.
DEFAULT_CONCURRENCY_GOVERNOR = ConcurrencyGovernor()
