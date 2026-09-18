# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/parsing/redirection.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Redirection parsing for shell commands.

Supported operators (only recognized outside of single/double quotes):

* ``< file``           - stdin from file
* ``> file``           - stdout to file (truncate)
* ``>> file``          - stdout to file (append)
* ``2> file``          - stderr to file (truncate)
* ``2>> file``         - stderr to file (append)
* ``&> file``          - stdout + stderr to file (truncate)
* ``&>> file``         - stdout + stderr to file (append)
* ``<< WORD``          - stdin from collected heredoc body
* ``<<- WORD``         - stdin from collected heredoc body with tab stripping
* ``<<< WORD``         - stdin from collected here-string content

The target file may be attached to the operator (``>file``) or separated by
whitespace (``> file``). Targets may be quoted.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import StrEnum

from pysh.parsing.errors import ParseError
from pysh.parsing.heredoc import HereDocBody, parse_heredoc_operator


class RedirectionActionKind(StrEnum):
    """Operation applied to one descriptor in lexical order."""

    READ = "read"
    WRITE = "write"
    DUP = "dup"
    DATA = "data"


@dataclass(frozen=True)
class RedirectionAction:
    """One ordered file-descriptor redirection operation."""

    fd: int
    kind: RedirectionActionKind
    path: str | None = None
    append: bool = False
    source_fd: int | None = None
    data: bytes | None = None


@dataclass
class RedirectionSpec:
    """Captured redirections for a single command."""

    stdin_path: str | None = None
    stdin_data: bytes | None = None
    stdout_path: str | None = None
    stdout_append: bool = False
    stderr_path: str | None = None
    stderr_append: bool = False
    stderr_to_stdout: bool = False
    actions: list[RedirectionAction] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.actions
            and self.stdin_path is None
            and self.stdin_data is None
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


def _read_required_target(command: str, idx: int, operator: str) -> tuple[str, int]:
    """Read a non-empty file target or raise a deterministic parse error."""
    target, end = _read_target(command, idx)
    if not target:
        raise ParseError(f"missing redirection target after {operator}")
    return target, end


def _at_token_boundary(command: str, i: int) -> bool:
    """Return True if position ``i`` is at the start of a token."""
    if i == 0:
        return True
    prev = command[i - 1]
    return prev in " \t<>&;|"


