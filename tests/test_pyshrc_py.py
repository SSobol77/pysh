# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_pyshrc_py.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the Python-native configuration layer (``~/.pyshrc.py``)."""
from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

import pytest

from pysh.config.api import (
    DEFAULT_CURSOR_OPTIONS,
    DEFAULT_EDITOR_OPTIONS,
    DEFAULT_PROMPT_COLOR_MODES,
    DEFAULT_PROMPT_COLORS,
    DEFAULT_PROMPT_OPTIONS,
    DEFAULT_PYSHRC_PY,
    DEFAULT_SENSITIVE_INPUT,
    ConfigError,
    ShellConfigAPI,
    ensure_default_config,
    load_python_config,
    validate_prompt_color,
    validate_prompt_color_mode,
    validate_prompt_option,
)
from pysh.core.shell import PyShell


class FakeShell:
    """Minimal ConfigurableShell used for unit-level API tests."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.environment: dict[str, str] = {}
        self.prompt_options: dict[str, object] = dict(DEFAULT_PROMPT_OPTIONS)
        self.editor_options: dict[str, object] = dict(DEFAULT_EDITOR_OPTIONS)
        self.prompt_colors: dict[str, str] = dict(DEFAULT_PROMPT_COLORS)
        self.prompt_color_modes: dict[str, object] = dict(DEFAULT_PROMPT_COLOR_MODES)

    def register_alias(self, name: str, value: str) -> None:
        self.aliases[name] = value

    def set_environment(self, name: str, value: str) -> None:
        self.environment[name] = value

    def set_prompt_option(self, name: str, value: object) -> None:
        validate_prompt_option(name, value)
        self.prompt_options[name] = value

    def set_editor_option(self, name: str, value: object) -> None:
        from pysh.config.api import validate_editor_option

        validate_editor_option(name, value)
        self.editor_options[name] = value

    def set_mc_integration(self, value: str) -> None:
        from pysh.config.api import validate_editor_option

        validate_editor_option("mc_integration", value)
        self.editor_options["mc_integration"] = value

    def set_mc_warning_enabled(self, value: bool) -> None:
        from pysh.config.api import validate_editor_option

        validate_editor_option("mc_warning_enabled", value)
        self.editor_options["mc_warning_enabled"] = value

    def set_prompt_color(self, segment: str, color: str) -> None:
        validate_prompt_color(segment, color)
        self.prompt_colors[segment] = color

    def set_prompt_color_mode(self, name: str, value: object) -> None:
        validate_prompt_color_mode(name, value)
        self.prompt_color_modes[name] = value


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


@pytest.fixture(autouse=True)
def _hide_external_prompt_tools(monkeypatch) -> None:
    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda _executable: None)


def _use_legacy_single_line_prompt(shell: PyShell) -> None:
    shell.set_prompt_option("prompt_layout", "single")
    shell.set_prompt_option("symbol", "$")
    shell.set_prompt_option("show_host", False)
    shell.set_prompt_option("show_virtualenv", False)
    shell.set_prompt_option("show_git_branch", False)
    shell.set_prompt_option("show_git_dirty", False)
    shell.set_prompt_option("show_python_version", False)
    shell.set_prompt_option("show_uv_version", False)
    shell.set_prompt_option("show_ruff_version", False)
    shell.set_prompt_option("show_rust_version", False)
    shell.set_prompt_option("show_node_version", False)
    shell.set_prompt_option("show_npm_version", False)
    shell.set_prompt_option("show_last_status", False)
    shell.set_prompt_option("cwd_style", "full")


# --------------------------------------------------------------- file creation
def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:
    target = tmp_path / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()
    assert target.read_text(encoding="utf-8") == DEFAULT_PYSHRC_PY


def test_default_template_is_exact_accepted_production_template() -> None:
    expected = """\
# PySH Python-native configuration: ~/.pyshrc.py
#
# This file is loaded after the legacy ~/.pyshrc file and after all
# ~/.pyshrc.d/*.pysh plugin snippets. Values configured here have the final
# priority for the interactive PySH session.
#
# The file is ordinary Python. Keep all configuration inside configure(shell).
# Every setting below is optional. Comment out any block you do not want.
#
# Security note:
# PySH does not intercept passwords for ordinary commands such as:
#
#     sudo apt upgrade
#     ssh host
#     su
#     gpg
#
# Sensitive input indication is available only for explicit secure commands:
#
#     secure sudo -v
#     secure sudo apt upgrade
#
# The secure indicator never shows one symbol per password character and never
# reveals password length. It uses a fixed-size rotating activity indicator.


