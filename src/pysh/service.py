# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/service.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Minimal PyInit service client used by the ``svc`` builtin.

This module is intentionally small and side-effect-light. It implements
PID-file based status checks and signal delivery so the shell can offer a
useful subset of service control even when no PyInit control socket is
present. The full launch/restart story still requires PyInit supervision,
and ``svc start`` returns a deterministic unsupported error when no control
interface has been registered.

The runtime root (the directory holding ``*.pid`` files) is configurable so
tests can use a temporary path without touching ``/run/pyinit``.
"""
from __future__ import annotations

import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PID_ROOT = Path("/run/pyinit")


class ServiceError(RuntimeError):
    """Raised by the service client on user-visible failures."""


@dataclass(frozen=True)
class ServiceStatus:
    """Snapshot of a single service's runtime state."""

    name: str
    pid: int | None
    active: bool


def _read_pid(pid_file: Path) -> int | None:
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text.split()[0])
    except ValueError:
        return None


def _default_alive_check(pid: int) -> bool:
    """Return True if signal 0 to ``pid`` succeeds (process exists)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user.
        return True
    except OSError:
        return False
    return True


def _default_signal(pid: int, sig: int) -> None:
    os.kill(pid, sig)


class ServiceController:
    """Abstract hook for an external PyInit control interface.

    PySH does not ship a control-plane implementation. A site-specific
    integration may subclass :class:`ServiceController` and pass an instance
    to :class:`ServiceClient` to gain ``svc start`` / ``svc restart`` support.
    """

    def start(self, name: str) -> None:  # pragma: no cover - abstract hook
        raise ServiceError(
            f"{name}: ServiceController.start is not implemented"
        )


class ServiceClient:
    """Thin PID-file based service control client."""

    def __init__(
        self,
        pid_root: Path = DEFAULT_PID_ROOT,
        *,
        alive_check: Callable[[int], bool] | None = None,
        signaler: Callable[[int, int], None] | None = None,
        controller: ServiceController | None = None,
    ) -> None:
        self.pid_root = Path(pid_root)
        self._alive_check = alive_check or _default_alive_check
        self._signaler = signaler or _default_signal
        self._controller = controller

    # ----------------------------------------------------------------- query
    def list_services(self) -> list[ServiceStatus]:
        """Return a status snapshot for each ``*.pid`` file under the root."""
        if not self.pid_root.exists() or not self.pid_root.is_dir():
            return []
        try:
            entries = sorted(self.pid_root.iterdir(), key=lambda p: p.name)
        except OSError:
            return []
        out: list[ServiceStatus] = []
        for entry in entries:
            if not entry.is_file() or entry.suffix != ".pid":
                continue
            name = entry.stem
            out.append(self._status_for(name, entry))
        return out

    def status(self, name: str) -> ServiceStatus:
        return self._status_for(name, self._pid_path(name))

    def _status_for(self, name: str, pid_file: Path) -> ServiceStatus:
        pid = _read_pid(pid_file)
        if pid is None:
            return ServiceStatus(name=name, pid=None, active=False)
        return ServiceStatus(name=name, pid=pid, active=self._alive_check(pid))

    # ----------------------------------------------------------------- mutate
    def stop(self, name: str) -> ServiceStatus:
        status = self.status(name)
        if status.pid is None:
            raise ServiceError(f"{name}: no pid file")
        if not status.active:
            return status
        try:
            self._signaler(status.pid, signal.SIGTERM)
        except ProcessLookupError as exc:
            raise ServiceError(f"{name}: process not found") from exc
        except PermissionError as exc:
            raise ServiceError(f"{name}: permission denied") from exc
        return self.status(name)

    def restart(self, name: str) -> ServiceStatus:
        """Attempt to restart ``name``.

        Without a PyInit control interface only SIGTERM is delivered and a
        diagnostic is raised so the user knows supervision is required to
        actually re-launch the process.
        """
        self.stop(name)
        if self._controller is None:
            raise ServiceError(
                f"{name}: restart requires PyInit supervision "
                "(no control interface configured)"
            )
        self._controller.start(name)
        return self.status(name)

    def start(self, name: str) -> ServiceStatus:
        if self._controller is None:
            raise ServiceError(
                f"{name}: start requires a PyInit control interface"
            )
        self._controller.start(name)
        return self.status(name)

    # ----------------------------------------------------------------- helpers
    def _pid_path(self, name: str) -> Path:
        return self.pid_root / f"{name}.pid"


# --------------------------------------------------------------- CLI helpers
def format_status(status: ServiceStatus) -> str:
    state = "active" if status.active else "dead"
    pid_str = f"pid={status.pid}" if status.pid is not None else "pid=-"
    return f"{status.name}\t{state}\t{pid_str}"


def format_list(statuses: list[ServiceStatus]) -> str:
    if not statuses:
        return "no services"
    return "\n".join(format_status(s) for s in statuses)
