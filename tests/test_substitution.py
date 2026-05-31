# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_substitution.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for command substitution: $() and backticks."""
from __future__ import annotations

import pytest

from pysh.parser import expand_command_substitution


def _record_runner(log: list[str]):
    def runner(command: str, _timeout: float) -> str:
        log.append(command)
        return f"<{command}>"

    return runner


def test_substitution_dollar_paren() -> None:
    log: list[str] = []
    out = expand_command_substitution("echo $(date)", runner=_record_runner(log))
    assert out == "echo <date>"
    assert log == ["date"]


def test_substitution_backticks() -> None:
    log: list[str] = []
    out = expand_command_substitution("echo `uname -r`", runner=_record_runner(log))
    assert out == "echo <uname -r>"
    assert log == ["uname -r"]


def test_substitution_inside_double_quotes() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        'echo "Kernel: `uname -r`"',
        runner=_record_runner(log),
    )
    assert out == 'echo "Kernel: <uname -r>"'
    assert log == ["uname -r"]


def test_substitution_inside_double_quotes_dollar_paren() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        'echo "Date: $(date \'+%Y-%m-%d\')"',
        runner=_record_runner(log),
    )
    assert out == "echo \"Date: <date '+%Y-%m-%d'>\""
    assert log == ["date '+%Y-%m-%d'"]


def test_substitution_suppressed_in_single_quotes() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        "echo 'No substitution: $(date)'",
        runner=_record_runner(log),
    )
    assert out == "echo 'No substitution: $(date)'"
    assert log == []


def test_substitution_suppressed_in_single_quotes_backticks() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        "echo 'No: `date`'",
        runner=_record_runner(log),
    )
    assert out == "echo 'No: `date`'"
    assert log == []


def test_substitution_unmatched_paren_is_literal() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        "echo $(unterminated",
        runner=_record_runner(log),
    )
    assert out == "echo $(unterminated"
    assert log == []


def test_substitution_unmatched_backtick_is_literal() -> None:
    log: list[str] = []
    out = expand_command_substitution(
        "echo `unterminated",
        runner=_record_runner(log),
    )
    assert out == "echo `unterminated"
    assert log == []


def test_substitution_with_default_runner_runs_real_command() -> None:
    # Use a benign POSIX-portable command.
    out = expand_command_substitution("echo $(printf hello)")
    assert out == "echo hello"


def test_substitution_strips_trailing_newlines() -> None:
    out = expand_command_substitution("X=$(printf 'a\\n\\n')")
    assert out == "X=a"


def test_substitution_timeout_returns_empty(capsys: pytest.CaptureFixture[str]) -> None:
    # Use a tiny timeout to force the substitution to expire.
    out = expand_command_substitution("X=$(sleep 5)", timeout=0.1)
    assert out == "X="
    captured = capsys.readouterr()
    assert "timed out" in captured.err
