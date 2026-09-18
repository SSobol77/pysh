# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/loader.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Controlled file-based loading for explicitly enabled PySH plugins."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

from pysh.plugins.api import PluginAPI
from pysh.plugins.errors import PluginLoadError, PluginValidationError
from pysh.plugins.models import PluginInfo, PluginRecord, PluginState
from pysh.plugins.names import validate_plugin_name
from pysh.plugins.version import check_api_compatibility


def load_plugin_record(record: PluginRecord, manager: object) -> PluginInfo:
    """Import, validate, instantiate and register one plugin record."""
    path = record.candidate.path
    module: ModuleType | None = None
    try:
        module = _import_module_from_path(path, record.candidate.discovery_name)
        plugin_class = _find_plugin_class(module)
        info = _validate_plugin_metadata(plugin_class)
        if info.name != record.candidate.discovery_name:
            raise PluginValidationError(
                f"metadata name {info.name!r} must match filename {record.candidate.discovery_name!r}"
            )
        plugin = plugin_class()
        register = getattr(plugin, "register", None)
        if not callable(register):
            raise PluginValidationError("plugin register attribute is not callable")
        bundle = manager.begin_registration(info.name)
        api = PluginAPI(manager, info.name, bundle=bundle)
        register(api)
        manager.commit_registration_bundle(bundle)
    except BaseException as exc:
        if module is not None:
            sys.modules.pop(module.__name__, None)
        record.state = PluginState.FAILED
        record.errors.append(str(exc))
        raise PluginLoadError(str(exc)) from exc
    record.info = info
    record.state = PluginState.LOADED
    return info


def _import_module_from_path(path: Path, discovery_name: str) -> ModuleType:
    resolved = path.resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    module_name = f"pysh_plugin_{discovery_name.replace('-', '_')}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _find_plugin_class(module: ModuleType) -> type[object]:
    candidates: list[type[object]] = []
    for _name, value in inspect.getmembers(module, inspect.isclass):
        if value.__module__ != module.__name__:
            continue
        if all(hasattr(value, attr) for attr in ("name", "version", "api_version")):
            if callable(getattr(value, "register", None)):
                candidates.append(value)
    if not candidates:
        raise PluginValidationError("module defines no valid plugin class")
    if len(candidates) > 1:
        raise PluginValidationError("module defines multiple plugin classes")
    return candidates[0]


def _validate_plugin_metadata(plugin_class: type[object]) -> PluginInfo:
    name = validate_plugin_name(getattr(plugin_class, "name", None))
    version = getattr(plugin_class, "version", None)
    if not isinstance(version, str) or not version:
        raise PluginValidationError("plugin version must be a non-empty string")
    api_version = check_api_compatibility(getattr(plugin_class, "api_version", None))
    description = getattr(plugin_class, "description", "")
    author = getattr(plugin_class, "author", "")
    if not isinstance(description, str):
        raise PluginValidationError("plugin description must be a string")
    if not isinstance(author, str):
        raise PluginValidationError("plugin author must be a string")
    return PluginInfo(
        name=name,
        version=version,
        api_version=api_version,
        description=description,
        author=author,
    )
