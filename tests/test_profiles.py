# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_profiles.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Issue #31 configuration profiles."""
from __future__ import annotations

from pathlib import Path

from pysh.config.profiles import resolve_profiles
from pysh.config.schema import apply_config, merge_toml_documents
from pysh.core.shell import PyShell


def test_builtin_profile_selection_applies_prompt_options(tmp_path: Path) -> None:
    shell = PyShell()
    config = merge_toml_documents([(tmp_path / "config.toml", {"profile": {"active": "minimal"}})])
    shell.config_profiles = config.profiles
    shell.config_themes = config.themes
    apply_config(shell, config)
    assert shell.active_profile == "minimal"
    assert shell.prompt_options["prompt_layout"] == "single"


def test_invalid_profile_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = merge_toml_documents([(path, {"profile": {"active": "missing"}})])
    assert any(
        diag.reason == "unknown profile" and diag.path == path
        for diag in config.diagnostics
    )


def test_custom_profile_inheritance() -> None:
    profiles, diagnostics = resolve_profiles(
        {"focus": {"base": "minimal", "prompt": {"show_git_branch": True}}}
    )
    assert diagnostics == ()
    assert profiles["focus"]["prompt"]["prompt_layout"] == "single"
    assert profiles["focus"]["prompt"]["show_git_branch"] is True


def test_profile_cycle_detection() -> None:
    _, diagnostics = resolve_profiles({"a": {"base": "b"}, "b": {"base": "a"}})
    assert any(diag.reason == "profile inheritance cycle" for diag in diagnostics)
