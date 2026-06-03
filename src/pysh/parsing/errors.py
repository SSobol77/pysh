# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

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
