# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_completion.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for interactive completion metadata."""
from __future__ import annotations

from pysh.completion import Completer
from pysh.shell import PyShell


def test_completer_builtin_list_matches_shell_builtins() -> None:
    assert set(PyShell.BUILTINS).issubset(set(Completer.BUILTINS))


def test_completion_exposes_migration_builtins() -> None:
    builtins = set(Completer.BUILTINS)
    assert "source_zsh_profile" in builtins
    assert "source_sh_aliases" in builtins
    assert "run_script" in builtins
    assert "compat_check" in builtins


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
