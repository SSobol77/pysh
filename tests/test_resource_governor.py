# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resource_governor.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #53 Slice 1: resource-budget contract, profiles, and ceilings."""
from __future__ import annotations

import ast
import dataclasses
import math
import subprocess
import sys
from pathlib import Path

import pytest

from pysh.plugins.isolated import resources, runtime
from pysh.plugins.isolated.errors import LifecycleError, ResourcePolicyError
from pysh.plugins.isolated.manifest import validate_isolated_plugin_manifest
from pysh.plugins.isolated.protocol import MAX_FRAME_BYTES
from pysh.plugins.isolated.resources import (
    DEFAULT_RESOURCE_PROFILES,
    HARD_RESOURCE_CEILINGS,
    ResourceBudget,
    ResourceProfile,
    ResourceViolation,
    build_profile_catalog,
    resolve_resource_budget,
    violation_for_field,
)
from pysh.plugins.isolated.runtime import IsolatedPluginRuntime, IsolatedPluginState

FIELDS = tuple(f.name for f in dataclasses.fields(ResourceBudget))


def _manifest(resource_class: str | None = "small"):
    data: dict[str, object] = {
        "manifest_version": 1,
        "name": "gov-plugin",
        "plugin_version": "1.0",
        "protocol_version": 1,
        "entrypoint": [str(Path(sys.executable).resolve()), "-c", "pass"],
        "requested_capabilities": [],
    }
    if resource_class is not None:
        data["resource_class"] = resource_class
    return validate_isolated_plugin_manifest(data)


def test_budget_fields_are_the_documented_set() -> None:
    assert FIELDS == (
        "cpu_seconds",
        "memory_bytes",
        "wall_clock_seconds",
        "file_descriptors",
        "processes",
        "message_bytes",
        "concurrency",
    )


def test_default_profiles_exist_and_are_complete() -> None:
    assert set(DEFAULT_RESOURCE_PROFILES) == {"small", "standard", "large"}
    for name, profile in DEFAULT_RESOURCE_PROFILES.items():
        assert profile.name == name
        assert profile.budget.is_complete


def test_hard_ceilings_exist_and_message_ceiling_is_protocol_limit() -> None:
    assert HARD_RESOURCE_CEILINGS.is_complete
    assert HARD_RESOURCE_CEILINGS.message_bytes == MAX_FRAME_BYTES


@pytest.mark.parametrize("name", sorted(DEFAULT_RESOURCE_PROFILES))
def test_profile_values_never_exceed_hard_ceilings(name: str) -> None:
    budget = DEFAULT_RESOURCE_PROFILES[name].budget
    for field in FIELDS:
        assert getattr(budget, field) <= getattr(HARD_RESOURCE_CEILINGS, field)


def test_profiles_are_ordered_small_standard_large() -> None:
    small, standard, large = (DEFAULT_RESOURCE_PROFILES[n].budget for n in
                              ("small", "standard", "large"))
    for field in FIELDS:
        assert getattr(small, field) <= getattr(standard, field) <= getattr(large, field)


def test_profile_catalog_is_immutable() -> None:
    with pytest.raises(TypeError):
        DEFAULT_RESOURCE_PROFILES["huge"] = DEFAULT_RESOURCE_PROFILES["large"]  # type: ignore[index]


