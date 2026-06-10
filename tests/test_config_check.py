# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_config_check.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Issue #31 config diagnostic builtins."""
from __future__ import annotations

from pathlib import Path

from pysh.core.shell import PyShell


def test_config_check_validate_reports_valid(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    shell = PyShell()
    assert shell._dispatch_builtin(["config_check", "--validate"]) == 0
    out = capsys.readouterr().out
    assert "pysh: config: valid" in out


def test_config_profile_list(capsys) -> None:
    shell = PyShell()
    assert shell._dispatch_builtin(["config_profile", "list"]) == 0
    assert "default" in capsys.readouterr().out


def test_config_theme_preview(capsys) -> None:
    shell = PyShell()
    assert shell._dispatch_builtin(["config_theme", "preview", "default"]) == 0
    assert "theme: default" in capsys.readouterr().out


def test_config_alias_pack_show(capsys) -> None:
    shell = PyShell()
    assert shell._dispatch_builtin(["config_alias_pack", "show", "git"]) == 0
    assert "gs='git status --short'" in capsys.readouterr().out


def test_config_check_diff_default_outputs_no_changes(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    shell = PyShell()
    assert shell._dispatch_builtin(["config_check", "--diff"]) == 0
    assert capsys.readouterr().out == ""


def test_config_check_diff_prints_changed_option(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    shell = PyShell()
    shell.set_prompt_option("symbol", "$")
    assert shell._dispatch_builtin(["config_check", "--diff"]) == 0
    out = capsys.readouterr().out
    assert "prompt.symbol='$'" in out
    assert "prompt.prompt_layout" not in out


def test_config_check_diff_redacts_secret_like_alias(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    shell = PyShell()
    shell.register_alias("API_TOKEN", "super-secret-value")
    assert shell._dispatch_builtin(["config_check", "--diff"]) == 0
    out = capsys.readouterr().out
    assert "aliases.API_TOKEN=<redacted>" in out
    assert "super-secret-value" not in out


def test_config_reset_runtime_state() -> None:
    shell = PyShell()
    shell.set_prompt_option("symbol", "$")
    assert shell._dispatch_builtin(["config_reset", "prompt"]) == 0
    assert shell.prompt_options["symbol"] == ">"


def test_config_reset_all_resets_profile_theme_and_color_modes() -> None:
    shell = PyShell()
    shell.active_profile = "developer"
    shell.active_theme = "nord"
    shell.prompt_color_modes["vga"] = False
    shell.set_prompt_option("symbol", "$")
    assert shell._dispatch_builtin(["config_reset", "all"]) == 0
    assert shell.active_profile == "default"
    assert shell.active_theme == "default"
    assert shell.prompt_color_modes["vga"] is True
    assert shell.prompt_options["symbol"] == ">"
