# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Python-native ``py`` runtime bridge."""
from __future__ import annotations

import pytest

from pysh.shell import PyShell


def test_py_builtin_executes_code(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()
    assert shell.execute('py print("hello from python")') == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello from python"


def test_py_builtin_preserves_variable_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py x = 10") == 0
    assert shell.execute("py print(x)") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "10"


def test_py_builtin_preserves_import_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py import pathlib") == 0
    assert shell.execute('py print(pathlib.Path(".").exists())') == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "True"


def test_py_builtin_allows_semicolon_python_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py import sys; print(sys.version_info.major)") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "3"


def test_py_builtin_exception_returns_nonzero_without_killing_shell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py 1 / 0") == 1
    assert shell.execute('py print("still alive")') == 0
    captured = capsys.readouterr()
    assert "ZeroDivisionError" in captured.err
    assert "still alive" in captured.out
