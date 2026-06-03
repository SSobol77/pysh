# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the ``~/.pyshrc`` loader and the ``source`` builtin."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pysh.config.rc import execute_rc, iter_rc_lines, read_rc_file
from pysh.core.shell import PyShell


def test_iter_rc_lines_strips_comments_and_blanks() -> None:
    lines = iter_rc_lines(
        [
            "",
            "  # comment",
            "FOO=1",
            "    ",
            "BAR=2 # not a stripped trailing comment",
            "# another",
        ]
    )
    assert lines == ["FOO=1", "BAR=2 # not a stripped trailing comment"]


def test_read_rc_file_missing(tmp_path: Path) -> None:
    assert read_rc_file(tmp_path / "missing") == []


def test_read_rc_file_existing(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text("# header\nA=1\n\nB=2\n")
    assert read_rc_file(rc) == ["A=1", "B=2"]


def test_source_reads_rc_file_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_RC_VAR", raising=False)
    rc = tmp_path / "myrc"
    rc.write_text(
        "# example rc\n"
        "MYVAR=42\n"
        "export PYSH_RC_VAR=ok\n"
        'alias greet="echo hello"\n'
    )
    shell = PyShell()
    status = shell.execute(f"source {rc}")
    assert status == 0
    assert shell.local_vars["MYVAR"] == "42"
    assert os.environ["PYSH_RC_VAR"] == "ok"
    assert shell.aliases["greet"] == "echo hello"


def test_execute_rc_continues_on_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = tmp_path / "rc"
    rc.write_text(
        "VALID=ok\n"
        "definitely_not_a_real_command_xyz\n"
        "AFTER=also_ok\n"
    )
    shell = PyShell()
    execute_rc(rc, shell.execute, quiet_missing=False)
    assert shell.local_vars["VALID"] == "ok"
    assert shell.local_vars["AFTER"] == "also_ok"


def test_source_missing_file_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shell = PyShell()
    status = shell.execute(f"source {tmp_path}/does_not_exist")
    assert status == 0
    captured = capsys.readouterr()
    assert "no such file" in captured.err
