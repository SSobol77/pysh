# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_secure_builtin.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the explicit ``secure`` builtin integration."""
from __future__ import annotations

import inspect
import sys

import pytest

import pysh.security.secure_runner as secure_runner
from pysh.core.shell import PyShell


def test_secure_builtin_no_args_returns_usage(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()

    assert shell.execute("secure") == 2
    captured = capsys.readouterr()
    assert "secure: usage: secure <command> [args ...]" in captured.err


def test_secure_builtin_runs_command(capfd: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()

    status = shell.execute(f"{sys.executable} -c \"print('normal')\"")
    assert status == 0
    normal = capfd.readouterr()

    status = shell.execute(f"secure {sys.executable} -c \"print('hi')\"")
    assert status == 0
    captured = capfd.readouterr()

    assert normal.out.strip() == "normal"
    assert captured.out.replace("\r\n", "\n").strip() == "hi"


def test_secure_builtin_propagates_child_exit_status() -> None:
    shell = PyShell()

    assert shell.execute(f"secure {sys.executable} -c \"raise SystemExit(17)\"") == 17


def test_secure_builtin_missing_command_returns_127(
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("secure definitely_missing_pysh_secure_command") == 127
    captured = capfd.readouterr()
    assert "command not found" in captured.out


def test_secure_is_registered_as_builtin() -> None:
    assert "secure" in PyShell.BUILTINS


def test_normal_external_path_does_not_reference_sensitive_input() -> None:
    assert "sensitive_input" not in inspect.getsource(PyShell._run_external)
    assert "sensitive_input" not in inspect.getsource(PyShell._run_pipeline)


def test_secure_builtin_is_only_shell_runtime_reader_of_sensitive_input() -> None:
    readers = []
    for name, member in inspect.getmembers(PyShell, inspect.isfunction):
        if name == "__init__":
            continue
        source = inspect.getsource(member)
        if "sensitive_input" in source and name != "set_sensitive_input_indicator":
            readers.append(name)

    assert readers == ["_builtin_secure"]


def test_security_forbidden_strings_absent() -> None:
    combined = "\n".join(
        (
            inspect.getsource(PyShell),
            inspect.getsource(secure_runner),
        )
    )

    assert "sudo -S" not in combined
    assert "[sudo] password" not in combined


def test_no_pty_input_written_to_history_or_logs() -> None:
    assert "history.add" not in inspect.getsource(secure_runner)
    assert "logging" not in inspect.getsource(secure_runner)
    assert "logger" not in inspect.getsource(secure_runner)
    assert "subprocess.run" not in inspect.getsource(secure_runner)
