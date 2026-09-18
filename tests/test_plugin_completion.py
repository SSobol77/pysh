# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_completion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Plugin API completion integration."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pysh.core.shell import PyShell


def test_plugin_command_is_completed_at_command_position() -> None:
    shell = PyShell()
    shell.plugin_manager.register_command("plug", "hello", lambda argv: 0)

    result = shell.completer.raw_completion("he", 2)

    assert "hello" in result.candidates


def test_plugin_command_completion_has_no_substring_fallback() -> None:
    shell = PyShell()
    shell.plugin_manager.register_command("plug", "hello", lambda argv: 0)
    assert "hello" not in shell.completer.raw_completion("ell", 3).candidates


def test_readline_and_raw_completion_return_same_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.plugin_manager.register_command("plug", "hello", lambda argv: 0)
    raw = shell.completer.raw_completion("he", 2).candidates
    fake_readline = SimpleNamespace(
        get_line_buffer=lambda: "he",
        get_endidx=lambda: 2,
    )
    monkeypatch.setitem(sys.modules, "readline", fake_readline)
    readline_matches: list[str] = []
    state = 0
    while (candidate := shell.completer.complete("he", state)) is not None:
        readline_matches.append(candidate)
        state += 1
    assert tuple(readline_matches) == raw


def test_plugin_completer_runs_only_for_matching_command() -> None:
    shell = PyShell()
    shell.plugin_manager.register_completer("plug", "hello", lambda args, cursor: ["world"])

    assert "world" in shell.completer.raw_completion("hello w", 7).candidates
    assert "world" not in shell.completer.raw_completion("other w", 7).candidates


def test_plugin_completer_invalid_result_fails_closed() -> None:
    shell = PyShell()
    shell.plugin_manager.register_completer("plug", "hello", lambda args, cursor: [1])  # type: ignore[list-item]

    assert 1 not in shell.completer.raw_completion("hello ", 6).candidates
