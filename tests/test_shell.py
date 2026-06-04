# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the PyShell class."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.core.shell import PyShell


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
