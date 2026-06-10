# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/runtime.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Runtime orchestration for declarative PySH TOML configuration."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pysh.config.paths import config_file_locations, plugin_config_paths, primary_config_path
from pysh.config.schema import (
    DeclarativeConfig,
    PluginConfig,
    apply_config,
    load_plugin_config,
    merge_toml_documents,
    print_config_diagnostics,
    validate_plugin_name,
)
from pysh.config.toml_loader import load_toml_file

DEFAULT_CONFIG_TOML = """\
# PySH declarative configuration: ~/.config/pysh/config.toml
#
# This file is safe TOML data. It does not execute commands, shell
# expressions, Python expressions, plugins, or startup hooks.

[profile]
active = "default"

[theme]
active = "default"

[prompt]
prompt_layout = "two_line"
show_git_branch = true
show_python_version = true
show_last_status = true

[editor]
line_editor = "auto"
autosuggest = true
syntax_highlight = true

[completion]
enabled = true
case_sensitive = false
show_hidden = false
menu = "compact"

[history]
max_length = 10000
dedup_mode = "consecutive"
ignore_space_prefix = true

[colors.prompt]
cwd = "yellow"
git = "green"
symbol = "white"

[colors.highlight]
builtin = "aqua"
alias = "fuchsia"
comment = "gray"
heredoc = "yellow"

[alias_packs]
enabled = []

[aliases]
# gs = "git status --short"

[env]
# EDITOR = "nano"

[features]
project_plugins = false
"""


def ensure_default_toml_config(path: Path | None = None) -> bool:
    """Create a safe commented TOML config template if missing."""
    target = primary_config_path() if path is None else path
    if target.exists():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    except OSError:
        return False
    return True


def load_plugin_configs(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, PluginConfig]:
    """Discover and load all plugin TOML configuration files without executing them.

    Files with unsafe names are skipped with a stderr diagnostic.  Files that
    fail to parse are returned with diagnostics recorded; they do not crash
    shell startup.
    """
    import sys

    from pysh.config.diagnostics import error

    configs: dict[str, PluginConfig] = {}
    for path in plugin_config_paths(environ=environ, home=home):
        stem = path.stem
        if not validate_plugin_name(stem):
            diag = error(path, None, None, stem, f"unsafe plugin config filename: {path.name!r}")
            print(diag.format(), file=sys.stderr)
            continue
        pc = load_plugin_config(path)
        if pc is None:
            continue
        for diag in pc.diagnostics:
            print(diag.format(), file=sys.stderr)
        configs[pc.name] = pc
    return configs


def load_declarative_config() -> DeclarativeConfig:
    """Load configured TOML files without mutating shell state."""
    diagnostics = []
    documents = []
    for path in config_file_locations():
        loaded = load_toml_file(path)
        diagnostics.extend(loaded.diagnostics)
        if loaded.loaded:
            documents.append((path, loaded.data))
    config = merge_toml_documents(documents)
    config.diagnostics[:0] = diagnostics
    return config


def apply_declarative_config(shell: object, config: DeclarativeConfig | None = None) -> DeclarativeConfig:
    """Load, report, and apply declarative config to *shell*."""
    loaded = load_declarative_config() if config is None else config
    if hasattr(shell, "config_profiles"):
        shell.config_profiles = loaded.profiles  # type: ignore[attr-defined]
    if hasattr(shell, "config_themes"):
        shell.config_themes = loaded.themes  # type: ignore[attr-defined]
    if hasattr(shell, "config_diagnostics"):
        shell.config_diagnostics = list(loaded.diagnostics)  # type: ignore[attr-defined]
    if hasattr(shell, "config_loaded_paths"):
        shell.config_loaded_paths = list(loaded.loaded_paths)  # type: ignore[attr-defined]
    if hasattr(shell, "plugin_configs"):
        plugin_cfgs = load_plugin_configs()
        shell.plugin_configs = {  # type: ignore[attr-defined]
            name: dict(pc.data) for name, pc in plugin_cfgs.items()
        }
    apply_config(shell, loaded)  # type: ignore[arg-type]
    print_config_diagnostics(loaded.diagnostics)
    return loaded
