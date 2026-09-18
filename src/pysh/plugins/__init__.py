# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/__init__.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Versioned trusted-code plugin subsystem for PySH."""
from __future__ import annotations

from pysh.plugins.version import PLUGIN_API_VERSION, check_api_compatibility

__all__ = [
    "PLUGIN_API_VERSION",
    "check_api_compatibility",
]
