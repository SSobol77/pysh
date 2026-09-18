# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_multiline_grammar.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Multiline grammar foundation tests for Issue #8."""
from __future__ import annotations

import subprocess
import unittest.mock as mock

from pysh.core.shell import PyShell
from pysh.parsing.multiline import (
    ContinuationKind,
    continuation_state,
    iter_logical_lines,
    join_backslash_continuations,
)
from pysh.parsing.parser import validate_unsupported_syntax


def _mock_popen() -> mock.MagicMock:
    proc = mock.MagicMock()
    proc.wait.return_value = 0
    proc.stdout = None
    return mock.MagicMock(return_value=proc)


def test_unterminated_single_quote_requests_continuation() -> None:
    state = continuation_state("echo 'hello")
    assert state.needs_more
    assert state.kind is ContinuationKind.SINGLE_QUOTE


def test_unterminated_double_quote_requests_continuation() -> None:
    state = continuation_state('echo "hello')
    assert state.needs_more
    assert state.kind is ContinuationKind.DOUBLE_QUOTE


def test_quote_continuation_completes_as_one_logical_line() -> None:
    assert list(iter_logical_lines(["echo 'hello", "world'"])) == ["echo 'hello\nworld'"]


def test_backslash_newline_joins_logical_line() -> None:
    assert join_backslash_continuations("echo hello \\\nworld") == "echo hello world"
    assert list(iter_logical_lines(["echo hello \\", "world"])) == ["echo hello world"]


def test_shell_execute_supports_backslash_newline() -> None:
    popen = _mock_popen()
    with mock.patch.object(subprocess, "Popen", popen):
        assert PyShell().execute("echo hello \\\nworld") == 0
    assert popen.call_args.args[0] == ["echo", "hello", "world"]


def test_python_block_coalescing_remains_correct() -> None:
    lines = ["py {", "x = 1", "print(x)", "}"]
    assert list(iter_logical_lines(lines)) == ["py {\nx = 1\nprint(x)\n}"]


def test_heredoc_placeholder_no_longer_rejects_issue_10_syntax() -> None:
    validate_unsupported_syntax("cat << EOF")


def test_iter_logical_lines_coalesces_heredoc_body() -> None:
    lines = ["cat << EOF", "hello", "EOF", "echo done"]
    assert list(iter_logical_lines(lines)) == ["cat << EOF\nhello\nEOF", "echo done"]
