# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_system_profile.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the Debian/system profile helpers."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from pysh.shell import PyShell
from pysh.system_profile import (
    REDACTED_PLACEHOLDER,
    apt_check,
    apt_search,
    env_audit,
    path_audit,
    sys_info,
    which_all,
)


def test_sys_info_prints_expected_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sys_info() == 0
    out = capsys.readouterr().out
    for field in (
        "platform=",
        "python=",
        "executable=",
        "cwd=",
        "user=",
        "home=",
        "shell=",
        "path_entries=",
    ):
        assert field in out


def test_env_audit_redacts_secret_keys() -> None:
    env = {
        "PATH": "/usr/bin",
        "HOME": "/home/user",
        "API_KEY": "supersecret",
        "MY_TOKEN": "abcd",
        "OAUTH_PASSWORD": "topsecret",
        "GOOGLE_CREDENTIAL_FILE": "/opt/creds",
        "AUTH_SOMETHING": "x",
    }
    buf = io.StringIO()
    assert env_audit(env=env, stream=buf) == 0
    text = buf.getvalue()
    assert "API_KEY=<redacted>" in text
    assert "MY_TOKEN=<redacted>" in text
    assert "OAUTH_PASSWORD=<redacted>" in text
    assert "GOOGLE_CREDENTIAL_FILE=<redacted>" in text
    assert "AUTH_SOMETHING=<redacted>" in text
    assert REDACTED_PLACEHOLDER in text
    assert "supersecret" not in text


def test_env_audit_emits_safe_whitelist() -> None:
    env = {"PATH": "/usr/bin", "HOME": "/home/u"}
    buf = io.StringIO()
    assert env_audit(env=env, stream=buf) == 0
    text = buf.getvalue()
    assert "PATH=/usr/bin" in text
    assert "HOME=/home/u" in text
    assert "TERM=<unset>" in text


def test_path_audit_detects_missing_and_duplicates(tmp_path: Path) -> None:
    real = tmp_path / "bin"
    real.mkdir()
    fake = tmp_path / "missing"
    path = os.pathsep.join([str(real), str(fake), str(real)])
    env = {"PATH": path}
    buf = io.StringIO()
    rc = path_audit(env=env, stream=buf)
    text = buf.getvalue()
    assert f"ok\t{real}" in text
    assert f"missing\t{fake}" in text
    assert f"duplicate\t{real}" in text
    assert rc == 1


def test_path_audit_ok_for_clean_path(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    env = {"PATH": os.pathsep.join([str(a), str(b)])}
    buf = io.StringIO()
    assert path_audit(env=env, stream=buf) == 0


def test_which_all_finds_multiple_matches(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    name = "demo-cmd"
    for d in (a, b):
        exe = d / name
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(0o755)
    env = {"PATH": os.pathsep.join([str(a), str(b)])}
    buf = io.StringIO()
    rc = which_all(name, env=env, stream=buf)
    text = buf.getvalue()
    assert rc == 0
    assert str(a / name) in text
    assert str(b / name) in text


def test_which_all_returns_one_when_missing(tmp_path: Path) -> None:
    env = {"PATH": str(tmp_path)}
    rc = which_all("does-not-exist", env=env, stream=io.StringIO())
    assert rc == 1


def test_which_all_missing_argument_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert which_all("") == 2
    err = capsys.readouterr().err
    assert "command argument required" in err


def test_apt_check_returns_127_when_apt_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = apt_check(apt_resolver=lambda _name: None)
    assert rc == 127
    assert "apt not found" in capsys.readouterr().err


def test_apt_check_runs_list_upgradable_without_sudo() -> None:
    captured: list[list[str]] = []

    def fake_runner(argv: list[str]) -> int:
        captured.append(list(argv))
        return 0

    rc = apt_check(apt_resolver=lambda _name: "/usr/bin/apt", runner=fake_runner)
    assert rc == 0
    assert captured == [["/usr/bin/apt", "list", "--upgradable"]]
    assert all("sudo" not in arg for arg in captured[0])


def test_apt_search_runs_safely_without_shell_true() -> None:
    captured: list[list[str]] = []

    def fake_runner(argv: list[str]) -> int:
        captured.append(list(argv))
        return 0

    rc = apt_search(
        "vim",
        apt_resolver=lambda _name: "/usr/bin/apt",
        runner=fake_runner,
    )
    assert rc == 0
    assert captured == [["/usr/bin/apt", "search", "vim"]]
    assert all("sudo" not in arg for arg in captured[0])


def test_apt_search_missing_query_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert apt_search("") == 2
    assert "query argument required" in capsys.readouterr().err


def test_apt_search_returns_127_when_apt_missing() -> None:
    rc = apt_search("vim", apt_resolver=lambda _name: None)
    assert rc == 127


# ----------------------------------------------------------- builtin integration

def test_shell_builtin_sys_info(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("sys_info") == 0
    out = capsys.readouterr().out
    assert "platform=" in out


def test_shell_builtin_env_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("env_audit") == 0
    out = capsys.readouterr().out
    assert "total=" in out


def test_shell_builtin_path_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    rc = shell.execute("path_audit")
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "\t" in out


def test_shell_builtin_which_all_missing_arg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("which_all") == 2
    err = capsys.readouterr().err
    assert "usage" in err


def test_shell_builtin_which_all_found(tmp_path: Path) -> None:
    name = "demo-bin"
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    sys.stdout.flush()
    shell = PyShell()
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp_path)
    try:
        assert shell.execute(f"which_all {name}") == 0
    finally:
        os.environ["PATH"] = old_path


def test_shell_builtin_apt_check_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("pysh.system_profile.shutil.which", lambda _n: None)
    shell = PyShell()
    assert shell.execute("apt_check") == 127
    assert "apt not found" in capsys.readouterr().err


def test_shell_builtin_apt_search_missing_arg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("apt_search") == 2
    assert "usage" in capsys.readouterr().err
