# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/profiles.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Built-in and user-defined profile resolution for PySH config."""
from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any

from pysh.config.diagnostics import ConfigDiagnostic, error

ProfileMap = dict[str, dict[str, Any]]


BUILTIN_PROFILES: MappingProxyType[str, dict[str, Any]] = MappingProxyType(
    {
        "default": {
            "description": "Current PySH default behavior.",
            "prompt": {},
            "editor": {},
            "completion": {},
            "history": {},
        },
        "minimal": {
            "description": "Quiet prompt and minimal visual noise.",
            "prompt": {
                "prompt_layout": "single",
                "show_git_branch": False,
                "show_python_version": False,
                "show_node_version": False,
                "show_rust_version": False,
                "show_command_duration": False,
            },
            "editor": {"autosuggest": True, "syntax_highlight": True},
            "completion": {"enabled": True},
            "history": {},
        },
        "developer": {
            "description": "Daily software engineering profile.",
            "theme": "default",
            "prompt": {
                "prompt_layout": "two_line",
                "show_git_branch": True,
                "show_python_version": True,
                "show_uv_version": True,
                "show_ruff_version": True,
                "show_rust_version": True,
                "show_node_version": True,
                "show_npm_version": True,
                "show_last_status": True,
                "show_command_duration": True,
            },
            "editor": {"autosuggest": True, "syntax_highlight": True},
            "completion": {"enabled": True},
            "history": {},
        },
        "server": {
            "description": "Remote/server-oriented profile with clear host state.",
            "theme": "dark",
            "prompt": {
                "prompt_layout": "two_line",
                "show_user": True,
                "show_host": True,
                "show_git_branch": False,
                "show_python_version": False,
                "show_last_status": True,
            },
            "editor": {"autosuggest": True, "syntax_highlight": True},
            "completion": {"enabled": True},
            "history": {},
        },
        "presentation": {
            "description": "Clean readable profile for demos.",
            "theme": "light",
            "prompt": {
                "prompt_layout": "single",
                "show_user": False,
                "show_host": False,
                "show_last_status": True,
                "show_command_duration": False,
            },
            "editor": {"autosuggest": True, "syntax_highlight": True},
            "completion": {"enabled": True},
            "history": {},
        },
        "plain": {
            "description": "No icons and low ANSI dependence.",
            "theme": "plain",
            "prompt": {
                "prompt_layout": "single",
                "symbol": ">",
                "show_git_branch": False,
                "show_python_version": False,
                "show_node_version": False,
                "show_rust_version": False,
            },
            "editor": {"autosuggest": True, "syntax_highlight": False},
            "completion": {"enabled": True},
            "history": {},
        },
    }
)


def profile_names(user_profiles: ProfileMap | None = None) -> list[str]:
    """Return built-in plus user profile names."""
    names = set(BUILTIN_PROFILES)
    if user_profiles:
        names.update(user_profiles)
    return sorted(names)


def resolve_profiles(user_profiles: ProfileMap) -> tuple[ProfileMap, tuple[ConfigDiagnostic, ...]]:
    """Resolve profile inheritance and detect unknown bases or cycles."""
    profiles: ProfileMap = {name: deepcopy(value) for name, value in BUILTIN_PROFILES.items()}
    profiles.update(deepcopy(user_profiles))
    diagnostics: list[ConfigDiagnostic] = []
    resolved: ProfileMap = {}
    visiting: set[str] = set()

    def resolve(name: str) -> dict[str, Any]:
        if name in resolved:
            return deepcopy(resolved[name])
        current = profiles.get(name)
        if current is None:
            diagnostics.append(error(None, "profiles", name, name, "unknown profile"))
            return {}
        if name in visiting:
            diagnostics.append(error(None, "profiles", name, name, "profile inheritance cycle"))
            return {}
        visiting.add(name)
        base_name = current.get("base")
        if base_name is not None:
            if not isinstance(base_name, str) or base_name not in profiles:
                diagnostics.append(error(None, f"profiles.{name}", "base", base_name, "unknown base profile"))
                base = {}
            else:
                base = resolve(base_name)
        else:
            base = {}
        merged = _merge_profile(base, current)
        visiting.remove(name)
        resolved[name] = merged
        return deepcopy(merged)

    for profile_name in profiles:
        resolve(profile_name)
    return resolved, tuple(diagnostics)


def _merge_profile(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in override.items():
        if key in {"prompt", "editor", "completion", "history"} and isinstance(value, dict):
            section = out.get(key)
            if not isinstance(section, dict):
                section = {}
            section.update(deepcopy(value))
            out[key] = section
        elif key != "base":
            out[key] = deepcopy(value)
    return out
