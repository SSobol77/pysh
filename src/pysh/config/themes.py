# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/themes.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Built-in and user-defined theme resolution for PySH config."""
from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any

from pysh.config.diagnostics import ConfigDiagnostic, error

ThemeMap = dict[str, dict[str, Any]]

_DEFAULT_PROMPT = {
    "user": "lime",
    "host": "aqua",
    "cwd": "yellow",
    "git": "green",
    "python": "blue",
    "status": "red",
    "duration": "yellow",
    "symbol": "white",
}
_DEFAULT_HIGHLIGHT = {
    "builtin": "aqua",
    "alias": "fuchsia",
    "command_valid": "lime",
    "command_invalid": "red",
    "string": "green",
    "operator": "yellow",
    "option": "aqua",
    "variable": "fuchsia",
    "path": "aqua",
    "comment": "gray",
    "heredoc": "yellow",
    "error": "red",
    "continuation": "yellow",
    "paste": "yellow",
    "reverse_search": "fuchsia",
}

BUILTIN_THEMES: MappingProxyType[str, dict[str, Any]] = MappingProxyType(
    {
        "default": {"description": "Default PySH colors.", "colors": {"prompt": _DEFAULT_PROMPT, "highlight": _DEFAULT_HIGHLIGHT}},
        "minimal": {"base": "default", "description": "Reduced visual intensity."},
        "dark": {"base": "default", "description": "Readable dark-terminal palette."},
        "light": {"base": "default", "description": "Readable light-terminal palette.", "colors": {"prompt": {"cwd": "blue", "symbol": "black"}}},
        "catppuccin-mocha": {"base": "dark", "description": "Catppuccin Mocha-inspired palette.", "colors": {"prompt": {"cwd": "aqua", "git": "fuchsia"}}},
        "catppuccin-latte": {"base": "light", "description": "Catppuccin Latte-inspired palette.", "colors": {"prompt": {"cwd": "blue", "git": "green"}}},
        "tokyo-night": {"base": "dark", "description": "Tokyo Night-inspired palette.", "colors": {"prompt": {"cwd": "blue", "git": "purple"}}},
        "nord": {"base": "dark", "description": "Nord-inspired palette.", "colors": {"prompt": {"cwd": "aqua", "git": "green"}}},
        "gruvbox-dark": {"base": "dark", "description": "Gruvbox dark-inspired palette.", "colors": {"prompt": {"cwd": "yellow", "git": "orange"}}},
        "solarized-dark": {"base": "dark", "description": "Solarized dark-inspired palette.", "colors": {"prompt": {"cwd": "teal", "git": "green"}}},
        "solarized-light": {"base": "light", "description": "Solarized light-inspired palette.", "colors": {"prompt": {"cwd": "blue", "git": "green"}}},
        "plain": {"description": "Plain no-frills theme.", "colors": {"prompt": {"symbol": "white"}, "highlight": {}}},
    }
)


def theme_names(user_themes: ThemeMap | None = None) -> list[str]:
    """Return built-in plus user theme names."""
    names = set(BUILTIN_THEMES)
    if user_themes:
        names.update(user_themes)
    return sorted(names)


def resolve_themes(user_themes: ThemeMap) -> tuple[ThemeMap, tuple[ConfigDiagnostic, ...]]:
    """Resolve theme inheritance and detect unknown bases or cycles."""
    themes: ThemeMap = {name: deepcopy(value) for name, value in BUILTIN_THEMES.items()}
    diagnostics: list[ConfigDiagnostic] = []
    for name, theme in user_themes.items():
        if name in BUILTIN_THEMES and theme.get("override") is not True:
            diagnostics.append(error(None, f"themes.{name}", None, name, "built-in theme collision requires override = true"))
            continue
        themes[name] = deepcopy(theme)
    resolved: ThemeMap = {}
    visiting: set[str] = set()

    def resolve(name: str) -> dict[str, Any]:
        if name in resolved:
            return deepcopy(resolved[name])
        current = themes.get(name)
        if current is None:
            diagnostics.append(error(None, "themes", name, name, "unknown theme"))
            return {}
        if name in visiting:
            diagnostics.append(error(None, "themes", name, name, "theme inheritance cycle"))
            return {}
        visiting.add(name)
        base_name = current.get("base")
        if base_name is not None:
            if not isinstance(base_name, str) or base_name not in themes:
                diagnostics.append(error(None, f"themes.{name}", "base", base_name, "unknown base theme"))
                base = {}
            else:
                base = resolve(base_name)
        else:
            base = {}
        merged = _merge_theme(base, current)
        visiting.remove(name)
        resolved[name] = merged
        return deepcopy(merged)

    for theme_name in themes:
        resolve(theme_name)
    return resolved, tuple(diagnostics)


def _merge_theme(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in override.items():
        if key == "colors" and isinstance(value, dict):
            colors = out.get("colors")
            if not isinstance(colors, dict):
                colors = {}
            for color_section, mapping in value.items():
                if not isinstance(mapping, dict):
                    colors[color_section] = deepcopy(mapping)
                    continue
                section = colors.get(color_section)
                if not isinstance(section, dict):
                    section = {}
                section.update(deepcopy(mapping))
                colors[color_section] = section
            out["colors"] = colors
        elif key not in {"base", "override"}:
            out[key] = deepcopy(value)
    return out
