# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/paths.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""XDG-aware declarative configuration paths for PySH."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

PYSH_CONFIG_DIRNAME = "pysh"
PYSH_CONFIG_FILENAME = "config.toml"
PYSH_CONFIG_DROPIN_DIRNAME = "conf.d"
PYSH_PLUGIN_CONFIG_DIRNAME = "plugins"


def config_home(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the XDG configuration home used for PySH config discovery."""
    env = os.environ if environ is None else environ
    raw = env.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser()
    base_home = Path.home() if home is None else home
    return base_home / ".config"


def config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the PySH declarative configuration directory."""
    return config_home(environ=environ, home=home) / PYSH_CONFIG_DIRNAME


def primary_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the primary declarative TOML configuration path."""
    return config_dir(environ=environ, home=home) / PYSH_CONFIG_FILENAME


def dropin_config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the declarative TOML drop-in directory."""
    return config_dir(environ=environ, home=home) / PYSH_CONFIG_DROPIN_DIRNAME


def dropin_config_paths(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path, ...]:
    """Return existing drop-ins in deterministic lexical order."""
    directory = dropin_config_dir(environ=environ, home=home)
    try:
        entries = tuple(directory.glob("*.toml"))
    except OSError:
        return ()
    return tuple(sorted((p for p in entries if p.is_file()), key=lambda p: str(p)))


def config_file_locations(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path, ...]:
    """Return the primary config path followed by existing drop-ins."""
    primary = primary_config_path(environ=environ, home=home)
    return (primary, *dropin_config_paths(environ=environ, home=home))


def plugin_config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the PySH plugin configuration directory."""
    return config_dir(environ=environ, home=home) / PYSH_PLUGIN_CONFIG_DIRNAME


def plugin_config_path(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the plugin TOML configuration path for *name*."""
    return plugin_config_dir(environ=environ, home=home) / f"{name}.toml"


def plugin_config_paths(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path, ...]:
    """Return existing plugin TOML files in deterministic lexical order."""
    directory = plugin_config_dir(environ=environ, home=home)
    try:
        entries = tuple(directory.glob("*.toml"))
    except OSError:
        return ()
    return tuple(sorted((p for p in entries if p.is_file()), key=lambda p: str(p)))
