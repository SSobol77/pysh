# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Midnight Commander environment detection and mc-safe mode."""
from __future__ import annotations

import unittest.mock as mock

import pytest

from pysh.compat.mc import is_mc_environment
from pysh.core.shell import PyShell

# ---------------------------------------------------------------- detection


def test_no_mc_env_when_vars_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MC_TMPDIR", "MC_SID", "MC_CONTROL_FILE", "MC_CONTROL_FILE_NAME"):
        monkeypatch.delenv(var, raising=False)
    assert not is_mc_environment()


def test_mc_tmpdir_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MC_TMPDIR", "/tmp/.mc-12345")
    assert is_mc_environment()


def test_mc_sid_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MC_TMPDIR", "MC_CONTROL_FILE", "MC_CONTROL_FILE_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MC_SID", "42")
    assert is_mc_environment()


def test_mc_control_file_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MC_TMPDIR", "MC_SID", "MC_CONTROL_FILE_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MC_CONTROL_FILE", "/tmp/.mc-12345/console")
    assert is_mc_environment()


def test_mc_control_file_name_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MC_TMPDIR", "MC_SID", "MC_CONTROL_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MC_CONTROL_FILE_NAME", "console")
    assert is_mc_environment()


def test_empty_mc_var_not_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MC_TMPDIR", "MC_SID", "MC_CONTROL_FILE", "MC_CONTROL_FILE_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MC_TMPDIR", "")
    # An empty string is falsy, so is_mc_environment() returns False.
    assert not is_mc_environment()


# ---------------------------------------------------------------- mc-safe mode (shell integration)


def test_mc_env_disables_raw_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    """MC environment forces mc-safe mode, meaning raw editor is disabled."""
    monkeypatch.setenv("MC_TMPDIR", "/tmp/.mc-test")
    shell = PyShell()
    # MC environment must disable the raw editor regardless of TTY state.
    # In tests stdin/stdout are not TTYs, so _stdio_is_tty() is False, which
    # would normally be sufficient to disable the raw editor.  We verify that
    # the MC-specific branch is reached by calling _should_use_raw_editor()
    # with a mocked TTY gate that returns True.
    import unittest.mock as mock

    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        # Patch where the name is bound inside shell.py, not at the source module.
        with mock.patch("pysh.core.shell.colors_enabled", return_value=True):
            assert not shell._should_use_raw_editor()


def test_no_mc_env_allows_raw_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without MC environment vars the raw editor is enabled when TTY and capable TERM are available."""
    for var in ("MC_TMPDIR", "MC_SID", "MC_CONTROL_FILE", "MC_CONTROL_FILE_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    shell = PyShell()
    import unittest.mock as mock

    with mock.patch.object(PyShell, "_stdio_is_tty", return_value=True):
        assert shell._should_use_raw_editor()


def test_mc_safe_prompt_leaves_cursor_after_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """In mc-safe mode, input() is used which leaves the cursor after the prompt."""
    monkeypatch.setenv("MC_TMPDIR", "/tmp/.mc-test")
    shell = PyShell()
    import unittest.mock as mock

    captured_prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        captured_prompts.append(prompt)
        return "echo hello"

    with mock.patch("builtins.input", side_effect=fake_input):
        line = shell._read_interactive_line()

    assert line == "echo hello"
    # Prompt was printed once via input(); no cursor-repositioning sequences.
    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    # No ANSI cursor-up or cursor-down sequences in the prompt string.
    assert "\033[A" not in prompt_text
    assert "\033[B" not in prompt_text


# ---------------------------------------------------------------- mc builtin wrapper


def test_mc_default_integration_is_auto() -> None:
    assert PyShell().editor_options["mc_integration"] == "auto"


def test_mc_builtin_auto_adds_no_subshell(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc") == 0
    assert calls == [["/usr/bin/mc", "-u"]]
    captured = capsys.readouterr()
    assert "Ctrl+O will only show the previous screen" in captured.err
    assert "not an active PySH prompt" in captured.err


def test_mc_builtin_preserves_existing_no_subshell(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = PyShell()
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc -u /tmp") == 0
    assert calls == [["/usr/bin/mc", "-u", "/tmp"]]


def test_mc_builtin_auto_warning_once_per_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc") == 0
    assert shell.execute("mc /tmp") == 0
    captured = capsys.readouterr()
    assert captured.err.count("MC does not support PySH as a live Ctrl+O subshell") == 1
    assert calls == [["/usr/bin/mc", "-u"], ["/usr/bin/mc", "-u", "/tmp"]]


def test_mc_builtin_auto_warning_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = PyShell()
    shell.set_mc_warning_enabled(False)
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc") == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert calls == [["/usr/bin/mc", "-u"]]


def test_mc_builtin_safe_removes_subshell_request(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = PyShell()
    shell.set_mc_integration("safe")
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc --subshell /tmp") == 0
    assert calls == [["/usr/bin/mc", "-u", "/tmp"]]


@pytest.mark.parametrize("mode", ["off", "subshell"])
def test_mc_builtin_passthrough_modes(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell()
    shell.set_mc_integration(mode)
    calls: list[list[str]] = []

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda name: "/usr/bin/mc" if name == "mc" else None)
    monkeypatch.setattr(
        shell,
        "_run_external",
        lambda argv, _spec, **_kwargs: calls.append(argv) or 0,
    )

    assert shell.execute("mc --subshell /tmp") == 0
    assert calls == [["/usr/bin/mc", "--subshell", "/tmp"]]


def test_mc_builtin_missing_external_returns_127(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = PyShell()

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda _name: None)
    with mock.patch.object(shell, "_run_external") as run_external:
        assert shell.execute("mc") == 127
    run_external.assert_not_called()
