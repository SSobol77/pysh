# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for configurable terminal cursor color."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.config.api import (
    DEFAULT_CURSOR_OPTIONS,
    ConfigError,
    ShellConfigAPI,
    load_python_config,
    validate_cursor_color,
    validate_cursor_color_enabled,
)
from pysh.core.shell import PyShell, _osc_reset_cursor_color, _osc_set_cursor_color


class FakeStdout:
    """Small stdout replacement for OSC emission tests."""

    def __init__(self, *, tty: bool) -> None:
        self.tty = tty
        self.writes: list[str] = []
        self.flushes = 0

    def isatty(self) -> bool:
        return self.tty

    def write(self, text: str) -> int:
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        self.flushes += 1


def test_cursor_defaults_exact() -> None:
    assert DEFAULT_CURSOR_OPTIONS == {
        "enabled": False,
        "color": "orange",
    }
    assert PyShell().cursor_options == DEFAULT_CURSOR_OPTIONS


def test_cursor_color_enabled_accepts_bool_and_rejects_wrong_type() -> None:
    shell = PyShell()
    api = ShellConfigAPI(shell)

    api.set_cursor_color_enabled(True)
    assert shell.cursor_options["enabled"] is True
    api.set_cursor_color_enabled(False)
    assert shell.cursor_options["enabled"] is False

    with pytest.raises(ConfigError):
        api.set_cursor_color_enabled("yes")  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        validate_cursor_color_enabled(1)


def test_cursor_color_accepts_named_and_hex_and_rejects_invalid() -> None:
    shell = PyShell()
    api = ShellConfigAPI(shell)

    api.set_cursor_color("orange")
    assert shell.cursor_options["color"] == "#FFA500"
    api.set_cursor_color("#FF9900")
    assert shell.cursor_options["color"] == "#FF9900"

    with pytest.raises(ConfigError):
        api.set_cursor_color("not-a-color")
    with pytest.raises(ConfigError):
        validate_cursor_color(42)


def test_cursor_osc_sequences_are_exact() -> None:
    assert _osc_set_cursor_color("#FF9900") == "\x1b]12;#FF9900\x07"
    assert _osc_reset_cursor_color() == "\x1b]112\x07"


def test_disabled_cursor_color_emits_no_osc(monkeypatch) -> None:
    stream = FakeStdout(tty=True)
    shell = PyShell()
    monkeypatch.setattr("pysh.core.shell.sys.stdout", stream)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)

    shell._apply_cursor_color()

    assert stream.writes == []
    assert shell._cursor_color_applied is False


def test_no_color_dumb_and_non_tty_emit_no_osc(monkeypatch) -> None:
    shell = PyShell()
    shell.set_cursor_color_enabled(True)
    shell.set_cursor_color("#FF9900")

    stream = FakeStdout(tty=True)
    monkeypatch.setattr("pysh.core.shell.sys.stdout", stream)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("NO_COLOR", "1")
    shell._apply_cursor_color()
    assert stream.writes == []

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    shell._apply_cursor_color()
    assert stream.writes == []

    monkeypatch.setenv("TERM", "xterm-256color")
    stream.tty = False
    shell._apply_cursor_color()
    assert stream.writes == []


def test_enabled_tty_gate_emits_set_osc_once_and_reset(monkeypatch) -> None:
    stream = FakeStdout(tty=True)
    shell = PyShell()
    shell.set_cursor_color_enabled(True)
    shell.set_cursor_color("#FF9900")
    monkeypatch.setattr("pysh.core.shell.sys.stdout", stream)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)

    shell._apply_cursor_color()
    shell._apply_cursor_color()
    assert stream.writes == ["\x1b]12;#FF9900\x07"]
    assert shell._cursor_color_applied is True

    shell._reset_cursor_color()
    assert stream.writes == ["\x1b]12;#FF9900\x07", "\x1b]112\x07"]
    assert shell._cursor_color_applied is False

    shell._reset_cursor_color()
    assert stream.writes == ["\x1b]12;#FF9900\x07", "\x1b]112\x07"]


def test_reset_does_not_emit_if_never_applied(monkeypatch) -> None:
    stream = FakeStdout(tty=True)
    shell = PyShell()
    monkeypatch.setattr("pysh.core.shell.sys.stdout", stream)

    shell._reset_cursor_color()

    assert stream.writes == []


def test_pyshrc_can_configure_cursor_color(tmp_path: Path) -> None:
    target = tmp_path / ".pyshrc.py"
    target.write_text(
        "def configure(shell):\n"
        "    shell.set_cursor_color_enabled(True)\n"
        "    shell.set_cursor_color('#FF9900')\n",
        encoding="utf-8",
    )
    shell = PyShell()

    assert load_python_config(shell, path=target) == 0

    assert shell.cursor_options == {
        "enabled": True,
        "color": "#FF9900",
    }


def test_pyshrc_can_enable_secure_indicator(tmp_path: Path) -> None:
    target = tmp_path / ".pyshrc.py"
    target.write_text(
        "def configure(shell):\n"
        "    shell.set_sensitive_input_indicator('enabled', True)\n",
        encoding="utf-8",
    )
    shell = PyShell()

    assert load_python_config(shell, path=target) == 0

    assert shell.sensitive_input["enabled"] is True
