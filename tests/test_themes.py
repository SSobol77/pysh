# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_themes.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Issue #31 configuration themes."""
from __future__ import annotations

from pathlib import Path

from pysh.config.schema import apply_config, merge_toml_documents
from pysh.config.themes import resolve_themes
from pysh.core.shell import PyShell


def test_builtin_theme_selection_applies_colors(tmp_path: Path) -> None:
    shell = PyShell()
    config = merge_toml_documents([(tmp_path / "config.toml", {"theme": {"active": "nord"}})])
    shell.config_themes = config.themes
    apply_config(shell, config)
    assert shell.active_theme == "nord"
    assert shell.prompt_colors["cwd"] == "aqua"


def test_invalid_theme_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = merge_toml_documents([(path, {"theme": {"active": "missing"}})])
    assert any(
        diag.reason == "unknown theme" and diag.path == path
        for diag in config.diagnostics
    )


def test_custom_theme_inheritance() -> None:
    themes, diagnostics = resolve_themes(
        {"mine": {"base": "default", "colors": {"prompt": {"cwd": "lime"}}}}
    )
    assert diagnostics == ()
    assert themes["mine"]["colors"]["prompt"]["git"] == "green"
    assert themes["mine"]["colors"]["prompt"]["cwd"] == "lime"


def test_theme_cycle_detection() -> None:
    _, diagnostics = resolve_themes({"a": {"base": "b"}, "b": {"base": "a"}})
    assert any(diag.reason == "theme inheritance cycle" for diag in diagnostics)


def test_theme_color_validation(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [(tmp_path / "config.toml", {"themes": {"mine": {"colors": {"prompt": {"cwd": "bad;"}}}}})]
    )
    assert any("invalid color" in diag.reason for diag in config.diagnostics)
