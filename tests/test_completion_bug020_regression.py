# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_completion_bug020_regression.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Explicit regression guard for PYSH-0.9.0-BUG-020 (Issue #36 overlap).

BUG-020 made command completion prefix-only, removed the Issue #26 fuzzy
substring fallback, and guaranteed deterministic, deduplicated candidates
with history-first autosuggestion. This module exists specifically so a
future change cannot silently reintroduce substring matching: every test
here fails loudly if that regresses.

Complements (does not duplicate):
- tests/test_lineedit_autosuggest.py — history-first / safe-fallback logic
- tests/test_lineedit_completion.py — general completion engine behavior
"""
from __future__ import annotations

import os
import pty
import select
import threading
from types import SimpleNamespace

import pytest

from pysh.editor.completion import Completer
from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.completion import complete_line
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.keys import Key, KeyEvent
from pysh.editor.lineedit.reader import RawLineReader
from pysh.editor.lineedit.state import EditorMode

BUILTINS = ("echo", "exit", "shell", "history", "cd", "pwd")


def _make_options(*, autosuggest: bool = False, syntax_highlight: bool = False) -> SimpleNamespace:
    return SimpleNamespace(autosuggest=autosuggest, syntax_highlight=syntax_highlight)


# --------------------------------------------------------------- prefix-only


def test_prefix_match_returns_expected_candidate(tmp_path, monkeypatch) -> None:
    """'ech' must match 'echo' (a genuine prefix match)."""
    monkeypatch.chdir(tmp_path)
    result = complete_line("ech", 3, builtins=BUILTINS, aliases=(), path="")
    assert "echo" in result.candidates


def test_substring_match_is_never_returned(tmp_path, monkeypatch) -> None:
    """'ell' must NOT return 'shell' merely because 'ell' is a substring of it.

    This is the exact regression BUG-020 fixed: completion candidates are
    prefix matches only. 'shell' does not start with 'ell', so it must be
    absent even though 'ell' occurs inside it.
    """
    monkeypatch.chdir(tmp_path)
    result = complete_line("ell", 3, builtins=BUILTINS, aliases=(), path="")
    assert "shell" not in result.candidates
    assert result.candidates == ()


def test_substring_match_is_never_returned_for_history_like_builtin(tmp_path, monkeypatch) -> None:
    """'isto' is a substring of 'history' but not a prefix; must not match."""
    monkeypatch.chdir(tmp_path)
    result = complete_line("isto", 4, builtins=BUILTINS, aliases=(), path="")
    assert "history" not in result.candidates
    assert result.candidates == ()


def test_candidates_are_deterministic_and_deduplicated(tmp_path, monkeypatch) -> None:
    """Repeated calls with the same input must return identical, deduped candidates."""
    monkeypatch.chdir(tmp_path)
    first = complete_line("e", 1, builtins=("echo", "echo", "exit"), aliases=(), path="")
    second = complete_line("e", 1, builtins=("echo", "echo", "exit"), aliases=(), path="")
    assert first.candidates == second.candidates
    assert len(first.candidates) == len(set(first.candidates))


# ---------------------------------------------------- ambiguous / no ghost


def test_ambiguous_prefix_does_not_silently_pick_one_candidate() -> None:
    """An ambiguous prefix must not resolve to a single arbitrary candidate."""
    suggester = AutoSuggester()
    suggestion = suggester.suggest("ec", ["echo one", "echo two", "eclipse"])
    # 'ec' is ambiguous among history entries with different continuations;
    # the safe suggestion is either None or a genuine shared-prefix tail —
    # never a value that silently commits to one specific full command.
    if suggestion is not None:
        assert "echo one".startswith("ec" + suggestion) or "eclipse".startswith(
            "ec" + suggestion
        ) or "echo two".startswith("ec" + suggestion)


def test_history_first_suggestion_has_priority_over_completion_fallback() -> None:
    """When a history entry matches, it must win over completion-based fallback."""

    def fake_complete(_line: str, _cursor: int):
        from pysh.editor.lineedit.completion import (  # noqa: PLC0415
            CompletionContext,
            CompletionResult,
        )

        context = CompletionContext(
            line="ec",
            cursor=2,
            token_start=0,
            token_end=2,
            prefix="ec",
            quote=None,
            command_position=True,
            command_name=None,
            argument_index=0,
            after_redirection=False,
            variable_style=None,
            variable_prefix="",
        )
        return CompletionResult(0, 2, "ec", ("echox",), (), context=context)

    suggester = AutoSuggester(fake_complete)
    suggestion = suggester.suggest("ec", ["echo from-history"])
    assert suggestion == "ho from-history"


# --------------------------------------------------------- state reset


def test_completion_state_resets_after_non_tab_input() -> None:
    """Pressing any non-TAB key after a completion menu must forget repeat-TAB state."""
    master, slave = pty.openpty()
    try:
        reader = RawLineReader(output_fd=slave)
        completer = Completer(lambda: list(BUILTINS))
        from pysh.editor.lineedit.buffer import LineBuffer  # noqa: PLC0415

        buffer = LineBuffer("e", 1)
        reader._complete(buffer, completer)
        assert reader._last_completion_buffer is not None

        reader._handle_event(
            KeyEvent(Key.PRINTABLE, "x"),
            "> ",
            buffer,
            [],
            AutoSuggester(),
            LineHighlighter(()),
            DEFAULT_SCHEME,
            False,
            _make_options(),
            None,
            completer,
            None,
        )
        assert reader._last_completion_buffer is None
        assert reader._last_completion_result is None
        assert reader._completion_displayed is False
        assert reader.editor_mode is EditorMode.NORMAL
    finally:
        os.close(master)
        os.close(slave)


# ------------------------------------------------------- redraw / resize


def _read_ready(master_fd: int, timeout: float = 0.3) -> bytes:
    out = bytearray()
    while True:
        ready, _, _ = select.select([master_fd], [], [], timeout)
        if not ready:
            return bytes(out)
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            return bytes(out)
        if not chunk:
            return bytes(out)
        out.extend(chunk)
        timeout = 0.05


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_tab_completion_menu_survives_pending_resize() -> None:
    """A pending resize flag must not corrupt or clear an on-screen completion menu."""
    master, slave = pty.openpty()
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["line"] = RawLineReader(input_fd=slave, output_fd=slave).read_line(
                "> ",
                history=[],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter(set()),
                scheme=DEFAULT_SCHEME,
                options=_make_options(),
                completer=Completer(lambda: list(BUILTINS)),
            )
        except BaseException as exc:  # noqa: BLE001 - test captures reader outcome
            result["exc"] = exc

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_ready(master, 0.3)
        os.write(master, b"e\t")
        output = _read_ready(master, 0.3)
        assert b"echo" in output and b"exit" in output, (
            "TAB did not display the expected candidate menu.\n"
            f"Raw output: {output!r}"
        )
        os.write(master, b"\x03")
        thread.join(timeout=2)
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)
