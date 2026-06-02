# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_lineedit_autosuggest.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

from pysh.editor.lineedit.autosuggest import AutoSuggester


def test_suggest_most_recent_distinct_tail() -> None:
    history = ["echo old", "git status", "echo old", "echo newer"]
    assert AutoSuggester().suggest("echo ", history) == "newer"


def test_no_suggestion_cases() -> None:
    suggester = AutoSuggester()
    assert suggester.suggest("", ["echo hi"]) is None
    assert suggester.suggest("nope", ["echo hi"]) is None
    assert suggester.suggest("echo hi", ["echo hi"]) is None
    assert suggester.suggest("echo higher", ["echo hi"]) is None

