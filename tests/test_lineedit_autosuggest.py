from __future__ import annotations

from pysh.lineedit.autosuggest import AutoSuggester


def test_suggest_most_recent_distinct_tail() -> None:
    history = ["echo old", "git status", "echo old", "echo newer"]
    assert AutoSuggester().suggest("echo ", history) == "newer"


def test_no_suggestion_cases() -> None:
    suggester = AutoSuggester()
    assert suggester.suggest("", ["echo hi"]) is None
    assert suggester.suggest("nope", ["echo hi"]) is None
    assert suggester.suggest("echo hi", ["echo hi"]) is None
    assert suggester.suggest("echo higher", ["echo hi"]) is None

