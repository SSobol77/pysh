# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/manifest.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Non-executing TOML manifest loader for isolated plugins."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pysh.plugins.isolated.capabilities import Capability, parse_capability
from pysh.plugins.isolated.errors import CapabilityError, ManifestError
from pysh.plugins.names import validate_plugin_name

ISOLATED_MANIFEST_VERSION = 1
ISOLATED_PROTOCOL_VERSION = 1
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ENTRYPOINT_ARGUMENTS = 64
MAX_ENTRYPOINT_ARGUMENT_BYTES = 4096

_KNOWN_FIELDS = frozenset({
    "manifest_version",
    "name",
    "plugin_version",
    "protocol_version",
    "entrypoint",
    "requested_capabilities",
    "resource_class",
})
_RESOURCE_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class IsolatedPluginManifest:
    """Validated, immutable isolated-plugin startup declaration."""

    manifest_version: int
    name: str
    plugin_version: str
    protocol_version: int
    entrypoint: tuple[str, ...]
    requested_capabilities: frozenset[Capability]
    resource_class: str | None = None


def load_isolated_plugin_manifest(
    path: Path,
    *,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> IsolatedPluginManifest:
    """Read and validate one bounded TOML manifest without executing it."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise ManifestError("isolated-plugin manifest cannot be read") from exc
    if not path.is_file():
        raise ManifestError("isolated-plugin manifest must be a regular file")
    if stat_result.st_size > max_bytes:
        raise ManifestError(f"isolated-plugin manifest exceeds {max_bytes} bytes")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ManifestError("isolated-plugin manifest cannot be read") from exc
    if len(raw) > max_bytes:
        raise ManifestError(f"isolated-plugin manifest exceeds {max_bytes} bytes")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError("isolated-plugin manifest is not valid UTF-8 TOML") from exc
    return validate_isolated_plugin_manifest(data)


def validate_isolated_plugin_manifest(data: object) -> IsolatedPluginManifest:
    """Validate one already-parsed isolated-plugin manifest table."""
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ManifestError("isolated-plugin manifest must be a TOML table")
    unknown = set(data) - _KNOWN_FIELDS
    if unknown:
        raise ManifestError(f"unknown isolated-plugin manifest field: {sorted(unknown)[0]}")
    missing = _KNOWN_FIELDS - {"resource_class"} - set(data)
    if missing:
        raise ManifestError(f"missing isolated-plugin manifest field: {sorted(missing)[0]}")

    manifest_version = _required_version(data["manifest_version"], "manifest_version")
    if manifest_version != ISOLATED_MANIFEST_VERSION:
        raise ManifestError(f"unsupported isolated-plugin manifest version: {manifest_version}")
    protocol_version = _required_version(data["protocol_version"], "protocol_version")
    if protocol_version != ISOLATED_PROTOCOL_VERSION:
        raise ManifestError(f"unsupported isolated-plugin protocol version: {protocol_version}")

    try:
        name = validate_plugin_name(data["name"])
    except Exception as exc:
        raise ManifestError("isolated-plugin name is invalid") from exc
    plugin_version = data["plugin_version"]
    if not isinstance(plugin_version, str) or not plugin_version or len(plugin_version) > 128:
        raise ManifestError("plugin_version must be a non-empty string of at most 128 characters")
    if "\x00" in plugin_version:
        raise ManifestError("plugin_version must not contain NUL")

    entrypoint = _validate_entrypoint(data["entrypoint"])
    requested = data["requested_capabilities"]
    if not isinstance(requested, list):
        raise ManifestError("requested_capabilities must be an array of strings")
    capabilities: list[Capability] = []
    for declaration in requested:
        try:
            capability = parse_capability(declaration)
        except CapabilityError as exc:
            raise ManifestError(str(exc)) from exc
        if capability in capabilities:
            raise ManifestError("requested_capabilities must not contain duplicates")
        capabilities.append(capability)

    resource_class = data.get("resource_class")
    if resource_class is not None and (
        not isinstance(resource_class, str) or not _RESOURCE_CLASS_RE.fullmatch(resource_class)
    ):
        raise ManifestError("resource_class must be a valid identifier")

    return IsolatedPluginManifest(
        manifest_version=manifest_version,
        name=name,
        plugin_version=plugin_version,
        protocol_version=protocol_version,
        entrypoint=entrypoint,
        requested_capabilities=frozenset(capabilities),
        resource_class=resource_class,
    )


def _required_version(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ManifestError(f"{field} must be a positive integer")
    return value


def _validate_entrypoint(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestError("entrypoint must be a non-empty array of strings")
    if len(value) > MAX_ENTRYPOINT_ARGUMENTS:
        raise ManifestError(f"entrypoint must contain at most {MAX_ENTRYPOINT_ARGUMENTS} items")
    if not all(isinstance(item, str) and item for item in value):
        raise ManifestError("entrypoint must contain only non-empty strings")
    if any("\x00" in item for item in value):
        raise ManifestError("entrypoint must not contain NUL")
    if any(len(item.encode("utf-8")) > MAX_ENTRYPOINT_ARGUMENT_BYTES for item in value):
        raise ManifestError("entrypoint item exceeds the maximum encoded length")

    executable = Path(value[0])
    if not executable.is_absolute():
        raise ManifestError("entrypoint executable must be an absolute path")
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise ManifestError("entrypoint executable cannot be resolved") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ManifestError("entrypoint executable must be an executable regular file")
    return (str(resolved), *value[1:])
