# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/registry.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deterministic discovery registry for Plugin API candidates."""
from __future__ import annotations

from pathlib import Path

from pysh.plugins.models import PluginCandidate, PluginRecord, PluginSource, PluginState
from pysh.plugins.names import validate_plugin_name

USER_PLUGIN_DIR = Path("~/.config/pysh/plugins").expanduser()
PROJECT_PLUGIN_DIR = Path(".pysh/plugins")
PLUGIN_SUFFIX = ".py"


def discover_plugin_files(directory: Path, source: PluginSource) -> list[PluginCandidate]:
    """Return direct child ``.py`` plugin candidates in deterministic order."""
    if not directory.exists() or not directory.is_dir():
        return []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    candidates: list[PluginCandidate] = []
    for path in sorted(entries, key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix != PLUGIN_SUFFIX:
            continue
        candidates.append(
            PluginCandidate(
                path=path,
                source=source,
                discovery_name=path.stem,
            )
        )
    return candidates


class PluginRegistry:
    """Tracks discovered candidates and explicit enablement."""

    def __init__(self) -> None:
        self._records: list[PluginRecord] = []
        self._enabled_names: set[str] = set()
        self.project_plugins_enabled = False

    def enable(self, name: str) -> None:
        """Record explicit intent to load plugin ``name``."""
        self._enabled_names.add(validate_plugin_name(name))

    def disable(self, name: str) -> None:
        """Remove explicit load intent for plugin ``name``."""
        self._enabled_names.discard(validate_plugin_name(name))

    def is_enabled(self, name: str) -> bool:
        """Return whether plugin ``name`` is explicitly enabled."""
        return validate_plugin_name(name) in self._enabled_names

    def enabled_names(self) -> tuple[str, ...]:
        """Return enabled plugin names sorted deterministically."""
        return tuple(sorted(self._enabled_names, key=str.casefold))

    def discover(self, *candidates: PluginCandidate) -> None:
        """Replace discovery records with deterministic candidate records."""
        self._records = [PluginRecord(candidate=candidate) for candidate in candidates]

    def records(self) -> tuple[PluginRecord, ...]:
        """Return records in deterministic discovery order."""
        return tuple(self._records)

    def enabled_records(self) -> tuple[PluginRecord, ...]:
        """Return records that policy permits to execute."""
        out: list[PluginRecord] = []
        seen: set[str] = set()
        for record in self._records:
            name = record.candidate.discovery_name
            if not _valid_discovery_name(name):
                record.state = PluginState.FAILED
                record.errors.append("invalid discovery filename")
                continue
            if not self.is_enabled(name):
                record.state = PluginState.DISABLED
                continue
            if record.candidate.source is PluginSource.PROJECT and not self.project_plugins_enabled:
                record.state = PluginState.DISABLED
                continue
            if name in seen:
                record.state = PluginState.FAILED
                record.errors.append("duplicate plugin candidate")
                continue
            seen.add(name)
            out.append(record)
        return tuple(out)


def _valid_discovery_name(name: str) -> bool:
    try:
        validate_plugin_name(name)
    except Exception:
        return False
    return True