def configure(shell):
    \"\"\"Configure the interactive PySH session.\"\"\"

    # ----------------------------------------------------------------------
    # Aliases
    # ----------------------------------------------------------------------
    # Aliases are expanded on the first word of each command or pipeline stage.
    # Keep aliases simple and deterministic.

    shell.alias("ll", "ls -la --color=auto -F")
    shell.alias("la", "ls -la --color=auto -F")
    shell.alias("gs", "git status -sb")
    shell.alias("gd", "git diff")
    shell.alias("gl", "git log --oneline --decorate --graph -20")
    shell.alias("pyv", "python -V")
    shell.alias("uvt", "uv run pytest -q")
    shell.alias("uvr", "uv run ruff check src tests")
    shell.alias("uvpysh", "uv run pysh")

    # ----------------------------------------------------------------------
    # Environment
    # ----------------------------------------------------------------------
    # These values are exported for child processes and also mirrored into
    # PySH local variable expansion.

    shell.env("EDITOR", "nano")
    shell.env("PAGER", "less")
    shell.env("PYTHONDONTWRITEBYTECODE", "1")

    # ----------------------------------------------------------------------
    # Prompt layout and prompt segments
    # ----------------------------------------------------------------------
    # PySH uses a framed three-line prompt:
    #
    #   ┌─(.venv) 🐍 user@host ─ [~/project] ─ git:main
    #   │  py3.13 · uv0.11.17 · ruff0.15.15
    #   └─❯
    #
    # The command symbol is on a separate readline line for stability.

    shell.set_prompt_option("prompt_layout", "two_line")
    shell.set_prompt_option("symbol", ">")

    # Identity and location.
    shell.set_prompt_option("show_user", True)
    shell.set_prompt_option("show_host", True)
    shell.set_prompt_option("show_cwd", True)
    shell.set_prompt_option("cwd_style", "home")  # full | home | basename

    # Runtime / project context.
    shell.set_prompt_option("show_virtualenv", True)
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_git_dirty", True)
    shell.set_prompt_option("show_last_status", True)

    # Language and tool versions.
    shell.set_prompt_option("show_python_version", True)
    shell.set_prompt_option("show_uv_version", True)
    shell.set_prompt_option("show_ruff_version", True)
    shell.set_prompt_option("show_rust_version", True)
    shell.set_prompt_option("show_node_version", True)
    shell.set_prompt_option("show_npm_version", True)

    # ----------------------------------------------------------------------
    # Prompt colors
    # ----------------------------------------------------------------------
    # Colors accept canonical names or #RRGGBB values.
    #
    # VGA mode:
    #   True  -> map colors to nearest ANSI/VGA 16-color foreground.
    #   False -> emit ANSI 24-bit truecolor.
    #
    # Use VGA=True for maximum terminal compatibility.
    # Use VGA=False for richer modern terminals.

    shell.set_prompt_color_mode("vga", True)

    shell.set_prompt_color("venv", "fuchsia")
    shell.set_prompt_color("icon", "lime")
    shell.set_prompt_color("user", "lime")
    shell.set_prompt_color("host", "aqua")
    shell.set_prompt_color("cwd", "yellow")
    shell.set_prompt_color("git", "green")
    shell.set_prompt_color("python", "blue")
    shell.set_prompt_color("uv", "purple")
    shell.set_prompt_color("ruff", "teal")
    shell.set_prompt_color("rust", "#FF6600")
    shell.set_prompt_color("node", "lime")
    shell.set_prompt_color("npm", "red")
    shell.set_prompt_color("status", "red")
    shell.set_prompt_color("symbol", "white")

    # ----------------------------------------------------------------------
    # Terminal cursor color
    # ----------------------------------------------------------------------
    # Cursor coloring uses terminal OSC 12 when supported.
    # It is best-effort and resets when PySH exits.
    #
    # Recommended orange cursor:
    #
    #   #FF9900
    #
    # If your terminal does not support OSC 12, this setting is simply ignored
    # by the terminal.

    shell.set_cursor_color_enabled(True)
    shell.set_cursor_color("#FF9900")

    # ----------------------------------------------------------------------
    # Line editor
    # ----------------------------------------------------------------------
    # line_editor:
    #   auto     -> use PySH raw-mode editor on capable TTYs.
    #   readline -> force classic readline/input fallback.
    #   basic    -> raw editor without highlighting/autosuggest.
    #
    # mc_integration:
    #   auto     -> launch mc in PySH-safe mode when MC cannot use PySH as a
    #               supported concurrent subshell.
    #   safe     -> always add -u/--nosubshell for mc launched by PySH.
    #   subshell -> pass mc through unchanged; advanced users accept MC's
    #               shell-specific subshell behavior.
    #   off      -> disable PySH's mc wrapper policy.
    #
    # mc_warning_enabled:
    #   True  -> print one explanatory warning per PySH session in auto mode.
    #   False -> suppress that warning.
    #
    # autosuggest:
    #   Shows fish-style ghost-text suggestions from history.
    #
    # syntax_highlight:
    #   Colors the editable command line while typing.

    shell.set_editor_option("line_editor", "auto")
    shell.set_mc_integration("auto")
    shell.set_mc_warning_enabled(True)
    shell.set_editor_option("autosuggest", True)
    shell.set_editor_option("syntax_highlight", True)

    # Emergency fallback if the terminal behaves incorrectly:
    #
    # shell.set_editor_option("line_editor", "readline")

    # ----------------------------------------------------------------------
    # Sensitive input indicator for explicit secure commands
    # ----------------------------------------------------------------------
    # This applies ONLY to:
    #
    #     secure <command> [args...]
    #
    # It does NOT affect ordinary commands.
    #
    # Security model:
    # - The indicator is fixed-size.
    # - It never grows with typed password length.
    # - It never shows one star per character.
    # - It never reveals the password length.
    # - It never indicates password correctness.
    # - It never turns permanently green on success or red on failure.
    #
    # Ring mode:
    # - Displays a fixed indicator, for example:
    #
    #     * * * * *
    #
    # - Each keypress advances the active green slot by one position.
    # - All other slots remain idle/white.
    # - After the last slot, the active slot wraps back to the first one.
    #
    # Example:
    #   key 1 -> slot 1 active
    #   key 2 -> slot 2 active
    #   key 3 -> slot 3 active
    #   key 4 -> slot 4 active
    #   key 5 -> slot 5 active
    #   key 6 -> slot 1 active again

    shell.set_sensitive_input_indicator("enabled", True)
    shell.set_sensitive_input_indicator("symbol", "*")
    shell.set_sensitive_input_indicator("idle_color", "white")
    shell.set_sensitive_input_indicator("active_color", "lime")
    shell.set_sensitive_input_indicator("mode", "ring")
    shell.set_sensitive_input_indicator("slots", 5)

    # For a smaller indicator:
    #
    # shell.set_sensitive_input_indicator("slots", 3)
    #
    # For compatibility with the old one-symbol blink mode:
    #
    # shell.set_sensitive_input_indicator("mode", "single-blink")

    # ----------------------------------------------------------------------
    # Optional classic minimal prompt profile
    # ----------------------------------------------------------------------
    # Uncomment this block if you want a small historical prompt:
    #
    # shell.set_prompt_option("prompt_layout", "single")
    # shell.set_prompt_option("symbol", "$")
    # shell.set_prompt_option("show_host", False)
    # shell.set_prompt_option("show_virtualenv", False)
    # shell.set_prompt_option("show_git_branch", False)
    # shell.set_prompt_option("show_git_dirty", False)
    # shell.set_prompt_option("show_python_version", False)
    # shell.set_prompt_option("show_uv_version", False)
    # shell.set_prompt_option("show_ruff_version", False)
    # shell.set_prompt_option("show_rust_version", False)
    # shell.set_prompt_option("show_node_version", False)
    # shell.set_prompt_option("show_npm_version", False)
    # shell.set_prompt_option("show_last_status", False)

    return None
