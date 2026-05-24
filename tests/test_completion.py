# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for interactive completion metadata."""
from __future__ import annotations

from pysh.completion import Completer
from pysh.shell import PyShell


def test_completer_builtin_list_matches_shell_builtins() -> None:
    assert set(PyShell.BUILTINS).issubset(set(Completer.BUILTINS))
