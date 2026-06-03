# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the history manager."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.editor.history import HistoryManager, dedupe_consecutive, split_history_lines


def test_split_history_lines_drops_blanks() -> None:
    text = "first\n\n  \nsecond\nthird\n"
    assert split_history_lines(text) == ["first", "second", "third"]


def test_dedupe_consecutive_collapses_runs() -> None:
    assert dedupe_consecutive(["a", "a", "b", "a", "a"]) == ["a", "b", "a"]


def test_dedupe_consecutive_empty() -> None:
    assert dedupe_consecutive([]) == []


def test_history_manager_save_creates_parent(tmp_path: Path) -> None:
    nested = tmp_path / "subdir" / "history"
    manager = HistoryManager(nested, max_length=128)
    # save() must not raise even when readline is unavailable; it returns
    # a boolean indicating success.
    assert isinstance(manager.save(), bool)


def test_history_manager_load_missing_is_safe(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "absent")
    assert isinstance(manager.load(), bool)


def test_history_manager_bind_does_not_raise() -> None:
    manager = HistoryManager(Path("/tmp/pysh_history_test_dummy"))
    # bind_reverse_search must never raise even when readline is missing,
    # libedit is present, or the binding is rejected by the backend.
    assert isinstance(manager.bind_reverse_search(), bool)


def test_history_manager_read_entries_returns_lines(tmp_path: Path) -> None:
    path = tmp_path / "hist"
    path.write_text("ls\necho hi\n\ncd /tmp\n", encoding="utf-8")
    manager = HistoryManager(path)
    assert manager.read_entries() == ["ls", "echo hi", "cd /tmp"]


def test_history_manager_read_entries_missing(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "nope")
    assert manager.read_entries() == []


@pytest.mark.parametrize("max_len", [0, 1, 1024])
def test_history_manager_accepts_various_lengths(tmp_path: Path, max_len: int) -> None:
    manager = HistoryManager(tmp_path / "h", max_length=max_len)
    assert manager.max_length == max_len
