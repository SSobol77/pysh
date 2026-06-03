# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/parsing/lexer.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Quote-aware lexical scanning helpers for PySH parsing."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteState:
    """Final quote state after scanning text."""

    in_single: bool = False
    in_double: bool = False

    @property
    def is_open(self) -> bool:
        """Return True when a quote is still open."""
        return self.in_single or self.in_double


def scan_quote_state(text: str) -> QuoteState:
    """Return the final single/double quote state after scanning *text*."""
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\", "$", "`"):
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "'":
            in_single = True
        elif c == '"':
            in_double = True
        i += 1
    return QuoteState(in_single=in_single, in_double=in_double)


def has_unbalanced_quotes(line: str) -> bool:
    """Return True if ``line`` ends with an unclosed single or double quote."""
    return scan_quote_state(line).is_open


def strip_comments(line: str) -> str:
    """Remove a shell-style comment from ``line``.

    A ``#`` starts a comment only when it is unquoted and immediately follows
    whitespace, or appears at the start of the line. Characters inside single
    or double quotes are never treated as comment delimiters.
    """
    in_single = False
    in_double = False
    at_token_boundary = True
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_single:
            if c == "'":
                in_single = False
            at_token_boundary = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and line[i + 1] in ('"', "\\", "$", "`"):
                i += 2
                at_token_boundary = False
                continue
            if c == '"':
                in_double = False
            at_token_boundary = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            at_token_boundary = False
            continue
        if c in " \t":
            at_token_boundary = True
            i += 1
            continue
        if c == "#" and at_token_boundary:
            return line[:i].rstrip()
        if c == "'":
            in_single = True
        elif c == '"':
            in_double = True
        at_token_boundary = False
        i += 1
    return line.rstrip()


def is_unquoted_at(text: str, index: int) -> bool:
    """Return True when *index* is outside single and double quotes."""
    if index < 0 or index >= len(text):
        return False
    return not scan_quote_state(text[:index]).is_open
