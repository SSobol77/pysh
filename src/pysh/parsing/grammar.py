# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Quote-aware grammar helpers for command chains and pipelines."""
from __future__ import annotations

import re

from pysh.parsing.ast import ChainElement, ChainOp
from pysh.parsing.errors import ParseError, UnsupportedSyntaxError

_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_ASSIGNMENT_TOKEN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(=.*)$", re.DOTALL)


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
        if c == "&":
            if i + 1 < n and line[i + 1] == "&":
                parts.append(ChainElement("".join(buf).strip(), ChainOp.AND))
                buf = []
                i += 2
                continue
            if i + 1 < n and line[i + 1] == ">":
                # &> or &>> redirection -- not a chain operator; pass through as literal.
                buf.append(c)
                i += 1
                continue
            if i > 0 and line[i - 1] in "><":
                # Unsupported fd-duplication forms such as 2>&1 or <&0 must
                # not be misclassified as background execution.  Leave them
                # intact for the redirection/argv path to reject or pass
                # consistently with the existing unsupported-syntax contract.
                buf.append(c)
                i += 1
                continue
            # Bare unquoted & — background execution operator.
            cmd = "".join(buf).strip()
            if not cmd:
                raise ParseError("syntax error near unexpected '&'")
            parts.append(ChainElement(cmd, ChainOp.BACKGROUND))
            buf = []
            i += 1
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
    """Split a single command on unquoted ``|`` and reject empty stages."""
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
            _append_pipeline_stage(parts, buf)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    _append_pipeline_stage(parts, buf)
    return parts


def parse_assignment(line: str) -> tuple[str, str] | None:
    """If ``line`` looks like ``NAME=value`` return ``(NAME, value)``."""
    stripped = line.strip()
    m = _ASSIGNMENT_RE.match(stripped)
    if not m:
        return None
    return m.group(1), m.group(2)


def parse_leading_env_assignments(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    """Extract leading ``NAME=value`` tokens from a shlex-split token list."""
    env: dict[str, str] = {}
    for i, token in enumerate(tokens):
        m = _ASSIGNMENT_TOKEN_RE.match(token)
        if m:
            env[m.group(1)] = m.group(2)[1:]
        else:
            return env, tokens[i:]
    return env, []


def validate_unsupported_syntax(line: str) -> None:
    """Raise :class:`UnsupportedSyntaxError` for syntax owned by later issues."""
    if _contains_unquoted(line, "$(("):
        raise UnsupportedSyntaxError("arithmetic expansion $((...))", owner="Issue #8")
    stripped = line.lstrip()
    if stripped.startswith("(("):
        raise UnsupportedSyntaxError("arithmetic command ((...))", owner="Issue #8")
    if _first_word(stripped) == "let":
        raise UnsupportedSyntaxError("arithmetic let command", owner="Issue #8")


def _append_pipeline_stage(parts: list[str], buf: list[str]) -> None:
    stage = "".join(buf).strip()
    if not stage:
        raise ParseError("syntax error near unexpected '|'")
    parts.append(stage)


def _contains_unquoted(text: str, needle: str) -> bool:
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
            i += 1
            continue
        if c == '"':
            in_double = True
            i += 1
            continue
        if text.startswith(needle, i):
            return True
        i += 1
    return False


def _first_word(text: str) -> str:
    word: list[str] = []
    for char in text:
        if char in " \t\r\n":
            break
        word.append(char)
    return "".join(word)
