# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

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

