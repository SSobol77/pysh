# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugins.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the plugin loader."""
from __future__ import annotations

from pathlib import Path

from pysh.config.plugins import discover_plugins, load_plugins


def test_discover_plugins_returns_lexicographic_order(tmp_path: Path) -> None:
    (tmp_path / "20-z.pysh").write_text("# z", encoding="utf-8")
    (tmp_path / "10-a.pysh").write_text("# a", encoding="utf-8")
    (tmp_path / "30-m.pysh").write_text("# m", encoding="utf-8")
    plugins = discover_plugins(tmp_path)
    assert [p.name for p in plugins] == ["10-a.pysh", "20-z.pysh", "30-m.pysh"]


def test_discover_plugins_ignores_wrong_suffix(tmp_path: Path) -> None:
    (tmp_path / "01-keep.pysh").write_text("# ok", encoding="utf-8")
    (tmp_path / "02-skip.sh").write_text("# skip", encoding="utf-8")
    (tmp_path / "03-no-ext").write_text("# skip", encoding="utf-8")
    plugins = discover_plugins(tmp_path)
    assert [p.name for p in plugins] == ["01-keep.pysh"]


def test_discover_plugins_ignores_directories(tmp_path: Path) -> None:
    (tmp_path / "01-file.pysh").write_text("ok", encoding="utf-8")
    (tmp_path / "02-dir.pysh").mkdir()
    plugins = discover_plugins(tmp_path)
    assert [p.name for p in plugins] == ["01-file.pysh"]


def test_discover_plugins_missing_directory(tmp_path: Path) -> None:
    assert discover_plugins(tmp_path / "absent") == []


def test_load_plugins_executes_in_order(tmp_path: Path) -> None:
    (tmp_path / "10-first.pysh").write_text("first\n", encoding="utf-8")
    (tmp_path / "20-second.pysh").write_text("second\n", encoding="utf-8")
    executed: list[str] = []

    def executor(line: str) -> int:
        executed.append(line)
        return 0

    attempted = load_plugins(executor, directory=tmp_path)
    assert [p.name for p in attempted] == ["10-first.pysh", "20-second.pysh"]
    assert executed == ["first", "second"]


def test_load_plugins_continues_after_failure(tmp_path: Path) -> None:
    (tmp_path / "10-broken.pysh").write_text("BAD\n", encoding="utf-8")
    (tmp_path / "20-good.pysh").write_text("good\n", encoding="utf-8")
    executed: list[str] = []
    errors: list[str] = []

    def executor(line: str) -> int:
        executed.append(line)
        if line == "BAD":
            raise RuntimeError("simulated plugin failure")
        return 0

    load_plugins(executor, directory=tmp_path, reporter=errors.append)
    assert "good" in executed
    # The good plugin was still executed even though the bad one raised.


def test_load_plugins_no_directory(tmp_path: Path) -> None:
    executed: list[str] = []
    load_plugins(
        lambda line: executed.append(line) or 0,
        directory=tmp_path / "missing",
    )
    assert executed == []
