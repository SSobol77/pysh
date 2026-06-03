# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/parsing/multiline.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Multiline and logical-line helpers for PySH grammar."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum

from pysh.parsing.lexer import scan_quote_state

PY_BLOCK_OPENER = "py {"
PY_BLOCK_CLOSER = "}"


class UnterminatedBlockError(ValueError):
    """Raised when a multiline ``py { ... }`` block is never closed."""


class NestedBlockError(ValueError):
    """Raised when a nested ``py { ... }`` block opener is encountered."""


class ContinuationKind(StrEnum):
    """Reason a physical line requires continuation."""

    NONE = "none"
    SINGLE_QUOTE = "single_quote"
    DOUBLE_QUOTE = "double_quote"
    BACKSLASH_NEWLINE = "backslash_newline"
    PYTHON_BLOCK = "python_block"
    HEREDOC_PLACEHOLDER = "heredoc_placeholder"


@dataclass(frozen=True)
class ContinuationState:
    """Continuation decision for a logical shell line."""

    needs_more: bool
    kind: ContinuationKind = ContinuationKind.NONE


def is_block_opener(line: str) -> bool:
    """Return True if ``line`` opens a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_OPENER


def is_block_closer(line: str) -> bool:
    """Return True if ``line`` closes a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_CLOSER


def continuation_state(text: str) -> ContinuationState:
    """Return whether *text* requires a continuation line."""
    stripped = text.rstrip("\r\n")
    if is_block_opener(stripped):
        return ContinuationState(True, ContinuationKind.PYTHON_BLOCK)
    quote_state = scan_quote_state(stripped)
    if quote_state.in_single:
        return ContinuationState(True, ContinuationKind.SINGLE_QUOTE)
    if quote_state.in_double:
        return ContinuationState(True, ContinuationKind.DOUBLE_QUOTE)
    if has_trailing_line_continuation(stripped):
        return ContinuationState(True, ContinuationKind.BACKSLASH_NEWLINE)
    return ContinuationState(False, ContinuationKind.NONE)


def has_trailing_line_continuation(line: str) -> bool:
    """Return True when *line* ends with an unescaped backslash outside quotes."""
    text = line.rstrip()
    if not text.endswith("\\"):
        return False
    quote_state = scan_quote_state(text[:-1])
    if quote_state.is_open:
        return False
    backslashes = 0
    i = len(text) - 1
    while i >= 0 and text[i] == "\\":
        backslashes += 1
        i -= 1
    return backslashes % 2 == 1


def join_backslash_continuations(text: str) -> str:
    """Join unescaped backslash-newline pairs into a single logical line."""
    lines = text.splitlines()
    if len(lines) <= 1:
        return text
    logical: list[str] = []
    buffer = ""
    for line in lines:
        if has_trailing_line_continuation(line):
            buffer += line.rstrip()[:-1].rstrip() + " "
            continue
        logical.append(buffer + line)
        buffer = ""
    if buffer:
        logical.append(buffer.rstrip())
    return "\n".join(logical)


def iter_logical_lines(lines: Iterable[str]) -> Iterator[str]:
    """Yield logical command strings from physical lines.

    Python blocks are coalesced. Backslash-newline continuation is joined.
    Quote continuation is represented by joining physical lines until quotes
    close; the embedded newline is preserved inside the quoted text.
    """
    state: list[str] | None = None
    quote_lines: list[str] | None = None
    backslash_buffer = ""
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        if state is not None:
            if is_block_opener(line):
                raise NestedBlockError("nested py { ... } block is not supported")
            state.append(line)
            if is_block_closer(line):
                yield "\n".join(state)
                state = None
            continue
        if quote_lines is not None:
            quote_lines.append(line)
            joined = "\n".join(quote_lines)
            if not scan_quote_state(joined).is_open:
                yield joined
                quote_lines = None
            continue
        if backslash_buffer:
            line = backslash_buffer + line
            backslash_buffer = ""
        if is_block_opener(line):
            state = [line]
            continue
        if has_trailing_line_continuation(line):
            backslash_buffer = line.rstrip()[:-1].rstrip() + " "
            continue
        if scan_quote_state(line).is_open:
            quote_lines = [line]
            continue
        yield line
    if state is not None:
        raise UnterminatedBlockError("unterminated py { ... } block (missing '}')")
    if quote_lines is not None:
        yield "\n".join(quote_lines)
    elif backslash_buffer:
        yield backslash_buffer.rstrip()


def extract_block_body(text: str) -> str:
    """Return the inner body of a multi-line ``py { ... }`` block text."""
    physical = text.split("\n")
    if len(physical) < 2 or not is_block_opener(physical[0]):
        raise ValueError("text does not start with a py { opener")
    if not is_block_closer(physical[-1]):
        raise ValueError("text does not end with a } closer")
    body = physical[1:-1]
    return "\n".join(body)


def split_paste_commands(text: str) -> list[str]:
    """Split pasted multi-line text into individual command strings."""
    commands: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            buf.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\", "$", "`"):
                buf.append(c)
                buf.append(text[i + 1])
                i += 2
                continue
            buf.append(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(text[i + 1])
            i += 2
            continue
        if c == "'":
            in_single = True
            buf.append(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            buf.append(c)
            i += 1
            continue
        if c in "\n\r":
            cmd = "".join(buf).strip()
            if cmd:
                commands.append(cmd)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    cmd = "".join(buf).strip()
    if cmd:
        commands.append(cmd)
    return commands


def _strip_trailing_comment(text: str) -> str:
    """Strip a trailing ``# ...`` comment outside of any string literal."""
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
        elif c == "#":
            return text[:i].rstrip()
        i += 1
    return text.rstrip()
