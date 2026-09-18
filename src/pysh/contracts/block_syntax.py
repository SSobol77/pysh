# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/contracts/block_syntax.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical ``py { ... }`` block syntax primitives (Issue #14 / #19).

This module is the single source of truth for what counts as a ``py { ... }``
block opener or closer, including the pipeline-prefixed form
(``echo hi | py {``). Both :mod:`pysh.parsing` (full pipeline execution
splitting) and :mod:`pysh.python_layer` (rc-file and REPL block coalescing)
depend on it so neither package has to depend on the other, and there is
exactly one implementation of the underlying quote-aware pipe scan.

This module has no runtime dependencies on pysh implementation packages and
performs no I/O.
"""
from __future__ import annotations

PY_BLOCK_OPENER = "py {"
PY_BLOCK_CLOSER = "}"


def is_block_opener(line: str) -> bool:
    """Return True if ``line`` opens a multiline ``py { ... }`` block.

    Recognizes both the bare opener (``py {``) and a pipeline whose final
    unquoted stage is the opener (e.g. ``echo hi | py {``).
    """
    stripped = _strip_trailing_comment(line.strip())
    if stripped == PY_BLOCK_OPENER:
        return True
    stages = split_unquoted_pipe_stages(stripped)
    if len(stages) <= 1 or any(not stage for stage in stages):
        return False
    return stages[-1] == PY_BLOCK_OPENER


def is_block_closer(line: str) -> bool:
    """Return True if ``line`` closes a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_CLOSER


def split_unquoted_pipe_stages(command: str) -> list[str]:
    """Split *command* on unquoted, non-``||`` ``|`` characters.

    Purely syntactic: this never raises. An empty or dangling stage (e.g. a
    trailing ``|``) is returned as an empty string rather than rejected, so
    callers that only need the syntactic shape (not full pipeline
    validation, which belongs to :func:`pysh.parsing.grammar.split_pipeline`)
    can use it without depending on parser error types.
    """
    if not command.strip():
        return []
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if in_single:
            buf.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`"):
                buf.append(c)
                buf.append(command[i + 1])
                i += 2
                continue
            buf.append(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
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
        if c == "|":
            if i + 1 < n and command[i + 1] == "|":
                buf.append(c)
                buf.append(command[i + 1])
                i += 2
                continue
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf).strip())
    return parts


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
