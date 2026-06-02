# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_command_plan.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the command planning foundation."""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from pysh.core.shell import PyShell
from pysh.diagnostics.command_plan import classify, plan


def _classify(line: str) -> dict[str, str]:
    result = classify(line, builtins=PyShell.BUILTINS)
    return {
        "original": result.original,
        "kind": result.kind,
        "execution": result.execution,
        "risk": result.risk,
        "reason": result.reason,
    }


def test_classify_builtin_cd() -> None:
    res = _classify("cd /tmp")
    assert res["kind"] == "builtin"
    assert res["execution"] == "native"
    assert res["risk"] == "low"


def test_classify_builtin_alias() -> None:
    res = _classify("alias ll='ls -la'")
    assert res["kind"] == "builtin"
    assert res["execution"] == "native"


def test_classify_py_one_liner() -> None:
    res = _classify('py print("x")')
    assert res["kind"] == "python"
    assert res["execution"] == "python-runtime"
    assert res["risk"] == "low"


def test_classify_py_block_opener() -> None:
    res = _classify("py {")
    assert res["kind"] == "python"
    assert res["execution"] == "python-runtime"


def test_classify_external_command() -> None:
    res = _classify("ls -la")
    assert res["kind"] == "external"
    assert res["execution"] == "subprocess"
    assert res["risk"] == "low"


def test_classify_pipeline() -> None:
    res = _classify("ls | head")
    assert res["kind"] == "pipeline"
    assert res["execution"] == "native"


def test_classify_chain_and_or() -> None:
    res = _classify("echo a && echo b")
    assert res["kind"] == "chain"
    assert "&&" in res["reason"]


def test_classify_source_zsh_profile() -> None:
    res = _classify("source_zsh_profile ~/.zshrc")
    assert res["kind"] == "script"
    assert res["execution"] == "native"


def test_classify_run_script() -> None:
    res = _classify("run_script ./x.sh")
    assert res["kind"] == "script"
    assert res["execution"] == "subprocess"


def test_classify_zsh_delegation() -> None:
    res = _classify("zsh 'echo hi'")
    assert res["kind"] == "zsh-delegation"
    assert res["execution"] == "zsh"
    assert res["risk"] == "medium"


def test_classify_sudo_is_high_risk() -> None:
    res = _classify("sudo apt update")
    assert res["risk"] == "high"
    assert "sudo" in res["reason"]


def test_classify_eval_is_high_risk() -> None:
    res = _classify('eval "$(something)"')
    assert res["risk"] == "high"


def test_classify_command_substitution_is_medium_risk() -> None:
    res = _classify('echo "$(date)"')
    assert res["risk"] == "medium"
    assert "substitution" in res["reason"]


def test_classify_redirect_to_etc_is_high_risk() -> None:
    res = _classify("echo bad > /etc/hostname")
    assert res["risk"] == "high"
    assert "/etc" in res["reason"]


def test_classify_redirect_to_usr_is_high_risk() -> None:
    res = _classify("cat > /usr/local/bin/x")
    assert res["risk"] == "high"


def test_classify_empty_input() -> None:
    res = _classify("")
    assert res["kind"] == "unknown"
    assert res["execution"] == "none"


# --------------------------------------------------------- plan builtin

def test_plan_missing_args_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert plan([]) == 2
    err = capsys.readouterr().err
    assert "usage" in err


def test_plan_prints_expected_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    buf = io.StringIO()
    rc = plan(["echo", "hi"], builtins=PyShell.BUILTINS, stream=buf)
    assert rc == 0
    text = buf.getvalue()
    for field in ("original=", "kind=", "execution=", "risk=", "reason="):
        assert field in text


def test_plan_does_not_execute_command(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    shell = PyShell()
    assert shell.execute(f"plan touch {marker}") == 0
    assert not marker.exists()


def test_plan_does_not_mutate_aliases() -> None:
    shell = PyShell()
    before = dict(shell.aliases)
    shell.execute("plan alias zz='echo zz'")
    assert shell.aliases == before
    assert "zz" not in shell.aliases


def test_plan_does_not_mutate_env() -> None:
    shell = PyShell()
    key = "PYSH_PLAN_TEST_NEVER_SET"
    os.environ.pop(key, None)
    shell.execute(f"plan export {key}=oops")
    assert key not in os.environ


def test_plan_does_not_mutate_cwd(tmp_path: Path) -> None:
    shell = PyShell()
    start = os.getcwd()
    shell.execute(f"plan cd {tmp_path}")
    assert os.getcwd() == start


def test_plan_shell_builtin_emits_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    assert shell.execute("plan ls -la") == 0
    out = capsys.readouterr().out
    assert "kind=external" in out
