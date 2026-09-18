# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_shell_export.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for interactive SHELL / PYSH_SHELL / PYSH_INTERACTIVE auto-export."""
from __future__ import annotations

import os
import unittest.mock as mock

import pytest

from pysh.core.shell import PyShell


@pytest.fixture
def shell() -> PyShell:
    return PyShell()


# ---------------------------------------------------------------- _resolve_pysh_path


def test_resolve_pysh_path_shutil_which_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutil.which('pysh') is tried first."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/pysh" if name == "pysh" else None)
    shell = PyShell()
    assert shell._resolve_pysh_path() == "/usr/local/bin/pysh"


def test_resolve_pysh_path_falls_back_to_argv0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """sys.argv[0] is used when shutil.which returns None."""
    fake_script = tmp_path / "pysh"
    fake_script.touch()
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("sys.argv", [str(fake_script)])
    shell = PyShell()
    assert shell._resolve_pysh_path() == str(fake_script)


def test_resolve_pysh_path_falls_back_to_sys_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sys.executable is the final fallback."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("sys.argv", ["/nonexistent/pysh"])
    import sys

    shell = PyShell()
    assert shell._resolve_pysh_path() == sys.executable


# ---------------------------------------------------------------- _export_interactive_shell_vars


def test_interactive_tty_sets_shell_var(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SHELL is exported to the PySH path when stdin/stdout are TTYs."""
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pysh" if name == "pysh" else None)
    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        shell._export_interactive_shell_vars()
    assert os.environ.get("SHELL") == "/usr/bin/pysh"


def test_interactive_tty_sets_pysh_shell_var(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_SHELL", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pysh" if name == "pysh" else None)
    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        shell._export_interactive_shell_vars()
    assert os.environ.get("PYSH_SHELL") == "/usr/bin/pysh"


def test_interactive_tty_sets_pysh_interactive(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_INTERACTIVE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pysh" if name == "pysh" else None)
    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        shell._export_interactive_shell_vars()
    assert os.environ.get("PYSH_INTERACTIVE") == "1"


def test_non_interactive_does_not_force_shell(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In non-interactive mode (stdin not a TTY) SHELL must not be forced."""
    original = os.environ.get("SHELL")
    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=False):
        shell._export_interactive_shell_vars()
    # SHELL must remain unchanged (or absent) when not interactive.
    assert os.environ.get("SHELL") == original


def test_local_vars_mirror_exported_values(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exported vars must also appear in shell.local_vars for $VAR expansion."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pysh" if name == "pysh" else None)
    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        shell._export_interactive_shell_vars()
    assert shell.local_vars.get("SHELL") == "/usr/bin/pysh"
    assert shell.local_vars.get("PYSH_SHELL") == "/usr/bin/pysh"
    assert shell.local_vars.get("PYSH_INTERACTIVE") == "1"
