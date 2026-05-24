# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the redirection parser."""
from __future__ import annotations

from pysh.redirection import parse_redirections


def test_no_redirection() -> None:
    clean, spec = parse_redirections("ls -la")
    assert clean == "ls -la"
    assert spec.is_empty()


def test_stdout_redirection() -> None:
    clean, spec = parse_redirections("echo hi > out.txt")
    assert clean == "echo hi"
    assert spec.stdout_path == "out.txt"
    assert spec.stdout_append is False


def test_stdout_append() -> None:
    clean, spec = parse_redirections("echo hi >> out.txt")
    assert clean == "echo hi"
    assert spec.stdout_path == "out.txt"
    assert spec.stdout_append is True


def test_stdin_redirection() -> None:
    clean, spec = parse_redirections("cat < in.txt")
    assert clean == "cat"
    assert spec.stdin_path == "in.txt"


def test_stderr_redirection() -> None:
    clean, spec = parse_redirections("ls 2> err.log")
    assert clean == "ls"
    assert spec.stderr_path == "err.log"
    assert spec.stderr_append is False
    assert spec.stderr_to_stdout is False


def test_stderr_append() -> None:
    clean, spec = parse_redirections("ls 2>> err.log")
    assert clean == "ls"
    assert spec.stderr_path == "err.log"
    assert spec.stderr_append is True


def test_combined_redirection() -> None:
    clean, spec = parse_redirections("cmd &> all.log")
    assert clean == "cmd"
    assert spec.stdout_path == "all.log"
    assert spec.stdout_append is False
    assert spec.stderr_to_stdout is True


def test_combined_append_redirection() -> None:
    clean, spec = parse_redirections("cmd &>> all.log")
    assert clean == "cmd"
    assert spec.stdout_path == "all.log"
    assert spec.stdout_append is True
    assert spec.stderr_to_stdout is True


def test_redirection_attached_to_operator() -> None:
    clean, spec = parse_redirections("echo hi >out.txt")
    assert clean == "echo hi"
    assert spec.stdout_path == "out.txt"


def test_quoted_target_with_space() -> None:
    clean, spec = parse_redirections('echo hi > "my file.txt"')
    assert clean == "echo hi"
    assert spec.stdout_path == "my file.txt"


def test_redirection_inside_quotes_is_literal() -> None:
    clean, spec = parse_redirections('echo "hello > world"')
    assert clean == 'echo "hello > world"'
    assert spec.is_empty()


def test_pipe_with_stderr_redirection_does_not_eat_pipe() -> None:
    # ``parse_redirections`` is invoked per pipeline stage, so the caller
    # would have already split on ``|``. Still, verify that ``2>`` does not
    # bleed into the rest of the command.
    clean, spec = parse_redirections("ls -la 2>/dev/null")
    assert clean == "ls -la"
    assert spec.stderr_path == "/dev/null"


def test_multiple_redirections_last_wins_for_stdout() -> None:
    clean, spec = parse_redirections("cmd > a.txt > b.txt")
    assert clean == "cmd"
    assert spec.stdout_path == "b.txt"


def test_two_not_treated_as_stderr_when_in_word() -> None:
    # ``ab2>foo`` is not a redirection; the leading ``2`` is not at a
    # token boundary.
    clean, spec = parse_redirections("echo ab2>foo")
    assert clean == "echo ab2"
    assert spec.stdout_path == "foo"
