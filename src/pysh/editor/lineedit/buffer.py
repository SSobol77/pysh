# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/lineedit/buffer.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure editable line buffer with character-indexed cursor state."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def _display_width(text: str) -> int:
    """Return the terminal display width of ``text``."""
    width = 0
    for ch in text:
        if unicodedata.category(ch) == "Mn":
            continue
        width += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
    return width


@dataclass
class LineBuffer:
    """Mutable line buffer. Cursor is an index into Unicode characters."""

    text: str = ""
    cursor: int = 0

    def insert(self, value: str) -> None:
        self.text = self.text[: self.cursor] + value + self.text[self.cursor :]
        self.cursor += len(value)

    def backspace(self) -> None:
        if self.cursor == 0:
            return
        self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
        self.cursor -= 1

    def delete(self) -> None:
        if self.cursor >= len(self.text):
            return
        self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]

    def move_left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def move_right(self) -> None:
        self.cursor = min(len(self.text), self.cursor + 1)

    def move_home(self) -> None:
        self.cursor = 0

    def move_end(self) -> None:
        self.cursor = len(self.text)

    def kill_to_end(self) -> None:
        self.text = self.text[: self.cursor]

    def kill_to_start(self) -> None:
        self.text = self.text[self.cursor :]
        self.cursor = 0

    def kill_word_back(self) -> None:
        if self.cursor == 0:
            return
        i = self.cursor
        while i > 0 and self.text[i - 1].isspace():
            i -= 1
        while i > 0 and not self.text[i - 1].isspace():
            i -= 1
        self.text = self.text[:i] + self.text[self.cursor :]
        self.cursor = i

    def set(self, text: str, cursor: int | None = None) -> None:
        self.text = text
        self.cursor = len(text) if cursor is None else max(0, min(len(text), cursor))

    def cursor_width(self) -> int:
        """Return display columns before the cursor."""
        return _display_width(self.text[: self.cursor])
