# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/contracts/protocols.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structural interface protocols for PySH architecture boundaries.

Rules enforced by architecture tests:
- Imports only from the Python standard library.
- Must not import from any pysh implementation package.
- Performs no runtime initialisation, I/O, config loading, or subprocess calls.

Each Protocol describes a real extension or boundary surface — not a
speculative model of the runtime.  Add protocols only where they remove
genuine cross-layer coupling or define a documented public extension point.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class AliasRegistryView(Protocol):
    """Alias lookup and listing surface consumed by completion and compat.

    @runtime_checkable: compat helpers may use isinstance to verify that an
    object satisfies this interface before delegating alias operations.
    """

    def list_aliases(self) -> dict[str, str]:
        """Return a snapshot dict of all currently defined aliases."""
        ...

    def lookup_alias(self, name: str) -> str | None:
        """Return the expansion for *name*, or None if not defined."""
        ...


@runtime_checkable
class EnvironmentView(Protocol):
    """Environment and local-variable lookup surface.

    @runtime_checkable: completion may check whether a shell-state object
    satisfies this interface before requesting variable expansions.
    """

    def get_env(self, name: str, default: str = "") -> str:
        """Return the value of exported environment variable *name*."""
        ...

    def get_local(self, name: str, default: str = "") -> str:
        """Return the value of local shell variable *name*."""
        ...


class ShellStateView(Protocol):
    """Read-only view of shell state consumed by prompt and editor components.

    Exposes the minimum shell state that prompt renderers and the editor
    need without pulling in the full PyShell implementation.
    """

    @property
    def cwd(self) -> str:
        """Current working directory."""
        ...

    @property
    def last_status(self) -> int:
        """Exit status of the last executed command (0 = success)."""
        ...


class CommandResolverView(Protocol):
    """Command/builtin/alias resolution surface for completion and planning."""

    @property
    def builtin_names(self) -> frozenset[str]:
        """Immutable set of all registered builtin command names."""
        ...

    def is_builtin(self, name: str) -> bool:
        """Return True if *name* is a registered builtin."""
        ...

    def resolve_alias(self, name: str) -> str | None:
        """Return the alias expansion for *name*, or None if not an alias."""
        ...


class ConfigView(Protocol):
    """Config option access surface consumed by prompt and editor."""

    def get_bool(self, key: str, *, default: bool = False) -> bool:
        """Return a boolean config value for *key*."""
        ...

    def get_str(self, key: str, *, default: str = "") -> str:
        """Return a string config value for *key*."""
        ...


class PluginRegistrar(Protocol):
    """Plugin registration surface consumed by config loaders."""

    def register_alias(self, name: str, value: str) -> None:
        """Register an alias *name* expanding to *value*."""
        ...

    def register_env(self, name: str, value: str) -> None:
        """Register exported environment variable *name* with *value*."""
        ...

    def register_local(self, name: str, value: str) -> None:
        """Register local shell variable *name* with *value*."""
        ...


class CompatibilityBridge(Protocol):
    """Explicit compatibility bridge interface for compat helpers."""

    def is_available(self) -> bool:
        """Return True if the underlying compatibility target is available."""
        ...

    def execute(self, command: str) -> int:
        """Execute *command* via the bridge; return the exit status."""
        ...

    def execute_lines(self, commands: Iterator[str]) -> int:
        """Execute a sequence of *commands*; return the last exit status."""
        ...
