# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/lineedit/state.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Explicit editor-mode state machine for the interactive line editor.

``EditorState`` tracks which interactive editing mode is active
(:class:`EditorMode`) and the payload associated with that mode. It holds
only editor-state data — never shell execution logic, terminal I/O, or the
:class:`~pysh.editor.lineedit.buffer.LineBuffer` itself, which remains owned
per read cycle by :class:`~pysh.editor.lineedit.reader.RawLineReader`.

Transition rules
-----------------
* ``NORMAL`` may transition to any active mode.
* An active mode may transition only back to ``NORMAL``; it may not
  transition directly into another active mode (callers must call
  :meth:`EditorState.exit_to_normal` first, which also clears the mode's
  payload so stale state never survives into the next command).
* Re-entering the mode a state machine is already in is a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EditorMode(StrEnum):
    """Interactive editor modes tracked by :class:`EditorState`."""

    NORMAL = "normal"
    MULTILINE = "multiline"
    HEREDOC = "heredoc"
    REVERSE_SEARCH = "reverse_search"
    COMPLETION = "completion"
    PASTE_STAGED = "paste_staged"


class EditorStateError(RuntimeError):
    """Raised when an invalid editor-mode transition is attempted."""


_ACTIVE_MODES: frozenset[EditorMode] = frozenset(
    {
        EditorMode.MULTILINE,
        EditorMode.HEREDOC,
        EditorMode.REVERSE_SEARCH,
        EditorMode.COMPLETION,
        EditorMode.PASTE_STAGED,
    }
)

# Transition table: mode -> set of modes directly reachable from it.
_ALLOWED_TRANSITIONS: dict[EditorMode, frozenset[EditorMode]] = {
    EditorMode.NORMAL: _ACTIVE_MODES,
    EditorMode.MULTILINE: frozenset({EditorMode.NORMAL}),
    EditorMode.HEREDOC: frozenset({EditorMode.NORMAL}),
    EditorMode.REVERSE_SEARCH: frozenset({EditorMode.NORMAL}),
    EditorMode.COMPLETION: frozenset({EditorMode.NORMAL}),
    EditorMode.PASTE_STAGED: frozenset({EditorMode.NORMAL}),
}


@dataclass
class EditorState:
    """Editor-mode state machine.

    Attributes hold only the payload associated with the active mode. Every
    cancellation, error, and completion path must route through
    :meth:`exit_to_normal` so no fragment of one command's editor state can
    be observed by the next.
    """

    mode: EditorMode = EditorMode.NORMAL
    multiline_buffer: list[str] = field(default_factory=list)
    heredoc_delimiters: list[str] = field(default_factory=list)
    heredoc_body: list[str] = field(default_factory=list)
    paste_payload: str | None = None
    search_query: str = ""
    search_original_buffer: str = ""
    history_navigation_index: int | None = None

    def can_transition(self, target: EditorMode) -> bool:
        """Return whether a direct transition to *target* is legal."""
        if target is self.mode:
            return True
        return target in _ALLOWED_TRANSITIONS.get(self.mode, frozenset())

    def enter(self, target: EditorMode) -> None:
        """Transition to *target*, raising :class:`EditorStateError` if illegal."""
        if not self.can_transition(target):
            raise EditorStateError(
                f"pysh: editor: cannot transition from {self.mode.value!r} "
                f"to {target.value!r}"
            )
        self.mode = target

    def exit_to_normal(self) -> None:
        """Return to :attr:`EditorMode.NORMAL`, clearing mode-specific payload."""
        self.clear_mode_payload()
        self.mode = EditorMode.NORMAL

    def clear_mode_payload(self) -> None:
        """Clear all mode-specific payload without changing the active mode."""
        self.multiline_buffer = []
        self.heredoc_delimiters = []
        self.heredoc_body = []
        self.paste_payload = None
        self.search_query = ""
        self.search_original_buffer = ""
        self.history_navigation_index = None

    def enter_multiline(self, *, opener: str | None = None) -> None:
        """Enter :attr:`EditorMode.MULTILINE`, seeding the collected buffer."""
        self.enter(EditorMode.MULTILINE)
        self.multiline_buffer = [opener] if opener is not None else []

    def enter_heredoc(
        self,
        *,
        opener: str | None = None,
        delimiters: list[str] | None = None,
    ) -> None:
        """Enter :attr:`EditorMode.HEREDOC` for the given pending *delimiters*."""
        self.enter(EditorMode.HEREDOC)
        self.heredoc_body = [opener] if opener is not None else []
        self.heredoc_delimiters = list(delimiters) if delimiters is not None else []

    def enter_reverse_search(self, *, original_buffer: str = "") -> None:
        """Enter :attr:`EditorMode.REVERSE_SEARCH`, saving the buffer to restore."""
        self.enter(EditorMode.REVERSE_SEARCH)
        self.search_original_buffer = original_buffer
        self.search_query = ""

    def enter_paste(self, payload: str) -> None:
        """Enter :attr:`EditorMode.PASTE_STAGED` with the staged paste payload."""
        self.enter(EditorMode.PASTE_STAGED)
        self.paste_payload = payload

    def enter_completion(self) -> None:
        """Enter :attr:`EditorMode.COMPLETION` while a candidate menu is shown."""
        self.enter(EditorMode.COMPLETION)
