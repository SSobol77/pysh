# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/capabilities.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Typed, deterministic capability declarations for isolated plugins."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pysh.plugins.isolated.errors import CapabilityError
from pysh.plugins.names import validate_command_name, validate_plugin_name

_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_NETWORK_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


class CapabilityFamily(StrEnum):
    """Capability families enforced by the parent-side broker."""

    FILESYSTEM = "filesystem"
    ENVIRONMENT = "environment"
    NETWORK = "network"
    COMMAND = "command"


class FilesystemAccess(StrEnum):
    """Filesystem operations that may be granted for one canonical scope."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class FilesystemCapability:
    """Read or write access rooted at one canonical absolute path."""

    access: FilesystemAccess
    root: Path
    family: CapabilityFamily = CapabilityFamily.FILESYSTEM


@dataclass(frozen=True, slots=True)
class EnvironmentCapability:
    """Read access to one explicitly named parent environment variable."""

    name: str
    family: CapabilityFamily = CapabilityFamily.ENVIRONMENT


@dataclass(frozen=True, slots=True)
class NetworkCapability:
    """Reserved connect access to one explicit host and TCP/UDP port."""

    host: str
    port: int
    family: CapabilityFamily = CapabilityFamily.NETWORK


@dataclass(frozen=True, slots=True)
class CommandCapability:
    """Access to one explicitly registered parent-side named command."""

    name: str
    family: CapabilityFamily = CapabilityFamily.COMMAND


type Capability = (
    FilesystemCapability | EnvironmentCapability | NetworkCapability | CommandCapability
)


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """Immutable parent-owned requested/granted capability decision."""

    plugin_name: str
    requested: frozenset[Capability]
    granted: frozenset[Capability]

    @classmethod
    def create(
        cls,
        plugin_name: str,
        requested: frozenset[Capability],
        granted: frozenset[Capability] = frozenset(),
    ) -> CapabilityGrant:
        """Validate and construct a default-deny parent-side grant."""
        name = validate_plugin_name(plugin_name)
        undeclared = granted - requested
        if undeclared:
            labels = ", ".join(sorted(format_capability(item) for item in undeclared))
            raise CapabilityError(f"cannot grant undeclared capabilities: {labels}")
        return cls(plugin_name=name, requested=requested, granted=granted)

    def allows(self, capability: Capability) -> bool:
        """Return whether the exact capability was explicitly granted."""
        return capability in self.granted


def parse_capability(value: object) -> Capability:
    """Parse one manifest capability into a typed canonical object."""
    if not isinstance(value, str) or not value:
        raise CapabilityError("capability must be a non-empty string")
    if "\x00" in value:
        raise CapabilityError("capability must not contain NUL")

    if value.startswith("fs.read:"):
        return _filesystem_capability(FilesystemAccess.READ, value.removeprefix("fs.read:"))
    if value.startswith("fs.write:"):
        return _filesystem_capability(FilesystemAccess.WRITE, value.removeprefix("fs.write:"))
    if value.startswith("env.read:"):
        name = value.removeprefix("env.read:")
        if not _ENVIRONMENT_NAME_RE.fullmatch(name):
            raise CapabilityError("environment capability has an invalid variable name")
        return EnvironmentCapability(name=name)
    if value.startswith("command:"):
        name = value.removeprefix("command:")
        try:
            command_name = validate_command_name(name)
        except Exception as exc:
            raise CapabilityError("command capability has an invalid command name") from exc
        return CommandCapability(name=command_name)
    if value.startswith("network.connect:"):
        endpoint = value.removeprefix("network.connect:")
        host, separator, raw_port = endpoint.rpartition(":")
        if not separator or not _NETWORK_HOST_RE.fullmatch(host):
            raise CapabilityError("network capability must use host:port syntax")
        try:
            port = int(raw_port, 10)
        except ValueError as exc:
            raise CapabilityError("network capability port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise CapabilityError("network capability port must be between 1 and 65535")
        return NetworkCapability(host=host.casefold(), port=port)
    raise CapabilityError(f"unknown capability name: {value!r}")


def format_capability(capability: Capability) -> str:
    """Return the canonical wire/manifest label for one capability."""
    if isinstance(capability, FilesystemCapability):
        return f"fs.{capability.access.value}:{capability.root}"
    if isinstance(capability, EnvironmentCapability):
        return f"env.read:{capability.name}"
    if isinstance(capability, NetworkCapability):
        return f"network.connect:{capability.host}:{capability.port}"
    if isinstance(capability, CommandCapability):
        return f"command:{capability.name}"
    raise TypeError("unsupported capability object")


def _filesystem_capability(access: FilesystemAccess, raw_path: str) -> FilesystemCapability:
    if not raw_path:
        raise CapabilityError("filesystem capability path must not be empty")
    path = Path(raw_path)
    if not path.is_absolute():
        raise CapabilityError("filesystem capability path must be absolute")
    try:
        canonical = path.resolve(strict=False)
    except OSError as exc:
        raise CapabilityError("filesystem capability path cannot be resolved") from exc
    return FilesystemCapability(access=access, root=canonical)
