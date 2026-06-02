# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_zsh_transition.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for PySH zsh transition builtins."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.compat.zsh_bridge import ZSH_MISSING_STATUS, ZshResult
from pysh.core.shell import PyShell


class _FakeZshBridge:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def execute(self, command: str) -> ZshResult:
        self.commands.append(command)
        return ZshResult(
            command=command,
            returncode=0,
            stdout="fallback-ok\n",
            stderr="",
            timed_out=False,
        )


class _MissingZshBridge:
    def execute(self, command: str) -> ZshResult:
        return ZshResult(
            command=command,
            returncode=ZSH_MISSING_STATUS,
            stdout="",
            stderr="pysh: zsh: command not found\n",
            timed_out=False,
        )


def test_source_zsh_imports_simple_aliases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias_file = tmp_path / "aliases.zsh"
    alias_file.write_text(
        "alias ll='ls -lah'\n"
        'alias gs="git status -sb"\n'
        "alias update='sudo apt update && sudo apt upgrade'\n",
        encoding="utf-8",
    )
    shell = PyShell()
    assert shell.execute(f"source_zsh {alias_file}") == 0
    assert shell.aliases["ll"] == "ls -lah"
    assert shell.aliases["gs"] == "git status -sb"
    assert shell.aliases["update"] == "sudo apt update && sudo apt upgrade"
    captured = capsys.readouterr()
    assert f"imported=3 skipped=0 file={alias_file}" in captured.out


def test_source_zsh_ignores_comments_and_blank_lines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias_file = tmp_path / "aliases.zsh"
    alias_file.write_text(
        "\n"
        "# personal aliases\n"
        "alias gs='git status -sb'\n"
        "   # indented comment\n",
        encoding="utf-8",
    )
    shell = PyShell()
    assert shell.execute(f"source_zsh {alias_file}") == 0
    assert shell.aliases["gs"] == "git status -sb"
    captured = capsys.readouterr()
    assert "imported=1 skipped=0" in captured.out


def test_source_zsh_skips_unsupported_constructs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias_file = tmp_path / "aliases.zsh"
    alias_file.write_text(
        "function old_tool() { print hi }\n"
        "alias -g G='| grep'\n"
        "alias ok='echo ok'\n",
        encoding="utf-8",
    )
    shell = PyShell()
    assert shell.execute(f"source_zsh {alias_file}") == 0
    assert shell.aliases["ok"] == "echo ok"
    captured = capsys.readouterr()
    assert "imported=1 skipped=2" in captured.out


def test_source_zsh_reports_malformed_alias_lines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias_file = tmp_path / "aliases.zsh"
    alias_file.write_text("alias broken\n", encoding="utf-8")
    shell = PyShell()
    assert shell.execute(f"source_zsh {alias_file}") == 0
    captured = capsys.readouterr()
    assert "imported=0 skipped=1" in captured.out
    assert f"source_zsh: {alias_file}:1: malformed alias" in captured.err


def test_source_zsh_missing_file_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.zsh"
    shell = PyShell()
    assert shell.execute(f"source_zsh {missing}") == 1
    captured = capsys.readouterr()
    assert "file not found" in captured.err


def test_zsh_builtin_returns_127_when_zsh_unavailable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell(zsh_bridge=_MissingZshBridge())  # type: ignore[arg-type]
    assert shell.execute("zsh 'echo no-zsh'") == 127
    captured = capsys.readouterr()
    assert "pysh: zsh: command not found" in captured.err


def test_zsh_fallback_is_off_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeZshBridge()
    shell = PyShell(zsh_bridge=fake)  # type: ignore[arg-type]
    assert shell.execute("definitely_no_pysh_command_xyz") == 127
    assert fake.commands == []
    captured = capsys.readouterr()
    assert "command not found" in captured.err


def test_zsh_fallback_delegates_missing_external_when_enabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeZshBridge()
    shell = PyShell(zsh_bridge=fake)  # type: ignore[arg-type]
    assert shell.execute("zsh_fallback on") == 0
    assert shell.execute("zsh_native_only_command") == 0
    assert fake.commands == ["zsh_native_only_command"]
    captured = capsys.readouterr()
    assert "fallback-ok" in captured.out


def test_zsh_fallback_does_not_delegate_pysh_builtins(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeZshBridge()
    shell = PyShell(zsh_bridge=fake)  # type: ignore[arg-type]
    assert shell.execute("zsh_fallback on") == 0
    assert shell.execute(f"cd {tmp_path / 'missing'}") == 1
    assert fake.commands == []
    captured = capsys.readouterr()
    assert "No such file or directory" in captured.err
