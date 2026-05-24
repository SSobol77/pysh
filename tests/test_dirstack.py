# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for pushd / popd / dirs builtins."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.shell import PyShell


@pytest.fixture
def shell_in_tmp(tmp_path: Path):
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield PyShell(), tmp_path
    finally:
        os.chdir(original)


def test_pushd_changes_dir_and_pushes(shell_in_tmp) -> None:
    shell, root = shell_in_tmp
    sub = root / "sub"
    sub.mkdir()
    assert shell.execute(f"pushd {sub}") == 0
    assert Path.cwd() == sub
    assert shell.dir_stack == [root]


def test_pushd_missing_directory_fails(
    shell_in_tmp, capsys: pytest.CaptureFixture[str]
) -> None:
    shell, root = shell_in_tmp
    status = shell.execute(f"pushd {root / 'nope'}")
    assert status == 1
    captured = capsys.readouterr()
    assert "not a directory" in captured.err


def test_pushd_no_argument_fails(
    shell_in_tmp, capsys: pytest.CaptureFixture[str]
) -> None:
    shell, _ = shell_in_tmp
    status = shell.execute("pushd")
    assert status == 2
    captured = capsys.readouterr()
    assert "pushd" in captured.err


def test_popd_returns_to_previous_directory(shell_in_tmp) -> None:
    shell, root = shell_in_tmp
    sub = root / "sub"
    sub.mkdir()
    shell.execute(f"pushd {sub}")
    assert shell.execute("popd") == 0
    assert Path.cwd() == root
    assert shell.dir_stack == []


def test_popd_empty_stack_fails(
    shell_in_tmp, capsys: pytest.CaptureFixture[str]
) -> None:
    shell, _ = shell_in_tmp
    status = shell.execute("popd")
    assert status == 1
    captured = capsys.readouterr()
    assert "empty" in captured.err


def test_dirs_lists_current_and_stack(
    shell_in_tmp, capsys: pytest.CaptureFixture[str]
) -> None:
    shell, root = shell_in_tmp
    sub = root / "sub"
    sub.mkdir()
    shell.execute(f"pushd {sub}")
    capsys.readouterr()  # discard pushd output
    assert shell.execute("dirs") == 0
    captured = capsys.readouterr()
    assert captured.out.strip().split()  # at least one entry
