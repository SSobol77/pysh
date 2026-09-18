# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/lineedit/autosuggest.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure history autosuggestion logic."""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from pysh.editor.lineedit.completion import CompletionResult


class AutoSuggester:
    """Suggest the tail of the most recent matching history entry."""

    def __init__(
        self,
        complete: Callable[[str, int], CompletionResult] | None = None,
    ) -> None:
        self._complete = complete

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
        if self._complete is None:
            return None
        result = self._complete(line, len(line))
        context = result.context
        if context is None or not context.command_position or not result.candidates:
            return None
        prefix = context.prefix
        if len(result.candidates) == 1:
            candidate = result.candidates[0]
            return candidate[len(prefix) :] if len(candidate) > len(prefix) else None
        common = os.path.commonprefix(result.candidates)
        if len(common) <= len(prefix):
            return None
        return common[len(prefix) :]
