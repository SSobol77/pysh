# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_pyshrc_py.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the Python-native configuration layer (``~/.pyshrc.py``)."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from pysh.config_api import (
    DEFAULT_PROMPT_OPTIONS,
    ConfigError,
    ShellConfigAPI,
    ensure_default_config,
    load_python_config,
    validate_prompt_option,
)
from pysh.shell import PyShell


class FakeShell:
    """Minimal ConfigurableShell used for unit-level API tests."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.environment: dict[str, str] = {}
        self.prompt_options: dict[str, object] = dict(DEFAULT_PROMPT_OPTIONS)

    def register_alias(self, name: str, value: str) -> None:
        self.aliases[name] = value

    def set_environment(self, name: str, value: str) -> None:
        self.environment[name] = value

    def set_prompt_option(self, name: str, value: object) -> None:
        validate_prompt_option(name, value)
        self.prompt_options[name] = value


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _use_legacy_single_line_prompt(shell: PyShell) -> None:
    shell.set_prompt_option("prompt_layout", "single")
    shell.set_prompt_option("symbol", "$")


# --------------------------------------------------------------- file creation
def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:
    target = tmp_path / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()
    assert "def configure" in target.read_text(encoding="utf-8")


def test_ensure_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()


def test_ensure_does_not_overwrite_existing(tmp_path: Path) -> None:
    target = _write(tmp_path / ".pyshrc.py", "# user content\n")
    assert ensure_default_config(target) is False
    assert target.read_text(encoding="utf-8") == "# user content\n"


def test_default_template_is_inert(tmp_path: Path) -> None:
    # The generated configure() must not change any state on first run.
    target = tmp_path / ".pyshrc.py"
    ensure_default_config(target)
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases == {}
    assert shell.environment == {}
    assert shell.prompt_options == DEFAULT_PROMPT_OPTIONS


# ------------------------------------------------------------------- API layer
def test_api_alias_registration() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).alias("ll", "ls -la")
    assert shell.aliases == {"ll": "ls -la"}


def test_api_env_registration() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).env("EDITOR", "nano")
    assert shell.environment == {"EDITOR": "nano"}


@pytest.mark.parametrize("name", ["bad name", "", "a=b"])
def test_api_alias_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).alias(name, "value")


@pytest.mark.parametrize("name", ["1BAD", "with-dash", "has space", ""])
def test_api_env_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).env(name, "value")


def test_api_alias_rejects_non_string_value() -> None:
    with pytest.raises(ConfigError):
        ShellConfigAPI(FakeShell()).alias("ll", 123)  # type: ignore[arg-type]


# -------------------------------------------------------------- prompt options
def test_validate_prompt_option_unknown_name() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("does_not_exist", True)


def test_validate_prompt_option_wrong_type() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("symbol", 5)
    with pytest.raises(ConfigError):
        validate_prompt_option("show_user", "yes")


def test_validate_prompt_option_rejects_invalid_cwd_style() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("cwd_style", "short")


def test_api_set_prompt_option_applies() -> None:
    shell = FakeShell()
    ShellConfigAPI(shell).set_prompt_option("show_python_version", True)
    assert shell.prompt_options["show_python_version"] is True


def test_default_prompt_options_match_contract() -> None:
    assert DEFAULT_PROMPT_OPTIONS == {
        "show_user": True,
        "show_host": False,
        "show_python_version": False,
        "show_virtualenv": False,
        "show_git_branch": False,
        "show_git_dirty": False,
        "show_last_status": False,
        "show_cwd": True,
        "show_uv_version": False,
        "show_ruff_version": False,
        "cwd_style": "full",
        "symbol": ">",
        "prompt_layout": "two_line",
    }


@pytest.mark.parametrize(
    "name",
    [
        "show_virtualenv",
        "show_git_branch",
        "show_git_dirty",
        "show_last_status",
        "show_cwd",
        "show_uv_version",
        "show_ruff_version",
    ],
)
def test_validate_prompt_bool_options_reject_non_bool(name: str) -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option(name, "true")


def test_validate_prompt_option_rejects_invalid_prompt_layout() -> None:
    with pytest.raises(ConfigError):
        validate_prompt_option("prompt_layout", "stacked")


# ---------------------------------------------------------------- loader paths
def test_load_missing_file_returns_zero(tmp_path: Path) -> None:
    assert load_python_config(FakeShell(), path=tmp_path / "nope.py") == 0


def test_load_registers_alias_and_env(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n"
        "    shell.alias('ll', 'ls -la')\n"
        "    shell.env('EDITOR', 'nano')\n",
    )
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases == {"ll": "ls -la"}
    assert shell.environment == {"EDITOR": "nano"}


def test_load_sets_prompt_option(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n"
        "    shell.set_prompt_option('show_python_version', True)\n",
    )
    shell = FakeShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.prompt_options["show_python_version"] is True


def test_load_without_configure_is_ok(tmp_path: Path) -> None:
    target = _write(tmp_path / ".pyshrc.py", "X = 1\n")
    assert load_python_config(FakeShell(), path=target) == 0


def test_load_configure_not_callable(tmp_path: Path, capsys) -> None:
    target = _write(tmp_path / ".pyshrc.py", "configure = 42\n")
    assert load_python_config(FakeShell(), path=target) == 1
    assert "not callable" in capsys.readouterr().err


def test_load_syntax_error_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(tmp_path / ".pyshrc.py", "def configure(shell):\n    x = =\n")
    assert load_python_config(FakeShell(), path=target) == 1
    assert "syntax error" in capsys.readouterr().err


def test_load_configure_exception_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    raise RuntimeError('boom')\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "boom" in capsys.readouterr().err


def test_load_invalid_config_call_is_contained(tmp_path: Path, capsys) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    shell.set_prompt_option('nope', True)\n",
    )
    assert load_python_config(FakeShell(), path=target) == 1
    assert "unknown prompt option" in capsys.readouterr().err


# --------------------------------------------------- integration with PyShell
def test_pyshell_default_prompt_is_two_line(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    assert shell._prompt_info_line() == f"🐍 tester:{tmp_path}"
    assert shell._prompt() == "> "


def test_pyshell_single_layout_uses_prompt_body(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    shell.set_prompt_option("prompt_layout", "single")
    assert shell._prompt_info_line() == ""
    assert shell._prompt() == shell._prompt_body(shell.prompt_options) + "> "


def test_pyshell_prompt_exact_compatibility_progression(monkeypatch) -> None:
    monkeypatch.setenv("USER", "siergej")
    monkeypatch.setattr(socket, "gethostname", lambda: "vm")
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/home/claude/work")))
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    py = ".".join(str(p) for p in sys.version_info[:2])

    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    assert shell._prompt() == "🐍 siergej:/home/claude/work$ "

    shell.set_prompt_option("show_python_version", True)
    assert shell._prompt() == f"🐍 siergej:/home/claude/work py{py}$ "

    shell.set_prompt_option("show_host", True)
    assert shell._prompt() == f"🐍 siergej@vm:/home/claude/work py{py}$ "

    shell.set_prompt_option("symbol", "%")
    assert shell._prompt() == f"🐍 siergej@vm:/home/claude/work py{py}% "


def test_pyshell_prompt_python_version_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_python_version", True)
    assert " py3." in shell._prompt()


def test_pyshell_prompt_host_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_host", True)
    assert "tester@" in shell._prompt()


def test_pyshell_prompt_custom_symbol(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    shell.set_prompt_option("prompt_layout", "single")
    shell.set_prompt_option("symbol", "%")
    assert shell._prompt().endswith("% ")


def test_pyshell_prompt_tool_version_is_cached(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "uv 0.9.16\n"

    def fake_run(argv, **_kwargs):  # noqa: ANN001,ANN202 - local subprocess test double.
        calls.append(argv)
        return Result()

    monkeypatch.setattr("pysh.shell.subprocess.run", fake_run)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_uv_version", True)
    assert " uv0.9.16$ " in shell._prompt()
    assert " uv0.9.16$ " in shell._prompt()
    assert calls == [["uv", "--version"]]


def test_pyshell_prompt_tool_version_malformed_output_is_hidden(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "uv unknown\n"

    monkeypatch.setattr("pysh.shell.subprocess.run", lambda *_args, **_kwargs: Result())
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_uv_version", True)
    assert " uv" not in shell._prompt()


def test_pyshell_set_environment_is_mirrored(monkeypatch) -> None:
    monkeypatch.delenv("PYSH_TEST_VAR", raising=False)
    shell = PyShell()
    shell.set_environment("PYSH_TEST_VAR", "1")
    import os

    assert os.environ["PYSH_TEST_VAR"] == "1"
    assert shell.local_vars["PYSH_TEST_VAR"] == "1"


def test_pyshell_loads_config_file(tmp_path: Path) -> None:
    target = _write(
        tmp_path / ".pyshrc.py",
        "def configure(shell):\n    shell.alias('gg', 'git status')\n",
    )
    shell = PyShell()
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases["gg"] == "git status"


def test_pyshell_set_prompt_option_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        PyShell().set_prompt_option("unknown", True)


def test_pyshell_set_prompt_option_rejects_invalid_prompt_layout() -> None:
    with pytest.raises(ValueError):
        PyShell().set_prompt_option("prompt_layout", "stacked")


def test_pyshell_prompt_is_readline_safe(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    assert "\n" not in shell._prompt()
    shell.set_prompt_option("prompt_layout", "single")
    assert "\n" not in shell._prompt()


def test_pyshell_prompt_virtualenv_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/pysh-test-venv")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_virtualenv", True)
    assert shell._prompt().startswith("(pysh-test-venv) ")


def test_pyshell_prompt_last_status_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.last_status = 17
    shell.set_prompt_option("show_last_status", True)
    assert " [17]$ " in shell._prompt()


def test_pyshell_prompt_hides_zero_last_status(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.last_status = 0
    shell.set_prompt_option("show_last_status", True)
    assert " [0]" not in shell._prompt()


def test_pyshell_two_line_last_status_segment(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    shell.set_prompt_option("show_last_status", True)
    assert " [0]" not in shell._prompt_info_line()
    shell.last_status = 17
    assert " [17]" in shell._prompt_info_line()


def test_pyshell_prompt_cwd_basename(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USER", "tester")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("cwd_style", "basename")
    assert "tester:project" in shell._prompt()


def test_pyshell_prompt_cwd_full(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USER", "tester")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("cwd_style", "full")
    assert f"tester:{project}" in shell._prompt()


def test_pyshell_prompt_cwd_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USER", "tester")
    home = tmp_path / "home"
    project = home / "work"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("cwd_style", "home")
    assert "tester:~/work" in shell._prompt()


def test_pyshell_prompt_cwd_can_be_hidden(monkeypatch) -> None:
    monkeypatch.setenv("USER", "tester")
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_cwd", False)
    assert "tester$ " in shell._prompt()
    assert "tester:" not in shell._prompt()


def test_pyshell_prompt_git_branch_from_git_directory(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_git_branch", True)
    assert " git:main$ " in shell._prompt()


def test_pyshell_prompt_git_branch_from_git_file(monkeypatch, tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    real_git = tmp_path / "real-git-dir"
    worktree.mkdir()
    real_git.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_git}\n", encoding="utf-8")
    (real_git / "HEAD").write_text("ref: refs/heads/feature/prompt\n", encoding="utf-8")
    monkeypatch.chdir(worktree)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_git_branch", True)
    assert " git:feature/prompt$ " in shell._prompt()


def test_pyshell_prompt_git_detached_head(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_git_branch", True)
    assert " git:detached-0123456$ " in shell._prompt()


def test_pyshell_prompt_git_obvious_dirty_state(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "index.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(repo)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_git_dirty", True)
    assert " git:main*$ " in shell._prompt()


def test_pyshell_two_line_fully_enabled_exact_render(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home" / "ssobol"
    cwd = home / "Code" / "Project_PySH" / "pysh" / "pysh"
    git_dir = cwd / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    venv = cwd / ".venv"
    venv.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("USER", "ssobol")
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(socket, "gethostname", lambda: "sun")
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))

    class Result:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout

    def fake_run(argv, **_kwargs):  # noqa: ANN001,ANN202 - local subprocess test double.
        if argv[0] == "uv":
            return Result("uv 0.9.16\n")
        if argv[0] == "ruff":
            return Result("ruff 0.15.15\n")
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("pysh.shell.subprocess.run", fake_run)
    shell = PyShell()
    shell.set_prompt_option("show_host", True)
    shell.set_prompt_option("show_virtualenv", True)
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_git_dirty", True)
    shell.set_prompt_option("show_python_version", True)
    shell.set_prompt_option("show_uv_version", True)
    shell.set_prompt_option("show_ruff_version", True)
    shell.set_prompt_option("cwd_style", "home")
    py = ".".join(str(p) for p in sys.version_info[:2])

    assert shell._prompt_info_line() == (
        "(.venv) 🐍 ssobol@sun:~/Code/Project_PySH/pysh/pysh "
        f"git:main py{py} uv0.9.16 ruff0.15.15"
    )
    assert shell._prompt() == "> "
