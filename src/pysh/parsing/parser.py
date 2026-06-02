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
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS = 5.0


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
    *,
    special_vars: dict[str, str] | None = None,
) -> str:
    """Expand ``$NAME``, ``${NAME}``, and ``$?`` references in ``text``.

    * Local variables shadow environment variables.
    * Unknown variables expand to an empty string.
    * Expansion is suppressed inside single quotes.
    * Backslash escapes are preserved so downstream shlex sees correct quoting.
    * ``$?`` expands to the last command exit status supplied via *special_vars*.
      Only ``$?`` is supported as a special parameter (Issue #5).  Other POSIX
      special parameters (``$0``, ``$$``, ``$!``, etc.) are not implemented.
    """
    if env_vars is None:
        env_vars = dict(os.environ)
    _special = special_vars or {}

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
            # $? — last exit status (the only special parameter owned by Issue #5)
            if nxt == "?":
                out.append(_special.get("?", "0"))
                i += 2
                continue
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


def strip_comments(line: str) -> str:
    """Remove a shell-style comment from ``line``.

    A ``#`` starts a comment only when it is unquoted and immediately follows
    whitespace (or is at the very start of the line, possibly preceded by
    whitespace). Everything from that ``#`` through the end of the line is
    discarded. The result is rstripped.

    Characters inside single or double quotes are never treated as comment
    delimiters. A backslash outside quotes escapes the following character.
    """
    in_single = False
    in_double = False
    at_token_boundary = True  # True when we are between tokens (whitespace)
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
        # Outside quotes
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


_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

# Matches a single shlex-split token that is a NAME=value assignment.
# The name rule is the same as _ASSIGNMENT_RE but the regex is applied
# after shlex.split() so the value is already unquoted and may contain
# spaces (e.g. FOO=hello world after shlex strips the surrounding quotes).
_ASSIGNMENT_TOKEN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


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


def parse_leading_env_assignments(
    tokens: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Extract leading ``NAME=value`` tokens from a shlex-split token list.

    Returns ``(env_dict, remaining_tokens)`` where *env_dict* contains the
    assignments found before the first non-assignment token and
    *remaining_tokens* is the command and its arguments.

    The values in *tokens* are already unquoted (as produced by
    ``shlex.split(posix=True)``).  Both the name and the value are taken
    verbatim from the token; no further quoting or expansion is performed.

    A valid assignment token must match ``[A-Za-z_][A-Za-z0-9_]*=.*``.
    Tokens like ``1FOO=bar`` (starting with a digit) are not assignments and
    stop the scan immediately.  The scan also stops at the first token that
    does not contain ``=``.

    Examples::

        parse_leading_env_assignments(["FOO=bar", "env"])
        # → ({"FOO": "bar"}, ["env"])

        parse_leading_env_assignments(["FOO=", "BAR=hello world", "cmd", "arg"])
        # → ({"FOO": "", "BAR": "hello world"}, ["cmd", "arg"])

        parse_leading_env_assignments(["echo", "FOO=bar"])
        # → ({}, ["echo", "FOO=bar"])

        parse_leading_env_assignments(["FOO=bar", "BAR=baz"])
        # → ({"FOO": "bar", "BAR": "baz"}, [])
    """
    env: dict[str, str] = {}
    for i, token in enumerate(tokens):
        m = _ASSIGNMENT_TOKEN_RE.match(token)
        if m:
            env[m.group(1)] = m.group(2)
        else:
            return env, tokens[i:]
    return env, []


def split_paste_commands(text: str) -> list[str]:
    """Split pasted multi-line text into individual command strings.

    Splits on unquoted newlines (``\\n`` or ``\\r``).  A newline that occurs
    inside single or double quotes is *not* a command boundary.  Backslash
    escapes outside quotes are honoured.  Empty command strings (blank lines)
    are omitted from the result.

    This function is used by the raw-mode line reader to separate a pasted
    block into a sequence of commands that the shell executes one by one.
    It does not split on ``;``, ``&&`` or ``|``; those operators are handled
    later by :func:`split_chain` and :func:`split_pipeline` when the shell
    executes each returned command.

    Examples::

        split_paste_commands("echo one\\necho two\\n")
        # → ["echo one", "echo two"]

        split_paste_commands('echo "hello\\nworld"\\n')
        # → ['echo "hello\\nworld"']

        split_paste_commands("export FOO=bar\\nenv\\n")
        # → ["export FOO=bar", "env"]
    """
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


# ----------------------------------------------------------------- substitution
def _default_runner(command: str, timeout: float) -> str:
    """Run ``command`` in a system shell with a timeout and capture stdout.

    This is the fallback runner used when the shell does not supply one.
    Stdout is decoded as UTF-8 (errors replaced). Trailing newlines are
    stripped, matching POSIX command-substitution semantics.
    """
    try:
        completed = subprocess.run(  # noqa: S603,S607 - user-issued substitution
            ["/bin/sh", "-c", command],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"pysh: substitution timed out: {command}", file=sys.stderr)
        return ""
    except OSError as exc:
        print(f"pysh: substitution error: {exc}", file=sys.stderr)
        return ""
    try:
        text = completed.stdout.decode("utf-8", errors="replace")
    except (AttributeError, UnicodeDecodeError):
        return ""
    return text.rstrip("\n")


def expand_command_substitution(
    text: str,
    *,
    runner: Callable[[str, float], str] | None = None,
    timeout: float = DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS,
) -> str:
    """Expand ``$(command)`` and ``` `command` ``` substitutions in ``text``.

    Substitutions inside single quotes are left as literal text. Substitutions
    inside double quotes are evaluated. ``runner`` is a callable
    ``(command, timeout) -> stdout`` used to execute each substitution; if it
    is omitted, a safe subprocess-based runner is used.

    Nested substitutions are not expanded recursively; the inner ``$(...)``
    text is passed to the runner verbatim.
    """
    run = runner if runner is not None else _default_runner
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
        if c == "$" and i + 1 < n and text[i + 1] == "(":
            end = _find_matching_paren(text, i + 1)
            if end == -1:
                out.append(c)
                i += 1
                continue
            command = text[i + 2 : end]
            out.append(run(command, timeout))
            i = end + 1
            continue
        if c == "`":
            end = text.find("`", i + 1)
            if end == -1:
                out.append(c)
                i += 1
                continue
            command = text[i + 1 : end]
            out.append(run(command, timeout))
            i = end + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_matching_paren(text: str, open_idx: int) -> int:
    """Return the index of the ``)`` matching ``text[open_idx] == '('``.

    Tracks nested parens but ignores those inside single/double quotes.
    Returns ``-1`` when no match is found.
    """
    depth = 0
    in_single = False
    in_double = False
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n:
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
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1
