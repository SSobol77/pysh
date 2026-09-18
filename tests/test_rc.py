# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_rc.py
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


def test_pyshrc_is_canonical_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pysh.config import rc as rc_module

    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("SHOULD_NOT_RUN=1\n", encoding="utf-8")
    pyshrc = tmp_path / ".pyshrc"
    calls: list[str] = []

    def record(line: str) -> int:
        calls.append(line)
        return 0

    monkeypatch.setattr(rc_module, "RC_PATH", pyshrc)
    assert rc_module.load_default_rc(record) == 0
    assert calls == []

    pyshrc.write_text("PYSH_CANONICAL=1\n", encoding="utf-8")
    assert rc_module.load_default_rc(record) == 0
    assert calls == ["PYSH_CANONICAL=1"]


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


def _make_virtualenv(root: Path) -> Path:
    """Create the minimum validated virtualenv layout for activation tests."""
    bindir = root / "bin"
    bindir.mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    python = bindir / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    activate = bindir / "activate"
    activate.write_text("echo FOREIGN_ACTIVATION_MUST_NOT_RUN\n", encoding="utf-8")
    return activate


def test_source_native_virtualenv_activation_is_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    activate = _make_virtualenv(tmp_path / "venv")
    monkeypatch.setenv("PATH", "/base/bin:/usr/bin")
    monkeypatch.setenv("PYTHONHOME", "/old/pythonhome")
    monkeypatch.setenv("VIRTUAL_ENV", "/old/venv")
    before = {name: os.environ.get(name) for name in ("PATH", "PYTHONHOME", "VIRTUAL_ENV")}
    shell = PyShell()

    assert shell.execute(f"source {activate}") == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert os.environ["VIRTUAL_ENV"] == str(tmp_path / "venv")
    assert shell._prompt_virtualenv() == "venv"
    assert os.environ["PATH"].split(os.pathsep).count(str(tmp_path / "venv" / "bin")) == 1
    assert "PYTHONHOME" not in os.environ
    assert shell.execute("deactivate") == 0
    assert {name: os.environ.get(name) for name in before} == before


def test_virtualenv_switch_restores_original_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _make_virtualenv(tmp_path / "first")
    second = _make_virtualenv(tmp_path / "second")
    monkeypatch.setenv("PATH", "/original")
    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    shell = PyShell()

    assert shell.execute(f". {first}") == 0
    assert shell.execute(f"source {second}") == 0
    assert os.environ["VIRTUAL_ENV"] == str(tmp_path / "second")
    assert os.environ["PATH"] == f"{tmp_path / 'second' / 'bin'}:/original"
    assert shell.execute("deactivate") == 0
    assert os.environ["PATH"] == "/original"
    assert "VIRTUAL_ENV" not in os.environ
    assert "PYTHONHOME" not in os.environ


def test_invalid_activation_target_does_not_mutate_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "invalid" / "bin" / "activate"
    target.parent.mkdir(parents=True)
    target.write_text("export VIRTUAL_ENV=/corrupted\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "/safe")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    before = dict(os.environ)

    status = PyShell().execute(f"source {target}")

    assert status == 1
    assert dict(os.environ) == before