"""
    assert DEFAULT_PYSHRC_PY == expected


def test_ensure_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / ".pyshrc.py"
    assert ensure_default_config(target) is True
    assert target.exists()


def test_ensure_does_not_overwrite_existing(tmp_path: Path) -> None:
    target = _write(tmp_path / ".pyshrc.py", "# user content\n")
    assert ensure_default_config(target) is False
    assert target.read_text(encoding="utf-8") == "# user content\n"


def test_ensure_creation_failure_reports_deterministic_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent_file = _write(tmp_path / "not-a-directory", "")
    target = parent_file / ".pyshrc.py"

    assert ensure_default_config(target) is False

    assert capsys.readouterr().err.startswith(f"pysh: cannot create {target}: ")
    assert not target.exists()


def test_default_template_applies_accepted_active_profile(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / ".pyshrc.py"
    ensure_default_config(target)
    shell = PyShell()
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    assert load_python_config(shell, path=target) == 0
    assert shell.aliases["ll"] == "ls -la --color=auto -F"
    assert shell.aliases["uvr"] == "uv run ruff check src tests"
    assert shell.local_vars["EDITOR"] == "nano"
    assert shell.local_vars["PAGER"] == "less"
    assert shell.local_vars["PYTHONDONTWRITEBYTECODE"] == "1"
    assert shell.prompt_options == DEFAULT_PROMPT_OPTIONS
    assert shell.prompt_colors == {
        **DEFAULT_PROMPT_COLORS,
        "rust": "#FF6600",
    }
    assert shell.prompt_color_modes == DEFAULT_PROMPT_COLOR_MODES
    assert shell.cursor_options == {**DEFAULT_CURSOR_OPTIONS, "enabled": True, "color": "#FF9900"}
    assert shell.editor_options == DEFAULT_EDITOR_OPTIONS
    assert shell.sensitive_input == {**DEFAULT_SENSITIVE_INPUT, "enabled": True}


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


def test_api_set_prompt_color_valid_name_and_hex() -> None:
    shell = FakeShell()
    api = ShellConfigAPI(shell)
    api.set_prompt_color("user", "lime")
    api.set_prompt_color("python", "#33CCFF")
    assert shell.prompt_colors["user"] == "lime"
    assert shell.prompt_colors["python"] == "#33CCFF"


def test_api_set_prompt_color_rejects_invalid_segment_and_color() -> None:
    api = ShellConfigAPI(FakeShell())
    with pytest.raises(ConfigError):
        api.set_prompt_color("bad", "red")
    with pytest.raises(ConfigError):
        api.set_prompt_color("user", "red;")


def test_api_set_prompt_color_mode_accepts_and_rejects() -> None:
    shell = FakeShell()
    api = ShellConfigAPI(shell)
    api.set_prompt_color_mode("vga", True)
    api.set_prompt_color_mode("vga", False)
    assert shell.prompt_color_modes["vga"] is False
    with pytest.raises(ConfigError):
        api.set_prompt_color_mode("unknown", True)
    with pytest.raises(ConfigError):
        api.set_prompt_color_mode("vga", "yes")  # type: ignore[arg-type]


def test_default_prompt_options_match_contract() -> None:
    assert DEFAULT_PROMPT_OPTIONS == {
        "show_user": True,
        "show_host": True,
        "show_virtualenv": True,
        "show_git_branch": True,
        "show_git_dirty": True,
        "show_python_version": True,
        "show_uv_version": True,
        "show_ruff_version": True,
        "show_rust_version": True,
        "show_node_version": True,
        "show_npm_version": True,
        "show_last_status": True,
        "show_cwd": True,
        "cwd_style": "home",
        "prompt_layout": "two_line",
        "symbol": ">",
    }


@pytest.mark.parametrize(
    "name",
    [
        "show_user",
        "show_host",
        "show_python_version",
        "show_virtualenv",
        "show_git_branch",
        "show_git_dirty",
        "show_last_status",
        "show_cwd",
        "show_uv_version",
        "show_ruff_version",
        "show_rust_version",
        "show_node_version",
        "show_npm_version",
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
    monkeypatch.setattr(PyShell, "_unicode_capable", staticmethod(lambda: True))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: "vm")
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    info_line = shell._prompt_info_line()
    assert info_line  # not empty
    assert "🐍 tester@vm" in info_line
    assert f"[{tmp_path}]" in info_line  # CWD in brackets
    assert "py" in info_line  # Python version on line 2
    prompt = shell._prompt()
    assert "\n" not in prompt
    assert prompt == "└─❯ "


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


@pytest.mark.parametrize(
    ("option", "executable", "output", "expected"),
    [
        ("show_uv_version", "uv", "uv 0.9.16\n", "uv0.9.16"),
        ("show_ruff_version", "ruff", "ruff 0.15.15\n", "ruff0.15.15"),
        ("show_rust_version", "rustc", "rustc 1.83.0 (90b35a623 2024-11-26)\n", "rust1.83.0"),
        ("show_node_version", "node", "v22.3.0\n", "node22.3.0"),
        ("show_npm_version", "npm", "10.8.1\n", "npm10.8.1"),
    ],
)
def test_pyshell_prompt_tool_version_segments(
    monkeypatch,
    option: str,
    executable: str,
    output: str,
    expected: str,
) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = output
        stderr = ""

    def fake_run(argv, **_kwargs):  # noqa: ANN001,ANN202 - local subprocess test double.
        calls.append(argv)
        return Result()

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr("pysh.core.shell.subprocess.run", fake_run)
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option(option, True)
    assert f" {expected}$ " in shell._prompt()
    assert f" {expected}$ " in shell._prompt()
    assert calls == [[executable, "--version"]]


def test_pyshell_prompt_tool_version_malformed_output_is_hidden(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "uv unknown\n"
        stderr = ""

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr("pysh.core.shell.subprocess.run", lambda *_args, **_kwargs: Result())
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_uv_version", True)
    assert " uv" not in shell._prompt()


def test_pyshell_prompt_missing_tool_is_hidden(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda _exe: None)
    monkeypatch.setattr("pysh.core.shell.subprocess.run", lambda argv, **_kwargs: calls.append(argv))
    shell = PyShell()
    _use_legacy_single_line_prompt(shell)
    shell.set_prompt_option("show_node_version", True)
    assert " node" not in shell._prompt()
    assert calls == []


def test_pyshell_prompt_all_tool_versions_are_cached(monkeypatch) -> None:
    calls: list[list[str]] = []
    outputs = {
        "uv": "uv 0.9.16\n",
        "ruff": "ruff 0.15.15\n",
        "rustc": "rustc 1.83.0 (90b35a623 2024-11-26)\n",
        "node": "v22.3.0\n",
        "npm": "10.8.1\n",
    }

    class Result:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(argv, **_kwargs):  # noqa: ANN001,ANN202 - local subprocess test double.
        calls.append(argv)
        return Result(outputs[argv[0]])

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr("pysh.core.shell.subprocess.run", fake_run)
    shell = PyShell()
    shell._prompt_info_line()
    shell._prompt_info_line()
    assert calls == [
        ["uv", "--version"],
        ["ruff", "--version"],
        ["rustc", "--version"],
        ["node", "--version"],
        ["npm", "--version"],
    ]


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
    monkeypatch.setattr(PyShell, "_unicode_capable", staticmethod(lambda: True))

    class Result:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(argv, **_kwargs):  # noqa: ANN001,ANN202 - local subprocess test double.
        if argv[0] == "uv":
            return Result("uv 0.9.16\n")
        if argv[0] == "ruff":
            return Result("ruff 0.15.15\n")
        if argv[0] == "rustc":
            return Result("rustc 1.83.0 (90b35a623 2024-11-26)\n")
        if argv[0] == "node":
            return Result("v22.3.0\n")
        if argv[0] == "npm":
            return Result("10.8.1\n")
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("pysh.core.shell.shutil.which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr("pysh.core.shell.subprocess.run", fake_run)
    shell = PyShell()
    shell.set_prompt_option("cwd_style", "home")
    py = ".".join(str(p) for p in sys.version_info[:2])

    info = shell._prompt_info_line()
    line1, line2 = info.split("\n", 1)
    assert line1 == "┌─(.venv) 🐍 ssobol@sun ─ [~/Code/Project_PySH/pysh/pysh] ─ git:main"
    assert line2 == f"│  py{py} · uv0.9.16 · ruff0.15.15 · rust1.83.0 · node22.3.0 · npm10.8.1"
    assert shell._prompt() == "└─❯ "


def test_colored_prompt_contains_ansi_and_preserves_semantics(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: "vm")
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    plain_info = shell._prompt_info_line()
    plain_prompt = shell._prompt()
    monkeypatch.setattr(shell, "_prompt_colors_enabled", lambda: True)
    colored_info = shell._prompt_info_line()
    colored_prompt = shell._prompt()
    assert "\x1b[" in colored_info
    assert "\x1b[" in colored_prompt
    assert strip_ansi(colored_info) == plain_info
    assert strip_ansi(colored_prompt) == plain_prompt
    assert "\n" not in colored_prompt


def test_colored_prompt_truecolor_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    shell.set_prompt_color_mode("vga", False)
    shell.set_prompt_color("user", "#33CCFF")
    monkeypatch.setattr(shell, "_prompt_colors_enabled", lambda: True)
    assert "\x1b[38;2;51;204;255mtester" in shell._prompt_info_line()


def test_prompt_color_gate_disabled_emits_no_ansi(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(PyShell, "_prompt_icon", staticmethod(lambda: "🐍"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.chdir(tmp_path)
    shell = PyShell()
    monkeypatch.setattr(shell, "_prompt_colors_enabled", lambda: False)
    assert "\x1b[" not in shell._prompt_info_line()
    assert "\x1b[" not in shell._prompt()
