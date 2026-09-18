# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_parser.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the quote-aware command parser."""
from __future__ import annotations

from pysh.parsing.parser import (
    ChainOp,
    expand_variables,
    has_unbalanced_quotes,
    parse_assignment,
    split_chain,
    split_pipeline,
)


# --------------------------------------------------------------- split_chain
def test_split_chain_single_command() -> None:
    chain = split_chain("ls -la")
    assert len(chain) == 1
    assert chain[0].command == "ls -la"
    assert chain[0].operator is None


def test_split_chain_semicolon() -> None:
    chain = split_chain("echo a; echo b")
    assert [c.command for c in chain] == ["echo a", "echo b"]
    assert chain[0].operator is ChainOp.SEMI
    assert chain[1].operator is None


def test_split_chain_and_or() -> None:
    chain = split_chain("a && b || c")
    assert [c.command for c in chain] == ["a", "b", "c"]
    assert chain[0].operator is ChainOp.AND
    assert chain[1].operator is ChainOp.OR


def test_split_chain_keeps_semicolon_inside_double_quotes() -> None:
    chain = split_chain('python3.13 -c "import sys; print(\'Python:\', sys.version)"')
    assert len(chain) == 1
    assert chain[0].command.startswith("python3.13 -c")


def test_split_chain_keeps_semicolon_inside_single_quotes() -> None:
    chain = split_chain("python3.13 -c 'import sys; print(sys.version)'")
    assert len(chain) == 1


def test_split_chain_keeps_and_or_inside_quotes() -> None:
    chain = split_chain('echo "a && b || c"')
    assert len(chain) == 1
    assert chain[0].command == 'echo "a && b || c"'


def test_split_chain_keeps_pipe_inside_quotes() -> None:
    chain = split_chain('echo "Test | pipe & semicolon; && ok"')
    assert len(chain) == 1


def test_split_chain_mixed_quotes_and_operators() -> None:
    chain = split_chain('echo "hello;world"; echo done')
    assert [c.command for c in chain] == ['echo "hello;world"', "echo done"]


def test_split_chain_python_subprocess_semicolon() -> None:
    """Regression test for: python3.13 -c "import subprocess; print('ok')"."""
    chain = split_chain('python3.13 -c "import subprocess; print(\'ok\')"')
    assert len(chain) == 1
    assert chain[0].command == 'python3.13 -c "import subprocess; print(\'ok\')"'


# ------------------------------------------------------------ split_pipeline
def test_split_pipeline_basic() -> None:
    parts = split_pipeline("ls -la | head -3")
    assert parts == ["ls -la", "head -3"]


def test_split_pipeline_no_pipe() -> None:
    parts = split_pipeline("echo hello")
    assert parts == ["echo hello"]


def test_split_pipeline_keeps_pipe_in_quotes() -> None:
    parts = split_pipeline('echo "PySH | Python"')
    assert parts == ['echo "PySH | Python"']


def test_split_pipeline_keeps_pipe_in_single_quotes() -> None:
    parts = split_pipeline("echo 'a | b'")
    assert parts == ["echo 'a | b'"]


def test_split_pipeline_three_stages() -> None:
    parts = split_pipeline("cat file | grep foo | wc -l")
    assert parts == ["cat file", "grep foo", "wc -l"]


# --------------------------------------------------------- unbalanced quotes
def test_unbalanced_quote_detection() -> None:
    assert has_unbalanced_quotes('echo "hello') is True
    assert has_unbalanced_quotes("echo 'hello") is True
    assert has_unbalanced_quotes('echo "hello"') is False
    assert has_unbalanced_quotes("echo 'hello'") is False


# ---------------------------------------------------------- variable expand
def test_expand_local_variable() -> None:
    out = expand_variables("hello $NAME", {"NAME": "world"}, {})
    assert out == "hello world"


def test_expand_braced_variable() -> None:
    out = expand_variables("X=${V}Y", {"V": "ABC"}, {})
    assert out == "X=ABCY"


def test_expand_local_takes_precedence_over_env() -> None:
    out = expand_variables("$X", {"X": "local"}, {"X": "env"})
    assert out == "local"


def test_expand_falls_back_to_env() -> None:
    out = expand_variables("$HOME", {}, {"HOME": "/tmp"})
    assert out == "/tmp"


def test_expand_unknown_variable_is_empty() -> None:
    out = expand_variables("X=$UNDEF", {}, {})
    assert out == "X="


def test_expand_suppressed_in_single_quotes() -> None:
    out = expand_variables("'$NAME'", {"NAME": "world"}, {})
    assert out == "'$NAME'"


def test_expand_active_in_double_quotes() -> None:
    out = expand_variables('"$NAME"', {"NAME": "world"}, {})
    assert out == '"world"'


# ----------------------------------------------------------- parse_assignment
def test_parse_assignment_basic() -> None:
    assert parse_assignment("FOO=bar") == ("FOO", "bar")


def test_parse_assignment_quoted_value() -> None:
    assert parse_assignment('FOO="a b"') == ("FOO", '"a b"')


def test_parse_assignment_rejects_non_assignment() -> None:
    assert parse_assignment("echo hi") is None
    assert parse_assignment("=value") is None
