# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_python_runtime.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the Python-native ``py`` runtime bridge."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.core.shell import PyShell
from pysh.python_layer.runtime import (
    NestedBlockError,
    PythonRuntime,
    UnterminatedBlockError,
    extract_block_body,
    is_block_closer,
    is_block_opener,
    iter_logical_lines,
)


def test_py_builtin_executes_code(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()
    assert shell.execute('py print("hello from python")') == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello from python"


def test_py_builtin_preserves_variable_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py x = 10") == 0
    assert shell.execute("py print(x)") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "10"


def test_py_builtin_preserves_import_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py import pathlib") == 0
    assert shell.execute('py print(pathlib.Path(".").exists())') == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "True"


def test_py_builtin_allows_semicolon_python_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py import sys; print(sys.version_info.major)") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "3"


def test_py_builtin_exception_returns_nonzero_without_killing_shell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py 1 / 0") == 1
    assert shell.execute('py print("still alive")') == 0
    captured = capsys.readouterr()
    assert "ZeroDivisionError" in captured.err
    assert "still alive" in captured.out


# ----------------------------------------------------------- block runtime

def test_python_runtime_executes_block_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = PythonRuntime()
    body = "x = 10\nprint(x)"
    assert runtime.execute_block(body) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "10"


def test_python_runtime_block_persists_variables(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = PythonRuntime()
    assert runtime.execute_block("x = 7\ny = 3") == 0
    assert runtime.execute("print(x + y)") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "10"


def test_python_runtime_block_persists_imports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = PythonRuntime()
    assert runtime.execute_block("import math\nVALUE = math.pi") == 0
    assert runtime.execute("print(round(VALUE, 2))") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "3.14"


def test_python_runtime_empty_block_returns_zero() -> None:
    runtime = PythonRuntime()
    assert runtime.execute_block("") == 0
    assert runtime.execute_block("\n\n") == 0


def test_python_runtime_block_syntax_error_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = PythonRuntime()
    assert runtime.execute_block("if True\n    pass") == 1
    captured = capsys.readouterr()
    assert "SyntaxError" in captured.err


def test_python_runtime_block_dedents_indented_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = PythonRuntime()
    body = "    a = 1\n    print(a)"
    assert runtime.execute_block(body) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"


# ----------------------------------------------------------- block helpers

def test_is_block_opener_and_closer() -> None:
    assert is_block_opener("py {")
    assert is_block_opener("  py {  ")
    assert is_block_opener("py { # comment")
    assert not is_block_opener("py print('x')")
    assert is_block_closer("}")
    assert is_block_closer("  }  ")
    assert not is_block_closer("} else {")


def test_iter_logical_lines_yields_passthrough() -> None:
    lines = ["echo a", "echo b"]
    assert list(iter_logical_lines(lines)) == ["echo a", "echo b"]


def test_iter_logical_lines_collects_block() -> None:
    lines = ["echo before", "py {", "x = 1", "print(x)", "}", "echo after"]
    result = list(iter_logical_lines(lines))
    assert result[0] == "echo before"
    assert result[1] == "py {\nx = 1\nprint(x)\n}"
    assert result[2] == "echo after"


def test_iter_logical_lines_raises_on_unterminated() -> None:
    with pytest.raises(UnterminatedBlockError):
        list(iter_logical_lines(["py {", "x = 1"]))


def test_iter_logical_lines_raises_on_nested() -> None:
    with pytest.raises(NestedBlockError):
        list(iter_logical_lines(["py {", "py {", "}", "}"]))


def test_extract_block_body_returns_inner_lines() -> None:
    text = "py {\n    x = 1\n    print(x)\n}"
    assert extract_block_body(text) == "    x = 1\n    print(x)"


# ----------------------------------------------------------- shell integration

def test_shell_executes_multiline_block(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    block = "py {\nx = 41 + 1\nprint(x)\n}"
    assert shell.execute(block) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "42"


def test_shell_block_variables_visible_in_oneline_py(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    block = "py {\ndata = [1, 2, 3]\n}"
    assert shell.execute(block) == 0
    assert shell.execute("py print(sum(data))") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "6"


def test_shell_oneline_state_visible_in_block(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py n = 5") == 0
    block = "py {\nprint(n * 2)\n}"
    assert shell.execute(block) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "10"


def test_shell_block_exception_returns_nonzero_and_survives(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    block = "py {\nraise RuntimeError('oops')\n}"
    assert shell.execute(block) == 1
    assert shell.execute('py print("alive")') == 0
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "alive" in captured.out


def test_shell_block_syntax_error_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    block = "py {\nif True\n    pass\n}"
    assert shell.execute(block) == 1
    captured = capsys.readouterr()
    assert "SyntaxError" in captured.err


def test_shell_empty_block_returns_zero() -> None:
    shell = PyShell()
    assert shell.execute("py {\n}") == 0


def test_shell_bare_py_opener_is_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("py {") == 2
    captured = capsys.readouterr()
    assert "unterminated" in captured.err


def test_script_runner_unterminated_block_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = tmp_path / "blocky.pysh"
    script.write_text("py {\nx = 1\n", encoding="utf-8")
    shell = PyShell()
    status = shell.execute(f"run_script {script}")
    assert status != 0
    captured = capsys.readouterr()
    assert "unterminated" in captured.err


def test_script_runner_executes_block(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = tmp_path / "blocky.pysh"
    script.write_text("py {\nprint('block-ran')\n}\n", encoding="utf-8")
    shell = PyShell()
    assert shell.execute(f"run_script {script}") == 0
    captured = capsys.readouterr()
    assert "block-ran" in captured.out
