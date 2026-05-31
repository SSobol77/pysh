# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_rc_interpreter.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the extended rc mini-interpreter (if/for/while)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.rc import WHILE_ITER_LIMIT, evaluate_condition, execute_rc


# --------------------------------------------------------------- conditions
def test_condition_file_exists(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("hi", encoding="utf-8")
    assert evaluate_condition(f"[ -f {target} ]", {}) is True
    assert evaluate_condition(f"[ -f {tmp_path / 'missing'} ]", {}) is False


def test_condition_directory_exists(tmp_path: Path) -> None:
    assert evaluate_condition(f"[ -d {tmp_path} ]", {}) is True
    assert evaluate_condition(f"[ -d {tmp_path / 'absent'} ]", {}) is False


def test_condition_path_exists(tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("", encoding="utf-8")
    assert evaluate_condition(f"[ -e {target} ]", {}) is True


def test_condition_negation(tmp_path: Path) -> None:
    assert evaluate_condition(f"[ ! -f {tmp_path / 'nope'} ]", {}) is True
    target = tmp_path / "y"
    target.write_text("", encoding="utf-8")
    assert evaluate_condition(f"[ ! -f {target} ]", {}) is False


def test_condition_string_equality() -> None:
    assert evaluate_condition('[ "$X" = "$Y" ]', {"X": "a", "Y": "a"}) is True
    assert evaluate_condition('[ "$X" == "$Y" ]', {"X": "a", "Y": "a"}) is True
    assert evaluate_condition('[ "$X" != "$Y" ]', {"X": "a", "Y": "b"}) is True


def test_condition_zero_length() -> None:
    assert evaluate_condition('[ -z "$X" ]', {"X": ""}) is True
    assert evaluate_condition('[ -n "$X" ]', {"X": "ok"}) is True


def test_condition_invalid_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_condition("no brackets", {})


# ------------------------------------------------------------- if/else/fi
def test_if_then_executes_branch(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "if [ -d /tmp ]; then\n"
        "    A=yes\n"
        "fi\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == ["    A=yes"]


def test_if_else_runs_else_branch(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "if [ -d /does-not-exist-xyz ]; then\n"
        "    taken=true\n"
        "else\n"
        "    fallback=true\n"
        "fi\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == ["    fallback=true"]


def test_if_compat_else_with_colon(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "if [ -z foo ]; then\n"
        "    skipped=true\n"
        "else:\n"
        "    chosen=true\n"
        "fi\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == ["    chosen=true"]


# ----------------------------------------------------------------- for/do/done
def test_for_iterates_items(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "for item in a b c; do\n"
        "    echo $item\n"
        "done\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == ["    echo $item"] * 3


# --------------------------------------------------------------- while/do/done
def test_while_loop_runs_until_condition_false(tmp_path: Path) -> None:
    # The body cannot mutate the condition's state without going through
    # the executor; we test the safety guard separately. Here we use a
    # condition that is already false.
    rc = tmp_path / "rc"
    rc.write_text(
        'while [ -f /definitely/not/a/path ]; do\n'
        "    never=true\n"
        "done\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == []


def test_while_safety_limit_prevents_infinite_loop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        'while [ -d /tmp ]; do\n'
        "    spin=true\n"
        "done\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    captured = capsys.readouterr()
    assert "while loop exceeded" in captured.err
    assert len(seen) == WHILE_ITER_LIMIT


# --------------------------------------------------------------- nesting
def test_nested_if_inside_for(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "for x in a b; do\n"
        "    if [ -d /tmp ]; then\n"
        "        echo $x\n"
        "    fi\n"
        "done\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    execute_rc(rc, lambda line: seen.append(line) or 0)
    assert seen == ["        echo $x", "        echo $x"]
