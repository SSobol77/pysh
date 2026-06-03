# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Parser grammar foundation tests for Issue #8."""
from __future__ import annotations

import pytest

from pysh.core.errors import ExitCode
from pysh.core.shell import PyShell
from pysh.parsing.errors import ParseError
from pysh.parsing.parser import ChainOp, split_chain, split_pipeline, validate_unsupported_syntax
from pysh.parsing.redirection import parse_redirections


def test_chain_splitting_preserves_quoted_operators() -> None:
    chain = split_chain('echo "a;b && c || d"; echo done')
    assert [item.command for item in chain] == ['echo "a;b && c || d"', "echo done"]
    assert chain[0].operator is ChainOp.SEMI
    assert chain[1].operator is None


def test_pipeline_splitting_preserves_quoted_pipes() -> None:
    stages = split_pipeline('printf "a|b" | wc -c')
    assert stages == ['printf "a|b"', "wc -c"]


def test_redirection_parsing_contract_unchanged() -> None:
    command, spec = parse_redirections("echo hello > out.txt 2>> err.txt")
    assert command == "echo hello"
    assert spec.stdout_path == "out.txt"
    assert not spec.stdout_append
    assert spec.stderr_path == "err.txt"
    assert spec.stderr_append


def test_trailing_pipe_is_deterministic_parse_error() -> None:
    with pytest.raises(ParseError, match="unexpected '\\|'"):
        split_pipeline("echo hello | ")


def test_shell_maps_parser_error_to_exit_code_2(capsys: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("echo hello | ")
    captured = capsys.readouterr()
    assert status == ExitCode.BUILTIN_MISUSE
    assert "parse error" in captured.err


def test_heredoc_syntax_is_no_longer_unsupported() -> None:
    validate_unsupported_syntax("cat << EOF")


def test_quoted_heredoc_token_is_literal_text() -> None:
    validate_unsupported_syntax("echo '<<'")
