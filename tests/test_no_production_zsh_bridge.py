# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_no_production_zsh_bridge.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 2.7: PySH has no dedicated Zsh builtin or bridge.

``zsh`` is an ordinary program name. A repository-owned fake ``zsh`` on PATH
proves it is reached only through generic external-command execution. No real
Zsh, Bash or Fish is needed.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
from pathlib import Path

import pytest

from pysh.config.startup import NO_RC_STARTUP_POLICY
from pysh.core.shell import PyShell

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "pysh"


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty PATH directory (no zsh anywhere) and a private HOME/cwd."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return bin_dir


def _install_fake_zsh(bin_dir: Path, log: Path) -> None:
    fake = bin_dir / "zsh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"open({str(log)!r}, 'a').write(repr(sys.argv[1:]) + '\\n')\n"
        "print('FAKE-ZSH-RAN')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def _run(line: str, capfd) -> tuple[int, str, str]:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    capfd.readouterr()
    status = shell.execute(line)
    captured = capfd.readouterr()
    return status, captured.out, captured.err


def test_without_a_zsh_executable_it_is_ordinary_command_not_found(isolated, capfd) -> None:
    status, out, err = _run("zsh echo hello", capfd)
    assert status == 127
    assert err == "pysh: zsh: command not found\n" and out == ""


def test_a_zsh_executable_on_path_runs_as_a_generic_external_command(
    isolated, capfd, tmp_path: Path
) -> None:
    log = tmp_path / "invocations.log"
    _install_fake_zsh(isolated, log)
    status, out, _err = _run("zsh echo hello", capfd)
    assert status == 0 and out == "FAKE-ZSH-RAN\n"
    # Exactly the user's words: PySH injected no `-l`, `-c` or joined command string.
    assert log.read_text(encoding="utf-8").splitlines() == ["['echo', 'hello']"]


def test_a_program_named_zsh_is_resolved_like_any_other_program(
    isolated, capfd, tmp_path: Path
) -> None:
    log = tmp_path / "invocations.log"
    other = isolated / "otherprog"
    _install_fake_zsh(isolated, log)
    other.write_bytes((isolated / "zsh").read_bytes())
    other.chmod(0o755)
    assert _run("zsh a b", capfd)[1:2] == ("FAKE-ZSH-RAN\n",)
    assert _run("otherprog a b", capfd)[1:2] == ("FAKE-ZSH-RAN\n",)
    assert log.read_text(encoding="utf-8").splitlines() == ["['a', 'b']", "['a', 'b']"]


def test_no_zsh_builtin_exists_anywhere_in_the_builtin_surface() -> None:
    from pysh.contracts.builtins import BUILTIN_NAME_LIST, BUILTIN_NAMES
    from pysh.editor.completion import Completer

    assert "zsh" not in BUILTIN_NAMES and "zsh" not in BUILTIN_NAME_LIST
    assert "zsh" not in PyShell.BUILTINS and "zsh" not in Completer.BUILTINS
    assert not hasattr(PyShell, "_builtin_zsh")
    assert not hasattr(PyShell, "_run_zsh_command")
    # The remaining static-import builtins are unaffected.
    assert {"source_zsh", "source_zsh_profile", "source_sh_aliases", "run_script"} <= BUILTIN_NAMES


def test_help_and_builtin_documentation_do_not_list_a_zsh_builtin() -> None:
    text = (REPO_ROOT / "docs" / "user" / "builtins.md").read_text(encoding="utf-8")
    assert "## `zsh`" not in text and "## `zsh_fallback`" not in text


def test_builtin_completion_offers_no_zsh_but_path_completion_still_finds_the_program(
    isolated, tmp_path: Path
) -> None:
    from pysh.editor.completion import Completer

    _install_fake_zsh(isolated, tmp_path / "log")
    completer = Completer(lambda: ())
    assert "zsh" not in Completer.BUILTINS
    assert "zsh" in completer.complete_line("zs", 2)  # generic PATH executable completion


def test_command_plan_treats_zsh_as_an_external_command(isolated) -> None:
    from pysh.diagnostics.command_plan import classify

    result = classify("zsh -lc 'echo hi'", builtins=PyShell.BUILTINS)
    assert result.kind == "external" and result.execution == "subprocess"


def test_the_bridge_module_and_its_api_are_gone() -> None:
    assert not (SRC / "compat" / "zsh_bridge.py").exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pysh.compat.zsh_bridge")
    assert "zsh_bridge" not in inspect.signature(PyShell.__init__).parameters
    assert not hasattr(PyShell(startup_policy=NO_RC_STARTUP_POLICY), "zsh_bridge")


def test_production_never_injects_login_or_command_flags_for_a_legacy_shell() -> None:
    """No production string constant is a `-lc`-style shell flag bundle."""
    flag_bundles = {"-lc", "-ic", "-lic", "-ilc"}
    offenders = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in flag_bundles:
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []


def test_shebang_delegation_is_the_only_remaining_legacy_interpreter_path(
    isolated, capfd, tmp_path: Path
) -> None:
    log = tmp_path / "invocations.log"
    _install_fake_zsh(isolated, log)
    script = tmp_path / "legacy.sh"
    script.write_text("#!/bin/zsh\necho from-script\n", encoding="utf-8")
    status, out, _err = _run(f"run_script {script}", capfd)
    assert status == 0 and "FAKE-ZSH-RAN" in out
    assert log.read_text(encoding="utf-8").splitlines() == [f"['{script}']"]


def test_missing_shebang_interpreter_is_a_controlled_failure(isolated, capfd, tmp_path: Path) -> None:
    script = tmp_path / "legacy.sh"
    script.write_text("#!/bin/zsh\necho x\n", encoding="utf-8")
    status, _out, err = _run(f"run_script {script}", capfd)
    assert status == 127 and "pysh: run_script: zsh: command not found" in err


def test_production_does_not_import_the_differential_laboratory() -> None:
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in SRC.rglob("*.py")
        if "tests.differential" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [] and os.path.isdir(REPO_ROOT / "tests" / "differential")
