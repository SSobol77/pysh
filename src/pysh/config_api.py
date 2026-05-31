# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/config_api.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Python-native configuration layer for PySH (``~/.pyshrc.py``).

This module adds an additive, Python-first configuration path that runs
*after* the legacy ``~/.pyshrc`` and ``~/.pyshrc.d/*.pysh`` plugins, so that
Python configuration has the final word. The legacy shell-syntax layer is
left fully intact.

The configuration contract is intentionally small and stable. A user config
file defines a top-level ``configure`` function that receives a
:class:`ShellConfigAPI` instance::

    def configure(shell):
        shell.alias("ll", "ls -la --color=auto -F")
        shell.env("EDITOR", "nano")
        shell.set_prompt_option("show_python_version", True)

The API operates against the :class:`ConfigurableShell` protocol rather than
the concrete shell, which keeps this module decoupled from ``shell.py`` (no
import cycle) and independently testable with a lightweight fake shell.

User configuration must never crash the interactive session: import errors,
syntax errors and exceptions raised from ``configure`` are reported on stderr
and turned into a non-zero return code, but the shell keeps running.
"""
from __future__ import annotations

import importlib.util
import itertools
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, runtime_checkable

from pysh.colors import parse_color
from pysh.lineedit.buffer import _display_width

# Canonical location of the Python-native user configuration file.
PYSHRC_PY_PATH = Path("~/.pyshrc.py").expanduser()

# Name of the function PySH calls inside ``~/.pyshrc.py``.
CONFIGURE_FUNCTION = "configure"

# Default prompt options for the two-line prompt layout.
DEFAULT_PROMPT_OPTIONS: dict[str, object] = {
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

# Expected value type for each prompt option. ``bool`` is intentionally
# distinct from ``int`` here: ``isinstance(1, bool)`` is ``False`` so a stray
# integer is rejected for a boolean option.
PROMPT_OPTION_TYPES: dict[str, type] = {
    "show_user": bool,
    "show_host": bool,
    "show_python_version": bool,
    "show_virtualenv": bool,
    "show_git_branch": bool,
    "show_git_dirty": bool,
    "show_last_status": bool,
    "show_cwd": bool,
    "show_uv_version": bool,
    "show_ruff_version": bool,
    "show_rust_version": bool,
    "show_node_version": bool,
    "show_npm_version": bool,
    "cwd_style": str,
    "symbol": str,
    "prompt_layout": str,
}

PROMPT_OPTION_VALUES: dict[str, frozenset[str]] = {
    "cwd_style": frozenset({"full", "home", "basename"}),
    "prompt_layout": frozenset({"single", "two_line"}),
}

DEFAULT_EDITOR_OPTIONS: dict[str, object] = {
    "autosuggest": True,
    "syntax_highlight": True,
    "line_editor": "auto",
}

EDITOR_OPTION_TYPES: dict[str, type] = {
    "autosuggest": bool,
    "syntax_highlight": bool,
    "line_editor": str,
}

EDITOR_OPTION_VALUES: dict[str, frozenset[str]] = {
    "line_editor": frozenset({"auto", "readline", "basic"}),
}

DEFAULT_PROMPT_COLORS: dict[str, str] = {
    "venv": "fuchsia",
    "icon": "lime",
    "user": "lime",
    "host": "aqua",
    "cwd": "yellow",
    "git": "green",
    "python": "blue",
    "uv": "purple",
    "ruff": "teal",
    "rust": "maroon",
    "node": "lime",
    "npm": "red",
    "status": "red",
    "symbol": "white",
}

DEFAULT_PROMPT_COLOR_MODES: dict[str, object] = {
    "vga": True,
}

PROMPT_COLOR_SEGMENTS: frozenset[str] = frozenset(DEFAULT_PROMPT_COLORS)
PROMPT_COLOR_MODE_TYPES: dict[str, type] = {
    "vga": bool,
}

# --------------------------------------------------------- sensitive input
# These options describe the fixed keypress indicator used only by the
# EXPLICIT, user-invoked ``secure <cmd>`` PTY wrapper. They MUST NOT influence
# ordinary runtime paths: not the REPL, not the raw line editor, and not the
# normal external-command path. PySH never reads, counts, stores or logs
# password bytes for ordinary commands; those are owned by the child process
# and the terminal. See docs/security-sensitive-input.md for the full boundary.
DEFAULT_SENSITIVE_INPUT: dict[str, object] = {
    "enabled": False,
    "symbol": "*",
    "idle_color": "white",
    "active_color": "lime",
    "mode": "single-blink",
}

SENSITIVE_INPUT_TYPES: dict[str, type] = {
    "enabled": bool,
    "symbol": str,
    "idle_color": str,
    "active_color": str,
    "mode": str,
}

SENSITIVE_INPUT_VALUES: dict[str, frozenset[str]] = {
    "mode": frozenset({"single-blink"}),
}

_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Monotonic counter guarantees a fresh module object on every load, which
# avoids cross-call import caching (important for re-sourcing and tests).
_load_counter = itertools.count()


class ConfigError(ValueError):
    """Raised when a configuration call receives invalid input.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    continue to work, while allowing precise matching in tests.
    """


@runtime_checkable
class ConfigurableShell(Protocol):
    """Narrow contract the configuration API needs from the shell.

    Implemented by :class:`pysh.shell.PyShell`. Declaring it here (instead of
    importing the concrete shell) keeps this module free of import cycles and
    makes the API unit-testable against a fake implementation.
    """

    def register_alias(self, name: str, value: str) -> None:
        """Register or replace an alias."""
        ...

    def set_environment(self, name: str, value: str) -> None:
        """Export an environment variable for the session."""
        ...

    def set_prompt_option(self, name: str, value: object) -> None:
        """Set a single validated prompt option."""
        ...

    def set_editor_option(self, name: str, value: object) -> None:
        """Set a single validated editor option."""
        ...

    def set_prompt_color(self, segment: str, color: str) -> None:
        """Set a single validated prompt segment color."""
        ...

    def set_prompt_color_mode(self, name: str, value: object) -> None:
        """Set a single validated prompt color mode."""
        ...

    def set_sensitive_input_indicator(self, name: str, value: object) -> None:
        """Set a single validated secure-indicator option."""
        ...


def validate_prompt_option(name: str, value: object) -> None:
    """Validate a prompt option name/value pair.

    Raises :class:`ConfigError` for an unknown option name or a value whose
    type does not match :data:`PROMPT_OPTION_TYPES`.
    """
    expected = PROMPT_OPTION_TYPES.get(name)
    if expected is None:
        known = ", ".join(sorted(PROMPT_OPTION_TYPES))
        raise ConfigError(f"unknown prompt option {name!r} (known: {known})")
    if not isinstance(value, expected):
        raise ConfigError(
            f"prompt option {name!r} expects {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    allowed = PROMPT_OPTION_VALUES.get(name)
    if allowed is not None and value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ConfigError(f"prompt option {name!r} must be one of: {allowed_text}")


def validate_editor_option(name: str, value: object) -> None:
    """Validate a line editor option name/value pair."""
    expected = EDITOR_OPTION_TYPES.get(name)
    if expected is None:
        known = ", ".join(sorted(EDITOR_OPTION_TYPES))
        raise ConfigError(f"unknown editor option {name!r} (known: {known})")
    if not isinstance(value, expected):
        raise ConfigError(
            f"editor option {name!r} expects {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    allowed = EDITOR_OPTION_VALUES.get(name)
    if allowed is not None and value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ConfigError(f"editor option {name!r} must be one of: {allowed_text}")


def validate_prompt_color(segment: str, color: str) -> None:
    """Validate a prompt segment color assignment."""
    if segment not in PROMPT_COLOR_SEGMENTS:
        known = ", ".join(sorted(PROMPT_COLOR_SEGMENTS))
        raise ConfigError(f"unknown prompt color segment {segment!r} (known: {known})")
    if not isinstance(color, str):
        raise ConfigError(
            f"prompt color for {segment!r} expects str, got {type(color).__name__}"
        )
    try:
        parse_color(color)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def validate_prompt_color_mode(name: str, value: object) -> None:
    """Validate a prompt color mode name/value pair."""
    expected = PROMPT_COLOR_MODE_TYPES.get(name)
    if expected is None:
        known = ", ".join(sorted(PROMPT_COLOR_MODE_TYPES))
        raise ConfigError(f"unknown prompt color mode {name!r} (known: {known})")
    if not isinstance(value, expected):
        raise ConfigError(
            f"prompt color mode {name!r} expects {expected.__name__}, "
            f"got {type(value).__name__}"
        )


def validate_sensitive_input(name: str, value: object) -> None:
    """Validate a sensitive-input indicator option.

    These options describe the keypress indicator used only by explicit
    ``secure <cmd>`` PTY-wrapper invocations. They never affect ordinary
    external commands, prompt rendering, or the line editor.

    Rules:

    * ``enabled`` must be ``bool``.
    * ``symbol`` must be a string that occupies exactly one display column.
      Empty, multi-glyph and double-width (e.g. CJK) symbols are rejected so a
      keypress indicator can never encode password length information.
    * ``idle_color`` / ``active_color`` must parse via the shared color parser.
    * ``mode`` must be ``"single-blink"`` (the only value defined so far).
    """
    expected = SENSITIVE_INPUT_TYPES.get(name)
    if expected is None:
        known = ", ".join(sorted(SENSITIVE_INPUT_TYPES))
        raise ConfigError(f"unknown sensitive-input option {name!r} (known: {known})")
    if not isinstance(value, expected):
        raise ConfigError(
            f"sensitive-input option {name!r} expects {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    if name == "symbol":
        # A single fixed glyph is mandatory: the indicator must never be able to
        # represent how many characters were typed.
        assert isinstance(value, str)  # narrowed by the isinstance check above
        if _display_width(value) != 1:
            raise ConfigError(
                "sensitive-input option 'symbol' must be exactly one "
                "display column (no empty, multi-character, or wide glyphs)"
            )
    if name in {"idle_color", "active_color"}:
        assert isinstance(value, str)
        try:
            parse_color(value)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    allowed = SENSITIVE_INPUT_VALUES.get(name)
    if allowed is not None and value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ConfigError(
            f"sensitive-input option {name!r} must be one of: {allowed_text}"
        )


def _validate_alias_name(name: str) -> None:
    if not name or any(ch.isspace() for ch in name) or "=" in name:
        raise ConfigError(f"invalid alias name: {name!r}")


def _validate_env_name(name: str) -> None:
    if not _ENV_NAME_RE.fullmatch(name):
        raise ConfigError(f"invalid environment variable name: {name!r}")


class ShellConfigAPI:
    """Stable, typed surface passed to ``configure(shell)`` in ``~/.pyshrc.py``.

    Every method validates its arguments and delegates the actual mutation to
    the underlying :class:`ConfigurableShell`. The surface is intentionally
    minimal in this release (aliases, environment variables, prompt options)
    and is designed to grow without breaking callers.
    """

    def __init__(self, shell: ConfigurableShell) -> None:
        self._shell = shell

    def alias(self, name: str, value: str) -> None:
        """Define or replace an alias.

        Example::

            shell.alias("ll", "ls -la --color=auto -F")
        """
        if not isinstance(name, str) or not isinstance(value, str):
            raise ConfigError("alias() requires (name: str, value: str)")
        _validate_alias_name(name)
        self._shell.register_alias(name, value)

    def env(self, name: str, value: str) -> None:
        """Export an environment variable for the session.

        Example::

            shell.env("EDITOR", "nano")
        """
        if not isinstance(name, str) or not isinstance(value, str):
            raise ConfigError("env() requires (name: str, value: str)")
        _validate_env_name(name)
        self._shell.set_environment(name, value)

    def set_prompt_option(self, name: str, value: object) -> None:
        """Set a single prompt option.

        Recognised options (defaults in brackets):

        * ``show_user`` (bool) - show the current user [True]
        * ``show_host`` (bool) - show ``user@host`` [True]
        * ``show_virtualenv`` (bool) - prepend the active virtualenv name [True]
        * ``show_git_branch`` (bool) - append the current Git branch [True]
        * ``show_git_dirty`` (bool) - append ``*`` for obvious dirty Git states [True]
        * ``show_python_version`` (bool) - append the active Python version [True]
        * ``show_uv_version`` (bool) - append the active uv version [True]
        * ``show_ruff_version`` (bool) - append the active Ruff version [True]
        * ``show_rust_version`` (bool) - append the active rustc version [True]
        * ``show_node_version`` (bool) - append the active Node.js version [True]
        * ``show_npm_version`` (bool) - append the active npm version [True]
        * ``show_last_status`` (bool) - append non-zero last status [True]
        * ``show_cwd`` (bool) - show the current directory [True]
        * ``cwd_style`` (str) - ``full``, ``home`` or ``basename`` ["home"]
        * ``prompt_layout`` (str) - ``single`` or ``two_line`` ["two_line"]
        * ``symbol`` (str) - command-line prompt symbol [">"]
        """
        validate_prompt_option(name, value)
        self._shell.set_prompt_option(name, value)

    def set_editor_option(self, name: str, value: object) -> None:
        """Set a single line editor option.

        Recognised options (defaults in brackets):

        * ``autosuggest`` (bool) - show history ghost-text suggestions [True]
        * ``syntax_highlight`` (bool) - colorize editable input [True]
        * ``line_editor`` (str) - ``auto``, ``readline`` or ``basic`` ["auto"]
        """
        validate_editor_option(name, value)
        self._shell.set_editor_option(name, value)

    def set_prompt_color(self, segment: str, color: str) -> None:
        """Set one prompt segment color.

        ``segment`` must be one of ``venv``, ``icon``, ``user``, ``host``,
        ``cwd``, ``git``, ``python``, ``uv``, ``ruff``, ``rust``, ``node``,
        ``npm``, ``status`` or ``symbol``. ``color`` accepts canonical HTML
        color names or ``#RRGGBB``.
        """
        validate_prompt_color(segment, color)
        self._shell.set_prompt_color(segment, color)

    def set_prompt_color_mode(self, name: str, value: bool) -> None:
        """Set one prompt color mode.

        ``shell.set_prompt_color_mode("vga", True)`` maps configured colors to
        nearest ANSI/VGA 16-color foregrounds. ``False`` emits ANSI truecolor.
        """
        validate_prompt_color_mode(name, value)
        self._shell.set_prompt_color_mode(name, value)

    def set_sensitive_input_indicator(self, name: str, value: object) -> None:
        """Configure the explicit ``secure <cmd>`` keypress indicator.

        This API is validated and stored. It affects only explicit
        ``secure <cmd>`` invocations; it has no effect on the REPL, the raw
        line editor, prompt rendering, or ordinary external commands.

        PySH never intercepts, counts, stores or logs password input for
        ordinary commands (sudo/ssh/su/gpg); those are owned by the child
        process and the terminal. The indicator is a single fixed glyph that
        blinks on keyboard activity only, never revealing length or content.
        See ``docs/security-sensitive-input.md``.

        Recognised options:

        * ``enabled`` (bool) - enable the visual indicator inside ``secure`` [False]
        * ``symbol`` (str) - exactly one display column ["*"]
        * ``idle_color`` (str) - color name or ``#RRGGBB`` ["white"]
        * ``active_color`` (str) - color name or ``#RRGGBB`` ["lime"]
        * ``mode`` (str) - only ``"single-blink"`` ["single-blink"]
        """
        validate_sensitive_input(name, value)
        self._shell.set_sensitive_input_indicator(name, value)


# --------------------------------------------------------------- default file
DEFAULT_PYSHRC_PY = '''\
# PySH Python-native configuration: ~/.pyshrc.py
#
# This file is loaded *after* the legacy ~/.pyshrc and the
# ~/.pyshrc.d/*.pysh plugins, so anything configured here takes precedence.
#
# Define a top-level function named ``configure`` that receives the PySH
# configuration API. The default is already the full two-line prompt with
# environment, Git, language/tool versions, and last-status visibility.


def configure(shell):
    """Configure the interactive PySH session."""

    # Aliases: shell.alias(name, expansion)
    # shell.alias("ll", "ls -la --color=auto -F")
    # shell.alias("gs", "git status -sb")

    # Environment variables: shell.env(name, value)
    # shell.env("EDITOR", "nano")
    # shell.env("PAGER", "less")

    # Variant A: classic minimal single-line prompt.
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

    # Variant B: keep two-line prompt but hide tool versions.
    # shell.set_prompt_option("show_uv_version", False)
    # shell.set_prompt_option("show_ruff_version", False)
    # shell.set_prompt_option("show_rust_version", False)
    # shell.set_prompt_option("show_node_version", False)
    # shell.set_prompt_option("show_npm_version", False)

    # Variant C: tweak path style and command-line symbol.
    # shell.set_prompt_option("cwd_style", "basename")
    # shell.set_prompt_option("symbol", "pysh>")

    # --- Prompt colors ------------------------------------------------------
    # Colors accept canonical names (red, green, blue, fuchsia, aqua, ...)
    # or #RRGGBB HTML-style values. With VGA mode enabled, colors are mapped
    # to the nearest ANSI/VGA 16-color foreground. With VGA mode disabled,
    # PySH emits ANSI 24-bit truecolor.
    #
    # shell.set_prompt_color_mode("vga", True)   # nearest ANSI/VGA 16-color
    # shell.set_prompt_color_mode("vga", False)  # ANSI 24-bit truecolor
    #
    # shell.set_prompt_color("venv", "fuchsia")
    # shell.set_prompt_color("user", "lime")
    # shell.set_prompt_color("host", "aqua")
    # shell.set_prompt_color("cwd", "yellow")
    # shell.set_prompt_color("git", "green")
    # shell.set_prompt_color("python", "#33CCFF")
    # shell.set_prompt_color("uv", "purple")
    # shell.set_prompt_color("ruff", "teal")
    # shell.set_prompt_color("rust", "#FF6600")
    # shell.set_prompt_color("node", "lime")
    # shell.set_prompt_color("npm", "red")
    # shell.set_prompt_color("status", "red")
    # shell.set_prompt_color("symbol", "white")

    # --- Line editor (fish-style highlighting + autosuggestion) -------------
    # Defaults: syntax highlighting ON, history autosuggestion ON, editor auto.
    # A tool/segment renders nothing when unsupported by the terminal.
    #
    # Disable autosuggestion only:
    # shell.set_editor_option("autosuggest", False)
    #
    # Disable syntax highlighting only:
    # shell.set_editor_option("syntax_highlight", False)
    #
    # Force the classic readline editor (no highlighting, no ghost text):
    # shell.set_editor_option("line_editor", "readline")

    # --- Sensitive input indicator for explicit secure <cmd> only -----------
    # The secure builtin may show a single fixed keypress indicator while the
    # child PTY has echo disabled, so you can tell a key registered. It NEVER
    # reveals length or content, never logs, and never wraps ordinary
    # sudo/ssh/su/gpg automatically. These calls have no effect outside an
    # explicit secure <cmd> invocation.
    # See docs/security-sensitive-input.md.
    #
    # shell.set_sensitive_input_indicator("enabled", True)
    # shell.set_sensitive_input_indicator("symbol", "*")
    # shell.set_sensitive_input_indicator("idle_color", "white")
    # shell.set_sensitive_input_indicator("active_color", "lime")
    # shell.set_sensitive_input_indicator("mode", "single-blink")

    return None
'''


def ensure_default_config(path: Path = PYSHRC_PY_PATH) -> bool:
    """Create the default ``~/.pyshrc.py`` when it does not yet exist.

    Returns ``True`` only when a new file was written. Returns ``False`` if
    the file already exists or could not be created (the error is reported on
    stderr). The generated file is inert by default: its ``configure`` body is
    entirely commented out, so first-run creation never changes behaviour.
    """
    if path.exists():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_PYSHRC_PY, encoding="utf-8")
    except OSError as exc:
        print(f"pysh: cannot create {path}: {exc}", file=sys.stderr)
        return False
    return True


def _import_config_module(path: Path) -> ModuleType:
    """Import ``path`` as an isolated module and return it.

    A unique module name is used per call so repeated loads never collide in
    ``sys.modules``. On any failure the partially-initialised module is removed
    from ``sys.modules`` and the original exception propagates.
    """
    name = f"_pysh_user_config_{next(_load_counter)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _format_base_exception(exc: BaseException) -> str:
    """Return a safe, deterministic message for user configuration failures."""
    message = str(exc)
    if message:
        return message
    return type(exc).__name__


def load_python_config(
    shell: ConfigurableShell,
    *,
    path: Path = PYSHRC_PY_PATH,
) -> int:
    """Load and apply ``~/.pyshrc.py`` against ``shell``.

    Returns ``0`` on success (including when the file is absent or defines no
    ``configure`` function), and ``1`` when loading or applying the
    configuration fails. Failures are reported on stderr and never propagate,
    so a broken user config cannot terminate the shell.
    """
    if not path.exists():
        return 0

    try:
        module = _import_config_module(path)
    except SyntaxError as exc:
        print(f"pysh: {path}: syntax error: {exc.msg}", file=sys.stderr)
        return 1
    except BaseException as exc:  # noqa: BLE001 - user config must not crash the shell
        print(
            f"pysh: {path}: failed to load: {_format_base_exception(exc)}",
            file=sys.stderr,
        )
        return 1

    configure = getattr(module, CONFIGURE_FUNCTION, None)
    if configure is None:
        # A module without ``configure`` is allowed; top-level code already ran.
        return 0
    if not callable(configure):
        print(
            f"pysh: {path}: '{CONFIGURE_FUNCTION}' is defined but not callable",
            file=sys.stderr,
        )
        return 1

    api = ShellConfigAPI(shell)
    try:
        configure(api)
    except ConfigError as exc:
        print(f"pysh: {path}: {exc}", file=sys.stderr)
        return 1
    except BaseException as exc:  # noqa: BLE001 - contain user config failures
        print(
            f"pysh: {path}: {CONFIGURE_FUNCTION}() failed: {_format_base_exception(exc)}",
            file=sys.stderr,
        )
        return 1
    return 0
