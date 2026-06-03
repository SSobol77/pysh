# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/parsing/errors.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Parser-specific errors.

This module intentionally does not import ``pysh.core``. The execution boundary
maps ``ParseError.exit_code`` to the canonical Issue #5 exit code 2.
"""
from __future__ import annotations


class ParseError(ValueError):
    """Raised for deterministic shell syntax and parser-foundation errors."""

    exit_code = 2

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnsupportedSyntaxError(ParseError):
    """Raised when syntax is recognized but owned by a later issue."""

    def __init__(self, construct: str, *, owner: str) -> None:
        super().__init__(f"unsupported syntax: {construct} ({owner})")
        self.construct = construct
        self.owner = owner
