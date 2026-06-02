# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_editor_options.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

import termios

import pytest

from pysh.config_api import (
    DEFAULT_EDITOR_OPTIONS,
    ConfigError,
    ShellConfigAPI,
    validate_editor_option,
)
from pysh.shell import PyShell


def test_editor_options_defaults_exact() -> None:
    assert DEFAULT_EDITOR_OPTIONS == {
        "autosuggest": True,
        "syntax_highlight": True,
        "line_editor": "auto",
        "mc_integration": "auto",
        "mc_warning_enabled": True,
    }


def test_set_editor_option_valid() -> None:
    shell = PyShell()
    ShellConfigAPI(shell).set_editor_option("line_editor", "readline")
    ShellConfigAPI(shell).set_editor_option("mc_integration", "safe")
    ShellConfigAPI(shell).set_editor_option("mc_warning_enabled", False)
    assert shell.editor_options["line_editor"] == "readline"
    assert shell.editor_options["mc_integration"] == "safe"
    assert shell.editor_options["mc_warning_enabled"] is False


def test_set_mc_integration_valid() -> None:
    shell = PyShell()
    ShellConfigAPI(shell).set_mc_integration("subshell")
    assert shell.editor_options["mc_integration"] == "subshell"


def test_set_mc_warning_enabled_valid() -> None:
    shell = PyShell()
    ShellConfigAPI(shell).set_mc_warning_enabled(False)
    assert shell.editor_options["mc_warning_enabled"] is False


def test_editor_option_invalid_name_type_value() -> None:
    with pytest.raises(ConfigError):
        validate_editor_option("missing", True)
    with pytest.raises(ConfigError):
        validate_editor_option("autosuggest", "yes")
    with pytest.raises(ConfigError):
        validate_editor_option("line_editor", "ansi")
    with pytest.raises(ConfigError):
        validate_editor_option("mc_integration", "force")
    with pytest.raises(ConfigError):
        validate_editor_option("mc_warning_enabled", "no")


def test_pyshell_protocol_has_set_editor_option() -> None:
    shell = PyShell()
    shell.set_editor_option("syntax_highlight", False)
    assert shell.editor_options["syntax_highlight"] is False


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_raw_editor_auto_falls_back_for_non_tty(monkeypatch) -> None:
    shell = PyShell()
    monkeypatch.setattr("pysh.shell.sys.stdin", _FakeStream(False))
    monkeypatch.setattr("pysh.shell.sys.stdout", _FakeStream(True))
    assert shell._should_use_raw_editor() is False

    monkeypatch.setattr("pysh.shell.sys.stdin", _FakeStream(True))
    monkeypatch.setattr("pysh.shell.sys.stdout", _FakeStream(False))
    assert shell._should_use_raw_editor() is False


def test_raw_editor_auto_falls_back_for_color_gate(monkeypatch) -> None:
    shell = PyShell()
    monkeypatch.setattr("pysh.shell.sys.stdin", _FakeStream(True))
    monkeypatch.setattr("pysh.shell.sys.stdout", _FakeStream(True))
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert shell._should_use_raw_editor() is False

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("NO_COLOR", "1")
    assert shell._should_use_raw_editor() is False


def test_raw_editor_forced_readline_and_basic_modes(monkeypatch) -> None:
    shell = PyShell()
    monkeypatch.setattr("pysh.shell.sys.stdin", _FakeStream(True))
    monkeypatch.setattr("pysh.shell.sys.stdout", _FakeStream(True))
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)

    shell.set_editor_option("line_editor", "readline")
    assert shell._should_use_raw_editor() is False

    shell.set_editor_option("line_editor", "basic")
    assert shell._should_use_raw_editor() is True
    options = shell._resolved_editor_options()
    assert options.autosuggest is False
    assert options.syntax_highlight is False


def test_raw_mode_setup_failure_falls_back_to_input(monkeypatch) -> None:
    shell = PyShell()
    shell.set_editor_option("line_editor", "basic")
    monkeypatch.setattr("pysh.shell.sys.stdin", _FakeStream(True))
    monkeypatch.setattr("pysh.shell.sys.stdout", _FakeStream(True))
    monkeypatch.setattr(shell.line_reader, "read_line", lambda *_args, **_kwargs: (_ for _ in ()).throw(termios.error()))
    monkeypatch.setattr("builtins.input", lambda prompt: "fallback")
    assert shell._read_interactive_line() == "fallback"
