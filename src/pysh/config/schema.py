# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/schema.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Schema validation and application for declarative PySH TOML config."""
from __future__ import annotations

import re
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pysh.config.alias_packs import BUILTIN_ALIAS_PACKS
from pysh.config.api import (
    ConfigError,
    _validate_alias_name,
    _validate_env_name,
    validate_completion_option,
    validate_editor_option,
    validate_highlight_color,
    validate_history_option,
    validate_prompt_color,
    validate_prompt_option,
)
from pysh.config.diagnostics import ConfigDiagnostic, error, warning
from pysh.config.profiles import ProfileMap, resolve_profiles
from pysh.config.themes import ThemeMap, resolve_themes

_SAFE_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class PluginConfig:
    """Loaded plugin TOML configuration (data-only, never executed)."""

    name: str
    path: Path
    data: dict[str, Any]
    diagnostics: tuple[ConfigDiagnostic, ...]


def validate_plugin_name(name: str) -> bool:
    """Return True if *name* is a safe plugin identifier.

    Accepts lowercase letters, digits, ``_``, ``-``, and ``.``, starting with
    a letter or digit.  Path separators and uppercase are rejected.
    """
    return bool(_SAFE_PLUGIN_NAME_RE.match(name))


def load_plugin_config(path: Path, *, max_bytes: int = 256 * 1024) -> PluginConfig | None:
    """Load and structurally validate one plugin TOML file.

    Returns ``None`` when the file stem is not a safe plugin name so the caller
    can skip it with a diagnostic.  Returns a :class:`PluginConfig` with
    diagnostics recorded for any structural problem; the shell can log those
    but will not crash on a bad plugin config.
    """
    from pysh.config.toml_loader import load_toml_file

    stem = path.stem
    if not validate_plugin_name(stem):
        return None

    loaded = load_toml_file(path, max_bytes=max_bytes)
    diags: list[ConfigDiagnostic] = list(loaded.diagnostics)

    if not loaded.loaded:
        return PluginConfig(stem, path, {}, tuple(diags))

    data = loaded.data
    if not isinstance(data, dict):
        diags.append(error(path, None, None, None, "plugin config must be a TOML table"))
        return PluginConfig(stem, path, {}, tuple(diags))

    # Validate [plugin].name matches file stem when present
    plugin_section = data.get("plugin")
    if plugin_section is not None:
        if not isinstance(plugin_section, dict):
            diags.append(error(path, "plugin", None, plugin_section, "plugin section must be a table"))
        else:
            declared_name = plugin_section.get("name")
            if declared_name is not None:
                if not isinstance(declared_name, str):
                    diags.append(error(path, "plugin", "name", declared_name, "plugin name must be a string"))
                elif declared_name != stem:
                    diags.append(
                        error(
                            path,
                            "plugin",
                            "name",
                            declared_name,
                            f"plugin name {declared_name!r} does not match file stem {stem!r}",
                        )
                    )

    return PluginConfig(stem, path, dict(data), tuple(diags))


_TOP_LEVEL_SECTIONS = frozenset(
    {
        "profile",
        "theme",
        "prompt",
        "editor",
        "completion",
        "history",
        "colors",
        "alias_packs",
        "aliases",
        "env",
        "features",
        "profiles",
        "themes",
    }
)
_PROFILE_KEYS = frozenset({"active"})
_THEME_KEYS = frozenset({"active"})
_ALIAS_PACK_KEYS = frozenset({"enabled"})
_FEATURE_KEYS = frozenset({"project_plugins"})
_USER_PROFILE_KEYS = frozenset({"base", "theme", "description", "prompt", "editor", "completion", "history"})
_USER_THEME_KEYS = frozenset({"base", "description", "override", "colors"})
_THEME_COLOR_KEYS = frozenset({"prompt", "highlight"})


class ConfigTarget(Protocol):
    """Subset of shell mutation APIs used by declarative config application."""

    def set_prompt_option(self, name: str, value: object) -> None: ...
    def set_editor_option(self, name: str, value: object) -> None: ...
    def set_completion_option(self, name: str, value: object) -> None: ...
    def set_history_option(self, name: str, value: object) -> None: ...
    def set_prompt_color(self, segment: str, color: str) -> None: ...
    def set_highlight_color(self, role: str, color: str) -> None: ...
    def register_alias(self, name: str, value: str) -> None: ...
    def set_environment(self, name: str, value: str) -> None: ...
    def set_profile(self, name: str) -> None: ...
    def set_theme(self, name: str) -> None: ...
    def load_alias_pack(self, name: str) -> None: ...


