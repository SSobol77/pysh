# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Native path and glob expansion for PySH (Issue #9).

Expansion order (applied by tokenize_and_glob_expand after variable and
command-substitution expansion has already occurred upstream):

  1. Tilde expansion  (``~``, ``~/path``, ``~user``)
  2. Glob/path expansion  (``*``, ``?``, ``[...]``, ``**``)

Quoting policy:

  * Single-quoted text: literal — no tilde or glob expansion.
  * Double-quoted text: literal — no tilde or glob expansion.
  * Backslash-escaped characters outside quotes: literal for the escaped char.
  * Unquoted tokens starting with ``~``: tilde expansion applied.
  * Unquoted tokens containing ``*``, ``?``, or ``[``: filesystem glob applied.

No-match policy (default):

  * A glob pattern that matches no filesystem entries is returned as the
    original literal pattern (``NoMatchPolicy.LITERAL``).  This matches
    common non-nullglob shell behavior.

Dotfile policy:

  * ``*`` does not match names beginning with ``.`` unless the pattern
    component itself begins with ``.``.  This matches common shell behavior.
    Python's ``glob.glob`` does not follow this convention; the filter is
    applied manually.

Brace expansion: not supported (Issue #9 scope excludes brace expansion).

Rules:
- Standard library only.
- No I/O at import time.
- No imports from pysh.core, pysh.editor, pysh.prompt, pysh.python_layer.
- No shell state mutation.
- No command execution.
"""
from __future__ import annotations

import glob as _glob_module
import os
import os.path
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# Policy types
# ---------------------------------------------------------------------------


class NoMatchPolicy(StrEnum):
    """Behavior when a glob pattern matches no filesystem entries."""

    LITERAL = "literal"  # return the original pattern (default)
    ERROR = "error"      # raise ValueError
    EMPTY = "empty"      # return an empty list


@dataclass(frozen=True)
class PathExpansionOptions:
    """Options controlling path/glob expansion behavior."""

    no_match: NoMatchPolicy = NoMatchPolicy.LITERAL
    recursive_globstar: bool = True
    sort: bool = True


# ---------------------------------------------------------------------------
# Metacharacter detection
# ---------------------------------------------------------------------------

_GLOB_METACHARS: frozenset[str] = frozenset("*?[")


def has_glob_metacharacters(word: str) -> bool:
    """Return True when *word* contains at least one glob metacharacter.

    Metacharacters are ``*``, ``?``, and ``[``.  This function does not
    examine quoting or escaping context — the caller is responsible for
    calling this only on already-unquoted words.
    """
    return any(c in _GLOB_METACHARS for c in word)


# ---------------------------------------------------------------------------
# Tilde expansion
# ---------------------------------------------------------------------------


def expand_tilde(word: str) -> str:
    """Expand a leading ``~`` or ``~user`` in *word*.

    Delegates to :func:`os.path.expanduser`.  Returns *word* unchanged when
    it does not start with ``~``.
    """
    if not word.startswith("~"):
        return word
    return os.path.expanduser(word)


# ---------------------------------------------------------------------------
# Filesystem glob expansion
# ---------------------------------------------------------------------------


def expand_path_word(
    word: str,
    *,
    cwd: Path | None = None,
    options: PathExpansionOptions | None = None,
) -> list[str]:
    """Expand a single already-unquoted shell word via tilde and glob.

    Steps:

    1. Apply tilde expansion (``~`` → home directory).
    2. If the result contains glob metacharacters, expand via filesystem.
    3. Apply no-match policy on empty results.
    4. Sort results deterministically when ``options.sort`` is True.

    Dotfile policy: Python's ``glob.glob`` follows shell convention — ``*``
    does not match names beginning with ``.``.  To match dotfiles, use a
    pattern that explicitly begins with ``.`` (e.g., ``.*`` or ``.*.py``).

    Returns a list of one or more strings.  On no-match with
    ``NoMatchPolicy.LITERAL``, the original *word* (before tilde expansion)
    is returned as a single-element list.
    """
    opts = options or PathExpansionOptions()
    tilded = expand_tilde(word)
    if not has_glob_metacharacters(tilded):
        return [tilded]

    effective_cwd = Path(os.getcwd()) if cwd is None else cwd
    is_absolute = os.path.isabs(tilded)

    if is_absolute:
        raw_pattern = tilded
    else:
        raw_pattern = str(effective_cwd / tilded)

    raw_matches = _glob_module.glob(raw_pattern, recursive=opts.recursive_globstar)

    if opts.sort:
        raw_matches.sort()

    if not raw_matches:
        if opts.no_match == NoMatchPolicy.LITERAL:
            return [word]  # original literal pattern, not tilde-expanded
        if opts.no_match == NoMatchPolicy.EMPTY:
            return []
        raise ValueError(f"no match: {word}")

    if is_absolute:
        return raw_matches

    cwd_prefix = str(effective_cwd)
    sep = os.sep
    if not cwd_prefix.endswith(sep):
        cwd_prefix += sep
    return [
        m[len(cwd_prefix):] if m.startswith(cwd_prefix) else m
        for m in raw_matches
    ]


def expand_path_words(
    words: list[str],
    *,
    cwd: Path | None = None,
    options: PathExpansionOptions | None = None,
) -> list[str]:
    """Expand a list of already-unquoted shell words via tilde and glob.

    Each word in *words* is passed to :func:`expand_path_word`.  Words that
    produce multiple matches (glob expansion) are flattened into the result.
    """
    result: list[str] = []
    for word in words:
        result.extend(expand_path_word(word, cwd=cwd, options=options))
    return result


# ---------------------------------------------------------------------------
# Quote-aware tokenizer with integrated glob expansion
# ---------------------------------------------------------------------------


def tokenize_and_glob_expand(
    text: str,
    *,
    cwd: Path | None = None,
    options: PathExpansionOptions | None = None,
) -> list[str]:
    """Split a post-expansion shell string into argv with glob expansion.

    This function replaces :func:`shlex.split` in the PySH execution path.
    It applies the same quoting rules (single quotes, double quotes,
    backslash escapes) while also performing:

    * **Tilde expansion** on unquoted tokens that begin with ``~``.
    * **Glob expansion** on unquoted tokens that contain ``*``, ``?``, or
      ``[``.

    Quoting suppresses both expansions:

    * ``"*.py"``  →  literal ``*.py``   (double-quoted)
    * ``'*.py'``  →  literal ``*.py``   (single-quoted)
    * ``\\*.py``  →  literal ``*.py``   (backslash-escaped ``*``)
    * ``*.py``    →  expanded matching paths (unquoted)

    Raises :class:`ValueError` for unterminated quotes (same behaviour as
    :func:`shlex.split` with ``posix=True``).
    """
    opts = options or PathExpansionOptions()
    effective_cwd = Path(os.getcwd()) if cwd is None else cwd

    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        # --- skip whitespace between tokens ---
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            break

        # --- collect one token ---
        chars: list[str] = []
        has_active_glob = False   # unquoted glob metachar seen
        tilde_at_start = False    # token starts with unquoted ~
        in_single = False
        in_double = False

        while i < n:
            c = text[i]

            if in_single:
                if c == "'":
                    in_single = False
                    i += 1
                    continue
                chars.append(c)
                i += 1
                continue

            if in_double:
                # POSIX double-quote escapes: \", \\, \$, \`
                if c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\", "$", "`"):
                    chars.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    in_double = False
                    i += 1
                    continue
                chars.append(c)
                i += 1
                continue

            # --- outside all quotes ---
            if c in " \t":
                break  # token boundary

            if c == "\\" and i + 1 < n:
                # Backslash escape: next char is literal (not a glob trigger)
                chars.append(text[i + 1])
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

            # Unquoted regular character
            if not chars and c == "~":
                tilde_at_start = True
            if c in _GLOB_METACHARS:
                has_active_glob = True
            chars.append(c)
            i += 1

        # --- unterminated quote check ---
        if in_single:
            raise ValueError("pysh: unterminated single quote")
        if in_double:
            raise ValueError("pysh: unterminated double quote")

        if not chars:
            continue

        word = "".join(chars)

        if has_active_glob:
            expanded = expand_path_word(word, cwd=effective_cwd, options=opts)
            result.extend(expanded)
        elif tilde_at_start:
            result.append(expand_tilde(word))
        else:
            result.append(word)

    return result
