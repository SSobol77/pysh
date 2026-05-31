# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/completion.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tab completion for the interactive shell.

The completer is intentionally simple:

* If the user is completing the first word of the line, it matches against
  aliases and shell builtins, plus filesystem entries.
* If the user is completing a later word, only filesystem entries are
  considered.
* All filesystem access is wrapped in try/except so that permission errors
  on individual directories do not break completion.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from pysh.lineedit.completion import (
    CompletionResult,
    apply_single_completion,
    complete_line,
)


class Completer:
    """Readline completion driver."""

    BUILTINS: tuple[str, ...] = (
        "cd",
        "pwd",
        "alias",
        "unalias",
        "export",
        "source",
        ".",
        "source_zsh",
        "source_zsh_profile",
        "source_sh_aliases",
        "run_script",
        "compat_check",
        "zsh",
        "zsh_fallback",
        "py",
        "pushd",
        "popd",
        "dirs",
        "svc",
        "exit",
        "quit",
        "sys_info",
        "env_audit",
        "path_audit",
        "which_all",
        "apt_check",
        "apt_search",
        "plan",
        "secure",
    )

    def __init__(self, get_aliases: Callable[[], Iterable[str]]) -> None:
        self._get_aliases = get_aliases
        self._matches: list[str] = []

    def install(self) -> None:
        """Wire the completer into ``readline`` if it is importable."""
        try:
            import readline
        except ImportError:
            return
        readline.set_completer(self.complete)
        readline.set_completer_delims(" \t\n\"'><=;|&")
        doc = readline.__doc__ or ""
        if "libedit" in doc:
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            self._matches = self._build_matches(text)
        if state < len(self._matches):
            return self._matches[state]
        return None

    def complete_line(self, line: str, cursor: int) -> list[str]:
        """Return completion matches for raw-mode editing."""
        return list(self.raw_completion(line, cursor).candidates)

    def raw_completion(self, line: str, cursor: int) -> CompletionResult:
        """Return raw-mode completion metadata."""
        return complete_line(
            line,
            cursor,
            builtins=self.BUILTINS,
            aliases=self._get_aliases(),
        )

    def apply_raw_completion(self, line: str, result: CompletionResult) -> tuple[str, int]:
        """Apply a single raw-mode completion candidate."""
        return apply_single_completion(line, result)

    def _build_matches(self, text: str) -> list[str]:
        try:
            import readline

            line = readline.get_line_buffer()
            begin = readline.get_begidx()
            is_first_word = line[:begin].strip() == ""
        except ImportError:
            is_first_word = True

        matches: list[str] = []
        if is_first_word:
            for name in (*self.BUILTINS, *self._get_aliases()):
                if name.startswith(text):
                    matches.append(name)
        matches.extend(self.filesystem_matches(text))

        seen: set[str] = set()
        unique: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique

    def filesystem_matches(self, text: str) -> list[str]:
        """Return filesystem entries matching ``text``. Safe on permission errors."""
        expanded = os.path.expanduser(text) if text.startswith("~") else text
        directory, prefix = os.path.split(expanded)
        search_dir = Path(directory) if directory else Path.cwd()
        try:
            entries = list(search_dir.iterdir())
        except (OSError, PermissionError):
            return []
        results: list[str] = []
        for entry in entries:
            name = entry.name
            if not name.startswith(prefix):
                continue
            display = os.path.join(directory, name) if directory else name
            try:
                if entry.is_dir():
                    display += os.sep
            except OSError:
                pass
            results.append(display)
        results.sort()
        return results
