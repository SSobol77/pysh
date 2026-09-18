# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_lineedit_autosuggest.py
#
# Copyright (C) 2026 Siergej Sobolewski

from __future__ import annotations

from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.completion import complete_line


def test_suggest_most_recent_distinct_tail() -> None:
    history = ["echo old", "git status", "echo old", "echo newer"]
    assert AutoSuggester().suggest("echo ", history) == "newer"


def test_no_suggestion_cases() -> None:
    suggester = AutoSuggester()
    assert suggester.suggest("", ["echo hi"]) is None
    assert suggester.suggest("nope", ["echo hi"]) is None
    assert suggester.suggest("echo hi", ["echo hi"]) is None
    assert suggester.suggest("echo higher", ["echo hi"]) is None


def _complete(line: str, cursor: int, *, builtins: tuple[str, ...]):
    return complete_line(
        line,
        cursor,
        builtins=builtins,
        aliases=(),
        path="",
    )


def test_completion_fallback_suggests_unique_prefix() -> None:
    suggester = AutoSuggester(lambda line, cursor: _complete(line, cursor, builtins=("echo",)))
    assert suggester.suggest("ec", []) == "ho"


def test_history_has_priority_over_completion_fallback() -> None:
    suggester = AutoSuggester(lambda line, cursor: _complete(line, cursor, builtins=("git",)))
    assert suggester.suggest("git sta", ["git status"]) == "tus"


def test_ambiguous_completion_fallback_is_safe() -> None:
    commands = ("py", "python", "python3", "pysh")
    suggester = AutoSuggester(lambda line, cursor: _complete(line, cursor, builtins=commands))
    assert suggester.suggest("py", []) is None


def test_completion_fallback_uses_only_common_prefix() -> None:
    commands = ("source", "source_zsh")
    suggester = AutoSuggester(lambda line, cursor: _complete(line, cursor, builtins=commands))
    assert suggester.suggest("so", []) == "urce"
