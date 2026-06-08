# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_profile_importer.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for static profile import and compatibility reporting."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.compat.profile_importer import CompatAction, analyze_compatibility
from pysh.core.shell import PyShell


def test_source_zsh_profile_imports_simple_aliases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = tmp_path / "zshrc"
    profile.write_text(
        "alias ll='ls -lah'\n"
        'alias gs="git status -sb"\n',
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {profile}") == 0
    assert shell.aliases["ll"] == "ls -lah"
    assert shell.aliases["gs"] == "git status -sb"
    captured = capsys.readouterr()
    assert f"aliases=2 exports=0 vars=0 skipped=0 file={profile}" in captured.out


def test_source_zsh_profile_imports_exports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYSH_TEST_EDITOR", raising=False)
    monkeypatch.delenv("PYSH_TEST_PAGER", raising=False)
    profile = tmp_path / "zshrc"
    profile.write_text(
        "export PYSH_TEST_EDITOR=nano\n"
        'export PYSH_TEST_PAGER="less"\n',
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {profile}") == 0
    assert os.environ["PYSH_TEST_EDITOR"] == "nano"
    assert os.environ["PYSH_TEST_PAGER"] == "less"
    assert shell.local_vars["PYSH_TEST_EDITOR"] == "nano"


def test_source_zsh_profile_imports_local_assignments(tmp_path: Path) -> None:
    profile = tmp_path / "zshrc"
    profile.write_text(
        "PYSH_MODE=transition\n"
        "PYSH_GREETING='hello world'\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {profile}") == 0
    assert shell.local_vars["PYSH_MODE"] == "transition"
    assert shell.local_vars["PYSH_GREETING"] == "hello world"


def test_source_zsh_profile_skips_comments_blank_and_unsupported(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = tmp_path / "zshrc"
    profile.write_text(
        "\n"
        "# comment\n"
        "autoload -Uz compinit\n"
        "compinit\n"
        'eval "$(starship init zsh)"\n'
        "function foo() { echo hi; }\n"
        "plugins=(git docker)\n"
        'source "$HOME/.oh-my-zsh/oh-my-zsh.sh"\n'
        "alias ok='echo ok'\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {profile}") == 0
    assert shell.aliases["ok"] == "echo ok"
    captured = capsys.readouterr()
    assert "aliases=1 exports=0 vars=0 skipped=6" in captured.out


def test_source_zsh_profile_missing_file_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.zsh"
    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {missing}") == 1
    captured = capsys.readouterr()
    assert "file not found" in captured.err


def test_source_zsh_profile_does_not_execute_command_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "executed"
    monkeypatch.delenv("PYSH_STATIC_IMPORT_TEST", raising=False)
    profile = tmp_path / "zshrc"
    profile.write_text(
        f'export PYSH_STATIC_IMPORT_TEST="$(touch {marker})"\n',
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_zsh_profile {profile}") == 0
    assert not marker.exists()
    assert "PYSH_STATIC_IMPORT_TEST" not in os.environ
    captured = capsys.readouterr()
    assert "aliases=0 exports=0 vars=0 skipped=1" in captured.out


def test_source_sh_aliases_imports_bash_aliases_exports_and_assignments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYSH_SH_EXPORT", raising=False)
    aliases = tmp_path / ".bash_aliases"
    aliases.write_text(
        "alias la='ls -A'\n"
        "export PYSH_SH_EXPORT=yes\n"
        "PYSH_SH_LOCAL='local value'\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_sh_aliases {aliases}") == 0
    assert shell.aliases["la"] == "ls -A"
    assert os.environ["PYSH_SH_EXPORT"] == "yes"
    assert shell.local_vars["PYSH_SH_LOCAL"] == "local value"


def test_source_sh_aliases_skips_unsupported_constructs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    aliases = tmp_path / ".profile"
    aliases.write_text(
        "if [ -f ~/.bashrc ]; then\n"
        "source ~/.bashrc\n"
        "fi\n"
        "alias ok='echo ok'\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"source_sh_aliases {aliases}") == 0
    assert shell.aliases["ok"] == "echo ok"
    captured = capsys.readouterr()
    assert "aliases=1 exports=0 vars=0 skipped=3" in captured.out


def test_compat_check_reports_supported_lines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = tmp_path / "profile"
    profile.write_text(
        "alias ll='ls -lah'\n"
        "export EDITOR=nano\n"
        "PYSH_MODE=transition\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"compat_check {profile}") == 0
    captured = capsys.readouterr()
    assert "supported=3 delegated=0 skipped=0 risky=0" in captured.out
    assert "line=1 kind=alias action=supported" in captured.out
    assert "line=2 kind=export action=supported" in captured.out
    assert "line=3 kind=assignment action=supported" in captured.out


def test_compat_check_detects_risky_eval_and_returns_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = tmp_path / "profile"
    profile.write_text('eval "$(starship init zsh)"\n', encoding="utf-8")

    shell = PyShell()
    assert shell.execute(f"compat_check {profile}") == 2
    captured = capsys.readouterr()
    assert "supported=0 delegated=0 skipped=0 risky=1" in captured.out
    assert "line=1 kind=eval action=risky" in captured.out


def test_compatibility_detects_common_risky_and_delegated_patterns() -> None:
    report = analyze_compatibility(
        "echo $(date)\n"
        "function foo() { echo hi; }\n"
        "source ~/.profile\n"
        "plugins=(git docker)\n"
        "if [ -f x ]; then\n"
        "printf hi | wc -c\n"
        "echo hi > out\n"
    )

    findings = {(finding.kind, finding.action) for finding in report.findings}
    assert ("command_substitution", CompatAction.RISKY) in findings
    assert ("function", CompatAction.RISKY) in findings
    assert ("source", CompatAction.RISKY) in findings
    assert ("zsh_plugins", CompatAction.SKIPPED) in findings
    assert ("conditional", CompatAction.DELEGATED) in findings
    assert ("pipeline", CompatAction.DELEGATED) in findings
    assert ("redirect", CompatAction.DELEGATED) in findings
