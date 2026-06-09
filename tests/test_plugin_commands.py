# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_commands.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Plugin API command dispatch."""
from __future__ import annotations

from pysh.core.shell import PyShell


def test_plugin_command_executes_and_receives_argv(capsys) -> None:
    shell = PyShell()
    seen: list[list[str]] = []

    def handler(argv: list[str]) -> int:
        seen.append(argv)
        print("ok")
        return 7

    shell.plugin_manager.register_command("plug", "hello", handler)

    assert shell.execute("hello a b") == 7
    assert seen == [["a", "b"]]
    assert capsys.readouterr().out.strip() == "ok"


def test_plugin_command_non_int_and_exception_return_error() -> None:
    shell = PyShell()
    shell.plugin_manager.register_command("plug", "bad", lambda argv: "no")  # type: ignore[arg-type]
    shell.plugin_manager.register_command(
        "plug",
        "boom",
        lambda argv: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert shell.execute("bad") == 1
    assert shell.execute("boom") == 1


def test_core_builtin_wins_over_plugin_attempt() -> None:
    shell = PyShell()
    try:
        shell.plugin_manager.register_command("plug", "cd", lambda argv: 99)
    except Exception:
        pass

    assert shell.execute("cd .") == 0
