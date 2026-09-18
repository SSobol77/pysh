# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_editor_state.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the explicit editor state machine (Issue #36).

Covers valid/invalid transitions, cleanup on exit, repeated enter/exit
cycles, and that no mode's payload survives into a later mode.
"""
from __future__ import annotations

import pytest

from pysh.editor.lineedit.state import EditorMode, EditorState, EditorStateError

ACTIVE_MODES = [
    EditorMode.MULTILINE,
    EditorMode.HEREDOC,
    EditorMode.REVERSE_SEARCH,
    EditorMode.COMPLETION,
    EditorMode.PASTE_STAGED,
]


# --------------------------------------------------------------------- basic


def test_initial_mode_is_normal() -> None:
    state = EditorState()
    assert state.mode is EditorMode.NORMAL


@pytest.mark.parametrize("target", ACTIVE_MODES)
def test_normal_may_transition_to_any_active_mode(target: EditorMode) -> None:
    state = EditorState()
    assert state.can_transition(target)
    state.enter(target)
    assert state.mode is target


@pytest.mark.parametrize("target", ACTIVE_MODES)
def test_active_mode_may_transition_back_to_normal(target: EditorMode) -> None:
    state = EditorState()
    state.enter(target)
    assert state.can_transition(EditorMode.NORMAL)
    state.enter(EditorMode.NORMAL)
    assert state.mode is EditorMode.NORMAL


# ---------------------------------------------------------------- invalid


@pytest.mark.parametrize("source", ACTIVE_MODES)
@pytest.mark.parametrize("target", ACTIVE_MODES)
def test_active_modes_cannot_transition_directly_to_each_other(
    source: EditorMode, target: EditorMode
) -> None:
    if source is target:
        return
    state = EditorState()
    state.enter(source)
    assert not state.can_transition(target)
    with pytest.raises(EditorStateError):
        state.enter(target)
    # A failed transition must not mutate the current mode.
    assert state.mode is source


def test_same_mode_reentry_is_a_no_op() -> None:
    state = EditorState()
    state.enter(EditorMode.MULTILINE)
    state.multiline_buffer = ["py {"]
    assert state.can_transition(EditorMode.MULTILINE)
    state.enter(EditorMode.MULTILINE)
    assert state.mode is EditorMode.MULTILINE
    # Re-entering the same mode via enter() must not clear its payload;
    # only exit_to_normal()/clear_mode_payload() clear payload.
    assert state.multiline_buffer == ["py {"]


# ------------------------------------------------------------------ cleanup


def test_exit_to_normal_clears_all_payload_fields() -> None:
    state = EditorState()
    state.enter_multiline(opener="py {")
    state.exit_to_normal()
    assert state.mode is EditorMode.NORMAL
    assert state.multiline_buffer == []
    assert state.heredoc_delimiters == []
    assert state.heredoc_body == []
    assert state.paste_payload is None
    assert state.search_query == ""
    assert state.search_original_buffer == ""
    assert state.history_navigation_index is None


def test_clear_mode_payload_does_not_change_mode() -> None:
    state = EditorState()
    state.enter_heredoc(opener="cat <<EOF", delimiters=["EOF"])
    state.clear_mode_payload()
    assert state.mode is EditorMode.HEREDOC
    assert state.heredoc_body == []
    assert state.heredoc_delimiters == []


def test_repeated_enter_exit_cycles_leave_no_stale_state() -> None:
    state = EditorState()
    for _ in range(3):
        state.enter_multiline(opener="py {")
        state.multiline_buffer.append("print(1)")
        state.exit_to_normal()
        assert state.mode is EditorMode.NORMAL
        assert state.multiline_buffer == []

        state.enter_heredoc(opener="cat <<EOF", delimiters=["EOF"])
        state.heredoc_body.append("hello")
        state.exit_to_normal()
        assert state.mode is EditorMode.NORMAL
        assert state.heredoc_body == []


# ------------------------------------------------------------- per-mode API


def test_enter_paste_sets_payload_and_mode() -> None:
    state = EditorState()
    state.enter_paste("echo one\necho two\n")
    assert state.mode is EditorMode.PASTE_STAGED
    assert state.paste_payload == "echo one\necho two\n"


def test_paste_cleanup_clears_payload() -> None:
    state = EditorState()
    state.enter_paste("echo one\n")
    state.exit_to_normal()
    assert state.paste_payload is None
    assert state.mode is EditorMode.NORMAL


def test_second_paste_replaces_prior_payload_after_reentry() -> None:
    state = EditorState()
    state.enter_paste("first\n")
    state.exit_to_normal()
    state.enter_paste("second\n")
    assert state.paste_payload == "second\n"


def test_heredoc_cleanup_clears_delimiters_and_body() -> None:
    state = EditorState()
    state.enter_heredoc(opener="cat <<EOF", delimiters=["EOF"])
    state.heredoc_body.extend(["line one", "line two"])
    state.exit_to_normal()
    assert state.heredoc_delimiters == []
    assert state.heredoc_body == []
    assert state.mode is EditorMode.NORMAL


def test_multiline_cleanup_clears_buffer() -> None:
    state = EditorState()
    state.enter_multiline(opener="py {")
    state.multiline_buffer.append("x = 1")
    state.exit_to_normal()
    assert state.multiline_buffer == []
    assert state.mode is EditorMode.NORMAL


def test_search_cleanup_clears_query_and_original_buffer() -> None:
    state = EditorState()
    state.enter_reverse_search(original_buffer="echo partial")
    state.search_query = "echo"
    state.exit_to_normal()
    assert state.search_query == ""
    assert state.search_original_buffer == ""
    assert state.mode is EditorMode.NORMAL


def test_completion_returns_to_normal_cleanly() -> None:
    state = EditorState()
    state.enter_completion()
    assert state.mode is EditorMode.COMPLETION
    state.exit_to_normal()
    assert state.mode is EditorMode.NORMAL


# --------------------------------------------------------- cross-mode safety


def test_no_stale_payload_survives_into_next_mode() -> None:
    """A field left over from one mode must never leak into another mode's use."""
    state = EditorState()
    state.enter_multiline(opener="py {")
    state.multiline_buffer.append("print(1)")
    state.exit_to_normal()

    state.enter_heredoc(opener="cat <<EOF", delimiters=["EOF"])
    # The heredoc body must start empty, not carry over multiline fragments.
    assert state.heredoc_body == ["cat <<EOF"]
    assert state.multiline_buffer == []


def test_history_navigation_index_cleared_on_exit_to_normal() -> None:
    state = EditorState()
    state.history_navigation_index = 3
    state.enter_reverse_search(original_buffer="")
    state.exit_to_normal()
    assert state.history_navigation_index is None
