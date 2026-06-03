# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for shell-style comment stripping."""
from __future__ import annotations

import pytest

from pysh.core.shell import PyShell
from pysh.parsing.parser import strip_comments


# ---------------------------------------------------------------- strip_comments
def test_strip_comment_after_command() -> None:
    assert strip_comments("ls #abc") == "ls"


def test_strip_comment_multiple_spaces() -> None:
    assert strip_comments("ls    # abc") == "ls"


def test_full_line_comment() -> None:
    assert strip_comments("# abc") == ""


def test_indented_full_line_comment() -> None:
    assert strip_comments("   # abc") == ""


def test_hash_inside_double_quotes_preserved() -> None:
    assert strip_comments('echo "#abc"') == 'echo "#abc"'


def test_hash_inside_single_quotes_preserved() -> None:
    assert strip_comments("echo '#abc'") == "echo '#abc'"


def test_escaped_hash_preserved() -> None:
    assert strip_comments(r"echo \#abc") == r"echo \#abc"


def test_hash_mid_token_preserved() -> None:
    assert strip_comments("echo foo#bar") == "echo foo#bar"


def test_comment_after_argument() -> None:
    assert strip_comments("echo foo # bar") == "echo foo"


def test_comment_after_chain_operator() -> None:
    assert strip_comments("echo a && echo b # comment") == "echo a && echo b"


def test_comment_after_pipe() -> None:
    assert strip_comments("echo a | grep a # comment") == "echo a | grep a"


def test_no_comment_returns_original() -> None:
    assert strip_comments("echo hello world") == "echo hello world"


def test_empty_string() -> None:
    assert strip_comments("") == ""


def test_only_whitespace() -> None:
    assert strip_comments("   ") == ""


def test_hash_at_start() -> None:
    assert strip_comments("#comment") == ""


# -------------------------------------------------------------- execution tests
@pytest.fixture()
def shell() -> PyShell:
    return PyShell()


def test_exec_comment_only_returns_zero(shell: PyShell) -> None:
    assert shell.execute("# full line comment") == 0


def test_exec_indented_comment_returns_zero(shell: PyShell) -> None:
    assert shell.execute("   # also a comment") == 0


def test_exec_hash_not_passed_to_external(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ls #abc must not receive '#abc' as an argument."""
    captured: list[list[str]] = []

    def fake_run_external(argv, spec, *, original_stage=None, env_overrides=None):  # type: ignore[no-untyped-def]
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(shell, "_run_external", fake_run_external)
    shell.execute("ls #abc")
    assert captured == [["ls", "--color=auto", "-F"]]  # alias expands ls


def test_exec_double_quoted_hash_preserved(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """echo "#abc" must receive #abc as the argument, not strip it."""
    captured: list[list[str]] = []

    def fake_run_external(argv, spec, *, original_stage=None, env_overrides=None):  # type: ignore[no-untyped-def]
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(shell, "_run_external", fake_run_external)
    shell.execute('echo "#abc"')
    assert captured == [["echo", "#abc"]]


def test_exec_escaped_hash_preserved(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""echo \#abc must pass literal #abc to the command."""
    captured: list[list[str]] = []

    def fake_run_external(argv, spec, *, original_stage=None, env_overrides=None):  # type: ignore[no-untyped-def]
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(shell, "_run_external", fake_run_external)
    shell.execute(r"echo \#abc")
    assert captured == [["echo", "#abc"]]


def test_exec_hash_mid_token_preserved(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """echo foo#bar must pass foo#bar as a single argument."""
    captured: list[list[str]] = []

    def fake_run_external(argv, spec, *, original_stage=None, env_overrides=None):  # type: ignore[no-untyped-def]
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(shell, "_run_external", fake_run_external)
    shell.execute("echo foo#bar")
    assert captured == [["echo", "foo#bar"]]


def test_exec_comment_after_chain(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """echo a && echo b # comment — second command runs, no #comment arg."""
    captured: list[list[str]] = []

    def fake_run_external(argv, spec, *, original_stage=None, env_overrides=None):  # type: ignore[no-untyped-def]
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(shell, "_run_external", fake_run_external)
    shell.execute("echo a && echo b # comment")
    assert captured == [["echo", "a"], ["echo", "b"]]


def test_exec_comment_after_pipeline(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """printf x | cat # comment — pipeline runs without the comment arg."""
    captured: list[list[str]] = []

    def fake_run_pipeline(stages, *, original_command=""):  # type: ignore[no-untyped-def]
        for s in stages:
            import shlex

            captured.append(shlex.split(s))
        return 0

    monkeypatch.setattr(shell, "_run_pipeline", fake_run_pipeline)
    shell.execute("printf x | cat # comment")
    assert captured == [["printf", "x"], ["cat"]]
