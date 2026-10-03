# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_no_automatic_legacy_fallback.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 2.6: PySH never silently hands work to a legacy shell.

A repository-owned fake ``zsh`` on PATH records every invocation. No real Zsh,
Bash or Fish is needed or used.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pysh.config.startup import NO_RC_STARTUP_POLICY
from pysh.core.shell import PyShell


@pytest.fixture
def fake_zsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a recording fake ``zsh`` first on PATH; return the invocation log path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "zsh-invocations.log"
    fake = bin_dir / "zsh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"open({str(log)!r}, 'a').write(repr(sys.argv[1:]) + '\\n')\n"
        "print('FAKE-ZSH-RAN')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return log


def _invocations(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _shell() -> PyShell:
    return PyShell(startup_policy=NO_RC_STARTUP_POLICY)  # finds the fake zsh via PATH


def _run(shell: PyShell, capfd, line: str) -> tuple[int, str, str]:
    capfd.readouterr()
    status = shell.execute(line)
    captured = capfd.readouterr()
    return status, captured.out, captured.err


@pytest.fixture(params=[False, True], ids=["variable-unset", "PYSH_ZSH_FALLBACK=1"])
def old_variable(request, monkeypatch: pytest.MonkeyPatch) -> bool:
    """Run every fallback-trigger scenario with and without the removed variable."""
    if request.param:
        monkeypatch.setenv("PYSH_ZSH_FALLBACK", "1")
    else:
        monkeypatch.delenv("PYSH_ZSH_FALLBACK", raising=False)
    return request.param


def test_unknown_command_is_a_pysh_diagnostic_never_zsh(fake_zsh, old_variable, capfd) -> None:
    status, out, err = _run(_shell(), capfd, "no_such_command_xyz_1")
    assert status == 127
    assert "pysh: no_such_command_xyz_1: command not found" in err
    assert "FAKE-ZSH-RAN" not in out
    assert _invocations(fake_zsh) == []


def test_missing_command_in_a_pipeline_never_reaches_zsh(fake_zsh, old_variable, capfd) -> None:
    shell = _shell()
    for line in ("echo x | no_such_command_xyz_2", "no_such_command_xyz_3 | cat"):
        status, out, err = _run(shell, capfd, line)
        assert "FAKE-ZSH-RAN" not in out, line
        assert "command not found" in err, line
    assert _invocations(fake_zsh) == []


def test_process_creation_filenotfound_never_reaches_zsh(
    fake_zsh, old_variable, capfd, tmp_path: Path
) -> None:
    # An executable whose interpreter does not exist makes process creation raise
    # FileNotFoundError, the branch that used to fall back to zsh.
    broken = tmp_path / "broken-interp"
    broken.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    broken.chmod(0o755)
    status, out, err = _run(_shell(), capfd, f"{broken}")
    assert status == 127 and "FAKE-ZSH-RAN" not in out
    assert "command not found" in err
    assert _invocations(fake_zsh) == []


def test_path_expansion_failure_never_reaches_zsh(fake_zsh, old_variable, capfd) -> None:
    status, out, err = _run(_shell(), capfd, "echo 'unterminated")
    assert status != 0 and "FAKE-ZSH-RAN" not in out
    assert "pysh:" in err and "Traceback" not in err
    assert _invocations(fake_zsh) == []


def test_removed_builtin_cannot_enable_anything(fake_zsh, old_variable, capfd) -> None:
    shell = _shell()
    for line in ("zsh_fallback on", "zsh_fallback off", "zsh_fallback"):
        status, out, err = _run(shell, capfd, line)
        assert status == 127, line
        assert "zsh_fallback: command not found" in err, line
        assert "FAKE-ZSH-RAN" not in out
    status, out, err = _run(shell, capfd, "no_such_command_xyz_4")
    assert status == 127 and "FAKE-ZSH-RAN" not in out
    assert _invocations(fake_zsh) == []
    assert "zsh_fallback" not in PyShell.BUILTINS


def test_old_variable_has_no_control_meaning_when_assigned(fake_zsh, capfd) -> None:
    shell = _shell()
    for line in ("PYSH_ZSH_FALLBACK=1", "export PYSH_ZSH_FALLBACK=1"):
        assert _run(shell, capfd, line)[0] == 0, line
        status, out, err = _run(shell, capfd, "no_such_command_xyz_5")
        assert status == 127 and "FAKE-ZSH-RAN" not in out, line
    assert _invocations(fake_zsh) == []
    assert not hasattr(shell, "zsh_fallback_enabled")


def test_batch_cli_with_the_old_variable_does_not_fall_back(fake_zsh) -> None:
    env = {**os.environ, "PYSH_ZSH_FALLBACK": "1"}
    done = subprocess.run(
        [sys.executable, "-m", "pysh", "--no-rc", "-c", "no_such_command_xyz_6"],
        capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, check=False,
    )
    assert done.returncode == 127 and "command not found" in done.stderr
    assert "FAKE-ZSH-RAN" not in done.stdout and _invocations(fake_zsh) == []


def test_explicit_zsh_builtin_still_reaches_the_bridge_and_only_it(fake_zsh, capfd) -> None:
    shell = _shell()
    status, out, _err = _run(shell, capfd, "zsh echo hello")
    assert status == 0 and "FAKE-ZSH-RAN" in out
    assert _invocations(fake_zsh) == ["['-lc', 'echo hello']"]
    # An ordinary unknown command afterwards is still PySH-owned.
    status, out, err = _run(shell, capfd, "no_such_command_xyz_7")
    assert status == 127 and "FAKE-ZSH-RAN" not in out
    assert _invocations(fake_zsh) == ["['-lc', 'echo hello']"]


def test_explicit_zsh_shebang_delegation_stays_separate(fake_zsh, capfd, tmp_path: Path) -> None:
    script = tmp_path / "legacy.sh"
    script.write_text("#!/bin/zsh\necho from-script\n", encoding="utf-8")
    shell = _shell()
    status, out, _ = _run(shell, capfd, f"run_script {script}")
    assert status == 0 and "FAKE-ZSH-RAN" in out
    assert _invocations(fake_zsh) == [f"['{script}']"]
    # Direct native script mode ignores the shebang entirely.
    log_size = len(_invocations(fake_zsh))
    assert shell.run_script_file(script, [], native_only=True) in {0, 127}
    assert len(_invocations(fake_zsh)) == log_size


def test_command_substitution_never_reaches_zsh(fake_zsh, old_variable, capfd) -> None:
    status, out, err = _run(_shell(), capfd, "echo [$(no_such_command_xyz_8)]")
    assert (status, out) == (0, "[]\n")
    assert _invocations(fake_zsh) == []


def test_inventory_has_no_automatic_fallback_entries() -> None:
    from tests.differential import boundaries

    inventory = boundaries.load_inventory()
    assert [b.boundary_id for b in inventory if b.category == boundaries.AUTOMATIC_CATEGORY] == []
    assert boundaries.scan_forbidden() == {}
