# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_observability_diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Observability and diagnostics contract tests (Issue #13)."""
from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

from pysh.cli import main
from pysh.core.shell import PyShell
from pysh.diagnostics.command_plan import classify
from pysh.diagnostics.trace import RedactionPolicy
from pysh.prompt.system_profile import (
    REDACTED_PLACEHOLDER,
    apt_check,
    apt_search,
    env_audit,
    path_audit,
    sys_info,
    which_all,
)


def test_debug_trace_disabled_by_default(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert "[PYSH_DEBUG]" not in captured.err


def test_debug_trace_goes_to_stderr_and_stdout_stays_clean(
    capfd: pytest.CaptureFixture[str],
) -> None:
    status = main(["--debug", "-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert "[PYSH_DEBUG]" in captured.err
    assert "stage=INPUT" in captured.err
    assert "stage=RESOLVE" in captured.err
    assert "stage=EXECUTE_PLAN" in captured.err


def test_debug_parse_error_has_no_traceback(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["--debug", "-c", "echo hello |"])
    captured = capfd.readouterr()

    assert status == 2
    assert captured.out == ""
    assert "[PYSH_DEBUG]" in captured.err
    assert "stage=ERROR" in captured.err
    assert "Traceback" not in captured.err


def test_debug_command_not_found_preserves_127(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["--debug", "-c", "__pysh_missing_issue13_command__"])
    captured = capfd.readouterr()

    assert status == 127
    assert captured.out == ""
    assert "command not found" in captured.err
    assert "stage=ERROR" in captured.err


def test_short_sensitive_value_does_not_corrupt_unrelated_file_path() -> None:
    """A short sensitive value must not blot out a coincidental substring.

    A one-character value for a sensitive-named variable (e.g. a boolean-ish
    session flag) has no secrecy value on its own, but naive substring
    replacement would still corrupt unrelated diagnostic text containing that
    character, such as a digit embedded inside a file path.
    """
    policy = RedactionPolicy()
    env = {"SESSION_FLAG": "1"}

    redacted = policy.redact_text("/tmp/pytest-19/debug.pysh", env=env)

    assert redacted == "/tmp/pytest-19/debug.pysh"


def test_short_sensitive_value_does_not_corrupt_unrelated_numeric_text() -> None:
    policy = RedactionPolicy()
    env = {"SESSION_FLAG": "9"}

    redacted = policy.redact_text("status=192 elapsed=90ms", env=env)

    assert redacted == "status=192 elapsed=90ms"


def test_short_sensitive_value_redacted_in_recognizable_assignment_context() -> None:
    """``NAME=value`` exposure must still be redacted even for a 1-char value."""
    policy = RedactionPolicy()
    env = {"TOKEN": "x"}

    redacted = policy.redact_text("command='echo TOKEN=x'", env=env)

    assert "TOKEN=x" not in redacted
    assert REDACTED_PLACEHOLDER in redacted


def test_short_sensitive_value_redacted_as_bare_whole_token() -> None:
    """A short value exposed as its own token (not ``NAME=value``) is redacted."""
    policy = RedactionPolicy()
    env = {"TOKEN": "x"}

    redacted = policy.redact_text("command='echo x'", env=env)

    assert redacted == "command='echo <redacted>'"


def test_short_api_key_value_redacted_on_actual_exposure() -> None:
    policy = RedactionPolicy()
    env = {"API_KEY": "abc"}

    redacted = policy.redact_text("command='curl -H API_KEY=abc'", env=env)

    assert "API_KEY=abc" not in redacted
    assert REDACTED_PLACEHOLDER in redacted


def test_long_sensitive_value_still_redacted() -> None:
    policy = RedactionPolicy()
    env = {"SESSION_TOKEN": "long-enough-secret-value"}

    redacted = policy.redact_text("file=/tmp/long-enough-secret-value.txt", env=env)

    assert "long-enough-secret-value" not in redacted
    assert REDACTED_PLACEHOLDER in redacted


def test_redact_value_does_not_inject_regex_from_secret_characters() -> None:
    """A value containing regex metacharacters must be treated literally."""
    policy = RedactionPolicy()
    env = {"TOKEN": "a.*b"}

    redacted = policy.redact_text("command='echo a.*b' other='axxxxb'", env=env)

    assert redacted == f"command='echo {REDACTED_PLACEHOLDER}' other='axxxxb'"


def test_sensitive_env_value_redacted_in_env_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "super-secret-value")
    stream = io.StringIO()

    assert env_audit(stream=stream) == 0
    output = stream.getvalue()

    assert "PYSH_SECRET_TOKEN" in output
    assert REDACTED_PLACEHOLDER in output
    assert "super-secret-value" not in output


def test_sensitive_env_value_redacted_in_debug_trace(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "super-secret-value")

    status = main(["--debug", "-c", "echo super-secret-value"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "super-secret-value\n"
    assert "super-secret-value" not in captured.err
    assert REDACTED_PLACEHOLDER in captured.err


def test_plan_redacts_sensitive_env_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "super-secret-value")
    shell = PyShell()

    assert shell.execute("plan echo super-secret-value") == 0
    output = capsys.readouterr().out

    assert "super-secret-value" not in output
    assert REDACTED_PLACEHOLDER in output


def test_plan_echo_does_not_execute(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyShell()

    assert shell.execute("plan echo SHOULD_NOT_EXECUTE") == 0
    output = capsys.readouterr().out

    assert "kind=external" in output
    assert output.count("SHOULD_NOT_EXECUTE") == 1


def test_plan_reports_builtin_and_missing_without_execution() -> None:
    builtin = classify("cd /tmp", builtins=PyShell.BUILTINS)
    missing = classify("__pysh_missing_issue13_command__", builtins=PyShell.BUILTINS)

    assert builtin.kind == "builtin"
    assert missing.kind == "external"
    assert missing.execution == "subprocess"


def test_plan_handles_redirection_heredoc_and_glob_metadata() -> None:
    redirect = classify("echo hello > /etc/issue", builtins=PyShell.BUILTINS)
    heredoc = classify("cat << EOF", builtins=PyShell.BUILTINS)
    glob = classify("ls *.py", builtins=PyShell.BUILTINS)

    assert redirect.risk == "high"
    assert heredoc.kind == "external"
    assert glob.kind == "external"


def test_sys_info_stdout_has_expected_sections(capsys: pytest.CaptureFixture[str]) -> None:
    assert sys_info() == 0
    captured = capsys.readouterr()

    assert "platform=" in captured.out
    assert "python=" in captured.out
    assert "path_entries=" in captured.out
    assert captured.err == ""


def test_path_audit_handles_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    stream = io.StringIO()

    status = path_audit(env={"PATH": os.pathsep.join([str(tmp_path), str(missing)])}, stream=stream)
    output = stream.getvalue()

    assert status == 1
    assert f"ok\t{tmp_path}" in output
    assert f"missing\t{missing}" in output


def test_which_all_returns_path_order_and_does_not_execute(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        target = directory / "tool"
        target.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        target.chmod(0o755)
    stream = io.StringIO()

    status = which_all("tool", env={"PATH": os.pathsep.join([str(first), str(second)])}, stream=stream)

    assert status == 0
    assert stream.getvalue().splitlines() == [str(first / "tool"), str(second / "tool")]


def test_apt_helpers_do_not_use_sudo() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    assert apt_check(apt_resolver=lambda _: "/usr/bin/apt", runner=runner) == 0
    assert apt_search("python3", apt_resolver=lambda _: "/usr/bin/apt", runner=runner) == 0

    assert calls
    assert all("sudo" not in argv for argv in calls)
    assert calls[0] == ["/usr/bin/apt", "list", "--upgradable"]
    assert calls[1] == ["/usr/bin/apt", "search", "python3"]


def test_compat_check_reads_file_without_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = tmp_path / "profile.zsh"
    profile.write_text("alias ll='ls -la'\neval $(tool)\n", encoding="utf-8")

    def fail_popen(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("compat_check must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "Popen", fail_popen)
    shell = PyShell()

    status = shell.execute(f"compat_check {profile}")
    output = capsys.readouterr().out

    assert status == 2
    assert f"file={profile}" in output
    assert "risky=" in output


def test_redaction_lowercase_secret_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("pysh_secret_token", "lowercase-secret-value")
    stream = io.StringIO()

    assert env_audit(stream=stream) == 0
    output = stream.getvalue()

    assert "pysh_secret_token" in output
    assert REDACTED_PLACEHOLDER in output
    assert "lowercase-secret-value" not in output


def test_redaction_mixed_case_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("Api_Key", "mixed-case-api-value")
    stream = io.StringIO()

    assert env_audit(stream=stream) == 0
    output = stream.getvalue()

    assert "Api_Key" in output
    assert REDACTED_PLACEHOLDER in output
    assert "mixed-case-api-value" not in output


def test_redaction_mixed_case_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("myPassword", "mixed-case-password-value")
    stream = io.StringIO()

    assert env_audit(stream=stream) == 0
    output = stream.getvalue()

    assert "myPassword" in output
    assert REDACTED_PLACEHOLDER in output
    assert "mixed-case-password-value" not in output
