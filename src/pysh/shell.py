# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deprecated compatibility import path for the internal ``PyShell`` class.

New embedding code must use :class:`pysh.api.ShellSession`. The compatibility
symbol remains available through at least PySH 1.1.x and will not be removed
before PySH 1.2.0.
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pysh.core.shell import PyShell

__all__ = ["PyShell"]

_DEPRECATED_SINCE = "1.0.0"
_REMOVAL_NOT_BEFORE = "1.2.0"
_DEPRECATION_MESSAGE = (
    "pysh.shell.PyShell is deprecated; use pysh.api.ShellSession for supported "
    "embedding. It will not be removed before PySH 1.2.0."
)


def __getattr__(name: str) -> object:
    """Resolve the legacy symbol lazily and emit its deprecation warning."""
    if name != "PyShell":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    from pysh.core.shell import PyShell

    return PyShell


def __dir__() -> list[str]:
    """Include the compatibility export in deterministic introspection."""
    return sorted({*globals(), *__all__})
