# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure completion helpers for the raw-mode line editor."""
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompletionResult:
    """Completion candidates and token replacement metadata."""

    token_start: int
    token_end: int
    prefix: str
    candidates: tuple[str, ...]


def complete_line(
    line: str,
    cursor: int,
    *,
    builtins: Iterable[str],
    aliases: Iterable[str],
) -> CompletionResult:
    """Return prefix-filtered completion candidates for ``line`` at ``cursor``."""
    cursor = max(0, min(len(line), cursor))
    start, prefix = current_token(line, cursor)
    command_position = line[:start].strip() == ""
    matches: list[str] = []
    if command_position:
        for name in (*tuple(builtins), *tuple(aliases)):
            if name.startswith(prefix):
                matches.append(name)
    matches.extend(filesystem_matches(prefix))
    return CompletionResult(start, cursor, prefix, tuple(_dedupe(matches)))


def current_token(line: str, cursor: int) -> tuple[int, str]:
    """Return ``(start, token_text)`` for the token under the cursor."""
    cursor = max(0, min(len(line), cursor))
    i = cursor
    in_single = False
    in_double = False
    last_break = 0
    pos = 0
    while pos < cursor:
        ch = line[pos]
        if in_single:
            if ch == "'":
                in_single = False
            pos += 1
            continue
        if in_double:
            if ch == "\\" and pos + 1 < cursor:
                pos += 2
                continue
            if ch == '"':
                in_double = False
            pos += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch.isspace():
            last_break = pos + 1
        pos += 1
    return last_break, line[last_break:i]


def filesystem_matches(prefix: str) -> list[str]:
    """Return filesystem entries matching ``prefix``."""
    expanded = os.path.expanduser(prefix) if prefix.startswith("~") else prefix
    directory, name_prefix = os.path.split(expanded)
    search_dir = Path(directory) if directory else Path.cwd()
    try:
        entries = list(search_dir.iterdir())
    except (OSError, PermissionError):
        return []
    matches: list[str] = []
    for entry in entries:
        name = entry.name
        if not name.startswith(name_prefix):
            continue
        display = os.path.join(directory, name) if directory else name
        try:
            if entry.is_dir():
                display += os.sep
        except OSError:
            pass
        matches.append(display)
    matches.sort()
    return matches


def apply_single_completion(line: str, result: CompletionResult) -> tuple[str, int]:
    """Apply a single completion candidate and return ``(text, cursor)``."""
    if len(result.candidates) != 1:
        return line, result.token_end
    candidate = result.candidates[0]
    suffix = "" if candidate.endswith(os.sep) else " "
    replacement = candidate + suffix
    text = line[: result.token_start] + replacement + line[result.token_end :]
    return text, result.token_start + len(replacement)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out

