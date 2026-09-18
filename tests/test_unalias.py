# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_unalias.py
#
# Copyright (C) 2026 Siergej Sobolewski

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