@dataclass
class DeclarativeConfig:
    """Validated declarative configuration accumulated from TOML files."""

    profile: str | None = None
    theme: str | None = None
    prompt: dict[str, object] = field(default_factory=dict)
    editor: dict[str, object] = field(default_factory=dict)
    completion: dict[str, object] = field(default_factory=dict)
    history: dict[str, object] = field(default_factory=dict)
    prompt_colors: dict[str, str] = field(default_factory=dict)
    highlight_colors: dict[str, str] = field(default_factory=dict)
    alias_packs: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    features: dict[str, object] = field(default_factory=dict)
    profiles: ProfileMap = field(default_factory=dict)
    themes: ThemeMap = field(default_factory=dict)
    diagnostics: list[ConfigDiagnostic] = field(default_factory=list)
    loaded_paths: list[Path] = field(default_factory=list)
    profile_path: Path | None = None
    theme_path: Path | None = None
    alias_pack_paths: dict[str, Path] = field(default_factory=dict)


def merge_toml_documents(documents: list[tuple[Path, dict[str, Any]]]) -> DeclarativeConfig:
    """Validate and merge TOML documents in load order."""
    config = DeclarativeConfig()
    for path, data in documents:
        config.loaded_paths.append(path)
        _merge_document(config, path, data)
    resolved_profiles, profile_diags = resolve_profiles(config.profiles)
    config.profiles = resolved_profiles
    resolved_themes, theme_diags = resolve_themes(config.themes)
    config.themes = resolved_themes
    config.diagnostics.extend(profile_diags)
    config.diagnostics.extend(theme_diags)
    if config.profile is not None and config.profile not in config.profiles:
        config.diagnostics.append(
            error(config.profile_path, "profile", "active", config.profile, "unknown profile")
        )
    if config.theme is not None and config.theme not in config.themes:
        config.diagnostics.append(
            error(config.theme_path, "theme", "active", config.theme, "unknown theme")
        )
    for pack in config.alias_packs:
        if pack not in BUILTIN_ALIAS_PACKS:
            config.diagnostics.append(
                error(
                    config.alias_pack_paths.get(pack),
                    "alias_packs",
                    "enabled",
                    pack,
                    "unknown alias pack",
                )
            )
    return config


def print_config_diagnostics(diagnostics: list[ConfigDiagnostic]) -> None:
    """Print diagnostics to stderr without ANSI styling."""
    for diagnostic in diagnostics:
        print(diagnostic.format(), file=sys.stderr)


def apply_config(shell: ConfigTarget, config: DeclarativeConfig) -> None:
    """Apply validated declarative configuration to *shell*.

    Individual invalid settings are skipped after their diagnostics were
    recorded; this function does not execute TOML values.
    """
    if config.profile and not _has_errors_for("profile", "active", config.diagnostics):
        _safe_apply(config, None, "profile", "active", config.profile, shell.set_profile, config.profile)
    if config.theme and not _has_errors_for("theme", "active", config.diagnostics):
        _safe_apply(config, None, "theme", "active", config.theme, shell.set_theme, config.theme)
    for section, values, setter in (
        ("prompt", config.prompt, shell.set_prompt_option),
        ("editor", config.editor, shell.set_editor_option),
        ("completion", config.completion, shell.set_completion_option),
        ("history", config.history, shell.set_history_option),
    ):
        for key, value in values.items():
            if _has_errors_for(section, key, config.diagnostics):
                continue
            _safe_apply(config, None, section, key, value, setter, key, value)
    for key, color in config.prompt_colors.items():
        if not _has_errors_for("colors.prompt", key, config.diagnostics):
            _safe_apply(config, None, "colors.prompt", key, color, shell.set_prompt_color, key, color)
    for key, color in config.highlight_colors.items():
        if not _has_errors_for("colors.highlight", key, config.diagnostics):
            _safe_apply(config, None, "colors.highlight", key, color, shell.set_highlight_color, key, color)
    for pack in config.alias_packs:
        if not _has_errors_for("alias_packs", "enabled", config.diagnostics):
            _safe_apply(config, None, "alias_packs", "enabled", pack, shell.load_alias_pack, pack)
    for name, value in config.aliases.items():
        if not _has_errors_for("aliases", name, config.diagnostics):
            _safe_apply(config, None, "aliases", name, value, shell.register_alias, name, value)
    for name, value in config.env.items():
        if not _has_errors_for("env", name, config.diagnostics):
            _safe_apply(config, None, "env", name, value, shell.set_environment, name, value)


