# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the PyShell class."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.core.shell import PyShell, _ExitShell
from pysh.editor.lineedit.reader import QueuedCommand


@pytest.fixture
def shell() -> PyShell:
    return PyShell()


@pytest.fixture
def in_tmp_cwd(tmp_path: Path) -> Path:
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(original)


def test_cd_changes_directory(shell: PyShell, in_tmp_cwd: Path) -> None:
    sub = in_tmp_cwd / "sub"
    sub.mkdir()
    assert shell.execute(f"cd {sub}") == 0
    assert Path.cwd() == sub


def test_cd_to_home_when_no_argument(shell: PyShell, in_tmp_cwd: Path) -> None:
    assert shell.execute("cd") == 0
    assert Path.cwd() == Path.home()


def test_local_assignment(shell: PyShell) -> None:
    assert shell.execute("X=42") == 0
    assert shell.local_vars["X"] == "42"


def test_local_assignment_with_quotes(shell: PyShell) -> None:
    assert shell.execute('MSG="hello world"') == 0
    assert shell.local_vars["MSG"] == "hello world"


def test_export_sets_environ(shell: PyShell, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYSH_TEST_VAR", raising=False)
    assert shell.execute("export PYSH_TEST_VAR=hello") == 0
    assert os.environ["PYSH_TEST_VAR"] == "hello"


def test_export_existing_local(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_LOCAL_NAME", raising=False)
    shell.execute("PYSH_LOCAL_NAME=value")
    shell.execute("export PYSH_LOCAL_NAME")
    assert os.environ["PYSH_LOCAL_NAME"] == "value"


def test_alias_expansion_first_word_only(shell: PyShell) -> None:
    shell.execute('alias mygreet="echo greeting"')
    expanded = shell._expand_alias("mygreet world")
    assert expanded == "echo greeting world"
    # Alias name appearing later is not expanded.
    assert shell._expand_alias("echo mygreet") == "echo mygreet"


def test_alias_expansion_preserves_quoted_arguments(shell: PyShell) -> None:
    shell.execute('alias greet="echo hi"')
    expanded = shell._expand_alias('greet "with | pipe"')
    assert expanded == 'echo hi "with | pipe"'


def test_default_alias_present(shell: PyShell) -> None:
    assert "ll" in shell.aliases
    assert shell.aliases["ll"] == "ls --color=auto -laF"


def test_alias_can_be_overridden_via_alias_builtin(shell: PyShell) -> None:
    shell.execute('alias ll="ls -la --color=auto -F"')
    assert shell.aliases["ll"] == "ls -la --color=auto -F"


def test_pwd_builtin(shell: PyShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.execute("pwd")
    captured = capsys.readouterr()
    assert captured.out.strip() == os.getcwd()


def test_echo_quoted_pipe_does_not_split(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    """Regression: echo "PySH | Python" must print the literal string."""
    status = shell.execute('echo "PySH | Python"')
    assert status == 0
    captured = capfd.readouterr()
    assert captured.out.strip() == "PySH | Python"


def test_python_subprocess_semicolon_not_split(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    """Regression: python3.13 -c "import subprocess; print('ok')"."""
    status = shell.execute(
        'python3.13 -c "import subprocess; print(\'ok\')"'
    )
    assert status == 0
    captured = capfd.readouterr()
    assert captured.out.strip() == "ok"


def test_chain_and_short_circuits(
    shell: PyShell, in_tmp_cwd: Path
) -> None:
    status = shell.execute("false && echo should-not-run")
    # ``false`` returns 1; chain stops, so final status is 1.
    assert status == 1


def test_chain_or_runs_on_failure(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    status = shell.execute("false || echo recovered")
    assert status == 0
    captured = capfd.readouterr()
    assert captured.out.strip() == "recovered"


def test_chain_semicolon_runs_both(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    shell.execute("echo first; echo second")
    captured = capfd.readouterr()
    assert captured.out.strip().splitlines() == ["first", "second"]


def test_redirection_writes_file(shell: PyShell, in_tmp_cwd: Path) -> None:
    target = in_tmp_cwd / "out.txt"
    shell.execute(f'echo "hello" > {target}')
    assert target.read_text().strip() == "hello"


def test_redirection_append(shell: PyShell, in_tmp_cwd: Path) -> None:
    target = in_tmp_cwd / "out.txt"
    shell.execute(f"echo first > {target}")
    shell.execute(f"echo second >> {target}")
    assert target.read_text().splitlines() == ["first", "second"]


def test_pipeline_runs(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    status = shell.execute("printf 'a\\nb\\nc\\n' | head -2")
    assert status == 0
    captured = capfd.readouterr()
    assert captured.out.splitlines() == ["a", "b"]


def test_stderr_redirection(shell: PyShell, in_tmp_cwd: Path) -> None:
    target = in_tmp_cwd / "err.log"
    status = shell.execute(
        f'python3.13 -c "import sys; print(\'err\', file=sys.stderr)" 2> {target}'
    )
    assert status == 0
    assert target.read_text().strip() == "err"


def test_internal_command_not_found_stderr_redirection(
    shell: PyShell,
    in_tmp_cwd: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Internal diagnostics must honor command-level stderr redirection."""
    target = in_tmp_cwd / "pysh-error.txt"

    status = shell.execute(f"missing-command-xyz 2> {target}")

    captured = capfd.readouterr()
    assert status == 127
    assert captured.err == ""
    assert target.read_text(encoding="utf-8") == "pysh: missing-command-xyz: command not found\n"


def test_internal_command_not_found_combined_redirection(
    shell: PyShell,
    in_tmp_cwd: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Combined redirection must capture PySH-owned stderr diagnostics."""
    target = in_tmp_cwd / "pysh-all.txt"

    status = shell.execute(f"missing-command-xyz &> {target}")

    captured = capfd.readouterr()
    assert status == 127
    assert captured.out == ""
    assert captured.err == ""
    assert target.read_text(encoding="utf-8") == "pysh: missing-command-xyz: command not found\n"


def test_variable_expansion_in_command(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    shell.execute("NAME=world")
    shell.execute('echo "hello $NAME"')
    captured = capfd.readouterr()
    assert captured.out.strip() == "hello world"


def test_single_quoted_dollar_is_literal(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    shell.execute("echo '$HOME'")
    captured = capfd.readouterr()
    assert captured.out.strip() == "$HOME"


def test_external_command_not_found(
    shell: PyShell, capsys: pytest.CaptureFixture[str]
) -> None:
    status = shell.execute("definitely_not_a_real_command_xyz")
    assert status == 127
    captured = capsys.readouterr()
    assert "command not found" in captured.err


def test_command_substitution_in_execute(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    """The shell expands $() before splitting the chain."""
    status = shell.execute("echo $(printf hello)")
    assert status == 0
    captured = capfd.readouterr()
    assert "hello" in captured.out


def test_command_substitution_backticks_in_execute(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    status = shell.execute("echo `printf world`")
    assert status == 0
    captured = capfd.readouterr()
    assert "world" in captured.out


def test_command_substitution_suppressed_in_single_quotes(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    status = shell.execute("echo 'literal $(printf x)'")
    assert status == 0
    captured = capfd.readouterr()
    assert "literal $(printf x)" in captured.out


@pytest.mark.parametrize("command", ["exit", "exit ", "exit   ", "quit", "quit ", "quit   "])
def test_exit_and_quit_dispatch_through_exit_shell(command: str, shell: PyShell) -> None:
    """exit/quit must dispatch as builtins after deterministic command-word trimming."""
    with pytest.raises(_ExitShell) as exc:
        shell.execute(command)
    assert exc.value.code == 0


def test_exit_preserves_numeric_status(shell: PyShell) -> None:
    with pytest.raises(_ExitShell) as exc:
        shell.execute("exit 7")
    assert exc.value.code == 7


def test_exit_and_quit_are_registered_builtins(shell: PyShell) -> None:
    assert "exit" in shell.BUILTINS
    assert "quit" in shell.BUILTINS


# ---------------------------------------------------------------- Issue #22: paste state hardening


def test_parse_error_has_single_prefix_not_double(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    """Direct parse error must not have an embedded pysh: prefix in the message."""
    shell.execute('echo "unterminated')
    captured = capfd.readouterr()
    assert "parse error: unterminated double quote" in captured.err
    assert "parse error: pysh:" not in captured.err


def test_parse_error_from_paste_has_paste_attribution(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """paste_run with an unterminated quote must label the error as paste."""
    shell = PyShell()
    shell.pending_multiline_paste = 'echo "unterminated'
    shell._builtin_paste_run([])
    captured = capfd.readouterr()
    assert "parse error (paste): unterminated double quote" in captured.err
    assert "parse error: pysh:" not in captured.err


def test_parse_error_from_normal_input_has_no_paste_attribution(
    shell: PyShell, capfd: pytest.CaptureFixture[str]
) -> None:
    """Direct command with unterminated quote must show normal parse error label."""
    shell.execute('echo "unterminated')
    captured = capfd.readouterr()
    assert "parse error:" in captured.err
    assert "parse error (paste)" not in captured.err


def test_paste_cancel_clears_queued_commands(shell: PyShell) -> None:
    """paste_cancel must clear queued commands that arrived in the same terminal batch."""
    shell.pending_multiline_paste = "echo one\necho two"
    shell.line_reader._command_queue = [QueuedCommand("after")]
    shell._builtin_paste_cancel([])
    assert shell.pending_multiline_paste is None
    assert not shell.line_reader._command_queue


def test_paste_cancel_resets_executing_paste_flag(shell: PyShell) -> None:
    """paste_cancel must reset _executing_paste to False."""
    shell.pending_multiline_paste = "echo one"
    shell._executing_paste = True
    shell._builtin_paste_cancel([])
    assert not shell._executing_paste


def test_paste_run_clears_queued_commands_after_success(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """paste_run must clear queued commands after successful paste execution."""
    shell = PyShell()
    shell.pending_multiline_paste = "echo ok"
    shell.line_reader._command_queue = [QueuedCommand("after")]
    shell._builtin_paste_run([])
    assert shell.pending_multiline_paste is None
    assert not shell.line_reader._command_queue


def test_paste_run_clears_queued_commands_after_error(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """paste_run must clear queued commands even when paste parsing fails."""
    shell = PyShell()
    shell.pending_multiline_paste = 'echo "unterminated'
    shell.line_reader._command_queue = [QueuedCommand("after")]
    shell._builtin_paste_run([])
    assert shell.pending_multiline_paste is None
    assert not shell.line_reader._command_queue


def test_paste_run_resets_executing_paste_flag_after_success(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """paste_run must reset _executing_paste to False after normal execution."""
    shell = PyShell()
    shell.pending_multiline_paste = "echo ok"
    shell._builtin_paste_run([])
    assert not shell._executing_paste


def test_paste_run_resets_executing_paste_flag_after_error(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """paste_run must reset _executing_paste even when the payload has a parse error."""
    shell = PyShell()
    shell.pending_multiline_paste = 'echo "unterminated'
    shell._builtin_paste_run([])
    assert not shell._executing_paste


def test_paste_run_clears_pending_paste_before_execution(shell: PyShell) -> None:
    """pending_multiline_paste must be None before paste_run returns."""
    shell.pending_multiline_paste = "echo ok"
    shell._builtin_paste_run([])
    assert shell.pending_multiline_paste is None


def test_executing_paste_false_initially(shell: PyShell) -> None:
    """_executing_paste must start as False."""
    assert not shell._executing_paste
