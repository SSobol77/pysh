# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_repair_execution.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the PySH 0.9.0 execution repair wave."""
from __future__ import annotations

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from pysh.core.shell import PyShell


class _TTYStringIO(StringIO):
    """String stream with a controlled TTY identity for CLI routing tests."""

    def __init__(self, value: str = "", *, tty: bool) -> None:
        super().__init__(value)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_bare_non_tty_stdin_is_clean_batch_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pysh"],
        input="echo hello\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""


def test_batch_mode_returns_last_command_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pysh"],
        input="echo before\nfalse\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == "before\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("stdout_tty", "stderr_tty"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_non_tty_stdin_controls_batch_mode_for_all_output_tty_combinations(
    monkeypatch: pytest.MonkeyPatch,
    stdout_tty: bool,
    stderr_tty: bool,
) -> None:
    from pysh.cli import main

    stdin = _TTYStringIO("pwd\n", tty=False)
    stdout = _TTYStringIO(tty=stdout_tty)
    stderr = _TTYStringIO(tty=stderr_tty)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert main([]) == 0
    assert stdout.getvalue() == f"{os.getcwd()}\n"
    assert stderr.getvalue() == ""


def test_builtin_python_and_plugin_redirection(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.plugin_manager.register_command(
        "test",
        "plugin_echo",
        lambda _args: print("plugin") or 0,
    )
    pwd_file = tmp_path / "pwd"
    alias_file = tmp_path / "alias"
    command_file = tmp_path / "command"
    python_file = tmp_path / "python"
    plugin_file = tmp_path / "plugin"

    assert shell.execute(f"pwd > {pwd_file}") == 0
    assert shell.execute(f"alias > {alias_file}") == 0
    assert shell.execute(f"command -V py > {command_file}") == 0
    assert shell.execute(f"py print('python') > {python_file}") == 0
    assert shell.execute(f"plugin_echo > {plugin_file}") == 0

    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert pwd_file.read_text(encoding="utf-8") == f"{os.getcwd()}\n"
    assert "alias ls=" in alias_file.read_text(encoding="utf-8")
    assert command_file.read_text(encoding="utf-8") == "py is a PySH builtin\n"
    assert python_file.read_text(encoding="utf-8") == "python\n"
    assert plugin_file.read_text(encoding="utf-8") == "plugin\n"


def test_native_pipeline_stages_use_pysh_dispatch(capfd: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()
    shell.plugin_manager.register_command(
        "test",
        "plugin_echo",
        lambda _args: print("plugin-pipeline") or 0,
    )
    assert shell.execute("command -V py | cat") == 0
    assert capfd.readouterr().out == "py is a PySH builtin\n"
    assert shell.execute("alias | cat") == 0
    assert "alias ls=" in capfd.readouterr().out
    assert shell.execute("pwd | cat") == 0
    assert capfd.readouterr().out == f"{os.getcwd()}\n"
    assert shell.execute("plugin_echo | cat") == 0
    assert capfd.readouterr().out == "plugin-pipeline\n"
    assert shell.execute("printf 'python-inline\\n' | py print(input())") == 0
    assert capfd.readouterr().out == "python-inline\n"


def test_pipeline_status_is_final_stage_status() -> None:
    shell = PyShell()
    assert shell.execute("false | true") == 0
    assert shell.execute("true | false") == 1


def test_pipeline_builtin_state_is_isolated(tmp_path: Path) -> None:
    shell = PyShell()
    before = Path.cwd()
    assert shell.execute(f"cd {tmp_path} | cat") == 0
    assert Path.cwd() == before


def test_python_block_is_pipeline_stage(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = tmp_path / "pipeline.pysh"
    script.write_text(
        'echo "hello" | py {\n'
        "import sys\n"
        "data = sys.stdin.read()\n"
        'print(f"received: {data.strip()}")\n'
        "}\n",
        encoding="utf-8",
    )
    assert PyShell().run_script_file(script, [], native_only=True) == 0
    captured = capfd.readouterr()
    assert captured.out == "received: hello\n"
    assert captured.err == ""


def test_python_pipeline_block_preserves_python_operators(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = tmp_path / "operators.pysh"
    script.write_text(
        "echo ignored | py {\n"
        'value = 1 | 2; print(value); print("$HOME $(echo untouched)")\n'
        "}\n",
        encoding="utf-8",
    )
    assert PyShell().run_script_file(script, [], native_only=True) == 0
    assert capfd.readouterr().out == "3\n$HOME $(echo untouched)\n"


def test_numeric_fd_redirection_and_ordering(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    merged = tmp_path / "merged"
    stdout_only = tmp_path / "stdout-only"
    input_file = tmp_path / "input"
    input_file.write_text("input-data\n", encoding="utf-8")
    command = "python -c \"import sys; print('out'); print('err', file=sys.stderr)\""

    assert shell.execute(f"{command} >{merged} 2>&1") == 0
    assert merged.read_text(encoding="utf-8") == "err\nout\n"
    assert shell.execute(f"{command} 2>&1 >{stdout_only}") == 0
    assert stdout_only.read_text(encoding="utf-8") == "out\n"
    assert capfd.readouterr().out == "err\n"
    assert shell.execute(f"cat 0<{input_file}") == 0
    assert capfd.readouterr().out == "input-data\n"
    assert shell.execute("echo stderr 1>&2") == 0
    assert capfd.readouterr().err == "stderr\n"
    assert shell.execute("echo shorthand >&2") == 0
    assert capfd.readouterr().err == "shorthand\n"


def test_prompt_identity_uses_effective_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "spoofed")
    monkeypatch.setenv("LOGNAME", "also-spoofed")
    monkeypatch.setattr("pysh.core.shell.os.geteuid", lambda: 4242)
    passwd = type("Passwd", (), {"pw_name": "effective-user"})()
    monkeypatch.setattr("pysh.core.shell.pwd.getpwuid", lambda uid: passwd if uid == 4242 else None)
    options = {"show_user": True, "show_host": False}
    assert PyShell._prompt_identity(options) == "effective-user"
    assert PyShell._prompt_identity_segments(options) == [("effective-user", "user")]


def test_python_like_command_not_found_has_actionable_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert PyShell().execute("print('hello')") == 127
    captured = capsys.readouterr()
    assert "command not found" in captured.err
    assert "Python code requires the 'py' prefix" in captured.err


@pytest.mark.parametrize("command", ["for i in 1 2", "if true", "case x"])
def test_shell_control_flow_has_single_unsupported_diagnostic(
    command: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert PyShell().execute(command) == 2
    captured = capsys.readouterr()
    assert captured.err.count("unsupported syntax") == 1
    assert "command not found" not in captured.err


def test_process_substitution_has_deterministic_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert PyShell().execute("cat <(echo hello)") == 2
    captured = capsys.readouterr()
    assert "unsupported syntax: process substitution <(...)" in captured.err
    assert "No such file" not in captured.err
