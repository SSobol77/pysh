# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_env_assignment.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for leading temporary environment assignment support.

Covers parse_leading_env_assignments() and the shell's execution path for
commands like ``FOO=bar env`` and ``SHELL="..." mc -u``.
"""
from __future__ import annotations

import os
import unittest.mock as mock

import pytest

from pysh.core.shell import PyShell
from pysh.parsing.parser import parse_leading_env_assignments

# ---------------------------------------------------------------- parser unit tests


def test_single_assignment_extracted() -> None:
    env, cmd = parse_leading_env_assignments(["FOO=bar", "env"])
    assert env == {"FOO": "bar"}
    assert cmd == ["env"]


def test_multiple_assignments_extracted() -> None:
    env, cmd = parse_leading_env_assignments(["FOO=bar", "BAR=baz", "cmd", "arg"])
    assert env == {"FOO": "bar", "BAR": "baz"}
    assert cmd == ["cmd", "arg"]


def test_no_assignment_returns_empty_dict() -> None:
    env, cmd = parse_leading_env_assignments(["echo", "FOO=bar"])
    assert env == {}
    assert cmd == ["echo", "FOO=bar"]


def test_all_assignments_no_command() -> None:
    env, cmd = parse_leading_env_assignments(["FOO=bar", "BAR=baz"])
    assert env == {"FOO": "bar", "BAR": "baz"}
    assert cmd == []


def test_empty_value() -> None:
    env, cmd = parse_leading_env_assignments(["FOO=", "env"])
    assert env == {"FOO": ""}
    assert cmd == ["env"]


def test_value_with_spaces_already_unquoted() -> None:
    # shlex.split('BAR="hello world"') → ['BAR=hello world'] (quotes stripped)
    env, cmd = parse_leading_env_assignments(["BAR=hello world", "cmd"])
    assert env == {"BAR": "hello world"}
    assert cmd == ["cmd"]


def test_invalid_name_digit_prefix_not_assignment() -> None:
    env, cmd = parse_leading_env_assignments(["1FOO=bar", "cmd"])
    assert env == {}
    assert cmd == ["1FOO=bar", "cmd"]


def test_empty_token_list() -> None:
    env, cmd = parse_leading_env_assignments([])
    assert env == {}
    assert cmd == []


def test_assignment_stops_at_first_non_assignment() -> None:
    env, cmd = parse_leading_env_assignments(["A=1", "B=2", "echo", "A=3"])
    assert env == {"A": "1", "B": "2"}
    assert cmd == ["echo", "A=3"]


# ---------------------------------------------------------------- shell integration


@pytest.fixture
def shell() -> PyShell:
    return PyShell()


def _make_mock_popen(returncode: int = 0) -> tuple[mock.MagicMock, mock.MagicMock]:
    """Return (mock_popen_class, mock_process_instance)."""
    mock_proc = mock.MagicMock()
    mock_proc.wait.return_value = returncode
    mock_proc.stdout = None
    mock_popen = mock.MagicMock(return_value=mock_proc)
    return mock_popen, mock_proc


def test_foo_bar_env_receives_foo_in_child_env(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FOO=bar env must pass FOO=bar to the child process environment."""
    monkeypatch.delenv("PYSH_TEMP_TEST_FOO", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        status = shell.execute("PYSH_TEMP_TEST_FOO=sentinel env")
    assert status == 0
    call_kwargs = mock_popen.call_args
    child_env = call_kwargs[1].get("env") or call_kwargs.kwargs.get("env")
    assert child_env is not None
    assert child_env["PYSH_TEMP_TEST_FOO"] == "sentinel"


def test_temp_env_does_not_mutate_parent_environ(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Temporary assignment must not leak into os.environ after the command."""
    monkeypatch.delenv("PYSH_TEMP_LEAK_TEST", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        shell.execute("PYSH_TEMP_LEAK_TEST=leaked env")
    assert "PYSH_TEMP_LEAK_TEST" not in os.environ


def test_multiple_assignments_passed_to_child(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_T1", raising=False)
    monkeypatch.delenv("PYSH_T2", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        shell.execute("PYSH_T1=a PYSH_T2=b env")
    child_env = mock_popen.call_args[1]["env"]
    assert child_env["PYSH_T1"] == "a"
    assert child_env["PYSH_T2"] == "b"


def test_quoted_assignment_value(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quoted assignment values must be unquoted before passing to child."""
    monkeypatch.delenv("PYSH_T_QUOTED", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        shell.execute('PYSH_T_QUOTED="hello world" env')
    child_env = mock_popen.call_args[1]["env"]
    assert child_env["PYSH_T_QUOTED"] == "hello world"


def test_empty_assignment_value(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYSH_T_EMPTY", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        shell.execute("PYSH_T_EMPTY= env")
    child_env = mock_popen.call_args[1]["env"]
    assert child_env["PYSH_T_EMPTY"] == ""


def test_command_substitution_in_assignment_value(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Command substitution inside the assignment value must be expanded.

    We stub the substitution runner so no real subprocess is spawned for the
    expansion, then check that the expanded value reaches the child env.
    """
    monkeypatch.delenv("PYSH_T_SUBST", raising=False)
    mock_popen, _ = _make_mock_popen()

    def fake_runner(cmd: str, timeout: float) -> str:
        del timeout
        return "hello" if "echo" in cmd else ""

    # expand_command_substitution is imported by name in shell.py, so we patch
    # the bound name in that module to avoid subprocess.run / Popen conflicts.
    with (
        mock.patch(
            "pysh.core.shell.expand_command_substitution",
            side_effect=lambda text, **_kw: text.replace("$(echo hello)", "hello"),
        ),
        mock.patch("subprocess.Popen", mock_popen),
    ):
        shell.execute('PYSH_T_SUBST="$(echo hello)" env')

    child_env = mock_popen.call_args[1]["env"]
    assert child_env["PYSH_T_SUBST"] == "hello"


def test_invalid_token_not_treated_as_assignment(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token starting with a digit is not an env assignment."""
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        # 1FOO=bar is not a valid assignment name; it becomes the command argv[0].
        shell.execute("1FOO=bar env")
    # Popen should be called with argv[0]=="1FOO=bar" and no custom env.
    call_argv = mock_popen.call_args[0][0]
    assert call_argv[0] == "1FOO=bar"
    child_env = mock_popen.call_args[1].get("env")
    assert child_env is None


def test_echo_foo_bar_preserves_as_argument(shell: PyShell) -> None:
    """FOO=bar appearing after the command name is a normal argument, not an assignment."""
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        status = shell.execute("echo FOO=bar")
    assert status == 0
    call_argv = mock_popen.call_args[0][0]
    # "echo" is not aliased; the argument must arrive verbatim.
    assert call_argv[-1] == "FOO=bar"
    # No env override: parent env is used (env kwarg is None).
    assert mock_popen.call_args[1].get("env") is None


def test_all_assignments_no_command_updates_local_vars(shell: PyShell) -> None:
    """NAME=val OTHER=val (no command) updates local_vars, not os.environ."""
    shell.execute("PYSH_MULTI_A=x PYSH_MULTI_B=y")
    assert shell.local_vars.get("PYSH_MULTI_A") == "x"
    assert shell.local_vars.get("PYSH_MULTI_B") == "y"
    assert "PYSH_MULTI_A" not in os.environ
    assert "PYSH_MULTI_B" not in os.environ


# ---------------------------------------------------------------- semicolon with env assignment


def test_semicolon_env_assignment_then_command(
    shell: PyShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """export FOO=bar; echo $FOO must execute two commands and expand $FOO."""
    monkeypatch.delenv("PYSH_SEMI_T", raising=False)
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        status = shell.execute("export PYSH_SEMI_T=hello; echo $PYSH_SEMI_T")
    assert status == 0
    # The echo command receives the expanded value of $PYSH_SEMI_T.
    call_argv = mock_popen.call_args[0][0]
    assert "hello" in call_argv


def test_semicolon_inside_quotes_is_literal(shell: PyShell) -> None:
    """A semicolon inside quotes is literal text, not a command separator."""
    mock_popen, _ = _make_mock_popen()
    with mock.patch("subprocess.Popen", mock_popen):
        status = shell.execute('echo "a;b"')
    assert status == 0
    # echo must receive a;b as a single argument.
    call_argv = mock_popen.call_args[0][0]
    assert "a;b" in call_argv
