# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/parser.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Quote-aware command parser.

The parser is responsible for:
  * Splitting a shell line into command-chain elements on ``;``, ``&&`` and ``||``.
  * Splitting a single command on pipe ``|``.
  * Detecting whether a line has unbalanced quotes.
  * Expanding ``$NAME`` and ``${NAME}`` variables outside of single quotes.

The fundamental rule is: operators that appear inside single or double quotes
are NOT treated as operators. A backslash escapes the next character outside
single quotes.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum


class ChainOp(StrEnum):
    """Operator joining a command to the next one in a command chain."""

    SEMI = ";"
    AND = "&&"
    OR = "||"


@dataclass(frozen=True)
class ChainElement:
    """Single command in a chain with the operator that follows it.

    ``operator`` is ``None`` for the final command in the chain.
    """

    command: str
    operator: ChainOp | None


def has_unbalanced_quotes(line: str) -> bool:
    """Return True if ``line`` ends with an unclosed single or double quote."""
    in_single = False
    in_double = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and line[i + 1] in ('"', "\\", "$", "`"):
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
    return in_single or in_double


def split_chain(line: str) -> list[ChainElement]:
    """Split ``line`` into chain elements on unquoted ``;``, ``&&`` and ``||``."""
    if not line.strip():
        return []
    parts: list[ChainElement] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_single:
            buf.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and line[i + 1] in ('"', "\\", "$", "`"):
                buf.append(c)
                buf.append(line[i + 1])
                i += 2
                continue
            buf.append(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(line[i + 1])
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
        if c == "&" and i + 1 < n and line[i + 1] == "&":
            parts.append(ChainElement("".join(buf).strip(), ChainOp.AND))
            buf = []
            i += 2
            continue
        if c == "|" and i + 1 < n and line[i + 1] == "|":
            parts.append(ChainElement("".join(buf).strip(), ChainOp.OR))
            buf = []
            i += 2
            continue
        if c == ";":
            parts.append(ChainElement("".join(buf).strip(), ChainOp.SEMI))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append(ChainElement("".join(buf).strip(), None))
    return [p for p in parts if p.command]


def split_pipeline(command: str) -> list[str]:
    """Split a single command on unquoted ``|`` (but not ``||``)."""
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
                # ``||`` should already have been handled by split_chain;
                # keep it as literal text if it slipped through.
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
    return [p for p in parts if p]


_VAR_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def expand_variables(
    text: str,
    local_vars: dict[str, str],
    env_vars: dict[str, str] | None = None,
) -> str:
    """Expand ``$NAME`` and ``${NAME}`` references in ``text``.

    * Local variables shadow environment variables.
    * Unknown variables expand to an empty string.
    * Expansion is suppressed inside single quotes.
    * Backslash escapes are preserved so downstream shlex sees correct quoting.
    """
    if env_vars is None:
        env_vars = dict(os.environ)

    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            out.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_double = not in_double
            out.append(c)
            i += 1
            continue
        if c == "$" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "{":
                end = text.find("}", i + 2)
                if end == -1:
                    out.append(c)
                    i += 1
                    continue
                name = text[i + 2 : end]
                if not _VAR_NAME_RE.fullmatch(name):
                    out.append(text[i : end + 1])
                    i = end + 1
                    continue
                value = local_vars.get(name)
                if value is None:
                    value = env_vars.get(name, "")
                out.append(value)
                i = end + 1
                continue
            m = _VAR_NAME_RE.match(text, i + 1)
            if m:
                name = m.group(0)
                value = local_vars.get(name)
                if value is None:
                    value = env_vars.get(name, "")
                out.append(value)
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_assignment(line: str) -> tuple[str, str] | None:
    """If ``line`` looks like ``NAME=value`` return ``(NAME, value)``.

    The returned value is the raw right-hand side (still possibly quoted).
    Returns ``None`` if ``line`` is not a simple assignment.
    """
    stripped = line.strip()
    m = _ASSIGNMENT_RE.match(stripped)
    if not m:
        return None
    return m.group(1), m.group(2)