def _merge_document(config: DeclarativeConfig, path: Path, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if key not in _TOP_LEVEL_SECTIONS:
            config.diagnostics.append(error(path, key, None, None, "unknown top-level section"))
            continue
        if not isinstance(value, dict):
            config.diagnostics.append(error(path, key, None, value, "section must be a table"))
            continue
    _merge_active(config, path, data.get("profile"), "profile", _PROFILE_KEYS)
    _merge_active(config, path, data.get("theme"), "theme", _THEME_KEYS)
    _merge_options(config.prompt, config.diagnostics, path, "prompt", data.get("prompt"), validate_prompt_option)
    _merge_options(config.editor, config.diagnostics, path, "editor", data.get("editor"), validate_editor_option)
    _merge_options(config.completion, config.diagnostics, path, "completion", data.get("completion"), validate_completion_option)
    _merge_options(config.history, config.diagnostics, path, "history", data.get("history"), validate_history_option)
    _merge_colors(config, path, data.get("colors"))
    _merge_alias_packs(config, path, data.get("alias_packs"))
    _merge_aliases(config, path, data.get("aliases"))
    _merge_env(config, path, data.get("env"))
    _merge_features(config, path, data.get("features"))
    _merge_user_profiles(config, path, data.get("profiles"))
    _merge_user_themes(config, path, data.get("themes"))


def _merge_active(
    config: DeclarativeConfig,
    path: Path,
    table: object,
    section: str,
    allowed: frozenset[str],
) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, section, None, table, "section must be a table"))
        return
    for key, value in table.items():
        if key not in allowed:
            config.diagnostics.append(error(path, section, key, value, "unknown key"))
            continue
        if not isinstance(value, str):
            config.diagnostics.append(error(path, section, key, value, "value must be a string"))
            continue
        if section == "profile":
            config.profile = value
            config.profile_path = path
        else:
            config.theme = value
            config.theme_path = path


def _merge_options(
    target: dict[str, object],
    diagnostics: list[ConfigDiagnostic],
    path: Path,
    section: str,
    table: object,
    validator: object,
) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        diagnostics.append(error(path, section, None, table, "section must be a table"))
        return
    for key, value in table.items():
        try:
            validator(key, value)  # type: ignore[misc]
        except ConfigError as exc:
            diagnostics.append(error(path, section, key, value, str(exc)))
            continue
        target[key] = value


def _merge_colors(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "colors", None, table, "section must be a table"))
        return
    for key, value in table.items():
        if key not in _THEME_COLOR_KEYS:
            config.diagnostics.append(error(path, "colors", key, value, "unknown key"))
            continue
        if not isinstance(value, dict):
            config.diagnostics.append(error(path, f"colors.{key}", None, value, "section must be a table"))
            continue
        for color_key, color in value.items():
            if not isinstance(color, str):
                config.diagnostics.append(error(path, f"colors.{key}", color_key, color, "color must be a string"))
                continue
            try:
                if key == "prompt":
                    validate_prompt_color(color_key, color)
                    config.prompt_colors[color_key] = color
                else:
                    validate_highlight_color(color_key, color)
                    config.highlight_colors[color_key] = color
            except ConfigError as exc:
                config.diagnostics.append(error(path, f"colors.{key}", color_key, color, str(exc)))


def _merge_alias_packs(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "alias_packs", None, table, "section must be a table"))
        return
    for key, value in table.items():
        if key not in _ALIAS_PACK_KEYS:
            config.diagnostics.append(error(path, "alias_packs", key, value, "unknown key"))
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            config.diagnostics.append(error(path, "alias_packs", key, value, "value must be a list of strings"))
            continue
        config.alias_packs = list(value)
        config.alias_pack_paths = {item: path for item in value}


def _merge_aliases(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "aliases", None, table, "section must be a table"))
        return
    for key, value in table.items():
        try:
            _validate_alias_name(key)
        except ConfigError as exc:
            config.diagnostics.append(error(path, "aliases", key, value, str(exc)))
            continue
        if not isinstance(value, str):
            config.diagnostics.append(error(path, "aliases", key, value, "alias value must be a string"))
            continue
        if key in config.aliases:
            config.diagnostics.append(warning(path, "aliases", key, value, "alias overrides earlier declarative alias"))
        config.aliases[key] = value


