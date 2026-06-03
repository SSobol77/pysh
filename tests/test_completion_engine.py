# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Completion Engine v1 tests (Issue #12)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from pysh.editor.lineedit.completion import (
    CompletionKind,
    apply_single_completion,
    complete_line,
    parse_completion_context,
)

BUILTINS = ("cd", "echoish", "fg", "bg", "source", "pushd")


def test_context_command_position() -> None:
    context = parse_completion_context("ec", 2)
    assert context.command_position
    assert context.prefix == "ec"


def test_context_argument_position() -> None:
    context = parse_completion_context("echo RE", 7)
    assert not context.command_position
    assert context.command_name == "echo"
    assert context.prefix == "RE"


def test_context_after_redirection() -> None:
    context = parse_completion_context("cat > ou", 8)
    assert context.after_redirection
    assert context.prefix == "ou"


def test_context_quoted_token() -> None:
    context = parse_completion_context('echo "REA', 9)
    assert context.quote == '"'
    assert context.prefix == "REA"


def test_context_escaped_space() -> None:
    context = parse_completion_context(r"echo file\ na", 13)
    assert context.prefix == "file na"


def test_context_variable_plain_and_brace() -> None:
    plain = parse_completion_context("echo $HO", 8)
    brace = parse_completion_context("echo ${HO", 9)
    assert plain.variable_style == "plain"
    assert plain.variable_prefix == "HO"
    assert brace.variable_style == "brace"
    assert brace.variable_prefix == "HO"


def test_context_job_command() -> None:
    context = parse_completion_context("fg %", 4)
    assert context.command_name == "fg"
    assert context.argument_index == 1
    assert context.prefix == "%"


def test_builtin_completion_at_command_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("ec", 2, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("echoish",)
    assert result.rich_candidates[0].kind is CompletionKind.BUILTIN


def test_no_builtin_completion_in_argument_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo ec", 7, builtins=BUILTINS, aliases=(), path="")
    assert "echoish" not in result.candidates


def test_external_command_completion_dedupes_and_ignores_non_executable(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    missing = tmp_path / "missing"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        exe = directory / "tool"
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    non_exe = first / "torn"
    non_exe.write_text("", encoding="utf-8")
    result = complete_line(
        "to",
        2,
        builtins=(),
        aliases=(),
        path=os.pathsep.join([str(first), str(missing), str(second)]),
    )
    assert result.candidates == ("tool",)


def test_path_completion_files_dirs_and_hidden_policy(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / ".secret").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo ", 5, builtins=(), aliases=(), path="")
    assert "README.md" in result.candidates
    assert "src/" in result.candidates
    assert ".secret" not in result.candidates
    hidden = complete_line("echo .s", 7, builtins=(), aliases=(), path="")
    assert hidden.candidates == (".secret",)


def test_tilde_completion_preserves_tilde_prefix(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "alpha").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    result = complete_line("echo ~/a", 8, builtins=(), aliases=(), path="")
    assert result.candidates == ("~/alpha",)


def test_path_with_space_is_escaped_unquoted(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "file name.txt").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo file", 9, builtins=(), aliases=(), path="")
    assert result.candidates == (r"file\ name.txt",)
    assert apply_single_completion("echo file", result) == ("echo file\\ name.txt ", 20)


def test_quoted_path_completion_preserves_quote_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "file name.txt").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line('echo "file', 10, builtins=(), aliases=(), path="")
    assert result.candidates == ("file name.txt",)
    assert apply_single_completion('echo "file', result) == ('echo "file name.txt ', 20)


def test_directory_only_completion_after_cd(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "script.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("cd s", 4, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("src/",)


def test_variable_completion_names_only(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "do-not-show")
    result = complete_line(
        "echo $HO",
        8,
        builtins=(),
        aliases=(),
        env={"HOME": "secret"},
        locals={"HOSTNAME": "also-secret"},
        path="",
    )
    assert result.candidates == ("$HOME", "$HOSTNAME")
    assert all("secret" not in candidate for candidate in result.candidates)


def test_braced_variable_completion() -> None:
    result = complete_line(
        "echo ${HO",
        9,
        builtins=(),
        aliases=(),
        env={"HOME": "secret"},
        locals={},
        path="",
    )
    assert result.candidates == ("${HOME}",)


def test_job_completion_with_and_without_provider() -> None:
    none = complete_line("fg ", 3, builtins=BUILTINS, aliases=(), path="")
    jobs = complete_line("fg %", 4, builtins=BUILTINS, aliases=(), job_ids=(1, 12), path="")
    assert none.candidates == ()
    assert jobs.candidates == ("%1", "%12")


def test_directory_only_completion_after_pushd(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "script.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("pushd s", 7, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("src/",)
    assert "script.py" not in result.candidates


def test_no_completion_in_comment_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo hi # co", 12, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ()


def test_single_quotes_suppress_variable_completion(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    result = complete_line(
        "echo '$HO",
        9,
        builtins=(),
        aliases=(),
        env={"HOME": "do-not-complete"},
        locals={},
        path="",
    )
    assert result.candidates == ()
    assert result.context is not None
    assert result.context.variable_style is None

