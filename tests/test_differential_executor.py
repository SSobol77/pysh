# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_differential_executor.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 2: the hermetic executor, proven with a repository-owned fake child.

No Bash, Zsh or Fish is installed, located or executed here.
"""
from __future__ import annotations

import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

import pytest

from tests.differential import executor
from tests.differential.executor import (
    ExecutableNotFoundError,
    ExecutableNotRunnableError,
    ExecutorError,
    Termination,
    run_hermetic,
)
from tests.differential.model import Observation
from tests.fuzz_support import fdprobe
from tests.fuzz_support.execution import unreaped_child

FIXTURE = Path(__file__).parent / "fixtures" / "differential_reference_child.py"
PY = sys.executable


def run(*args: str, **kwargs):
    return run_hermetic(PY, [str(FIXTURE), *args], **kwargs)


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _assert_heartbeat_stopped(path: Path) -> None:
    first = _size(path)
    assert first > 0, "the grandchild never started"
    time.sleep(0.4)
    assert _size(path) == first, "the grandchild outlived the run"


def test_explicit_argv_is_preserved_and_metacharacters_stay_literal(tmp_path: Path) -> None:
    data = ["$(touch pwned)", "`id`", "a b", "x;y", "|", "*", "?", "'q'", '"d"', "\\n", ""]
    result = run("argv", *data)
    assert result.termination is Termination.EXIT and result.returncode == 0
    assert json.loads(result.stdout) == data
    listing = run("listdir")
    assert json.loads(listing.stdout) == []  # nothing was created by interpolation


def test_argv_prefix_precedes_arguments() -> None:
    result = run_hermetic(PY, ["argv", "tail"], argv_prefix=[str(FIXTURE)])
    assert json.loads(result.stdout) == ["tail"]


def test_home_and_cwd_are_private_and_empty() -> None:
    home = run("env", "HOME").stdout
    cwd = run("cwd").stdout.strip()
    host_home = os.environ.get("HOME", "")
    assert json.loads(home)["HOME"] != host_home
    assert Path(json.loads(home)["HOME"]).name == "home"
    assert Path(cwd).name == "work" and Path(cwd).parent.name.startswith("pysh-differential-")
    assert Path(cwd) != Path.cwd()
    assert json.loads(run("listdir").stdout) == []


def test_runs_do_not_share_state_and_temporary_directories_are_removed() -> None:
    first = run("cwd").stdout.strip()
    second = run("cwd").stdout.strip()
    assert first != second
    assert not Path(first).exists() and not Path(second).exists()


def test_host_environment_is_not_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SSH_AUTH_SOCK", "GITHUB_TOKEN", "PYSH_SECRET_PROBE", "VIRTUAL_ENV", "PYTHONPATH"):
        monkeypatch.setenv(name, "leak")
    keys = json.loads(run("envkeys").stdout)
    assert set(keys) <= {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"}
    assert {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"} <= set(keys)
    values = json.loads(run("env", "SSH_AUTH_SOCK", "GITHUB_TOKEN", "PYSH_SECRET_PROBE").stdout)
    assert values == {"SSH_AUTH_SOCK": None, "GITHUB_TOKEN": None, "PYSH_SECRET_PROBE": None}


def test_explicit_environment_is_added_and_validated() -> None:
    assert json.loads(run("env", "PYSH_X", environment={"PYSH_X": "1"}).stdout) == {"PYSH_X": "1"}
    for bad in ({"": "v"}, {"A=B": "v"}, {"A": "v\0"}):
        with pytest.raises(ExecutorError, match="invalid environment"):
            run("status", "0", environment=bad)


def test_startup_files_in_the_real_home_are_never_consulted(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".bashrc").write_text("echo LEAK\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert json.loads(run("listdir").stdout) == []
    assert json.loads(run("env", "HOME").stdout)["HOME"] != str(tmp_path)


def test_stdin_stdout_stderr_and_status_are_captured() -> None:
    assert run("stdin", stdin=b"fed\n").stdout == "fed\n"
    both = run("both")
    assert (both.stdout, both.stderr, both.returncode) == ("OUT\n", "ERR\n", 0)
    assert run("status", "42").returncode == 42
    assert run("stdin-ignored", stdin=b"x" * 500_000).returncode == 0  # closed pipe is not an error
    big = run("stdin", stdin=b"y" * 300_000)
    assert len(big.stdout) == 300_000


def test_test_owned_input_files_are_available_and_cannot_escape() -> None:
    assert run("readfile", "in.txt", input_files={"in.txt": b"data\n"}).stdout == "data\n"
    for bad in ("../x", "/abs"):
        with pytest.raises(ExecutorError, match="escapes"):
            run("status", "0", input_files={bad: b""})


def test_signal_termination_is_represented() -> None:
    result = run("signal", str(int(signal.SIGTERM)))
    assert result.termination is Termination.SIGNAL
    assert result.signal_number == signal.SIGTERM and result.returncode is None
    assert result.to_observation() == Observation(128 + signal.SIGTERM, "", "")


def test_observation_conversion_rejects_incomplete_runs() -> None:
    assert run("out", "hi").to_observation() == Observation(0, "hi", "")
    timeout = run("sleep", "30", timeout=0.3)
    with pytest.raises(ExecutorError, match="no valid observation"):
        timeout.to_observation()


def test_timeout_kills_the_group_including_a_spawned_child(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    start = time.monotonic()
    result = run("spawn", str(beat), timeout=1.0)
    assert time.monotonic() - start < 5
    assert result.termination is Termination.TIMEOUT and result.timed_out
    assert result.returncode is None
    assert result.stdout.strip().isdigit()  # the pid was printed before the kill
    _assert_heartbeat_stopped(beat)
    assert unreaped_child() is None


def test_sigterm_ignoring_child_is_escalated_to_sigkill() -> None:
    start = time.monotonic()
    result = run("ignore-term-sleep", "60", timeout=0.5)
    assert result.timed_out and "ready" in result.stdout
    assert time.monotonic() - start < executor.TERMINATE_GRACE_SECONDS * 3 + 1
    assert unreaped_child() is None


def test_background_grandchild_is_killed_even_after_a_normal_exit(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    result = run("spawn-exit", str(beat), timeout=5.0)
    assert result.termination is Termination.EXIT and result.returncode == 0
    time.sleep(0.2)
    _assert_heartbeat_stopped(beat)


def test_output_bound_terminates_and_is_recorded_not_silently_truncated() -> None:
    result = run("flood", "5000000", max_output_bytes=1000, timeout=10.0)
    assert result.termination is Termination.OUTPUT_LIMIT and result.output_limit_exceeded
    assert result.truncated and len(result.stdout) <= 1000
    ok = run("flood", "999", max_output_bytes=1000)
    assert ok.termination is Termination.EXIT and not ok.truncated and len(ok.stdout) == 999
    with pytest.raises(ExecutorError):
        result.to_observation()


def test_missing_and_unrunnable_executables_are_controlled_errors(tmp_path: Path) -> None:
    with pytest.raises(ExecutableNotFoundError):
        run_hermetic(tmp_path / "absent", [])
    with pytest.raises(ExecutableNotFoundError):
        run_hermetic(tmp_path, [])  # a directory
    plain = tmp_path / "plain"
    plain.write_text("#!/bin/sh\n", encoding="utf-8")
    plain.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(ExecutableNotRunnableError):
        run_hermetic(plain, [])
    not_a_program = tmp_path / "junk"
    not_a_program.write_bytes(b"\x00\x01binary-garbage")
    not_a_program.chmod(0o700)
    with pytest.raises(ExecutorError):
        run_hermetic(not_a_program, [])
    with pytest.raises(ExecutorError, match="absolute"):
        run_hermetic("python3", [])  # never searched on PATH
    with pytest.raises(ExecutorError, match="positive"):
        run("status", "0", timeout=0)


def test_results_are_deterministic_and_carry_no_paths_or_environment() -> None:
    first, second = run("both"), run("both")
    assert first == second
    text = repr(first)
    assert "pysh-differential" not in text and os.environ.get("HOME", "<none>") not in text


def test_repeated_runs_do_not_leak_descriptors_or_children(tmp_path: Path) -> None:
    run("both")  # warm up lazily-opened descriptors
    before = fdprobe.open_fds()
    for index in range(15):
        run("both")
        run("stdin", stdin=b"x")
        run("sleep", "30", timeout=0.2)
        run("flood", "100000", max_output_bytes=100)
        run("spawn-exit", str(tmp_path / f"b{index}"))
    assert fdprobe.open_fds() == before
    assert unreaped_child() is None


def test_executor_source_never_uses_a_shell_or_names_a_legacy_shell() -> None:
    import ast

    tree = ast.parse(Path(executor.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert isinstance(node.value, ast.Constant) and node.value.value is False
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in {"bash", "zsh", "fish", "sh", "/bin/sh"}
