# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/events.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Secret-free event seam for later structured audit integration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IsolatedPluginEventKind(StrEnum):
    """Lifecycle and authorization decisions exposed to Issue #50."""

    SPAWN = "spawn"
    HANDSHAKE = "handshake"
    RUNNING = "running"
    DENIED = "denied"
    FAILURE = "failure"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class IsolatedPluginEvent:
    """Bounded event metadata that never contains child payload values."""

    kind: IsolatedPluginEventKind
    plugin_name: str
    requested_capabilities: tuple[str, ...] = ()
    granted_capabilities: tuple[str, ...] = ()
    operation: str | None = None
    reason_code: str | None = None
