# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_registry.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Plugin API registry, names and versioning."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.contracts import PLUGIN_API_VERSION
from pysh.plugins.errors import PluginValidationError, PluginVersionError
from pysh.plugins.models import PluginSource
from pysh.plugins.names import validate_plugin_name
from pysh.plugins.registry import PluginRegistry, discover_plugin_files
from pysh.plugins.version import check_api_compatibility


@pytest.mark.parametrize("version", [(1, 0)])
def test_plugin_api_version_accepts_current(version: tuple[int, int]) -> None:
    assert PLUGIN_API_VERSION == (1, 0)
    assert check_api_compatibility(version) == version


@pytest.mark.parametrize(
    "version",
    [(1, 1), (2, 0), (0, 9), "1.0", (1,), (1, 0, 0), (True, 0), (1, "0")],
)
def test_plugin_api_version_rejects_incompatible_or_malformed(version: object) -> None:
    with pytest.raises(PluginVersionError):
        check_api_compatibility(version)


@pytest.mark.parametrize("name", ["a", "Plugin_1", "plugin-name", "A123"])
def test_plugin_name_validation_accepts_strict_names(name: str) -> None:
    assert validate_plugin_name(name) == name


@pytest.mark.parametrize("name", ["", "1bad", "-bad", ".hidden", "bad.name", "bad/name", "a" * 65])
def test_plugin_name_validation_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_name(name)


def test_discovery_is_direct_and_deterministic(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("", encoding="utf-8")

    candidates = discover_plugin_files(tmp_path, PluginSource.USER)

    assert [candidate.discovery_name for candidate in candidates] == ["a", "b"]


def test_registry_enabled_records_are_explicit(tmp_path: Path) -> None:
    candidate = discover_plugin_files(_write_plugin(tmp_path, "alpha"), PluginSource.USER)[0]
    registry = PluginRegistry()
    registry.discover(candidate)

    assert registry.enabled_records() == ()
    registry.enable("alpha")
    assert [record.candidate.discovery_name for record in registry.enabled_records()] == ["alpha"]


def test_project_records_require_project_opt_in(tmp_path: Path) -> None:
    candidate = discover_plugin_files(_write_plugin(tmp_path, "alpha"), PluginSource.PROJECT)[0]
    registry = PluginRegistry()
    registry.discover(candidate)
    registry.enable("alpha")

    assert registry.enabled_records() == ()
    registry.project_plugins_enabled = True
    assert [record.candidate.source for record in registry.enabled_records()] == [PluginSource.PROJECT]


def test_duplicate_plugin_names_are_deterministic(tmp_path: Path) -> None:
    user_candidate = discover_plugin_files(_write_plugin(tmp_path / "user", "alpha"), PluginSource.USER)[0]
    project_candidate = discover_plugin_files(
        _write_plugin(tmp_path / "project", "alpha"),
        PluginSource.PROJECT,
    )[0]
    registry = PluginRegistry()
    registry.discover(user_candidate, project_candidate)
    registry.enable("alpha")
    registry.project_plugins_enabled = True

    enabled = registry.enabled_records()

    assert [record.candidate.source for record in enabled] == [PluginSource.USER]


def _write_plugin(tmp_path: Path, name: str) -> Path:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / f"{name}.py").write_text("", encoding="utf-8")
    return tmp_path
