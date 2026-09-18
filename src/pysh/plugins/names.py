# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/names.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deterministic Plugin API name validation."""
from __future__ import annotations

import re

from pysh.plugins.errors import PluginValidationError

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def validate_plugin_name(name: object, *, label: str = "plugin name") -> str:
    """Validate and return a Plugin API identifier."""
    if not isinstance(name, str):
        raise PluginValidationError(f"{label} must be a string")
    if not _NAME_RE.fullmatch(name):
        raise PluginValidationError(
            f"{label} must match ^[A-Za-z][A-Za-z0-9_-]{{0,63}}$"
        )
    if "/" in name or "\\" in name or ".." in name:
        raise PluginValidationError(f"{label} must not contain path syntax")
    return name


def validate_command_name(name: object) -> str:
    """Validate and return a plugin command name."""
    return validate_plugin_name(name, label="command name")


def validate_segment_name(name: object) -> str:
    """Validate and return a plugin prompt segment name."""
    return validate_plugin_name(name, label="prompt segment name")
