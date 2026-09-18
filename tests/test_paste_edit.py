# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_paste_edit.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for PYSH-0.9.0-BUG-021 (editable staged multiline paste).

These tests drive :meth:`PyShell._builtin_paste_edit` with the raw editor
disabled and ``builtins.input`` scripted, so the transactional/rollback
behavior is exercised deterministically without a real TTY. End-to-end
raw-editor interaction (initial_text pre-fill via real keystrokes) is covered
separately by the PTY smoke tests in ``test_pty_integration.py``.
"""
from __future__ import annotations

import pytest

from pysh.core.errors import ExitCode
from pysh.core.shell import PyShell
from pysh.editor.lineedit.state import EditorMode


def _disable_raw_editor(monkeypatch: pytest.MonkeyPatch, shell: PyShell) -> None:
    monkeypatch.setattr(shell, "_should_use_raw_editor", lambda: False)


def _script_input(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> None:
    """Make ``input()`` return/raise each entry in *responses* in order."""
    iterator = iter(responses)

    def fake_input(prompt: str = "") -> str:
        del prompt
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", fake_input)


def test_paste_edit_with_no_pending_paste_is_a_clean_no_op(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    status = shell._builtin_paste_edit([])

    assert status == 2
    assert shell.pending_multiline_paste is None
    assert shell.line_reader.editor_mode is EditorMode.NORMAL
    captured = capsys.readouterr()
    assert "paste_edit" in captured.out
    assert "no pending multiline paste" in captured.out


def test_paste_edit_rejects_unexpected_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE"

    status = shell._builtin_paste_edit(["unexpected"])

    assert status == 2
    assert shell.pending_multiline_paste == "echo ONE"
    captured = capsys.readouterr()
    assert "usage: paste_edit" in captured.err


def test_paste_edit_updates_staged_payload_with_edited_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    status = shell._builtin_paste_edit([])

    assert status == 0
    assert shell.pending_multiline_paste == "echo EDITED_ONE\necho EDITED_TWO"


def test_paste_edit_preserves_trailing_newline_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO\n"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    shell._builtin_paste_edit([])

    assert shell.pending_multiline_paste == "echo EDITED_ONE\necho EDITED_TWO\n"


def test_paste_edit_does_not_add_trailing_newline_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    shell._builtin_paste_edit([])

    assert not shell.pending_multiline_paste.endswith("\n")


def test_paste_edit_followed_by_paste_show_reveals_edited_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    assert shell._builtin_paste_edit([]) == 0
    capsys.readouterr()  # discard paste_edit's own summary line

    assert shell._builtin_paste_show([]) == 0
    captured = capsys.readouterr()
    assert "echo EDITED_ONE" in captured.out
    assert "echo EDITED_TWO" in captured.out
    assert "echo ONE" not in captured.out
    assert "echo TWO" not in captured.out


def test_paste_edit_executes_nothing_by_itself(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ORIGINAL_ONE\necho ORIGINAL_TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    shell._builtin_paste_edit([])

    captured = capsys.readouterr()
    assert "EDITED_ONE" not in captured.out
    assert "EDITED_TWO" not in captured.out
    assert "ORIGINAL_ONE" not in captured.out
    assert "ORIGINAL_TWO" not in captured.out
    # Still staged, not executed: pending_multiline_paste is not cleared.
    assert shell.pending_multiline_paste is not None


def test_paste_run_after_successful_edit_executes_edited_lines_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ORIGINAL_ONE\necho ORIGINAL_TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    assert shell._builtin_paste_edit([]) == 0
    capsys.readouterr()

    status = shell._builtin_paste_run([])

    assert status == 0
    captured = capsys.readouterr()
    assert captured.out.count("EDITED_ONE") == 1
    assert captured.out.count("EDITED_TWO") == 1
    assert "ORIGINAL_ONE" not in captured.out
    assert "ORIGINAL_TWO" not in captured.out
    assert shell.pending_multiline_paste is None


def test_ctrl_c_during_first_line_preserves_original_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    original = "echo ONE\necho TWO"
    shell.pending_multiline_paste = original
    shell.line_reader.enter_paste_mode(original)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, [KeyboardInterrupt()])

    status = shell._builtin_paste_edit([])

    assert status == ExitCode.SIGINT
    assert shell.pending_multiline_paste == original
    assert shell.line_reader.editor_mode is EditorMode.PASTE_STAGED


def test_ctrl_c_during_later_line_rolls_back_all_prior_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    original = "echo ONE\necho TWO\necho THREE"
    shell.pending_multiline_paste = original
    shell.line_reader.enter_paste_mode(original)
    _disable_raw_editor(monkeypatch, shell)
    # First line edited successfully, interrupt arrives on the second line.
    _script_input(monkeypatch, ["echo EDITED_ONE", KeyboardInterrupt()])

    status = shell._builtin_paste_edit([])

    assert status == ExitCode.SIGINT
    assert shell.pending_multiline_paste == original
    assert "EDITED_ONE" not in shell.pending_multiline_paste


def test_eof_during_edit_preserves_original_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    original = "echo ONE\necho TWO"
    shell.pending_multiline_paste = original
    shell.line_reader.enter_paste_mode(original)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", EOFError()])

    status = shell._builtin_paste_edit([])

    assert status == ExitCode.GENERAL_ERROR
    assert shell.pending_multiline_paste == original


def test_paste_cancel_after_successful_edit_clears_payload_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    assert shell._builtin_paste_edit([]) == 0
    assert shell._builtin_paste_cancel([]) == 0

    assert shell.pending_multiline_paste is None
    assert shell.line_reader.editor_mode is EditorMode.NORMAL


def test_editor_mode_remains_paste_staged_after_successful_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    assert shell._builtin_paste_edit([]) == 0

    assert shell.line_reader.editor_mode is EditorMode.PASTE_STAGED


def test_exit_discard_contract_unchanged_after_successful_edit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """exit/quit must discard a pending paste the same way whether or not it
    was previously edited via paste_edit — no special-cased state remains."""
    shell = PyShell()
    shell.pending_multiline_paste = "echo ONE\necho TWO"
    shell.line_reader.enter_paste_mode(shell.pending_multiline_paste)
    _disable_raw_editor(monkeypatch, shell)
    _script_input(monkeypatch, ["echo EDITED_ONE", "echo EDITED_TWO"])

    assert shell._builtin_paste_edit([]) == 0
    capsys.readouterr()

    shell._discard_pending_paste_for_exit()

    assert shell.pending_multiline_paste is None
    assert shell.line_reader.editor_mode is EditorMode.NORMAL
    captured = capsys.readouterr()
    assert "paste_cancel: pending multiline paste discarded" in captured.out


def test_pending_paste_command_classifies_paste_edit_as_paste_action() -> None:
    assert PyShell._pending_paste_command("paste_edit") == "paste"


def test_staged_paste_capture_hint_advertises_paste_edit() -> None:
    """The hint shown when a paste is first staged must mention paste_edit,
    otherwise the feature is undiscoverable exactly when it is needed."""
    shell = PyShell()
    diagnostics = shell._capture_multiline_paste("echo one\necho two")

    hint_line = diagnostics[-1]
    assert "paste_edit = edit" in hint_line
    assert hint_line.index("paste_edit = edit") < hint_line.index("paste_show = inspect")


def test_staged_paste_retained_hint_advertises_paste_edit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hint re-shown after paste_show/clear (while still staged) must
    also mention paste_edit, matching the initial-capture hint."""
    shell = PyShell()
    shell.pending_multiline_paste = "echo one\necho two"

    shell._print_pending_paste_hint()

    captured = capsys.readouterr()
    assert "paste_edit = edit" in captured.out
    assert captured.out.index("paste_edit = edit") < captured.out.index("paste_show = inspect")
