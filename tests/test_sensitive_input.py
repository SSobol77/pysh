# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_sensitive_input.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for sensitive-input indicator configuration validation.

These tests assert validation behaviour and that the option store does not
affect ordinary shell runtime paths. The only runtime consumer is the explicit
``secure <cmd>`` PTY wrapper, covered separately in secure runner tests.
"""
from __future__ import annotations

import inspect

import pytest

from pysh.config.api import (
    DEFAULT_SENSITIVE_INPUT,
    ConfigError,
    ConfigurableShell,
    ShellConfigAPI,
    validate_sensitive_input,
)
from pysh.core.shell import PyShell


class FakeShell:
    """Minimal ConfigurableShell capturing sensitive-input writes."""

    def __init__(self) -> None:
        self.sensitive_input: dict[str, object] = dict(DEFAULT_SENSITIVE_INPUT)

    def register_alias(self, name: str, value: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_environment(self, name: str, value: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_prompt_option(self, name: str, value: object) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_editor_option(self, name: str, value: object) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_prompt_color(self, segment: str, color: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_prompt_color_mode(self, name: str, value: object) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_sensitive_input_indicator(self, name: str, value: object) -> None:
        validate_sensitive_input(name, value)
        self.sensitive_input[name] = value


# ------------------------------------------------------------------- defaults
def test_defaults_exact() -> None:
    assert DEFAULT_SENSITIVE_INPUT == {
        "enabled": False,
        "symbol": "*",
        "idle_color": "white",
        "active_color": "lime",
        "mode": "ring",
        "slots": 5,
    }


def test_default_is_disabled() -> None:
    assert DEFAULT_SENSITIVE_INPUT["enabled"] is False


# ----------------------------------------------------------------- valid sets
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("enabled", True),
        ("enabled", False),
        ("symbol", "*"),
        ("symbol", "\u25cf"),  # ● BLACK CIRCLE, width 1
        ("idle_color", "white"),
        ("active_color", "lime"),
        ("idle_color", "#FF8800"),
        ("mode", "ring"),
        ("mode", "single-blink"),
        ("slots", 3),
        ("slots", 5),
        ("slots", 9),
    ],
)
def test_api_accepts_valid(name: str, value: object) -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).set_sensitive_input_indicator(name, value)
    assert shell.sensitive_input[name] == value


# --------------------------------------------------------------- invalid sets
def test_unknown_option_rejected() -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator("nope", True)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("enabled", "yes"),   # str, not bool
        ("enabled", 1),       # int is not bool
        ("symbol", 42),       # not str
        ("idle_color", 0),    # not str
        ("mode", True),       # not str
        ("slots", "5"),       # not int
        ("slots", 5.0),       # not int
    ],
)
def test_wrong_type_rejected(name: str, value: object) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator(name, value)


@pytest.mark.parametrize(
    "symbol",
    [
        "",            # empty: zero columns
        "**",          # two glyphs
        "ab",          # two glyphs
        "\u65e5",      # 日 CJK, width 2
        "\U0001f40d",  # 🐍 emoji, width 2
    ],
)
def test_symbol_must_be_single_display_column(symbol: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator("symbol", symbol)


@pytest.mark.parametrize("color_opt", ["idle_color", "active_color"])
@pytest.mark.parametrize("bad", ["not-a-color", "#GGGGGG", "#FFF", ""])
def test_invalid_color_rejected(color_opt: str, bad: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator(color_opt, bad)


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator("mode", "double-blink")


@pytest.mark.parametrize("slots", [2, 10, 0, -1, True])
def test_invalid_slots_rejected(slots: object) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).set_sensitive_input_indicator("slots", slots)


def test_validate_function_directly() -> None:
    validate_sensitive_input("symbol", "*")  # no raise
    with pytest.raises(ConfigError):
        validate_sensitive_input("symbol", "")


# ------------------------------------------------------- PyShell integration
def test_pyshell_conforms_to_protocol() -> None:
    assert isinstance(PyShell(), ConfigurableShell)


def test_pyshell_stores_and_defaults() -> None:
    shell = PyShell()
    assert shell.sensitive_input == DEFAULT_SENSITIVE_INPUT
    shell.set_sensitive_input_indicator("enabled", True)
    shell.set_sensitive_input_indicator("symbol", "\u25cf")
    assert shell.sensitive_input["enabled"] is True
    assert shell.sensitive_input["symbol"] == "\u25cf"


def test_pyshell_rejects_invalid() -> None:
    with pytest.raises(ValueError):  # ConfigError is a ValueError
        PyShell().set_sensitive_input_indicator("symbol", "ab")


# --------------------------------------------- ordinary runtime non-interference
def _enable_all(shell: PyShell) -> None:
    shell.set_sensitive_input_indicator("enabled", True)
    shell.set_sensitive_input_indicator("symbol", "\u25cf")
    shell.set_sensitive_input_indicator("idle_color", "white")
    shell.set_sensitive_input_indicator("active_color", "lime")
    shell.set_sensitive_input_indicator("mode", "ring")
    shell.set_sensitive_input_indicator("slots", 5)


def test_prompt_identical_enabled_vs_disabled(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")

    def _deterministic(shell: PyShell) -> None:
        # Disable every segment whose value comes from a bounded subprocess
        # (uv/ruff/rust/node/npm) or from external repo/network state (git),
        # so the comparison isolates the sensitive-input option and never races
        # on a 0.2s tool-version timeout.
        for option in (
            "show_uv_version",
            "show_ruff_version",
            "show_rust_version",
            "show_node_version",
            "show_npm_version",
            "show_git_branch",
            "show_git_dirty",
        ):
            shell.set_prompt_option(option, False)

    disabled = PyShell()
    _deterministic(disabled)
    enabled = PyShell()
    _deterministic(enabled)
    _enable_all(enabled)
    # The secure-only option must not influence prompt rendering at all.
    assert enabled._prompt() == disabled._prompt()
    assert enabled._prompt_info_line() == disabled._prompt_info_line()
    assert enabled._prompt_body(enabled.prompt_options) == disabled._prompt_body(
        disabled.prompt_options
    )


def test_editor_strategy_unaffected(monkeypatch) -> None:
    # Enabling the indicator must not change input-strategy selection.
    shell = PyShell()
    before = shell._should_use_raw_editor()
    _enable_all(shell)
    assert shell._should_use_raw_editor() == before


def test_no_runtime_path_reads_sensitive_input() -> None:
    readers = []
    for name, member in inspect.getmembers(PyShell, inspect.isfunction):
        if name == "__init__" or name == "set_sensitive_input_indicator":
            continue
        if "sensitive_input" in inspect.getsource(member):
            readers.append(name)

    assert readers == ["_builtin_secure"]
