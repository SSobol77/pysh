# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_safe_startup.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Security-recovery startup tests for GitHub Issue #43."""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pysh import cli
from pysh.config.api import ensure_default_config, load_python_config
from pysh.config.plugins import load_plugins
from pysh.config.rc import execute_rc
from pysh.config.startup import DEFAULT_STARTUP_POLICY, NO_RC_STARTUP_POLICY, StartupPolicy
from pysh.core import shell as shell_module
from pysh.core.shell import PyShell

REPO_ROOT = Path(__file__).parent.parent


def _configure_one_prompt_run(shell: PyShell, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``shell.run()`` execute startup and then receive immediate EOF."""
    monkeypatch.setattr(shell, "_print_banner", lambda: None)
    monkeypatch.setattr(shell, "_setup_readline", lambda: None)
    monkeypatch.setattr(shell, "_export_interactive_shell_vars", lambda: None)
    monkeypatch.setattr(shell, "_apply_cursor_color", lambda: None)
    monkeypatch.setattr(shell, "_reset_cursor_color", lambda: None)
    monkeypatch.setattr(shell, "_save_history", lambda: None)
    monkeypatch.setattr(shell, "_stdio_is_tty", lambda: False)
    monkeypatch.setattr(shell, "_reap_and_notify_jobs", lambda: None)
    monkeypatch.setattr(shell, "_prompt_info_line", lambda: "")
    monkeypatch.setattr(shell, "_should_use_raw_editor", lambda: False)

    def end_of_input() -> str:
        raise EOFError

    monkeypatch.setattr(shell, "_read_interactive_line", end_of_input)


def _install_user_startup_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shell: PyShell,
    *,
    create_python_rc: bool = True,
) -> tuple[list[str], Path, Path]:
    """Install isolated startup files and route startup loaders to them."""
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    rc_path = home / ".pyshrc"
    rc_path.write_text("RC_STARTUP_MARKER=loaded\n", encoding="utf-8")

    rc_dir = home / ".pyshrc.d"
    rc_dir.mkdir()
    (rc_dir / "10-marker.pysh").write_text(
        "RC_DIR_STARTUP_MARKER=loaded\n",
        encoding="utf-8",
    )

    python_rc = home / ".pyshrc.py"
    if create_python_rc:
        python_rc.write_text(
            "def configure(shell):\n"
            "    shell.alias('python_rc_marker', 'echo loaded')\n"
            "    shell.enable_plugin('startup_plugin')\n"
            "    shell.enable_project_plugins()\n"
            "    shell.register_startup_hook(\n"
            "        lambda: shell.alias('python_hook_marker', 'echo loaded')\n"
            "    )\n",
            encoding="utf-8",
        )

    toml_path = xdg / "pysh" / "config.toml"
    calls: list[str] = []

    def load_rc(executor) -> int:
        calls.append("rc")
        return execute_rc(rc_path, executor)

    def load_rc_directory(executor, *, directory: Path) -> list[Path]:
        del directory
        calls.append("rc_dir")
        return load_plugins(executor, directory=rc_dir)

    def ensure_toml() -> bool:
        calls.append("ensure_toml")
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text("[profile]\nactive = 'default'\n", encoding="utf-8")
        return True

    def apply_toml(target: object) -> SimpleNamespace:
        del target
        calls.append("toml")
        return SimpleNamespace(
            profiles=shell.config_profiles,
            themes=shell.config_themes,
            diagnostics=[],
            loaded_paths=[toml_path],
        )

    def ensure_python_rc() -> bool:
        calls.append("ensure_python_rc")
        return ensure_default_config(python_rc)

    def load_python_rc(target: object) -> int:
        calls.append("python_rc")
        return load_python_config(target, path=python_rc)  # type: ignore[arg-type]

    monkeypatch.setattr(shell_module, "load_default_rc", load_rc)
    monkeypatch.setattr(shell_module, "load_plugins", load_rc_directory)
    monkeypatch.setattr(shell_module, "ensure_default_toml_config", ensure_toml)
    monkeypatch.setattr(shell_module, "apply_declarative_config", apply_toml)
    monkeypatch.setattr(shell_module, "ensure_default_config", ensure_python_rc)
    monkeypatch.setattr(shell_module, "load_python_config", load_python_rc)
    monkeypatch.setattr(
        shell.plugin_manager,
        "discover_and_load",
        lambda: calls.append("plugin_discovery"),
    )
    monkeypatch.setattr(
        shell.plugin_manager,
        "run_startup_hooks",
        lambda: calls.append("plugin_hooks"),
    )
    _configure_one_prompt_run(shell, monkeypatch)
    return calls, python_rc, toml_path


def test_no_rc_suppresses_pyshrc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    calls, _, _ = _install_user_startup_fixture(tmp_path, monkeypatch, shell)

    assert shell.run() == 0
    assert "rc" not in calls
    assert "RC_STARTUP_MARKER" not in shell.local_vars


def test_no_rc_suppresses_python_rc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    calls, _, _ = _install_user_startup_fixture(tmp_path, monkeypatch, shell)

    assert shell.run() == 0
    assert "python_rc" not in calls
    assert "python_rc_marker" not in shell.aliases
    assert "python_hook_marker" not in shell.aliases
    assert not shell.is_plugin_enabled("startup_plugin")
    assert not shell.plugin_manager.registry.project_plugins_enabled


def test_no_rc_suppresses_pyshrc_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    calls, _, _ = _install_user_startup_fixture(tmp_path, monkeypatch, shell)

    assert shell.run() == 0
    assert "rc_dir" not in calls
    assert "RC_DIR_STARTUP_MARKER" not in shell.local_vars


def test_no_rc_skips_toml_plugin_loading_and_all_startup_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    calls, _, toml_path = _install_user_startup_fixture(tmp_path, monkeypatch, shell)

    assert shell.run() == 0
    assert calls == []
    assert not toml_path.exists()
    assert not shell.is_plugin_enabled("startup_plugin")
    assert not shell.plugin_manager.registry.project_plugins_enabled


def test_no_rc_does_not_create_python_rc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    calls, python_rc, _ = _install_user_startup_fixture(
        tmp_path,
        monkeypatch,
        shell,
        create_python_rc=False,
    )

    assert not python_rc.exists()
    assert shell.run() == 0
    assert not python_rc.exists()
    assert "ensure_python_rc" not in calls


def test_normal_interactive_startup_remains_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = PyShell(startup_policy=DEFAULT_STARTUP_POLICY)
    calls, python_rc, toml_path = _install_user_startup_fixture(tmp_path, monkeypatch, shell)

    assert shell.run() == 0
    assert shell.local_vars["RC_STARTUP_MARKER"] == "loaded"
    assert shell.local_vars["RC_DIR_STARTUP_MARKER"] == "loaded"
    assert shell.aliases["python_rc_marker"] == "echo loaded"
    assert shell.aliases["python_hook_marker"] == "echo loaded"
    assert shell.is_plugin_enabled("startup_plugin")
    assert shell.plugin_manager.registry.project_plugins_enabled
    assert python_rc.exists()
    assert toml_path.exists()
    assert calls == [
        "rc",
        "rc_dir",
        "ensure_toml",
        "toml",
        "ensure_python_rc",
        "python_rc",
        "plugin_discovery",
        "plugin_hooks",
    ]


def test_no_rc_cli_policy_reaches_interactive_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[StartupPolicy] = []

    class RecordingShell:
        def __init__(self, *, trace: object, startup_policy: StartupPolicy) -> None:
            del trace
            observed.append(startup_policy)

        def run(self) -> int:
            return 0

    class TtyInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli, "PyShell", RecordingShell)
    monkeypatch.setattr(cli.sys, "stdin", TtyInput())

    assert cli.main(["--no-rc"]) == 0
    assert observed == [NO_RC_STARTUP_POLICY]


def test_no_rc_dash_c_executes_requested_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".pyshrc").write_text("echo startup-must-not-run\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert cli.main(["--no-rc", "-c", "echo safe-command"]) == 0
    captured = capfd.readouterr()
    assert captured.out == "safe-command\n"
    assert "startup-must-not-run" not in captured.out


def test_python_module_accepts_no_rc_dash_c(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".pyshrc.py").write_text(
        "raise RuntimeError('module startup must not run')\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")

    result = subprocess.run(
        [sys.executable, "-m", "pysh", "--no-rc", "-c", "echo module-safe"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == "module-safe\n"
    assert result.stderr == ""
