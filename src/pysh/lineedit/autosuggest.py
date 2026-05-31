# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/lineedit/autosuggest.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Pure history autosuggestion logic."""
from __future__ import annotations

from collections.abc import Sequence


class AutoSuggester:
    """Suggest the tail of the most recent matching history entry."""

    def suggest(self, line: str, history: Sequence[str]) -> str | None:
        """Return a completion tail from history, or ``None``."""
        if not line:
            return None
        seen: set[str] = set()
        for entry in reversed(history):
            if entry in seen:
                continue
            seen.add(entry)
            if len(entry) > len(line) and entry.startswith(line):
                return entry[len(line) :]
        return None

