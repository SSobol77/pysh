# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_zsh_transition.py
#
# Copyright (C) 2026 Siergej Sobolewski

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


def test_zsh_parameter_expansion_reports_actionable_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("${(f)PATH}") == 2

    captured = capsys.readouterr()
    assert "pysh: unsupported zsh syntax: ${( ... )}" in captured.err
    assert "PySH does not evaluate zsh parameter expansion" in captured.err


def test_zsh_glob_qualifier_reports_actionable_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("ls *(.)") == 2

    captured = capsys.readouterr()
    assert "pysh: unsupported zsh syntax: glob qualifier" in captured.err
    assert "not zsh glob qualifiers" in captured.err


def test_zsh_array_assignment_reports_actionable_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("array=(one two)") == 2

    captured = capsys.readouterr()
    assert "pysh: unsupported zsh syntax: array" in captured.err
    assert "PySH does not evaluate zsh arrays" in captured.err


def test_compinit_reports_actionable_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("compinit") == 2

    captured = capsys.readouterr()
    assert "pysh: unsupported zsh config command: compinit" in captured.err
    assert "Use PySH-native completion" in captured.err


@pytest.mark.parametrize("command", ["setopt autocd", "unsetopt autocd"])
def test_zsh_option_commands_report_actionable_diagnostic(
    command: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute(command) == 2

    captured = capsys.readouterr()
    assert f"pysh: unsupported zsh config command: {command.split()[0]}" in captured.err
    assert "Use PySH-native configuration in ~/.pyshrc" in captured.err


@pytest.mark.parametrize(
    "filename",
    [".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout"],
)
def test_source_zsh_startup_file_is_rejected_without_execution(
    filename: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / f"executed-{filename[1:]}"
    zsh_startup = tmp_path / filename
    zsh_startup.write_text(f"touch {marker}\n", encoding="utf-8")

    assert PyShell().execute(f"source {zsh_startup}") == 2

    captured = capsys.readouterr()
    assert "pysh: unsupported zsh configuration file:" in captured.err
    assert "PySH does not source zsh startup files" in captured.err
    assert not marker.exists()


def test_alias_and_export_remain_stable_after_zsh_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYSH_ZSH_HARDENING_EXPORT", raising=False)
    shell = PyShell()

    assert shell.execute("alias zz='echo zsh-hardening'") == 0
    assert shell.execute("export PYSH_ZSH_HARDENING_EXPORT=ok") == 0

    assert shell.aliases["zz"] == "echo zsh-hardening"
    assert shell.local_vars["PYSH_ZSH_HARDENING_EXPORT"] == "ok"


def test_command_not_found_diagnostic_remains_stable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("__pysh_missing_after_zsh_hardening__") == 127

    captured = capsys.readouterr()
    assert "pysh: __pysh_missing_after_zsh_hardening__: command not found" in captured.err
