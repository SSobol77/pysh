# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/contracts/__init__.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
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
