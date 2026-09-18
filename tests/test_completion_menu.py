# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_completion_menu.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for PYSH-0.9.0-BUG-022 (bounded completion candidate display).

BUG-022 bounds only how many already-ranked candidates the completion menu
*renders* at once, so a broad prefix (e.g. ``p<TAB>``) cannot flood the
terminal. Candidate discovery, ranking, deduplication, prefix-only matching,
and autosuggestion semantics (BUG-020) are untouched — those are covered by
tests/test_completion_bug020_regression.py and tests/test_lineedit_completion.py,
and are re-run here only where directly relevant to display bounding.
"""
from __future__ import annotations

import os
import re

from pysh.editor.completion import Completer
from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.completion import CompletionResult, complete_line
from pysh.editor.lineedit.reader import (
    _COMPLETION_MENU_COLUMN_SPACING,
    _MAX_COMPLETION_MENU_ROWS,
    RawLineReader,
)


class _StubCompleter:
    """Minimal completer returning one fixed, fully-controlled result.

    A real :class:`Completer` also discovers PySH builtins, PATH
    executables, and filesystem entries, so its candidate set for a short
    prefix like ``"ec"`` is not actually under a test's control (it depends
    on the host's PATH and cwd). This stub makes tests of ``_complete()``'s
    own logic (common-prefix insertion, menu bounding, buffer/cursor
    preservation) hermetic by returning exactly the candidates the test
    asks for, nothing more.
    """

    def __init__(self, result: CompletionResult) -> None:
        self._result = result

    def raw_completion(self, line: str, cursor: int) -> CompletionResult:
        del line, cursor
        return self._result

# ----------------------------------------------------- _format_completion_menu


def test_large_candidate_set_is_bounded_to_max_rows_with_exact_hidden_count() -> None:
    candidates = tuple(f"cmd{i:03d}" for i in range(250))
    menu = RawLineReader._format_completion_menu(candidates, terminal_width=80)

    lines = menu.split("\r\n")
    summary = lines[-1]
    candidate_rows = lines[:-1]

    assert len(candidate_rows) <= _MAX_COMPLETION_MENU_ROWS
    assert summary.startswith("…")
    assert "type more characters to narrow" in summary

    column_width = max(len(c) for c in candidates) + _COMPLETION_MENU_COLUMN_SPACING
    columns = 80 // column_width
    shown = min(len(candidates), _MAX_COMPLETION_MENU_ROWS * columns)
    hidden = len(candidates) - shown
    assert f"{hidden} more candidates" in summary


def test_hidden_count_matches_exactly_regardless_of_terminal_width() -> None:
    candidates = tuple(f"item{i:02d}" for i in range(37))
    for width in (40, 80, 120, 200):
        menu = RawLineReader._format_completion_menu(candidates, terminal_width=width)
        lines = menu.split("\r\n")
        column_width = max(len(c) for c in candidates) + _COMPLETION_MENU_COLUMN_SPACING
        columns = max(1, width // column_width)
        max_visible = _MAX_COMPLETION_MENU_ROWS * columns
        if len(candidates) <= max_visible:
            assert not lines[-1].startswith("…"), f"unexpected summary at width={width}"
            continue
        hidden = len(candidates) - max_visible
        assert lines[-1] == f"… {hidden} more candidates — type more characters to narrow"


def test_fitting_candidate_set_shows_all_with_no_summary() -> None:
    candidates = ("alpha", "beta", "gamma")
    menu = RawLineReader._format_completion_menu(candidates, terminal_width=80)

    for candidate in candidates:
        assert candidate in menu
    assert "…" not in menu
    assert "more candidates" not in menu


def test_narrow_terminal_produces_fewer_columns_than_wide_terminal() -> None:
    candidates = tuple(f"name{i:02d}" for i in range(40))
    narrow_menu = RawLineReader._format_completion_menu(candidates, terminal_width=20)
    wide_menu = RawLineReader._format_completion_menu(candidates, terminal_width=200)

    narrow_first_row = narrow_menu.split("\r\n")[0]
    wide_first_row = wide_menu.split("\r\n")[0]
    narrow_count = len(re.findall(r"name\d\d", narrow_first_row))
    wide_count = len(re.findall(r"name\d\d", wide_first_row))

    assert narrow_count < wide_count


def test_single_very_wide_candidate_still_renders_one_per_row() -> None:
    """A candidate wider than the terminal must still render (one per row)."""
    candidates = ("x" * 120,)
    menu = RawLineReader._format_completion_menu(candidates, terminal_width=40)
    assert candidates[0] in menu
    assert "\r\n" not in menu


def test_unicode_wide_candidates_use_display_width_for_column_layout() -> None:
    """East-Asian wide characters must not overflow the terminal width."""
    # Each candidate is 6 "wide" CJK characters -> 12 display columns.
    candidates = tuple("测试候选词" + str(i) for i in range(6))
    menu = RawLineReader._format_completion_menu(candidates, terminal_width=30)
    for line in menu.split("\r\n"):
        if line.startswith("…"):
            continue
        # Each wide char counts as 2 display columns; the row must not
        # exceed the terminal width once column padding is accounted for.
        display_width = sum(2 if "一" <= ch <= "鿿" else 1 for ch in line)
        assert display_width <= 30 + _COMPLETION_MENU_COLUMN_SPACING


def test_empty_candidates_render_nothing() -> None:
    assert RawLineReader._format_completion_menu((), terminal_width=80) == ""


# ---------------------------------------------------------------- via _complete


def test_single_candidate_completes_directly_without_a_menu() -> None:
    reader = RawLineReader(output_fd=os.open(os.devnull, os.O_WRONLY))
    completer = Completer(lambda: ["echo", "exit"])
    buffer = LineBuffer("ech", 3)

    reader._complete(buffer, completer)

    assert buffer.text == "echo "
    assert reader._completion_displayed is False


def test_common_prefix_insertion_is_unchanged_by_bounding() -> None:
    """A real Completer also discovers PySH builtins, PATH executables and
    filesystem entries, so a short prefix like "ec" is not actually under
    this test's control on an arbitrary host (extra real "ec*" commands
    could shrink the common prefix below "echo"). A stub completer with a
    fixed, fully-controlled candidate set keeps this test hermetic.
    """
    reader = RawLineReader(output_fd=os.open(os.devnull, os.O_WRONLY))
    result = CompletionResult(
        token_start=0,
        token_end=2,
        prefix="ec",
        candidates=("echo", "echox", "echoy"),
    )
    completer = _StubCompleter(result)
    buffer = LineBuffer("ec", 2)

    reader._complete(buffer, completer)

    assert buffer.text == "echo"
    assert buffer.cursor == 4
    assert reader._completion_displayed is False


def test_completion_menu_rendering_does_not_mutate_buffer_or_cursor() -> None:
    reader = RawLineReader(output_fd=os.open(os.devnull, os.O_WRONLY))
    completer = Completer(lambda: [f"p{i:02d}cmd" for i in range(40)])
    buffer = LineBuffer("p", 1)

    reader._complete(buffer, completer)

    assert buffer.text == "p"
    assert buffer.cursor == 1


def test_repeated_tab_on_unchanged_result_does_not_redisplay_menu(monkeypatch) -> None:
    reader = RawLineReader(output_fd=os.open(os.devnull, os.O_WRONLY))
    completer = Completer(lambda: [f"p{i:02d}cmd" for i in range(40)])
    buffer = LineBuffer("p", 1)

    write_calls: list[str] = []
    original_write = RawLineReader._write

    def counting_write(text: str, fd: int | None) -> None:
        write_calls.append(text)
        original_write(text, fd)

    monkeypatch.setattr(RawLineReader, "_write", staticmethod(counting_write))

    reader._complete(buffer, completer)
    first_call_count = len(write_calls)
    assert first_call_count >= 1

    reader._complete(buffer, completer)
    assert len(write_calls) == first_call_count, (
        "Repeated TAB on an unchanged buffer/result must not print another menu."
    )


def test_prefix_only_completion_unaffected_by_display_bounding(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("ec", 2, builtins=("echo", "exit"), aliases=(), path="")
    assert "echo" in result.candidates
    assert "exit" not in result.candidates


def test_substring_fallback_still_absent_with_bounded_display(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("ell", 3, builtins=("shell", "echo"), aliases=(), path="")
    assert "shell" not in result.candidates
    assert result.candidates == ()
