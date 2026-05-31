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

# Canonical location of the Python-native user configuration file.
PYSHRC_PY_PATH = Path("~/.pyshrc.py").expanduser()

# Name of the function PySH calls inside ``~/.pyshrc.py``.
CONFIGURE_FUNCTION = "configure"

# Default prompt options for the two-line prompt layout.
DEFAULT_PROMPT_OPTIONS: dict[str, object] = {
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
    "cwd_style": str,
    "symbol": str,
    "prompt_layout": str,
}

PROMPT_OPTION_VALUES: dict[str, frozenset[str]] = {
    "cwd_style": frozenset({"full", "home", "basename"}),
    "prompt_layout": frozenset({"single", "two_line"}),
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
        * ``show_host`` (bool) - show ``user@host`` [False]
        * ``show_python_version`` (bool) - append the active Python version [False]
        * ``show_virtualenv`` (bool) - prepend the active virtualenv name [False]
        * ``show_git_branch`` (bool) - append the current Git branch [False]
        * ``show_git_dirty`` (bool) - append ``*`` for obvious dirty Git states [False]
        * ``show_last_status`` (bool) - append non-zero last status [False]
        * ``show_cwd`` (bool) - show the current directory [True]
        * ``show_uv_version`` (bool) - append the active uv version [False]
        * ``show_ruff_version`` (bool) - append the active Ruff version [False]
        * ``cwd_style`` (str) - ``full``, ``home`` or ``basename`` ["full"]
        * ``symbol`` (str) - command-line prompt symbol [">"]
        * ``prompt_layout`` (str) - ``single`` or ``two_line`` ["two_line"]
        """
        validate_prompt_option(name, value)
        self._shell.set_prompt_option(name, value)


# --------------------------------------------------------------- default file
DEFAULT_PYSHRC_PY = '''\
# PySH Python-native configuration: ~/.pyshrc.py
#
# This file is loaded *after* the legacy ~/.pyshrc and the
# ~/.pyshrc.d/*.pysh plugins, so anything configured here takes precedence.
#
# Define a top-level function named ``configure`` that receives the PySH
# configuration API. Every call below is optional; the defaults reproduce the
# historical PySH behaviour.


def configure(shell):
    """Configure the interactive PySH session."""

    # Aliases: shell.alias(name, expansion)
    # shell.alias("ll", "ls -la --color=auto -F")
    # shell.alias("gs", "git status -sb")

    # Environment variables: shell.env(name, value)
    # shell.env("EDITOR", "nano")
    # shell.env("PAGER", "less")

    # Prompt options: shell.set_prompt_option(name, value)
    #   show_user            (bool)  show the current user               [True]
    #   show_host            (bool)  show user@host                      [False]
    #   show_python_version  (bool)  append the active Python version    [False]
    #   show_virtualenv      (bool)  prepend active virtualenv name      [False]
    #   show_git_branch      (bool)  append current Git branch           [False]
    #   show_git_dirty       (bool)  mark obvious dirty Git states       [False]
    #   show_last_status     (bool)  append non-zero last status         [False]
    #   show_cwd             (bool)  show current directory              [True]
    #   show_uv_version      (bool)  append detected uv version          [False]
    #   show_ruff_version    (bool)  append detected Ruff version        [False]
    #   cwd_style            (str)   full | home | basename              ["full"]
    #   symbol               (str)   command-line prompt symbol          [">"]
    #   prompt_layout        (str)   single | two_line                   ["two_line"]
    # shell.set_prompt_option("show_virtualenv", True)
    # shell.set_prompt_option("show_git_branch", True)
    # shell.set_prompt_option("show_git_dirty", True)
    # shell.set_prompt_option("show_python_version", True)
    # shell.set_prompt_option("show_uv_version", True)
    # shell.set_prompt_option("show_ruff_version", True)
    # shell.set_prompt_option("show_last_status", True)
    # shell.set_prompt_option("cwd_style", "home")
    # shell.set_prompt_option("prompt_layout", "single")

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
    except Exception as exc:  # noqa: BLE001 - user config must not crash the shell
        print(f"pysh: {path}: failed to load: {exc}", file=sys.stderr)
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
    except Exception as exc:  # noqa: BLE001 - contain user errors
        print(f"pysh: {path}: {CONFIGURE_FUNCTION}() failed: {exc}", file=sys.stderr)
        return 1
    return 0
