# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Persistent history and Ctrl+R reverse search support.

This module wraps the standard library :mod:`readline` so the interactive
shell can offer Bash-like persistent history and reverse incremental search.

Design rules:
  * History file path is configurable so tests can use a temporary location.
  * Loading and saving never raise; failures are silent and the shell keeps
    running.
  * Ctrl+R is bound only when GNU readline (not libedit) is detected. Other
    platforms degrade gracefully.
  * Pure helpers (`split_history_lines`, `dedupe_consecutive`) are exposed
    for unit testing without touching the global readline state.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

DEFAULT_HISTORY_PATH = Path("~/.pysh_history").expanduser()
DEFAULT_HISTORY_LENGTH = 10_000


def split_history_lines(text: str) -> list[str]:
    """Return non-empty history entries from a raw history file body."""
    return [line for line in text.splitlines() if line.strip()]


def dedupe_consecutive(entries: Iterable[str]) -> list[str]:
    """Collapse runs of duplicate adjacent entries, preserving order."""
    out: list[str] = []
    last: str | None = None
    for entry in entries:
        if entry != last:
            out.append(entry)
            last = entry
    return out


class HistoryManager:
    """Wrap readline history loading, saving, and Ctrl+R binding."""

    def __init__(
        self,
        path: Path = DEFAULT_HISTORY_PATH,
        max_length: int = DEFAULT_HISTORY_LENGTH,
    ) -> None:
        self.path = Path(path)
        self.max_length = max_length

    # ------------------------------------------------------------------ load
    def load(self) -> bool:
        """Load history from disk. Returns True if anything was loaded."""
        try:
            import readline
        except ImportError:
            return False
        try:
            if self.path.exists():
                readline.read_history_file(str(self.path))
        except OSError:
            return False
        try:
            readline.set_history_length(self.max_length)
        except (AttributeError, ValueError):
            pass
        return True

    # ------------------------------------------------------------------ save
    def save(self) -> bool:
        """Persist current readline history to disk. Returns success."""
        try:
            import readline
        except ImportError:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        try:
            readline.write_history_file(str(self.path))
        except OSError:
            return False
        return True

    # ----------------------------------------------------------------- reverse
    def bind_reverse_search(self) -> bool:
        """Bind Ctrl+R to reverse-search-history if the backend supports it.

        Returns True on success, False if readline is unavailable or the bind
        directive is rejected (e.g. libedit).
        """
        try:
            import readline
        except ImportError:
            return False
        doc = readline.__doc__ or ""
        try:
            if "libedit" in doc:
                # libedit uses a different bind syntax and historically lacks a
                # working reverse-i-search; do not break the user's terminal.
                return False
            readline.parse_and_bind(r'"\C-r": reverse-search-history')
        except Exception:  # noqa: BLE001 - any backend failure must be silent
            return False
        return True

    # ----------------------------------------------------------------- helpers
    def read_entries(self) -> list[str]:
        """Read entries directly from the on-disk history file."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return []
        return split_history_lines(text)

    def entries(self) -> list[str]:
        """Return current readline history if available, else on-disk entries."""
        try:
            import readline
        except ImportError:
            return self.read_entries()
        try:
            length = readline.get_current_history_length()
            return [
                item
                for i in range(1, length + 1)
                if (item := readline.get_history_item(i)) is not None
            ]
        except Exception:  # noqa: BLE001 - backend failures must not break editing
            return self.read_entries()

    def add(self, line: str) -> None:
        """Add one non-empty entry to readline history when available."""
        if not line.strip():
            return
        try:
            import readline
        except ImportError:
            return
        try:
            readline.add_history(line)
        except Exception:  # noqa: BLE001 - history backend failures are non-fatal
            return
