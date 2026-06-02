# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_unalias.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the unalias builtin."""
from __future__ import annotations

import pytest

from pysh.core.shell import PyShell


def test_unalias_removes_existing_alias() -> None:
    shell = PyShell()
    assert "ll" in shell.aliases
    assert shell.execute("unalias ll") == 0
    assert "ll" not in shell.aliases


def test_unalias_unknown_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    status = shell.execute("unalias not_a_known_alias")
    assert status == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_unalias_no_argument_returns_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    status = shell.execute("unalias")
    assert status == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err


def test_unalias_multiple_partial_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    status = shell.execute("unalias ls missing_alias")
    assert status == 1
    assert "ls" not in shell.aliases
    captured = capsys.readouterr()
    assert "missing_alias" in captured.err
