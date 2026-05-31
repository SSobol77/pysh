# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_pyshrc_py.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the Python-native configuration layer (``~/.pyshrc.py``)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.config_api import (
    DEFAULT_PROMPT_OPTIONS,
    ConfigError,
    ShellConfigAPI,
    ensure_default_config,
    load_python_config,
    validate_prompt_option,
)
from pysh.shell import PyShell


class FakeShell:
    """Minimal ConfigurableShell used for unit-level API tests."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.environment: dict[str, str] = {}
        self.prompt_options: dict[str, object] = dict(DEFAULT_PROMPT_OPTIONS)

    def register_alias(self, name: str, value: str) -> None:
        self.aliases[name] = value

    def set_environment(self, name: str, value: str) -> None:
        self.environment[name] = value

    def set_prompt_option(self, name: str, value: object) -> None:
        validate_prompt_option(name, value)
        self.prompt_options[name] = value


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------- file creation
def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:
    target = tmp_path / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()
    assert "def configure" in target.read_text(encoding="utf-8")


def test_ensure_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()


def test_ensure_does_not_overwrite_existing(tmp_path: Path) -> None:
    target = _write(tmp_path / ".pyshrc.py", "# user content\n")
    assert ensure_default_config(target) is False
    assert target.read_text(encoding="utf-8") == "# user content\n"


def test_default_template_is_inert(tmp_path: Path) -> None:
    # The generated configure() must not change any state on first run.
    target = tmp_path / ".pyshrc.py"
    ensure_default_config(target)
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases == {}
    assert shell.environment == {}
    assert shell.prompt_options == DEFAULT_PROMPT_OPTIONS


# ------------------------------------------------------------------- API layer
def test_api_alias_registration() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).alias("ll", "ls -la")
    assert shell.aliases == {"ll": "ls -la"}


def test_api_env_registration() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).env("EDITOR", "nano")
    assert shell.environment == {"EDITOR": "nano"}


@pytest.mark.parametrize("name", ["bad name", "", "a=b"])
def test_api_alias_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).alias(name, "value")


@pytest.mark.parametrize("name", ["1BAD", "with-dash", "has space", ""])
def test_api_env_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).env(name, "value")


def test_api_alias_rejects_non_string_value() -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).alias("ll", 123)  # type: ignore[arg-type]


# -------------------------------------------------------------- prompt options
def test_validate_prompt_option_unknown_name() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("does_not_exist", True)


def test_validate_prompt_option_wrong_type() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("symbol", 5)
    with pytest.raises(ConfigError):
        validate_prompt_option("show_user", "yes")


def test_api_set_prompt_option_applies() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).set_prompt_option("show_python_version", True)
    assert shell.prompt_options["show_python_version"] is True


# ---------------------------------------------------------------- loader paths
def test_load_missing_file_returns_zero(tmp_path: Path) -> None:
    assert load_python_config(FakeShell(), path=tmp_path / "nope.py") == 0


def test_load_registers_alias_and_env(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n"
        "    shell.alias('ll', 'ls -la')\n"
        "    shell.env('EDITOR', 'nano')\n",
    )
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases == {"ll": "ls -la"}
    assert shell.environment == {"EDITOR": "nano"}


def test_load_sets_prompt_option(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n"
        "    shell.set_prompt_option('show_python_version', True)\n",
    )
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.prompt_options["show_python_version"] is True


def test_load_without_configure_is_ok(tmp_path: Path) -> None:
    target = _write(tmp_path / ".pyshrc.py", "X = 1\n")
    assert load_python_config(FakeShell(), path=target) == 0


def test_load_configure_not_callable(tmp_path: Path, capsys) -> None:
    target = _write(tmp_path / ".pyshrc.py", "configure = 42\n")
    assert load_python_config(FakeShell(), path=target) == 1
    assert "not callable" in capsys.readouterr().err


def test_load_syntax_error_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(tmp_path / ".pyshrc.py", "def configure(shell):\n    x = =\n")
    assert load_python_config(FakeShell(), path=target) == 1
    assert "syntax error" in capsys.readouterr().err


def test_load_configure_exception_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    raise RuntimeError('boom')\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "boom" in capsys.readouterr().err


def test_load_invalid_config_call_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    shell.set_prompt_option('nope', True)\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "unknown prompt option" in capsys.readouterr().err


def test_load_top_level_system_exit_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(tmp_path / ".pyshrc.py", "raise SystemExit(7)\n")
    assert load_python_config(FakeShell(), path=target) == 1
    assert "failed to load" in capsys.readouterr().err


def test_load_configure_system_exit_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    raise SystemExit(7)\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "configure() failed" in capsys.readouterr().err


def test_load_configure_keyboard_interrupt_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    raise KeyboardInterrupt\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "configure() failed" in capsys.readouterr().err


# --------------------------------------------------- integration with PyShell
def test_pyshell_default_prompt_is_unchanged(monkeypatch) -> None:
    # Default options must reproduce "<icon> <user>:<cwd>$ ".
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    prompt = shell._prompt()
    assert "tester:" in prompt
    assert prompt.endswith("$ ")
    assert " py" not in prompt


def test_pyshell_prompt_python_version_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    shell.set_prompt_option("show_python_version", True)
    assert " py3." in shell._prompt()


def test_pyshell_prompt_host_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    shell.set_prompt_option("show_host", True)
    assert "tester@" in shell._prompt()


def test_pyshell_prompt_custom_symbol(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    shell.set_prompt_option("symbol", "%")
    assert shell._prompt().endswith("% ")


def test_pyshell_set_environment_is_mirrored(monkeypatch) -> None:
    monkeypatch.delenv("PYSH_TEST_VAR", raising=False)
    shell = PyShell()
    shell.set_environment("PYSH_TEST_VAR", "1")
    import os

    assert os.environ["PYSH_TEST_VAR"] == "1"
    assert shell.local_vars["PYSH_TEST_VAR"] == "1"


def test_pyshell_loads_config_file(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    shell.alias('gg', 'git status')\n",
    )
    shell = PyShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases["gg"] == "git status"


def test_pyshell_set_prompt_option_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        PyShell().set_prompt_option("unknown", True)
