# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_script_mode.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Script Mode v1 tests (Issue #14)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pysh.cli import main


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_runs_pysh_script(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(tmp_path / "basic.pysh", "echo script-start\n")

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "script-start\n"
    assert captured.err == ""


def test_module_mode_runs_pysh_script(tmp_path: Path) -> None:
    script = _write(tmp_path / "module.pysh", "echo module-ok\n")

    completed = subprocess.run(
        [sys.executable, "-m", "pysh", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "module-ok\n"
    assert completed.stderr == ""


def test_cli_script_missing_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    missing = tmp_path / "missing.pysh"

    status = main([str(missing)])
    captured = capsys.readouterr()

    assert status == 1
    assert captured.out == ""
    assert "file not found" in captured.err


def test_cli_script_directory_path(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    status = main([str(tmp_path)])
    captured = capsys.readouterr()

    assert status == 1
    assert captured.out == ""
    assert str(tmp_path) in captured.err


def test_shebang_line_is_ignored(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(
        tmp_path / "shebang.pysh",
        "#!/usr/bin/env pysh\n"
        "echo shebang-ok\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "shebang-ok\n"
    assert captured.err == ""


def test_positional_parameters(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(
        tmp_path / "args.pysh",
        "echo zero=$0\n"
        "echo one=$1\n"
        "echo two=$2\n"
        "echo count=$#\n"
        "echo quoted=\"$1\"\n"
        "echo all=\"$@\"\n",
    )

    status = main([str(script), "arg one", "arg2"])
    captured = capfd.readouterr()

    assert status == 0
    assert f"zero={script}" in captured.out
    assert "one=arg one" in captured.out
    assert "two=arg2" in captured.out
    assert "count=2" in captured.out
    assert "quoted=arg one" in captured.out
    assert "all=arg one arg2" in captured.out


def test_dollar_question_still_tracks_last_status(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(
        tmp_path / "last.pysh",
        "false\n"
        "echo last=$?\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "last=1\n"


def test_logical_lines_comments_blank_chains_and_conditionals(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(
        tmp_path / "logic.pysh",
        "\n"
        "# comment\n"
        "echo a; echo b\n"
        "false && echo no\n"
        "false || echo yes\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "a\nb\nyes\n"


def test_backslash_continuation(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(tmp_path / "continue.pysh", "echo hello \\\nworld\n")

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello world\n"


def test_heredoc_and_here_string(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(
        tmp_path / "stdin.pysh",
        "cat << EOF\n"
        "hello-from-heredoc\n"
        "EOF\n"
        "cat <<< \"hello-from-here-string\"\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello-from-heredoc\nhello-from-here-string\n"


def test_glob_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    script = _write(tmp_path / "glob.pysh", "echo *.py\n")
    monkeypatch.chdir(tmp_path)

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "a.py b.py\n"


def test_python_block(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(
        tmp_path / "block.pysh",
        "py {\n"
        "value = 40 + 2\n"
        "print(value)\n"
        "}\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "42\n"


def test_last_command_status_is_script_status(tmp_path: Path) -> None:
    script = _write(tmp_path / "status.pysh", "true\nfalse\n")

    assert main([str(script)]) == 1


def test_exit_builtin_terminates_script(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(tmp_path / "exit.pysh", "echo before\nexit 7\necho after\n")

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 7
    assert captured.out == "before\n"


def test_command_not_found_returns_127_when_last(tmp_path: Path) -> None:
    script = _write(tmp_path / "missing.pysh", "__pysh_no_such_issue14_command__\n")

    assert main([str(script)]) == 127


def test_parse_error_returns_2_and_stops(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(tmp_path / "parse.pysh", "echo 'unterminated\necho after\n")

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 2
    assert "unterminated" in captured.err
    assert "after" not in captured.out


def test_missing_heredoc_terminator_returns_2(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(tmp_path / "bad-heredoc.pysh", "cat << EOF\nhello\n")

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 2
    assert "missing heredoc terminator" in captured.err


def test_debug_trace_for_script_goes_to_stderr(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(tmp_path / "debug.pysh", "echo debug-script\n")

    status = main(["--debug", str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "debug-script\n"
    assert "[PYSH_DEBUG]" in captured.err
    assert f"file={script}" in captured.err


def test_debug_trace_redacts_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "super-secret-value")
    script = _write(tmp_path / "secret.pysh", "echo super-secret-value\n")

    status = main(["--debug", str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "super-secret-value\n"
    assert "super-secret-value" not in captured.err
    assert "<redacted>" in captured.err


def test_script_mode_does_not_source_foreign_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("echo should-not-source\n", encoding="utf-8")
    (home / ".bashrc").write_text("echo should-not-source\n", encoding="utf-8")
    script = _write(tmp_path / "safe.pysh", "echo explicit-script\n")
    monkeypatch.setenv("HOME", str(home))

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "explicit-script\n"
    assert "should-not-source" not in captured.out
    assert captured.err == ""


def test_dash_c_still_works(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo command-mode"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "command-mode\n"


def test_dash_c_rejects_script_argument(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo command-mode", "script.pysh"])
    captured = capsys.readouterr()

    assert status == 2
    assert "-c does not accept" in captured.err


def test_script_arguments_after_double_dash(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    script = _write(tmp_path / "dash.pysh", "echo one=$1\n")

    status = main([str(script), "--flag"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "one=--flag\n"


def test_executable_shebang_script_via_pysh_path(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    script = _write(
        tmp_path / "executable.pysh",
        "#!/usr/bin/env pysh\n"
        "echo executable-ok\n",
    )
    script.chmod(0o755)

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert os.access(script, os.X_OK)
    assert captured.out == "executable-ok\n"


def test_dollar_at_and_hash_with_no_args(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    script = _write(
        tmp_path / "noargs.pysh",
        "echo count=$#\n"
        "echo all=\"$@\"\n"
        "echo star=\"$*\"\n",
    )

    status = main([str(script)])
    captured = capfd.readouterr()

    assert status == 0
    assert "count=0" in captured.out
    assert "all=" in captured.out
    assert "star=" in captured.out
    assert captured.out == "count=0\nall=\nstar=\n"


def test_braced_positional_parameters(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    script = _write(
        tmp_path / "braced.pysh",
        "echo zero=${0}\n"
        "echo one=${1}\n"
        "echo count=${#}\n",
    )

    status = main([str(script), "braced-arg"])
    captured = capfd.readouterr()

    assert status == 0
    assert f"zero={script}" in captured.out
    assert "one=braced-arg" in captured.out
    assert "count=1" in captured.out
