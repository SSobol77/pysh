# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_command_builtin.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the POSIX-compatible ``command`` builtin."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.shell import PyShell


@pytest.fixture
def shell() -> PyShell:
    return PyShell()


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_command_v_resolves_builtin_first(
    shell: PyShell,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell.aliases["pwd"] = "echo alias-pwd"

    assert shell.execute("command -v pwd") == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "pwd"


def test_command_v_resolves_alias(
    shell: PyShell,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell.aliases["mine"] = "echo alias target"

    assert shell.execute("command -v mine") == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "alias mine='echo alias target'"


def test_command_v_resolves_path_executable(
    shell: PyShell,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exe = _write_executable(tmp_path / "tool", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(tmp_path))

    assert shell.execute("command -v tool") == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == str(exe)


def test_command_v_missing_returns_one(
    shell: PyShell,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PATH", "")

    assert shell.execute("command -v definitely_missing_pysh_command") == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_command_v_verbose_builtin_alias_and_path(
    shell: PyShell,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exe = _write_executable(tmp_path / "tool", "#!/bin/sh\nexit 0\n")
    shell.aliases["mine"] = "echo alias target"
    monkeypatch.setenv("PATH", str(tmp_path))

    assert shell.execute("command -V pwd mine tool") == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "pwd is a PySH builtin",
        "mine is aliased to 'echo alias target'",
        f"tool is {exe}",
    ]


def test_command_executes_external_with_alias_suppressed(
    shell: PyShell,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _write_executable(tmp_path / "tool", "#!/bin/sh\nprintf 'external:%s\\n' \"$1\"\n")
    shell.aliases["tool"] = "echo alias"
    monkeypatch.setenv("PATH", str(tmp_path))

    assert shell.execute("command tool arg") == 0

    captured = capfd.readouterr()
    assert captured.out.strip() == "external:arg"


def test_command_executes_builtin_with_alias_suppressed(
    shell: PyShell,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell.aliases["pwd"] = "echo alias-pwd"

    assert shell.execute("command pwd") == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == os.getcwd()


def test_command_executes_missing_external_returning_127(
    shell: PyShell,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PATH", "")

    assert shell.execute("command definitely_missing_pysh_command") == 127

    captured = capfd.readouterr()
    assert "command not found" in captured.err


@pytest.mark.parametrize("line", ["command", "command -v", "command -p pwd"])
def test_command_invalid_usage_returns_two(
    shell: PyShell,
    line: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert shell.execute(line) == 2

    captured = capsys.readouterr()
    assert "command:" in captured.err
