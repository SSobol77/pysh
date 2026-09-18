# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/parsing/expansion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Variable and command-substitution expansion helpers."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable

DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS = 5.0

_VAR_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_POSITIONAL_BRACED_RE = re.compile(r"[0-9]+|[?@#*]")
_UNSUPPORTED_PARAMETER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?::-|:=|:\?|#|%|/).+|^#[A-Za-z_][A-Za-z0-9_]*$"
)


def expand_variables(
    text: str,
    local_vars: dict[str, str],
    env_vars: dict[str, str] | None = None,
    *,
    special_vars: dict[str, str] | None = None,
) -> str:
    """Expand simple variable and special-parameter references in ``text``."""
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
            if nxt == "?":
                out.append(_special.get("?", "0"))
                i += 2
                continue
            if nxt in "@#*":
                out.append(_special.get(nxt, ""))
                i += 2
                continue
            if nxt.isdigit():
                out.append(_special.get(nxt, ""))
                i += 2
                continue
            if nxt == "{":
                end = text.find("}", i + 2)
                if end == -1:
                    out.append(c)
                    i += 1
                    continue
                name = text[i + 2 : end]
                if _POSITIONAL_BRACED_RE.fullmatch(name):
                    out.append(_special.get(name, "0" if name == "?" else ""))
                    i = end + 1
                    continue
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


def is_unsupported_parameter_expansion(expr: str) -> bool:
    """Return True when braced parameter content is recognized but unsupported."""
    return bool(_UNSUPPORTED_PARAMETER_RE.fullmatch(expr))


def _default_runner(command: str, timeout: float) -> str:
    """Run ``command`` in a system shell with a timeout and capture stdout."""
    try:
        completed = subprocess.run(  # noqa: S603,S607 - existing command substitution
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
    """Expand ``$(command)`` and ``` `command` ``` substitutions in ``text``."""
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
    """Return the index of the ``)`` matching ``text[open_idx] == '('``."""
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
