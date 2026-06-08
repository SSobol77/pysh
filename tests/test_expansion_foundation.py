# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_expansion_foundation.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Expansion foundation tests for Issue #8."""
from __future__ import annotations

import subprocess
import unittest.mock as mock

import pytest

from pysh.core.errors import ExitCode
from pysh.core.shell import PyShell
from pysh.parsing.errors import UnsupportedSyntaxError
from pysh.parsing.parser import (
    expand_variables,
    is_unsupported_parameter_expansion,
    validate_unsupported_syntax,
)


def _mock_popen(returncode: int = 0) -> mock.MagicMock:
    proc = mock.MagicMock()
    proc.wait.return_value = returncode
    proc.stdout = None
    return mock.MagicMock(return_value=proc)


def test_variable_expansion_preserves_existing_contract() -> None:
    assert expand_variables("$VAR ${VAR} $?", {"VAR": "x"}, {}, special_vars={"?": "7"}) == "x x 7"


def test_unset_variable_expands_to_empty_string() -> None:
    assert expand_variables("prefix=$MISSING", {}, {}) == "prefix="


@pytest.mark.parametrize(
    "expr",
    [
        "NAME:-default",
        "NAME:=default",
        "NAME:?error",
        "#NAME",
        "NAME#pattern",
        "NAME%pattern",
        "NAME/old/new",
    ],
)
def test_unsupported_parameter_expansions_are_identified(expr: str) -> None:
    assert is_unsupported_parameter_expansion(expr)


def test_unsupported_parameter_expansion_remains_literal() -> None:
    text = "${NAME:-default} ${#NAME} ${NAME/old/new}"
    assert expand_variables(text, {"NAME": "value"}, {}) == text


@pytest.mark.parametrize(
    "line",
    [
        "$((1 + 2))",
        "(( 1 + 2 ))",
        "let NAME=1+2",
    ],
)
def test_arithmetic_expansion_and_commands_are_unsupported(line: str) -> None:
    with pytest.raises(UnsupportedSyntaxError, match="Issue #8"):
        validate_unsupported_syntax(line)


def test_shell_arithmetic_diagnostic_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("echo $((1 + 2))")
    captured = capsys.readouterr()
    assert status == ExitCode.BUILTIN_MISUSE
    assert "arithmetic expansion" in captured.err


def test_glob_patterns_are_passed_as_literals() -> None:
    popen = _mock_popen()
    with mock.patch.object(subprocess, "Popen", popen):
        assert PyShell().execute('echo "*.py"') == 0
    assert popen.call_args.args[0] == ["echo", "*.py"]


def test_brace_expansion_is_passed_as_literal() -> None:
    popen = _mock_popen()
    with mock.patch.object(subprocess, "Popen", popen):
        assert PyShell().execute('echo "{a,b}"') == 0
    assert popen.call_args.args[0] == ["echo", "{a,b}"]
