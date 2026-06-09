# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/models.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Dataclasses and enums for the Plugin API subsystem."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

CommandHandler = Callable[[list[str]], int]
CompleterCallback = Callable[[list[str], int], list[str]]
PromptRenderer = Callable[[], str | None]
StartupHook = Callable[[], None]
ShutdownHook = Callable[[], None]
EnvChangeHook = Callable[[str, str | None, str | None], None]

PROMPT_POSITIONS: frozenset[str] = frozenset({"before_cwd", "after_git", "end"})


class PluginSource(StrEnum):
    """Source location for a plugin candidate."""

    USER = "user"
    PROJECT = "project"


class PluginState(StrEnum):
    """Lifecycle state for a plugin candidate."""

    DISCOVERED = "discovered"
    DISABLED = "disabled"
    LOADED = "loaded"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginInfo:
    """Validated public plugin metadata."""

    name: str
    version: str
    api_version: tuple[int, int]
    description: str = ""
    author: str = ""


@dataclass(frozen=True)
class PluginCandidate:
    """One discovered plugin file."""

    path: Path
    source: PluginSource
    discovery_name: str


@dataclass
class PluginRecord:
    """Mutable registry record for one plugin name/source pair."""

    candidate: PluginCandidate
    state: PluginState = PluginState.DISCOVERED
    info: PluginInfo | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginCommand:
    """Registered plugin command."""

    name: str
    plugin_name: str
    handler: CommandHandler


@dataclass(frozen=True)
class PluginCompleter:
    """Registered command-specific plugin completer."""

    command_name: str
    plugin_name: str
    completer: CompleterCallback


@dataclass(frozen=True)
class PluginPromptSegment:
    """Registered plugin prompt segment."""

    name: str
    plugin_name: str
    renderer: PromptRenderer
    position: str = "end"


@dataclass
class PluginRegistrationBundle:
    """Staged registrations for one plugin load transaction."""

    plugin_name: str
    commands: dict[str, PluginCommand] = field(default_factory=dict)
    completers: dict[str, PluginCompleter] = field(default_factory=dict)
    prompt_segments: list[PluginPromptSegment] = field(default_factory=list)
    startup_hooks: list[tuple[str, StartupHook]] = field(default_factory=list)
    shutdown_hooks: list[tuple[str, ShutdownHook]] = field(default_factory=list)
    env_hooks: list[tuple[str, EnvChangeHook]] = field(default_factory=list)
