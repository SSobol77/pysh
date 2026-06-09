# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/errors.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Plugin-specific exception hierarchy."""
from __future__ import annotations


class PluginError(Exception):
    """Base class for Plugin API failures."""


class PluginValidationError(PluginError, ValueError):
    """Raised when plugin metadata or names fail validation."""


class PluginLoadError(PluginError):
    """Raised when loading a plugin module or class fails."""


class PluginVersionError(PluginError):
    """Raised when a plugin API version is malformed or incompatible."""


class PluginRegistrationError(PluginError):
    """Raised when a plugin registration request is invalid."""
