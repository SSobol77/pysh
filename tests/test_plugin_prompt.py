# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_prompt.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Plugin API prompt segment integration."""
from __future__ import annotations

from pysh.core.shell import PyShell


def test_plugin_prompt_segment_renders_in_single_prompt() -> None:
    shell = PyShell()
    shell.set_prompt_option("prompt_layout", "single")
    shell.plugin_manager.register_prompt_segment("plug", "seg", lambda: "SEG", "end")

    assert "SEG" in shell._prompt()


def test_plugin_prompt_segment_renders_in_two_line_prompt() -> None:
    shell = PyShell()
    shell.set_prompt_option("prompt_layout", "two_line")
    shell.plugin_manager.register_prompt_segment("plug", "seg", lambda: "SEG", "after_git")

    assert "SEG" in shell._prompt_info_line()


def test_plugin_prompt_segment_failure_is_skipped() -> None:
    shell = PyShell()
    shell.plugin_manager.register_prompt_segment(
        "plug",
        "seg",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        "end",
    )

    assert "boom" not in shell._prompt_body(shell.prompt_options)
