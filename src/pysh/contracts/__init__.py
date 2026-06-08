# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/contracts/__init__.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Architecture contract protocols for PySH (Issue #3).

This package contains typing.Protocol definitions that describe read-only or
action surfaces crossing package boundaries.  It has no runtime dependencies
on pysh implementation packages and performs no runtime initialisation,
terminal I/O, config loading, or subprocess calls.
"""
from __future__ import annotations

from pysh.contracts.protocols import (
    AliasRegistryView,
    CommandResolverView,
    CompatibilityBridge,
    ConfigView,
    EnvironmentView,
    PluginRegistrar,
    ShellStateView,
)

__all__ = [
    "AliasRegistryView",
    "CompatibilityBridge",
    "CommandResolverView",
    "ConfigView",
    "EnvironmentView",
    "PluginRegistrar",
    "ShellStateView",
]
