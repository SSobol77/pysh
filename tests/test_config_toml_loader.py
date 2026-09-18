# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_config_toml_loader.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for non-executing TOML file loading."""
from __future__ import annotations

from pathlib import Path

from pysh.config.toml_loader import load_toml_file


def test_load_toml_file_success(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[prompt]\nsymbol = '$'\n", encoding="utf-8")
    loaded = load_toml_file(path)
    assert loaded.loaded is True
    assert loaded.data["prompt"]["symbol"] == "$"
    assert loaded.diagnostics == ()


def test_load_toml_file_parse_error_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[prompt\n", encoding="utf-8")
    loaded = load_toml_file(path)
    assert loaded.loaded is False
    assert loaded.data == {}
    assert "invalid TOML" in loaded.diagnostics[0].reason


def test_load_toml_file_size_guard(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("x" * 20, encoding="utf-8")
    loaded = load_toml_file(path, max_bytes=10)
    assert loaded.loaded is False
    assert "exceeds" in loaded.diagnostics[0].reason
