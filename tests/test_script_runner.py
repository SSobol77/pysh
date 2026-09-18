# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_script_runner.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the script transition runner."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pysh.core.shell import PyShell
from pysh.script_runner import ScriptRunner, detect_script_type


def test_detects_zsh_bash_and_sh_shebangs(tmp_path: Path) -> None:
    zsh_script = tmp_path / "legacy.zsh"
    bash_script = tmp_path / "legacy.bash"
    sh_script = tmp_path / "legacy.sh"
    zsh_script.write_text("#!/usr/bin/env zsh\n", encoding="utf-8")
    bash_script.write_text("#!/bin/bash\n", encoding="utf-8")
    sh_script.write_text("#!/usr/bin/env sh\n", encoding="utf-8")

    assert detect_script_type(zsh_script).interpreter == "zsh"
    assert detect_script_type(bash_script).interpreter == "bash"
    assert detect_script_type(sh_script).interpreter == "sh"


def test_run_script_zsh_shebang_when_available(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    if shutil.which("zsh") is None:
        pytest.skip("zsh is not installed")
    script = tmp_path / "legacy.zsh"
    script.write_text("#!/usr/bin/env zsh\nprint -r -- zsh-ok\n", encoding="utf-8")

    shell = PyShell()
    assert shell.execute(f"run_script {script}") == 0
    captured = capfd.readouterr()
    assert "zsh-ok" in captured.out


def test_run_script_bash_shebang_passes_args_safely(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not installed")
    marker = tmp_path / "executed"
    script = tmp_path / "legacy.bash"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '<%s>\\n' \"$1\"\n"
        "printf '<%s>\\n' \"$2\"\n",
        encoding="utf-8",
    )

    shell = PyShell()
    assert shell.execute(f"run_script {script} 'arg one' '$(touch {marker})'") == 0
    captured = capfd.readouterr()
    assert "<arg one>" in captured.out
    assert f"<$(touch {marker})>" in captured.out
    assert not marker.exists()


def test_run_script_sh_shebang_when_available(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    if shutil.which("sh") is None:
        pytest.skip("sh is not installed")
    script = tmp_path / "legacy.sh"
    script.write_text("#!/usr/bin/env sh\nprintf '%s\\n' sh-ok\n", encoding="utf-8")

    shell = PyShell()
    assert shell.execute(f"run_script {script}") == 0
    captured = capfd.readouterr()
    assert "sh-ok" in captured.out


def test_run_script_missing_interpreter_is_deterministic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = tmp_path / "legacy.zsh"
    script.write_text("#!/usr/bin/env zsh\nprint should-not-run\n", encoding="utf-8")
    runner = ScriptRunner(lambda _line: 0, interpreter_resolver=lambda _name: None)

    assert runner.run(script, []) == 127
    captured = capsys.readouterr()
    assert "pysh: run_script: zsh: command not found" in captured.err


def test_run_script_interpreter_invocation_does_not_use_shell_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "legacy.bash"
    script.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        def wait(self) -> int:
            return 7

        def terminate(self) -> None:
            return None

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        calls.append((argv, kwargs))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    runner = ScriptRunner(lambda _line: 0, interpreter_resolver=lambda _name: "/bin/bash")

    assert runner.run(script, ["--dry-run"]) == 7
    assert calls == [(["/bin/bash", str(script), "--dry-run"], {})]


def test_run_script_no_shebang_runs_native_lines(tmp_path: Path) -> None:
    script = tmp_path / "pysh-script"
    script.write_text("\n# comment\nONE=1\necho ok\n", encoding="utf-8")
    executed: list[str] = []
    runner = ScriptRunner(lambda line: executed.append(line) or 0)

    assert runner.run(script, []) == 0
    assert executed == ["ONE=1", "echo ok"]


def test_run_script_without_filename_is_usage_error(
    capfd: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()

    assert shell.execute("run_script") == 2

    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "run_script: filename argument required\n"


def test_run_script_no_shebang_returns_last_status_by_default(tmp_path: Path) -> None:
    script = tmp_path / "pysh-script"
    script.write_text("false\nfinal\n", encoding="utf-8")
    executed: list[str] = []

    def execute(line: str) -> int:
        executed.append(line)
        return 3 if line == "false" else 9

    runner = ScriptRunner(execute)
    assert runner.run(script, []) == 9
    assert executed == ["false", "final"]


def test_run_script_no_shebang_continues_for_error_operator(tmp_path: Path) -> None:
    script = tmp_path / "pysh-script"
    script.write_text("false || true\necho after\n", encoding="utf-8")
    executed: list[str] = []

    def execute(line: str) -> int:
        executed.append(line)
        return 1 if line.startswith("false") else 0

    runner = ScriptRunner(execute)
    assert runner.run(script, []) == 0
    assert executed == ["false || true", "echo after"]
