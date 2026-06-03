# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Safe ANSI color support and a command classifier for previews.

The shell does not attempt true live-input coloring (that would require a
custom readline binding for each keystroke and is fragile across terminals).
Instead, this module provides:

  * Pure helpers to decide whether colors should be emitted.
  * A small token classifier that labels operators, redirections, builtins,
    aliases, and external commands.
  * A renderer used by the shell to print colorized previews and colorized
    diagnostics without touching the input line.

Colors are disabled when any of the following hold:
  * stdout is not a TTY
  * the environment defines NO_COLOR (any value, even empty)
  * TERM is unset or equal to "dumb"

``PYSH_COLOR`` may override the default terminal policy:
  * ``PYSH_COLOR=0`` disables colors
  * ``PYSH_COLOR=1`` enables colors when the terminal is capable
  * ``PYSH_COLOR=always`` forces ANSI output, except when ``NO_COLOR`` is set
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import IO

# ANSI SGR sequences. Kept compact; reset is shared.
_RESET = "\033[0m"
_COLORS: dict[str, str] = {
    "builtin": "\033[1;36m",       # bold cyan
    "alias": "\033[1;35m",         # bold magenta
    "external": "\033[1;32m",      # bold green
    "operator": "\033[1;33m",      # bold yellow
    "redirection": "\033[1;31m",   # bold red
    "string": "\033[0;33m",        # yellow
    "variable": "\033[0;34m",      # blue
    "comment": "\033[0;90m",       # bright black
    "error": "\033[1;31m",         # bold red
    "info": "\033[0;36m",          # cyan
    "warn": "\033[1;33m",          # bold yellow
}

OPERATOR_TOKENS: frozenset[str] = frozenset({"&&", "||", ";", "|"})
REDIRECTION_TOKENS: frozenset[str] = frozenset(
    {">", ">>", "<", "2>", "2>>", "&>", "&>>"}
)


class TokenKind(StrEnum):
    """Kind labels used by the classifier."""

    BUILTIN = "builtin"
    ALIAS = "alias"
    EXTERNAL = "external"
    OPERATOR = "operator"
    REDIRECTION = "redirection"
    STRING = "string"
    VARIABLE = "variable"
    COMMENT = "comment"
    WORD = "word"


@dataclass(frozen=True)
class Token:
    """One classified token from a shell line."""

    text: str
    kind: TokenKind


def colors_enabled(stream: IO[str] | None = None, env: dict[str, str] | None = None) -> bool:
    """Return True when it is safe to emit ANSI color sequences."""
    env = os.environ if env is None else env
    if "NO_COLOR" in env:
        return False
    override = env.get("PYSH_COLOR", "").strip().lower()
    if override in {"0", "false", "no", "off"}:
        return False
    if override == "always":
        return True
    term = env.get("TERM", "")
    if not term or term == "dumb":
        return False
    if override not in {"", "1", "true", "yes", "on"}:
        return False
    s = stream if stream is not None else sys.stdout
    try:
        return bool(s.isatty())
    except (AttributeError, ValueError):
        return False


def paint(text: str, kind: str, *, enabled: bool = True) -> str:
    """Wrap ``text`` in the ANSI sequence for ``kind`` if coloring is on."""
    if not enabled:
        return text
    code = _COLORS.get(kind)
    if not code:
        return text
    return f"{code}{text}{_RESET}"


def tokenize(line: str) -> list[str]:
    """Split a shell line into raw tokens, preserving quoted segments."""
    tokens: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(line)

    def flush() -> None:
        if buf:
            tokens.append("".join(buf))
            buf.clear()

    while i < n:
        c = line[i]
        if in_single:
            buf.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n:
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
        if c == "#" and not buf:
            tokens.append(line[i:])
            return tokens
        if c in " \t":
            flush()
            i += 1
            continue
        if c == "&" and i + 1 < n and line[i + 1] == "&":
            flush()
            tokens.append("&&")
            i += 2
            continue
        if c == "|" and i + 1 < n and line[i + 1] == "|":
            flush()
            tokens.append("||")
            i += 2
            continue
        if c == "|":
            flush()
            tokens.append("|")
            i += 1
            continue
        if c == ";":
            flush()
            tokens.append(";")
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return tokens


def classify(
    tokens: list[str],
    *,
    builtins: frozenset[str] | set[str],
    aliases: dict[str, str],
) -> list[Token]:
    """Classify each token using the current builtin and alias tables."""
    out: list[Token] = []
    expect_command = True
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("#"):
            out.append(Token(tok, TokenKind.COMMENT))
            continue
        if tok in OPERATOR_TOKENS:
            out.append(Token(tok, TokenKind.OPERATOR))
            expect_command = True
            continue
        if tok in REDIRECTION_TOKENS:
            out.append(Token(tok, TokenKind.REDIRECTION))
            # Next token is the target, not a command.
            expect_command = False
            continue
        if tok.startswith('"') or tok.startswith("'"):
            out.append(Token(tok, TokenKind.STRING))
            expect_command = False
            continue
        if tok.startswith("$"):
            out.append(Token(tok, TokenKind.VARIABLE))
            expect_command = False
            continue
        if expect_command:
            if tok in builtins:
                out.append(Token(tok, TokenKind.BUILTIN))
            elif tok in aliases:
                out.append(Token(tok, TokenKind.ALIAS))
            else:
                out.append(Token(tok, TokenKind.EXTERNAL))
            expect_command = False
        else:
            out.append(Token(tok, TokenKind.WORD))
    return out


def render(
    classified: list[Token],
    *,
    enabled: bool = True,
) -> str:
    """Render a classified token list back to a colorized string."""
    parts: list[str] = []
    for tok in classified:
        if tok.kind is TokenKind.WORD:
            parts.append(tok.text)
        else:
            parts.append(paint(tok.text, tok.kind.value, enabled=enabled))
    return " ".join(parts)


def diagnostic(message: str, level: str = "error", *, enabled: bool = True) -> str:
    """Return a colorized diagnostic line for stderr."""
    return paint(message, level, enabled=enabled)
