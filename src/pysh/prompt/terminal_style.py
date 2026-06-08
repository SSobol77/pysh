# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/prompt/terminal_style.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Centralized ANSI SGR styling helpers for PySH interactive UI.

Covers paste preview, diagnostics, key hints, and search labels.
NO_COLOR and PYSH_NO_COLOR are always respected — they disable ANSI
output only and must never affect bracketed-paste mode or execution
behaviour (that is enforced in shell.py, not here).

The plain-text structure of every output block is preserved when
styling is off so that test assertions that check substrings after
ANSI stripping remain stable.

Color-safety notes
------------------
All SGR codes used here were chosen to remain readable on both dark-theme
and light-theme terminal emulators, including VS Code's default themes.

Codes intentionally avoided:
  \033[2;37m — dim+white: renders as near-invisible black on dark backgrounds.
  \033[34m   — blue:      too dark on dark backgrounds, often appears black.

Safe codes used:
  \033[90m — bright-black (gray): universally readable as secondary text.
  \033[32m — green   \033[33m — yellow   \033[35m — magenta   \033[36m — cyan
  \033[31m — red (bold for errors only)
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable

_RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Semantic palette — safe on dark AND light terminal themes.
# Specifically: no dim-white (2;37), no dark-blue (34).
# ---------------------------------------------------------------------------
_ROLE_SGR: dict[str, str] = {
    "prompt":      "\033[36m",    # cyan
    "warning":     "\033[33m",    # yellow — paste header, cancel notice
    "error":       "\033[1;31m",  # bold red — errors only
    "hint":        "\033[36m",    # cyan — key hints, secondary labels
    "frame":       "\033[90m",    # bright-black (gray) — [paste:begin] markers
    "line_number": "",            # no styling — plain numerals are visually clear
    "payload":     "",            # no styling — syntax highlighting provides colour
    "success":     "\033[32m",    # green — paste_run header
    "search":      "\033[35m",    # magenta — search label
    "pending":     "\033[33m",    # yellow — [paste:N] pending state tag
}

# ---------------------------------------------------------------------------
# Minimal Python preview highlighter (stdlib only, no pysh imports).
# Used for py { ... } block content in paste preview.
# ---------------------------------------------------------------------------
_PY_KEYWORDS: frozenset[str] = frozenset({
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
    "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "True", "False", "None",
})

_PY_KW_SGR  = "\033[36m"   # cyan — keywords (not dark blue; readable everywhere)
_PY_STR_SGR = "\033[32m"   # green — strings
_PY_CMT_SGR = "\033[90m"   # bright-black (gray) — comments (NOT dim+white 2;37)
_PY_NUM_SGR = "\033[33m"   # yellow — numeric literals

_PY_NUM_BARE_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")

# ---------------------------------------------------------------------------
# Minimal shell preview highlighter (stdlib only, no pysh imports).
# Safer than editor.highlight: avoids dark-blue variable colour (\033[34m).
# ---------------------------------------------------------------------------
_SH_CMD_SGR = "\033[36m"   # cyan    — command names
_SH_OP_SGR  = "\033[33m"   # yellow  — operators and redirections
_SH_VAR_SGR = "\033[35m"   # magenta — shell variables ($VAR, $?, ${FOO})
_SH_STR_SGR = "\033[32m"   # green   — quoted strings
_SH_CMT_SGR = "\033[90m"   # gray    — comments

# Characters that end a plain shell word token.
_SH_WORD_STOP = frozenset(' \t;|><"\'$#&()')


def highlight_shell_preview_line(line: str, *, enabled: bool) -> str:
    """Safe shell line highlighter for paste preview.

    Uses cyan for command names, magenta for variables, yellow for
    operators/redirections, green for quoted strings, gray for comments.
    Avoids dark-blue (\033[34m) which renders as black on dark backgrounds.
    The result is ANSI-strip-stable: stripping all SGR codes recovers the
    original line exactly.
    """
    if not enabled or not line.strip():
        return line

    out: list[str] = []
    i = 0
    n = len(line)
    expect_command = True  # True when the next word token is a command name.

    while i < n:
        c = line[i]

        # Whitespace — emit directly.
        if c in " \t":
            out.append(c)
            i += 1
            continue

        # Comment — rest of line.
        if c == "#":
            out.append(f"{_SH_CMT_SGR}{line[i:]}{_RESET}")
            break

        # Single-quoted string (no escapes inside).
        if c == "'":
            j = i + 1
            while j < n and line[j] != "'":
                j += 1
            if j < n:
                j += 1  # include closing quote
            out.append(f"{_SH_STR_SGR}{line[i:j]}{_RESET}")
            i = j
            expect_command = False
            continue

        # Double-quoted string (backslash escapes).
        if c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\" and j + 1 < n:
                    j += 2
                elif line[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            out.append(f"{_SH_STR_SGR}{line[i:j]}{_RESET}")
            i = j
            expect_command = False
            continue

        # Variable: $VAR, ${VAR}, $?, $@, $*, $#, $0-$9.
        if c == "$":
            j = i + 1
            if j < n and line[j] == "{":
                j += 1
                while j < n and line[j] != "}":
                    j += 1
                if j < n:
                    j += 1
            elif j < n and (line[j].isalnum() or line[j] in "_?@*#"):
                while j < n and (line[j].isalnum() or line[j] == "_"):
                    j += 1
            out.append(f"{_SH_VAR_SGR}{line[i:j]}{_RESET}")
            i = j
            expect_command = False
            continue

        # Two-character operators first.
        two = line[i : i + 2]
        if two in ("&&", "||", ">>", "2>", "&>", "<<", "<<"):
            out.append(f"{_SH_OP_SGR}{two}{_RESET}")
            i += 2
            expect_command = True
            continue

        # Single-character operators.
        if c in (";", "|", ">", "<"):
            out.append(f"{_SH_OP_SGR}{c}{_RESET}")
            i += 1
            expect_command = True
            continue

        # Plain word token.
        j = i
        while j < n and line[j] not in _SH_WORD_STOP:
            j += 1
        token = line[i:j]
        if expect_command and token:
            out.append(f"{_SH_CMD_SGR}{token}{_RESET}")
            expect_command = False
        else:
            out.append(token)
        i = j

    return "".join(out)


def highlight_python_preview_line(line: str, *, enabled: bool) -> str:
    """Return a minimally syntax-highlighted Python line for paste preview.

    Uses a single left-to-right character scan so that applied SGR codes
    are never re-processed by later patterns.  Highlights: inline comments,
    quoted strings, numeric literals, and keyword-starting tokens.
    """
    if not enabled or not line.strip():
        return line

    out: list[str] = []
    i = 0
    n = len(line)

    word_buf: list[str] = []

    def flush_word() -> None:
        if not word_buf:
            return
        word = "".join(word_buf)
        word_buf.clear()
        bare = word.rstrip(":,(")
        if bare in _PY_KEYWORDS:
            suffix = word[len(bare):]
            out.append(f"{_PY_KW_SGR}{bare}{_RESET}{suffix}")
        elif _PY_NUM_BARE_RE.fullmatch(bare):
            suffix = word[len(bare):]
            out.append(f"{_PY_NUM_SGR}{bare}{_RESET}{suffix}")
        else:
            out.append(word)

    while i < n:
        c = line[i]

        if c == "#":
            flush_word()
            out.append(f"{_PY_CMT_SGR}{line[i:]}{_RESET}")
            i = n
            break

        if c in ('"', "'"):
            flush_word()
            q = c
            if line[i : i + 3] in ('"""', "'''"):
                q = line[i : i + 3]
            j = i + len(q)
            while j < n:
                if line[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if line[j : j + len(q)] == q:
                    j += len(q)
                    break
                j += 1
            out.append(f"{_PY_STR_SGR}{line[i:j]}{_RESET}")
            i = j
            continue

        if c.isalnum() or c == "_":
            word_buf.append(c)
            i += 1
            continue

        flush_word()
        out.append(c)
        i += 1

    flush_word()
    return "".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def style_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True when ANSI styling may be emitted to stdout.

    Does NOT affect bracketed-paste mode or any execution behaviour.
    """
    _env = os.environ if env is None else env
    if "NO_COLOR" in _env:
        return False
    if _env.get("PYSH_NO_COLOR") == "1":
        return False
    override = _env.get("PYSH_COLOR", "").strip().lower()
    if override in {"0", "false", "no", "off"}:
        return False
    if override == "always":
        return True
    term = _env.get("TERM", "")
    if not term or term == "dumb":
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def style(text: str, role: str, *, enabled: bool) -> str:
    """Wrap *text* in the ANSI SGR sequence for *role* when *enabled*."""
    if not enabled or not text:
        return text
    code = _ROLE_SGR.get(role, "")
    if not code:
        return text
    return f"{code}{text}{_RESET}"


def frame_preview(
    payload: str,
    title: str,
    *,
    enabled: bool,
    max_lines: int | None = None,
    line_highlighter: Callable[[str, int], str] | None = None,
) -> list[str]:
    """Return a numbered preview block for paste payload display.

    The ``[title:begin]`` / ``N | line`` / ``[title:end]`` structure is
    preserved in both color and no-color modes so that test assertions
    checking plain-text substrings after ANSI stripping remain stable.

    *line_highlighter*, when provided, is called as ``fn(line_text, index)``
    (0-based index) and may return an ANSI-coloured version of the line.
    It is only called when *enabled* is True.
    """
    lines = payload.splitlines() or [""]
    visible = lines if max_lines is None else lines[:max_lines]
    truncated = max_lines is not None and len(lines) > max_lines

    result: list[str] = [style(f"[{title}:begin]", "frame", enabled=enabled)]
    for i, ln in enumerate(visible, start=1):
        num = style(str(i), "line_number", enabled=enabled)
        if enabled and line_highlighter is not None:
            body = line_highlighter(ln, i - 1)
        else:
            body = ln
        result.append(f"{num} | {body}")
    if truncated:
        hidden = len(lines) - (max_lines or 0)
        result.append(
            style(
                f"... {hidden} more lines hidden; use paste_show to inspect all",
                "hint",
                enabled=enabled,
            )
        )
    result.append(style(f"[{title}:end]", "frame", enabled=enabled))
    return result


def format_key_hints(hints: list[tuple[str, str]], *, enabled: bool) -> str:
    """Return a formatted key-hint line for user-action reminders."""
    if enabled:
        parts = [f"{style(key, 'hint', enabled=enabled)} = {desc}" for key, desc in hints]
        return "  ".join(parts)
    parts = [f"{key} = {desc}" for key, desc in hints]
    return " | ".join(parts)
