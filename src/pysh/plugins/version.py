# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/version.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Plugin API version compatibility checks."""
from __future__ import annotations

from pysh.contracts import PLUGIN_API_VERSION
from pysh.plugins.errors import PluginVersionError


def normalize_api_version(value: object) -> tuple[int, int]:
    """Return a validated ``(major, minor)`` API version tuple."""
    if not isinstance(value, tuple) or len(value) != 2:
        raise PluginVersionError("api_version must be a tuple[int, int] of length 2")
    major, minor = value
    if (
        isinstance(major, bool)
        or isinstance(minor, bool)
        or not isinstance(major, int)
        or not isinstance(minor, int)
    ):
        raise PluginVersionError("api_version entries must be non-bool integers")
    if major < 0 or minor < 0:
        raise PluginVersionError("api_version entries must be non-negative")
    return major, minor


def check_api_compatibility(plugin_api_version: object) -> tuple[int, int]:
    """Validate and return a plugin API version compatible with this PySH."""
    major, minor = normalize_api_version(plugin_api_version)
    pysh_major, pysh_minor = PLUGIN_API_VERSION
    if major != pysh_major or minor > pysh_minor:
        raise PluginVersionError(
            f"unsupported plugin API version {(major, minor)!r}; "
            f"PySH supports {PLUGIN_API_VERSION!r}"
        )
    return major, minor