def _merge_env(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "env", None, table, "section must be a table"))
        return
    for key, value in table.items():
        try:
            _validate_env_name(key)
        except ConfigError as exc:
            config.diagnostics.append(error(path, "env", key, value, str(exc)))
            continue
        if not isinstance(value, str):
            config.diagnostics.append(error(path, "env", key, value, "environment value must be a string"))
            continue
        config.env[key] = value


def _merge_features(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "features", None, table, "section must be a table"))
        return
    for key, value in table.items():
        if key not in _FEATURE_KEYS:
            config.diagnostics.append(error(path, "features", key, value, "unknown key"))
            continue
        if not isinstance(value, bool):
            config.diagnostics.append(error(path, "features", key, value, "feature value must be bool"))
            continue
        config.features[key] = value


def _merge_user_profiles(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "profiles", None, table, "section must be a table"))
        return
    for name, value in table.items():
        if not isinstance(value, dict):
            config.diagnostics.append(error(path, "profiles", name, value, "profile must be a table"))
            continue
        if "aliases" in value or "alias_packs" in value:
            config.diagnostics.append(error(path, f"profiles.{name}", None, None, "profiles must not define aliases or alias packs"))
        clean = deepcopy(value)
        for key in value:
            if key not in _USER_PROFILE_KEYS:
                config.diagnostics.append(error(path, f"profiles.{name}", key, value[key], "unknown key"))
        _validate_nested_options(
            config,
            path,
            f"profiles.{name}.prompt",
            value.get("prompt"),
            validate_prompt_option,
        )
        _validate_nested_options(
            config,
            path,
            f"profiles.{name}.editor",
            value.get("editor"),
            validate_editor_option,
        )
        _validate_nested_options(
            config,
            path,
            f"profiles.{name}.completion",
            value.get("completion"),
            validate_completion_option,
        )
        _validate_nested_options(
            config,
            path,
            f"profiles.{name}.history",
            value.get("history"),
            validate_history_option,
        )
        config.profiles[name] = clean


def _merge_user_themes(config: DeclarativeConfig, path: Path, table: object) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, "themes", None, table, "section must be a table"))
        return
    for name, value in table.items():
        if not isinstance(value, dict):
            config.diagnostics.append(error(path, "themes", name, value, "theme must be a table"))
            continue
        for key in value:
            if key not in _USER_THEME_KEYS:
                config.diagnostics.append(error(path, f"themes.{name}", key, value[key], "unknown key"))
        colors = value.get("colors")
        if colors is not None:
            _validate_theme_colors(config, path, name, colors)
        config.themes[name] = deepcopy(value)


def _validate_theme_colors(config: DeclarativeConfig, path: Path, name: str, colors: object) -> None:
    if not isinstance(colors, dict):
        config.diagnostics.append(error(path, f"themes.{name}.colors", None, colors, "colors must be a table"))
        return
    for section, values in colors.items():
        if section not in _THEME_COLOR_KEYS:
            config.diagnostics.append(error(path, f"themes.{name}.colors", section, values, "unknown color section"))
            continue
        if not isinstance(values, dict):
            config.diagnostics.append(error(path, f"themes.{name}.colors.{section}", None, values, "color section must be a table"))
            continue
        for key, color in values.items():
            try:
                if section == "prompt":
                    validate_prompt_color(key, color)
                else:
                    validate_highlight_color(key, color)
            except ConfigError as exc:
                config.diagnostics.append(error(path, f"themes.{name}.colors.{section}", key, color, str(exc)))


def _validate_nested_options(
    config: DeclarativeConfig,
    path: Path,
    section: str,
    table: object,
    validator: object,
) -> None:
    if table is None:
        return
    if not isinstance(table, dict):
        config.diagnostics.append(error(path, section, None, table, "section must be a table"))
        return
    for key, value in table.items():
        try:
            validator(key, value)  # type: ignore[misc]
        except ConfigError as exc:
            config.diagnostics.append(error(path, section, key, value, str(exc)))


def _has_errors_for(section: str, key: str | None, diagnostics: list[ConfigDiagnostic]) -> bool:
    for diagnostic in diagnostics:
        if diagnostic.severity != "error":
            continue
        if diagnostic.section == section and (key is None or diagnostic.key == key):
            return True
    return False


def _safe_apply(
    config: DeclarativeConfig,
    path: Path | None,
    section: str,
    key: str | None,
    value: object,
    fn: object,
    *args: object,
) -> None:
    try:
        fn(*args)  # type: ignore[misc]
    except (ConfigError, ValueError) as exc:
        config.diagnostics.append(error(path, section, key, value, str(exc)))