def parse_redirections(
    command: str,
    heredoc_bodies: list[HereDocBody] | None = None,
) -> tuple[str, RedirectionSpec]:
    """Strip redirection clauses from ``command``.

    Returns ``(clean_command, RedirectionSpec)`` where ``clean_command`` is
    suitable to pass to :func:`shlex.split`. Redirection operators inside
    single or double quotes are left intact.
    """
    spec = RedirectionSpec()
    heredocs = heredoc_bodies if heredoc_bodies is not None else []
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
        heredoc_operator = parse_heredoc_operator(command, i)
        if heredoc_operator is not None:
            target, end = _read_target(command, i + len(heredoc_operator.value))
            if not target:
                raise ParseError(f"missing heredoc delimiter after {heredoc_operator.value}")
            if not heredocs:
                raise ParseError(f"missing heredoc body for {target}")
            body = heredocs.pop(0)
            spec.stdin_path = None
            spec.stdin_data = body.data.encode("utf-8")
            spec.actions.append(
                RedirectionAction(0, RedirectionActionKind.DATA, data=spec.stdin_data)
            )
            i = end
            continue
        # Descriptor duplication. These forms must be recognized before file
        # redirection so ``2>&1`` cannot degrade into ``2>`` plus an argv token.
        duplication: tuple[int, int, int] | None = None
        if command.startswith("2>&1", i) and _at_token_boundary(command, i):
            duplication = (2, 1, 4)
        elif command.startswith("1>&2", i) and _at_token_boundary(command, i):
            duplication = (1, 2, 4)
        elif command.startswith(">&2", i) and _at_token_boundary(command, i):
            duplication = (1, 2, 3)
        if duplication is not None:
            fd, source_fd, width = duplication
            spec.actions.append(
                RedirectionAction(fd, RedirectionActionKind.DUP, source_fd=source_fd)
            )
            if fd == 2 and source_fd == 1:
                spec.stderr_to_stdout = True
                spec.stderr_path = None
            i += width
            continue
        # Combined stdout/stderr redirection
        if (
            c == "&"
            and i + 2 < n
            and command[i + 1] == ">"
            and command[i + 2] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_required_target(command, i + 3, "&>>")
            spec.stdout_path = target
            spec.stdout_append = True
            spec.stderr_to_stdout = True
            spec.stderr_path = None
            spec.stderr_append = False
            spec.actions.append(
                RedirectionAction(1, RedirectionActionKind.WRITE, path=target, append=True)
            )
            spec.actions.append(
                RedirectionAction(2, RedirectionActionKind.DUP, source_fd=1)
            )
            i = end
            continue
        if (
            c == "&"
            and i + 1 < n
            and command[i + 1] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_required_target(command, i + 2, "&>")
            spec.stdout_path = target
            spec.stdout_append = False
            spec.stderr_to_stdout = True
            spec.stderr_path = None
            spec.stderr_append = False
            spec.actions.append(
                RedirectionAction(1, RedirectionActionKind.WRITE, path=target)
            )
            spec.actions.append(
                RedirectionAction(2, RedirectionActionKind.DUP, source_fd=1)
            )
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
            target, end = _read_required_target(command, i + 3, "2>>")
            spec.stderr_path = target
            spec.stderr_append = True
            spec.stderr_to_stdout = False
            spec.actions.append(
                RedirectionAction(2, RedirectionActionKind.WRITE, path=target, append=True)
            )
            i = end
            continue
        if (
            c == "2"
            and i + 1 < n
            and command[i + 1] == ">"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_required_target(command, i + 2, "2>")
            spec.stderr_path = target
            spec.stderr_append = False
            spec.stderr_to_stdout = False
            spec.actions.append(
                RedirectionAction(2, RedirectionActionKind.WRITE, path=target)
            )
            i = end
            continue
        # Explicit stdout descriptor (1> / 1>>).
        if (
            c == "1"
            and i + 2 < n
            and command[i + 1 : i + 3] == ">>"
            and _at_token_boundary(command, i)
        ):
            target, end = _read_required_target(command, i + 3, "1>>")
            spec.stdout_path = target
            spec.stdout_append = True
            spec.actions.append(
                RedirectionAction(1, RedirectionActionKind.WRITE, path=target, append=True)
            )
            i = end
            continue
        if c == "1" and i + 1 < n and command[i + 1] == ">" and _at_token_boundary(command, i):
            target, end = _read_required_target(command, i + 2, "1>")
            spec.stdout_path = target
            spec.stdout_append = False
            spec.actions.append(RedirectionAction(1, RedirectionActionKind.WRITE, path=target))
            i = end
            continue
        # stdout redirection (> / >>)
        if c == ">" and i + 1 < n and command[i + 1] == ">":
            target, end = _read_required_target(command, i + 2, ">>")
            spec.stdout_path = target
            spec.stdout_append = True
            spec.actions.append(
                RedirectionAction(1, RedirectionActionKind.WRITE, path=target, append=True)
            )
            i = end
            continue
        if c == ">":
            target, end = _read_required_target(command, i + 1, ">")
            spec.stdout_path = target
            spec.stdout_append = False
            spec.actions.append(RedirectionAction(1, RedirectionActionKind.WRITE, path=target))
            i = end
            continue
        # Explicit stdin descriptor (0<).
        if c == "0" and i + 1 < n and command[i + 1] == "<" and _at_token_boundary(command, i):
            target, end = _read_required_target(command, i + 2, "0<")
            spec.stdin_path = target
            spec.stdin_data = None
            spec.actions.append(RedirectionAction(0, RedirectionActionKind.READ, path=target))
            i = end
            continue
        # stdin redirection
        if c == "<":
            target, end = _read_required_target(command, i + 1, "<")
            spec.stdin_path = target
            spec.stdin_data = None
            spec.actions.append(RedirectionAction(0, RedirectionActionKind.READ, path=target))
            i = end
            continue
        out.append(c)
        i += 1
    clean = "".join(out).strip()
    # Collapse runs of whitespace that may have been left behind.
    clean = " ".join(clean.split())
    return clean, spec
