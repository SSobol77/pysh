# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_zsh_bridge.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the optional zsh compatibility bridge."""
from __future__ import annotations

import shutil

import pytest

from pysh.compat.zsh_bridge import ZSH_MISSING_STATUS, ZshBridge


def test_zsh_bridge_missing_zsh_is_deterministic() -> None:
    bridge = ZshBridge(executable="/definitely/not/zsh")
    result = bridge.execute("echo should-not-run")
    assert bridge.available is False
    assert result.command == "echo should-not-run"
    assert result.returncode == ZSH_MISSING_STATUS
    assert result.stdout == ""
    assert "command not found" in result.stderr
    assert result.timed_out is False


def test_zsh_bridge_executes_simple_command_when_zsh_available() -> None:
    if shutil.which("zsh") is None:
        pytest.skip("zsh is not installed")
    bridge = ZshBridge()
    result = bridge.execute("print -r -- pysh-zsh-ok")
    assert result.returncode == 0
    assert result.stdout == "pysh-zsh-ok\n"
    assert result.stderr == ""
    assert result.timed_out is False
