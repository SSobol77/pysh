# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/redirection.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Redirection parsing for shell commands.

Supported operators (only recognized outside of single/double quotes):

* ``< file``           - stdin from file
* ``> file``           - stdout to file (truncate)
* ``>> file``          - stdout to file (append)
* ``2> file``          - stderr to file (truncate)
* ``2>> file``         - stderr to file (append)
* ``&> file``          - stdout + stderr to file (truncate)
* ``&>> file``         - stdout + stderr to file (append)

The target file may be attached to the operator (``>file``) or separated by
whitespace (``> file``). Targets may be quoted.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass
class RedirectionSpec:
    """Captured redirections for a single command."""

    stdin_path: str | None = None
    stdout_path: str | None = None
    stdout_append: bool = False
    stderr_path: str | None = None
    stderr_append: bool = False
    stderr_to_stdout: bool = False

    def is_empty(self) -> bool:
        return (
            self.stdin_path is None
            and self.stdout_path is None
            and self.stderr_path is None
            and not self.stderr_to_stdout
        )


_WORD_BOUNDARY = " \t<>&;|"


def _read_target(command: str, idx: int) -> tuple[str, int]:
    """Read a redirection target starting at ``idx``.

    Returns ``(unquoted_target, next_index)``. Skips leading whitespace.
    The target spans until the next unquoted whitespace or redirection
    metacharacter. Quoted segments are honoured but stripped from the
    final value.
    """
    n = len(command)
    while idx < n and command[idx] in " \t":
        idx += 1
    start = idx
    in_single = False
    in_double = False
    while idx < n:
        c = command[idx]
        if in_single:
            if c == "'":
                in_single = False
            idx += 1
            continue
        if in_double:
            if c == "\\" and idx + 1 < n and command[idx + 1] in ('"', "\\", "$", "`"):
                idx += 2
                continue
            if c == '"':
                in_double = False
            idx += 1
            continue
        if c == "\\" and idx + 1 < n:
            idx += 2
            continue
        if c == "'":
            in_single = True
            idx += 1
            continue
        if c == '"':
            in_double = True
            idx += 1
            continue
        if c in _WORD_BOUNDARY:
            break
        idx += 1
    raw = command[start:idx]
    if not raw:
        return "", idx
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError:
        return raw, idx
    return ("".join(parts) if parts else raw), idx


def _at_token_boundary(command: str, i: int) -> bool:
    """Return True if position ``i`` is at the start of a token."""
    if i == 0:
        return True
    prev = command[i - 1]
    return prev in " \t<>&;|"


def parse_redirections(command: str) -> tuple[str, RedirectionSpec]:
    """Strip redirection clauses from ``command``.

    Returns ``(clean_command, RedirectionSpec)`` where ``clean_command`` is
    suitable to pass to :func:`shlex.split`. Redirection operators inside
    single or double quotes are left intact.
    """
    spec = RedirectionSpec()
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if in_single:
            out.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`"):
                out.append(c)
                out.append(command[i + 1])
                i += 2
                continue
            out.append(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c)
            out.append(command[i + 1])
            i += 2
            continue
        if c == "'":
            in_single = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            out.append(c)
            i += 1
            continue
        # Combined stdout/stderr redirection
        if (
            c == "&"
            and i + 2 < n
            and command[i + 1] == ">"
            and command[i + 2] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_target(command, i + 3)
            spec.stdout_path = target
            spec.stdout_append = True
            spec.stderr_to_stdout = True
            spec.stderr_path = None
            spec.stderr_append = False
            i = end
            continue
        if (
            c == "&"
            and i + 1 < n
            and command[i + 1] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_target(command, i + 2)
            spec.stdout_path = target
            spec.stdout_append = False
            spec.stderr_to_stdout = True
            spec.stderr_path = None
            spec.stderr_append = False
            i = end
            continue
        # stderr redirection (2> / 2>>)
        if (
            c == "2"
            and i + 2 < n
            and command[i + 1] == ">"
            and command[i + 2] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_target(command, i + 3)
            spec.stderr_path = target
            spec.stderr_append = True
            spec.stderr_to_stdout = False
            i = end
            continue
        if (
            c == "2"
            and i + 1 < n
            and command[i + 1] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_target(command, i + 2)
            spec.stderr_path = target
            spec.stderr_append = False
            spec.stderr_to_stdout = False
            i = end
            continue
        # stdout redirection (> / >>)
        if c == ">" and i + 1 < n and command[i + 1] == ">":
            target, end = _read_target(command, i + 2)
            spec.stdout_path = target
            spec.stdout_append = True
            i = end
            continue
        if c == ">":
            target, end = _read_target(command, i + 1)
            spec.stdout_path = target
            spec.stdout_append = False
            i = end
            continue
        # stdin redirection
        if c == "<":
            target, end = _read_target(command, i + 1)
            spec.stdin_path = target
            i = end
            continue
        out.append(c)
        i += 1
    clean = "".join(out).strip()
    # Collapse runs of whitespace that may have been left behind.
    clean = " ".join(clean.split())
    return clean, spec
