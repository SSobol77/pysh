# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_alias_packs.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Issue #31 alias packs."""
from __future__ import annotations

from pathlib import Path

from pysh.config.schema import apply_config, merge_toml_documents
from pysh.core.shell import PyShell


def test_alias_pack_loading_is_additive(tmp_path: Path) -> None:
    shell = PyShell()
    config = merge_toml_documents(
        [(tmp_path / "config.toml", {"alias_packs": {"enabled": ["git", "python"]}})]
    )
    apply_config(shell, config)
    assert shell.aliases["gs"] == "git status --short"
    assert shell.aliases["pyv"] == "python --version"


def test_invalid_alias_pack_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = merge_toml_documents([(path, {"alias_packs": {"enabled": ["missing"]}})])
    assert any(
        diag.reason == "unknown alias pack" and diag.path == path
        for diag in config.diagnostics
    )


def test_alias_override_diagnostic(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [
            (tmp_path / "config.toml", {"aliases": {"gs": "git status"}}),
            (tmp_path / "conf.d" / "10.toml", {"aliases": {"gs": "git status --short"}}),
        ]
    )
    assert any(diag.severity == "warning" and "overrides" in diag.reason for diag in config.diagnostics)
