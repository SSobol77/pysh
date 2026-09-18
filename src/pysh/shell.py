# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Compatibility import shim for the moved PyShell runtime.

The runtime implementation lives in pysh.core.shell.
Scheduled removal milestone: GitHub Issue #19.
"""
from __future__ import annotations

from pysh.core.shell import PyShell

__all__ = ["PyShell"]
