# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Here-document and here-string tests for Issue #10."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.core.errors import ExitCode
from pysh.core.shell import PyShell
from pysh.parsing.errors import ParseError
from pysh.parsing.heredoc import (
    HereDocExpansionMode,
    HereDocOperator,
    collect_heredoc_bodies,
    parse_heredoc_specs,
)
from pysh.parsing.redirection import parse_redirections


def test_detect_standard_heredoc() -> None:
    spec = parse_heredoc_specs("cat << EOF")[0]
    assert spec.operator is HereDocOperator.HEREDOC
    assert spec.delimiter == "EOF"
    assert spec.expansion_mode is HereDocExpansionMode.EXPAND


def test_detect_tab_stripping_heredoc() -> None:
    spec = parse_heredoc_specs("cat <<- EOF")[0]
    assert spec.operator is HereDocOperator.HEREDOC_STRIP_TABS
    assert spec.strips_tabs


def test_detect_here_string() -> None:
    spec = parse_heredoc_specs('cat <<< "hello"')[0]
    assert spec.operator is HereDocOperator.HERE_STRING
    assert spec.raw_word == '"hello"'


def test_quoted_delimiter_is_literal_mode() -> None:
    for command in ("cat << 'EOF'", 'cat << "EOF"'):
        spec = parse_heredoc_specs(command)[0]
        assert spec.delimiter == "EOF"
        assert spec.quoted_delimiter
        assert spec.expansion_mode is HereDocExpansionMode.LITERAL


def test_missing_delimiter_word_is_parse_error() -> None:
    with pytest.raises(ParseError, match="missing heredoc delimiter"):
        parse_heredoc_specs("cat <<")


def test_missing_terminator_is_parse_error() -> None:
    with pytest.raises(ParseError, match="missing heredoc terminator: EOF"):
        collect_heredoc_bodies("cat << EOF\nhello", {})


def test_body_line_preservation() -> None:
    command, bodies = collect_heredoc_bodies("cat << EOF\nhello\nworld\nEOF", {})
    assert command == "cat << PYSH_HEREDOC"
    assert bodies[0].data == "hello\nworld\n"


def test_tab_stripping_removes_only_tabs() -> None:
    _, bodies = collect_heredoc_bodies("cat <<- EOF\n\thello\n  keep-space\n\tEOF", {})
    assert bodies[0].data == "hello\n  keep-space\n"


def test_no_glob_expansion_in_heredoc_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    _, bodies = collect_heredoc_bodies("cat << EOF\n*.py\nEOF", {})
    assert bodies[0].data == "*.py\n"


def test_parse_redirections_consumes_collected_heredoc() -> None:
    command, bodies = collect_heredoc_bodies("cat << EOF\nhello\nEOF", {})
    clean, spec = parse_redirections(command, bodies)
    assert clean == "cat"
    assert spec.stdin_data == b"hello\n"


def test_standard_heredoc_prints_body(capfd: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("cat << EOF\nhello\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "hello\n"


def test_unquoted_heredoc_expands_variables(capfd: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()
    shell.local_vars["VAR"] = "value"
    status = shell.execute("cat << EOF\n$VAR\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "value\n"


def test_single_quoted_heredoc_delimiter_leaves_variables_literal(
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.local_vars["VAR"] = "value"
    status = shell.execute("cat << 'EOF'\n$VAR\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "$VAR\n"


def test_double_quoted_heredoc_delimiter_leaves_variables_literal(
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.local_vars["VAR"] = "value"
    status = shell.execute('cat << "EOF"\n$VAR\nEOF')
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "$VAR\n"


def test_tab_stripping_heredoc_prints_stripped_body(capfd: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("cat <<- EOF\n\thello\n\tEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "hello\n"


def test_here_string_appends_newline(capfd: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute('cat <<< "hello"')
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "hello\n"


def test_here_string_expands_variable(capfd: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()
    shell.local_vars["VAR"] = "value"
    status = shell.execute('cat <<< "$VAR"')
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "value\n"


def test_here_string_does_not_glob_expand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    status = PyShell().execute('cat <<< "*.py"')
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "*.py\n"


def test_regular_glob_expansion_remains_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    status = PyShell().execute("echo *.py")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "a.py\n"


def test_command_not_found_after_heredoc_collection(capsys: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("missing-command-xyz << EOF\nhello\nEOF")
    captured = capsys.readouterr()
    assert status == ExitCode.COMMAND_NOT_FOUND
    assert "command not found" in captured.err


def test_missing_terminator_returns_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    status = PyShell().execute("cat << EOF\nhello")
    captured = capsys.readouterr()
    assert status == ExitCode.BUILTIN_MISUSE
    assert "missing heredoc terminator" in captured.err


def test_last_stdin_redirection_wins_file_after_heredoc(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("from-file\n", encoding="utf-8")
    status = PyShell().execute(f"cat << EOF < {input_file}\nfrom-heredoc\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "from-file\n"


def test_last_stdin_redirection_wins_heredoc_after_file(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("from-file\n", encoding="utf-8")
    status = PyShell().execute(f"cat < {input_file} << EOF\nfrom-heredoc\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "from-heredoc\n"


def test_multiple_heredocs_are_supported_last_one_wins(
    capfd: pytest.CaptureFixture[str],
) -> None:
    status = PyShell().execute("cat << A << B\na\nA\nb\nB")
    captured = capfd.readouterr()
    assert status == 0
    assert captured.out == "b\n"


def test_command_after_heredoc_runs_via_logical_line(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Command on a line after the heredoc terminator must execute."""
    from pysh.parsing.multiline import iter_logical_lines

    shell = PyShell()
    text = "cat << EOF\nhello\nEOF\necho after"
    status = 0
    for logical_line in iter_logical_lines(text.splitlines()):
        status = shell.execute(logical_line)
    captured = capfd.readouterr()
    assert status == 0
    assert "hello\n" in captured.out
    assert "after\n" in captured.out


def test_semicolon_after_delimiter_word_is_not_terminator(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A line like 'EOF; echo after' must NOT be treated as the heredoc terminator.

    Only an exact match of the delimiter on an otherwise-empty line terminates
    the heredoc body.
    """
    _, bodies = collect_heredoc_bodies("cat << EOF\nEOF; echo after\nEOF", {})
    # The body must contain the non-terminator line literally
    assert bodies[0].data == "EOF; echo after\n"


def test_heredoc_body_line_is_not_executed_as_shell_command(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Heredoc body lines that look like shell commands must not be executed."""
    status = PyShell().execute("cat << EOF\necho sneaky\nEOF")
    captured = capfd.readouterr()
    assert status == 0
    # cat should print the literal text, not execute 'echo sneaky'
    assert captured.out == "echo sneaky\n"


def test_missing_delimiter_word_returns_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    """'cat <<' with no delimiter word must return exit status 2."""
    status = PyShell().execute("cat <<")
    captured = capsys.readouterr()
    assert status == ExitCode.BUILTIN_MISUSE
    assert "missing heredoc delimiter" in captured.err