def test_budget_and_profile_objects_are_immutable() -> None:
    budget = ResourceBudget(cpu_seconds=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        budget.cpu_seconds = 2  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_RESOURCE_PROFILES["small"].name = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        HARD_RESOURCE_CEILINGS.cpu_seconds = 10**6  # type: ignore[misc]
    assert not hasattr(budget, "__dict__")


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize(
    "bad",
    [0, -1, True, False, 1.5, math.inf, math.nan, "5", b"5", [1]],
)
def test_invalid_values_rejected(field: str, bad: object) -> None:
    with pytest.raises(ResourcePolicyError):
        ResourceBudget(**{field: bad})


@pytest.mark.parametrize("field", FIELDS)
def test_value_above_hard_ceiling_rejected_and_ceiling_accepted(field: str) -> None:
    ceiling = getattr(HARD_RESOURCE_CEILINGS, field)
    assert getattr(ResourceBudget(**{field: ceiling}), field) == ceiling
    with pytest.raises(ResourcePolicyError, match="hard ceiling"):
        ResourceBudget(**{field: ceiling + 1})


def test_message_budget_cannot_exceed_protocol_frame_limit() -> None:
    with pytest.raises(ResourcePolicyError):
        ResourceBudget(message_bytes=MAX_FRAME_BYTES + 1)
    effective = resolve_resource_budget("large")
    assert effective.message_bytes <= MAX_FRAME_BYTES


def test_resolution_without_override_returns_profile_budget() -> None:
    assert resolve_resource_budget("standard") == DEFAULT_RESOURCE_PROFILES["standard"].budget


def test_override_lowering_is_applied_per_field() -> None:
    base = DEFAULT_RESOURCE_PROFILES["standard"].budget
    effective = resolve_resource_budget(
        "standard", ResourceBudget(cpu_seconds=1, concurrency=1)
    )
    assert effective.cpu_seconds == 1
    assert effective.concurrency == 1
    assert effective.memory_bytes == base.memory_bytes
    assert effective.is_complete


@pytest.mark.parametrize("field", FIELDS)
def test_override_equal_to_profile_is_accepted(field: str) -> None:
    base = DEFAULT_RESOURCE_PROFILES["small"].budget
    effective = resolve_resource_budget(
        "small", ResourceBudget(**{field: getattr(base, field)})
    )
    assert effective == base


@pytest.mark.parametrize("field", FIELDS)
def test_override_cannot_raise_profile_budget(field: str) -> None:
    base = getattr(DEFAULT_RESOURCE_PROFILES["small"].budget, field)
    with pytest.raises(ResourcePolicyError, match="profile budget"):
        resolve_resource_budget("small", ResourceBudget(**{field: base + 1}))


@pytest.mark.parametrize("field", FIELDS)
def test_override_cannot_raise_hard_ceiling(field: str) -> None:
    with pytest.raises(ResourcePolicyError):
        resolve_resource_budget(
            "large", ResourceBudget(**{field: getattr(HARD_RESOURCE_CEILINGS, field) + 1})
        )


@pytest.mark.parametrize("name", sorted(DEFAULT_RESOURCE_PROFILES))
def test_effective_equals_min_of_profile_override_and_ceiling(name: str) -> None:
    profile = DEFAULT_RESOURCE_PROFILES[name].budget
    for field in FIELDS:
        lowered = max(1, getattr(profile, field) // 2)
        effective = resolve_resource_budget(name, ResourceBudget(**{field: lowered}))
        expected = min(getattr(profile, field), lowered, getattr(HARD_RESOURCE_CEILINGS, field))
        assert getattr(effective, field) == expected


def test_unknown_missing_and_non_string_resource_class_fail_closed() -> None:
    with pytest.raises(ResourcePolicyError, match="unknown resource class"):
        resolve_resource_budget("test")
    with pytest.raises(ResourcePolicyError, match="unknown resource class"):
        resolve_resource_budget("SMALL")
    with pytest.raises(ResourcePolicyError, match="required"):
        resolve_resource_budget(None)
    with pytest.raises(ResourcePolicyError):
        resolve_resource_budget(1)  # type: ignore[arg-type]


def test_requested_budget_type_is_validated() -> None:
    with pytest.raises(ResourcePolicyError):
        resolve_resource_budget("small", {"cpu_seconds": 1})  # type: ignore[arg-type]


def test_injected_test_profile_works_without_becoming_production() -> None:
    profile = ResourceProfile("test", ResourceBudget(
        cpu_seconds=1, memory_bytes=1024, wall_clock_seconds=1, file_descriptors=8,
        processes=1, message_bytes=1024, concurrency=1,
    ))
    catalog = build_profile_catalog((profile,))
    assert resolve_resource_budget("test", catalog=catalog) == profile.budget
    assert "test" not in DEFAULT_RESOURCE_PROFILES
    with pytest.raises(ResourcePolicyError):
        resolve_resource_budget("test")


def test_profile_must_be_complete_valid_named_and_unique() -> None:
    with pytest.raises(ResourcePolicyError, match="complete"):
        ResourceProfile("partial", ResourceBudget(cpu_seconds=1))
    with pytest.raises(ResourcePolicyError, match="identifier"):
        ResourceProfile("../x", DEFAULT_RESOURCE_PROFILES["small"].budget)
    small = DEFAULT_RESOURCE_PROFILES["small"]
    with pytest.raises(ResourcePolicyError, match="duplicate"):
        build_profile_catalog((small, small))
    with pytest.raises(ResourcePolicyError):
        build_profile_catalog(("small",))  # type: ignore[arg-type]


def test_environment_cannot_change_ceilings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PYSH_RESOURCE_CPU_SECONDS", "PYSH_RESOURCE_MEMORY_BYTES", "RLIMIT_CPU"):
        monkeypatch.setenv(name, "999999999")
    with pytest.raises(ResourcePolicyError):
        ResourceBudget(cpu_seconds=resources.HARD_CEILING_CPU_SECONDS + 1)
    assert resolve_resource_budget("large") == DEFAULT_RESOURCE_PROFILES["large"].budget


def test_violation_vocabulary_is_bounded_and_mapped() -> None:
    assert {v.value for v in ResourceViolation} == {
        "wall_clock", "cpu", "memory", "file_descriptors",
        "processes", "message_size", "concurrency",
    }
    assert {violation_for_field(f) for f in FIELDS} == set(ResourceViolation)
    with pytest.raises(ResourcePolicyError):
        violation_for_field("bogus")


def test_compat_alias_is_the_canonical_type() -> None:
    assert runtime.IsolatedResourceLimits is ResourceBudget
    assert resources.IsolatedResourceLimits is ResourceBudget
    assert ResourceBudget(memory_bytes=1024).configured
    assert not ResourceBudget().configured


def _imported_modules() -> set[str]:
    tree = ast.parse(Path(resources.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_resources_module_has_no_enforcement_or_platform_imports() -> None:
    forbidden = {"resource", "os", "signal", "subprocess", "threading", "sys"}
    assert not (_imported_modules() & forbidden)


# --- runtime integration ---------------------------------------------------


@pytest.fixture
def no_spawn(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def refuse(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("subprocess spawned")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    return calls


def test_runtime_refuses_spawn_when_valid_budget_configured(no_spawn: list[object]) -> None:
    rt = IsolatedPluginRuntime(
        _manifest("small"), resource_limits=ResourceBudget(memory_bytes=1024)
    )
    with pytest.raises(LifecycleError, match="Issue #53"):
        rt.start()
    assert rt.state is IsolatedPluginState.NEW
    assert rt.process_id is None
    assert no_spawn == []


def test_runtime_unknown_resource_class_fails_closed_without_spawn(no_spawn: list[object]) -> None:
    rt = IsolatedPluginRuntime(
        _manifest("test"), resource_limits=ResourceBudget(memory_bytes=1024)
    )
    with pytest.raises(LifecycleError, match="unknown resource class"):
        rt.start()
    assert rt.state is IsolatedPluginState.NEW
    assert no_spawn == []


def test_runtime_missing_resource_class_fails_closed_without_spawn(no_spawn: list[object]) -> None:
    rt = IsolatedPluginRuntime(
        _manifest(None), resource_limits=ResourceBudget(cpu_seconds=1)
    )
    with pytest.raises(LifecycleError, match="resource class is required"):
        rt.start()
    assert no_spawn == []


def test_runtime_override_above_profile_fails_closed_without_spawn(no_spawn: list[object]) -> None:
    rt = IsolatedPluginRuntime(
        _manifest("small"), resource_limits=ResourceBudget(cpu_seconds=60)
    )
    with pytest.raises(LifecycleError, match="profile budget"):
        rt.start()
    assert no_spawn == []


def test_runtime_without_budget_still_spawns_and_resource_class_is_inert() -> None:
    rt = IsolatedPluginRuntime(_manifest("anything-goes"))
    assert rt.state is IsolatedPluginState.NEW
    assert rt.shutdown() is True
