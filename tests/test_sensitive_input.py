# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_sensitive_input.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Validation tests for the reserved sensitive-input indicator configuration."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from pysh.config_api import (
    DEFAULT_SENSITIVE_INPUT,
    ConfigError,
    ConfigurableShell,
    ShellConfigAPI,
    validate_sensitive_input,
)
from pysh.shell import PyShell


def test_sensitive_input_defaults_exact_match() -> None:
    assert DEFAULT_SENSITIVE_INPUT == {
        "enabled": False,
        "symbol": "*",
        "idle_color": "white",
        "active_color": "lime",
        "mode": "single-blink",
    }
    assert PyShell().sensitive_input == DEFAULT_SENSITIVE_INPUT


def test_set_sensitive_input_indicator_accepts_valid_values() -> None:
    shell = PyShell()
    api = ShellConfigAPI(shell)

    api.set_sensitive_input_indicator("enabled", True)
    api.set_sensitive_input_indicator("symbol", "+")
    api.set_sensitive_input_indicator("idle_color", "#FFFFFF")
    api.set_sensitive_input_indicator("active_color", "green")
    api.set_sensitive_input_indicator("mode", "single-blink")

    assert shell.sensitive_input == {
        "enabled": True,
        "symbol": "+",
        "idle_color": "#FFFFFF",
        "active_color": "green",
        "mode": "single-blink",
    }


def test_sensitive_input_rejects_unknown_name() -> None:
    with pytest.raises(ConfigError):
        validate_sensitive_input("unknown", True)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("enabled", "true"),
        ("symbol", 7),
        ("idle_color", 7),
        ("active_color", 7),
        ("mode", 7),
    ),
)
def test_sensitive_input_rejects_wrong_type(name: str, value: object) -> None:
    with pytest.raises(ConfigError):
        validate_sensitive_input(name, value)


@pytest.mark.parametrize("symbol", ("", "ab", "界", "e\u0301"))
def test_sensitive_input_rejects_unsafe_symbol_width(symbol: str) -> None:
    with pytest.raises(ConfigError):
        validate_sensitive_input("symbol", symbol)


def test_sensitive_input_rejects_invalid_mode() -> None:
    with pytest.raises(ConfigError):
        validate_sensitive_input("mode", "per-key")


@pytest.mark.parametrize("name", ("idle_color", "active_color"))
def test_sensitive_input_rejects_invalid_color(name: str) -> None:
    with pytest.raises(ConfigError):
        validate_sensitive_input(name, "not-a-color")


def test_pyshell_conforms_to_configurable_shell_protocol() -> None:
    assert isinstance(PyShell(), ConfigurableShell)


def test_sensitive_input_is_inert_for_prompt_output(monkeypatch) -> None:
    monkeypatch.setattr("pysh.shell.shutil.which", lambda _executable: None)

    disabled = PyShell()
    enabled = PyShell()
    enabled.set_sensitive_input_indicator("enabled", True)
    enabled.set_sensitive_input_indicator("symbol", "+")
    enabled.set_sensitive_input_indicator("idle_color", "white")
    enabled.set_sensitive_input_indicator("active_color", "lime")
    enabled.set_sensitive_input_indicator("mode", "single-blink")

    assert enabled._prompt_info_line() == disabled._prompt_info_line()
    assert enabled._prompt() == disabled._prompt()


def test_sensitive_input_is_inert_for_interactive_line_reader(monkeypatch) -> None:
    shell = PyShell()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_read_line(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "line"

    monkeypatch.setattr(shell, "_should_use_raw_editor", lambda: True)
    monkeypatch.setattr(shell.line_reader, "read_line", fake_read_line)

    assert shell._read_interactive_line() == "line"
    before = calls[-1]

    shell.set_sensitive_input_indicator("enabled", True)
    shell.set_sensitive_input_indicator("symbol", "+")
    shell.set_sensitive_input_indicator("idle_color", "#FFFFFF")
    shell.set_sensitive_input_indicator("active_color", "#00FF00")
    shell.set_sensitive_input_indicator("mode", "single-blink")

    assert shell._read_interactive_line() == "line"
    after = calls[-1]

    assert before[0] == after[0]
    assert before[1].keys() == after[1].keys()
    assert isinstance(before[1]["options"], SimpleNamespace)
    assert before[1]["options"] == after[1]["options"]
    for key in before[1].keys() - {"options"}:
        assert before[1][key] == after[1][key]


def test_sensitive_input_store_is_not_read_by_runtime_paths() -> None:
    assert "sensitive_input" not in inspect.getsource(PyShell._read_interactive_line)
    assert "sensitive_input" not in inspect.getsource(PyShell._prompt)
    assert "sensitive_input" not in inspect.getsource(PyShell._prompt_info_line)
    assert "sensitive_input" not in inspect.getsource(PyShell._run_external)
    assert "sensitive_input" not in inspect.getsource(PyShell._run_pipeline)
