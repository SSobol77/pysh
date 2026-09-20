# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/errors.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Contained failure types for the isolated-plugin subsystem."""
from __future__ import annotations


class IsolatedPluginError(Exception):
    """Base class for isolated-plugin failures contained by the parent."""


class ManifestError(IsolatedPluginError, ValueError):
    """Raised when an isolated-plugin manifest is invalid."""


class CapabilityError(IsolatedPluginError, ValueError):
    """Raised when a capability declaration or grant is invalid."""


class CapabilityDeniedError(CapabilityError):
    """Raised when a broker request lacks its required parent-side grant."""


class ProtocolError(IsolatedPluginError):
    """Raised for malformed or unexpected IPC input."""


class FrameTooLargeError(ProtocolError):
    """Raised before allocation when an IPC frame exceeds the hard limit."""


class LifecycleError(IsolatedPluginError):
    """Raised when the isolated child violates its lifecycle contract."""


class LifecycleTimeoutError(LifecycleError, TimeoutError):
    """Raised when a bounded lifecycle operation exceeds its deadline."""
