# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_completion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for interactive completion metadata."""
from __future__ import annotations

from pysh.contracts.builtins import BUILTIN_NAMES
from pysh.core.shell import PyShell
from pysh.editor.completion import Completer


def test_completer_builtin_list_matches_shell_builtins() -> None:
    assert PyShell.BUILTINS == BUILTIN_NAMES
    assert set(Completer.BUILTINS) == BUILTIN_NAMES


def test_completion_exposes_migration_builtins() -> None:
    builtins = set(Completer.BUILTINS)
    assert "source_zsh_profile" in builtins
    assert "source_sh_aliases" in builtins
    assert "run_script" in builtins
    assert "compat_check" in builtins
    assert "zsh" in builtins
    assert "zsh_fallback" in builtins


def test_completion_exposes_system_profile_builtins() -> None:
    builtins = set(Completer.BUILTINS)
    for name in (
        "sys_info",
        "env_audit",
        "path_audit",
        "which_all",
        "apt_check",
        "apt_search",
    ):
        assert name in builtins


def test_completion_exposes_plan_builtin() -> None:
    assert "plan" in set(Completer.BUILTINS)
