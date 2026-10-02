# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/resources.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Resource-budget contract, profiles, hard ceilings, and resolution policy.

This module is the canonical Issue #53 policy layer for isolated plugins. It
only *describes*, *resolves*, and *plans* budgets. It performs no OS
enforcement: ``setrlimit`` is applied by the separate launcher boundary
(``pysh.plugins.isolated.launcher``). It is stdlib-only, free of
platform-specific imports, and never reads environment variables, so no
ambient state can raise a ceiling.

Resolution rule (one deterministic rule, no silent clamping)::

    profile budget <= hard ceiling          (checked when a profile is built)
    requested      <= profile budget        (overrides may only LOWER)
    effective      = requested if present else profile budget

Because every accepted override is ``<=`` the profile and every profile is
``<=`` the ceiling, ``effective == min(profile, requested, ceiling)`` always
holds. An override that would raise a value is rejected, never clamped.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pysh.plugins.isolated.errors import ResourcePolicyError
from pysh.plugins.isolated.protocol import MAX_FRAME_BYTES

RESOURCE_CONTRACT_VERSION: Final = 1

_KIB: Final = 1024
_MIB: Final = 1024 * _KIB

# --- Hard ceilings -------------------------------------------------------
# Project policy data. No configuration, manifest, environment variable, or
# plugin value can raise these. Rationale: isolated plugins are short-lived
# helpers; the roadmap's existing point limits are a 5 s command-substitution
# timeout and a 2 s IPC handshake/request default, so even the largest
# ceiling is a bounded multiple, not an open-ended allowance.

#: CPU time in whole seconds. 120 s caps a runaway busy loop at two minutes.
HARD_CEILING_CPU_SECONDS: Final = 120
#: Address-space/resident memory in bytes. 1 GiB is generous for a CPython
#: helper and small enough to protect a developer workstation.
HARD_CEILING_MEMORY_BYTES: Final = 1024 * _MIB
#: Wall-clock lifetime in whole seconds. 600 s (10 min) bounds even idle hangs.
HARD_CEILING_WALL_CLOCK_SECONDS: Final = 600
#: Open file descriptors (count). 256 covers sockets/pipes for brokered use.
HARD_CEILING_FILE_DESCRIPTORS: Final = 256
#: Simultaneous processes/threads in the plugin process group (count).
HARD_CEILING_PROCESSES: Final = 32
#: Bytes of one IPC message/output. Never above the wire-protocol frame limit.
HARD_CEILING_MESSAGE_BYTES: Final = MAX_FRAME_BYTES
#: Simultaneous in-flight requests per plugin (count).
HARD_CEILING_CONCURRENCY: Final = 8

_RESOURCE_CLASS_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class ResourceViolation(StrEnum):
    """Bounded categories of resource-budget violation.

    Declared by Slice 1 so later enforcement and ``RESOURCE`` diagnostics share
    one vocabulary. Slice 1 never emits a violation.
    """

    WALL_CLOCK = "wall_clock"
    CPU = "cpu"
    MEMORY = "memory"
    FILE_DESCRIPTORS = "file_descriptors"
    PROCESSES = "processes"
    MESSAGE_SIZE = "message_size"
    CONCURRENCY = "concurrency"


_CEILINGS: Final[Mapping[str, int]] = MappingProxyType({
    "cpu_seconds": HARD_CEILING_CPU_SECONDS,
    "memory_bytes": HARD_CEILING_MEMORY_BYTES,
    "wall_clock_seconds": HARD_CEILING_WALL_CLOCK_SECONDS,
    "file_descriptors": HARD_CEILING_FILE_DESCRIPTORS,
    "processes": HARD_CEILING_PROCESSES,
    "message_bytes": HARD_CEILING_MESSAGE_BYTES,
    "concurrency": HARD_CEILING_CONCURRENCY,
})

_VIOLATION_FOR_FIELD: Final[Mapping[str, ResourceViolation]] = MappingProxyType({
    "cpu_seconds": ResourceViolation.CPU,
    "memory_bytes": ResourceViolation.MEMORY,
    "wall_clock_seconds": ResourceViolation.WALL_CLOCK,
    "file_descriptors": ResourceViolation.FILE_DESCRIPTORS,
    "processes": ResourceViolation.PROCESSES,
    "message_bytes": ResourceViolation.MESSAGE_SIZE,
    "concurrency": ResourceViolation.CONCURRENCY,
})


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """Immutable resource budget. ``None`` means "not specified".

    Units (all positive integers):

    * ``cpu_seconds``: CPU time, whole seconds.
    * ``memory_bytes``: memory, bytes.
    * ``wall_clock_seconds``: elapsed real time, whole seconds.
    * ``file_descriptors``: open descriptor count.
    * ``processes``: simultaneous process/thread count in the plugin group.
    * ``message_bytes``: bytes per IPC message/output; never above
      ``MAX_FRAME_BYTES``.
    * ``concurrency``: simultaneous in-flight requests.

    Every present value must be ``<=`` its hard ceiling. A partial budget is a
    valid *override*; a complete budget (see :attr:`is_complete`) is a profile
    or an effective result.
    """

    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    wall_clock_seconds: int | None = None
    file_descriptors: int | None = None
    processes: int | None = None
    message_bytes: int | None = None
    concurrency: int | None = None

    def __post_init__(self) -> None:
        for name, ceiling in _CEILINGS.items():
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ResourcePolicyError(f"{name} must be a positive integer or None")
            if value <= 0:
                raise ResourcePolicyError(f"{name} must be a positive integer or None")
            if value > ceiling:
                raise ResourcePolicyError(f"{name} exceeds the hard ceiling of {ceiling}")

    @property
    def configured(self) -> bool:
        """Return whether any limit is specified."""
        return any(getattr(self, f.name) is not None for f in fields(self))

    @property
    def is_complete(self) -> bool:
        """Return whether every limit is specified."""
        return all(getattr(self, f.name) is not None for f in fields(self))


#: Compatibility name for the Issue #44 seam type; the same canonical class.
IsolatedResourceLimits = ResourceBudget

HARD_RESOURCE_CEILINGS: Final = ResourceBudget(**_CEILINGS)


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    """Named, complete, immutable default budget for one task class."""

    name: str
    budget: ResourceBudget

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _RESOURCE_CLASS_RE.fullmatch(self.name):
            raise ResourcePolicyError("resource profile name must be a valid identifier")
        if not isinstance(self.budget, ResourceBudget) or not self.budget.is_complete:
            raise ResourcePolicyError(f"resource profile {self.name!r} must be a complete budget")


SMALL_PROFILE: Final = ResourceProfile(
    "small",
    ResourceBudget(
        cpu_seconds=5,
        memory_bytes=128 * _MIB,
        wall_clock_seconds=10,
        file_descriptors=32,
        processes=4,
        message_bytes=64 * _KIB,
        concurrency=1,
    ),
)
STANDARD_PROFILE: Final = ResourceProfile(
    "standard",
    ResourceBudget(
        cpu_seconds=15,
        memory_bytes=256 * _MIB,
        wall_clock_seconds=30,
        file_descriptors=64,
        processes=8,
        message_bytes=128 * _KIB,
        concurrency=2,
    ),
)
LARGE_PROFILE: Final = ResourceProfile(
    "large",
    ResourceBudget(
        cpu_seconds=60,
        memory_bytes=512 * _MIB,
        wall_clock_seconds=300,
        file_descriptors=128,
        processes=16,
        message_bytes=MAX_FRAME_BYTES,
        concurrency=4,
    ),
)

#: Production profile catalog. Immutable; tests inject their own catalogs.
DEFAULT_RESOURCE_PROFILES: Final[Mapping[str, ResourceProfile]] = MappingProxyType({
    profile.name: profile for profile in (SMALL_PROFILE, STANDARD_PROFILE, LARGE_PROFILE)
})


def build_profile_catalog(profiles: tuple[ResourceProfile, ...]) -> Mapping[str, ResourceProfile]:
    """Return an immutable catalog from validated profiles; duplicates are rejected."""
    catalog: dict[str, ResourceProfile] = {}
    for profile in profiles:
        if not isinstance(profile, ResourceProfile):
            raise ResourcePolicyError("catalog entries must be ResourceProfile instances")
        if profile.name in catalog:
            raise ResourcePolicyError(f"duplicate resource profile {profile.name!r}")
        catalog[profile.name] = profile
    return MappingProxyType(catalog)


def resolve_resource_budget(
    resource_class: str | None,
    requested: ResourceBudget | None = None,
    *,
    catalog: Mapping[str, ResourceProfile] = DEFAULT_RESOURCE_PROFILES,
) -> ResourceBudget:
    """Resolve the complete effective budget for ``resource_class``.

    Fails closed with :class:`ResourcePolicyError` when the class is missing or
    unknown, or when ``requested`` would raise any profile value. There is no
    fallback profile and nothing is read from the environment.
    """
    if resource_class is None:
        raise ResourcePolicyError("a resource class is required to resolve a resource budget")
    if not isinstance(resource_class, str):
        raise ResourcePolicyError("resource class must be a string")
    profile = catalog.get(resource_class)
    if profile is None:
        raise ResourcePolicyError(f"unknown resource class {resource_class!r}")
    override = requested if requested is not None else ResourceBudget()
    if not isinstance(override, ResourceBudget):
        raise ResourcePolicyError("requested budget must be a ResourceBudget")
    values: dict[str, int] = {}
    for name in _CEILINGS:
        base = getattr(profile.budget, name)
        wanted = getattr(override, name)
        if wanted is not None and wanted > base:
            raise ResourcePolicyError(
                f"requested {name} exceeds the {resource_class!r} profile budget of {base}"
            )
        values[name] = base if wanted is None else wanted
    return ResourceBudget(**values)


def violation_for_field(field_name: str) -> ResourceViolation:
    """Return the violation category for a budget field name."""
    try:
        return _VIOLATION_FOR_FIELD[field_name]
    except KeyError:
        raise ResourcePolicyError(f"unknown resource budget field {field_name!r}") from None


# --- Enforcement planning (Slice 2) ----------------------------------------
# Floors below which a budget is structurally unable to run a CPython plugin.
# They are rejected deterministically; a lower request is never raised silently.

#: Descriptors 0-2 plus the interpreter's startup needs.
MIN_ENFORCED_FILE_DESCRIPTORS: Final = 8
#: Virtual address space (``RLIMIT_AS``) below this cannot map a CPython image.
MIN_ENFORCED_MEMORY_BYTES: Final = 32 * _MIB
#: A handshake frame must be able to fit.
MIN_ENFORCED_MESSAGE_BYTES: Final = 1024

#: Fields applied by the OS-backed launcher (``setrlimit``).
OS_ENFORCED_FIELDS: Final = ("cpu_seconds", "memory_bytes", "file_descriptors")
#: Fields enforced by the parent at the IPC boundary.
PROTOCOL_ENFORCED_FIELDS: Final = ("message_bytes",)
#: Fields with no independent enforcement yet (later Issue #53 slices).
UNENFORCED_FIELDS: Final = ("wall_clock_seconds", "concurrency")

_MINIMUMS: Final[Mapping[str, int]] = MappingProxyType({
    "file_descriptors": MIN_ENFORCED_FILE_DESCRIPTORS,
    "memory_bytes": MIN_ENFORCED_MEMORY_BYTES,
    "message_bytes": MIN_ENFORCED_MESSAGE_BYTES,
})


class ProcessLimitMode(StrEnum):
    """How the ``processes`` budget is treated.

    ``RLIMIT_NPROC`` is a per-real-UID process count, not a per-plugin
    descendant count, so it cannot truthfully enforce a plugin-tree budget.

    * ``DEFERRED`` (default): ``processes`` is not enforced; it is reported as
      deferred. An *explicit* process override is refused (fail closed).
    * ``OS_PER_UID``: opt in to applying the value to ``RLIMIT_NPROC`` with its
      real per-UID semantics.
    """

    DEFERRED = "deferred"
    OS_PER_UID = "os_per_uid"


@dataclass(frozen=True, slots=True)
class ResourceEnforcementPlan:
    """What is enforced, how, and what is knowingly not enforced."""

    effective: ResourceBudget
    os_limits: Mapping[str, int]
    message_bytes: int
    deferred_fields: tuple[str, ...]


def plan_enforcement(
    effective: ResourceBudget,
    requested: ResourceBudget | None = None,
    *,
    process_mode: ProcessLimitMode = ProcessLimitMode.DEFERRED,
) -> ResourceEnforcementPlan:
    """Turn a resolved budget into an enforcement plan, failing closed.

    Rejects budgets below the enforceable floors and *explicit* requests for
    fields that no layer enforces yet. Profile defaults for such fields are
    reported in ``deferred_fields`` instead of being silently ignored.
    """
    if not isinstance(effective, ResourceBudget) or not effective.is_complete:
        raise ResourcePolicyError("an enforcement plan requires a complete effective budget")
    if not isinstance(process_mode, ProcessLimitMode):
        raise ResourcePolicyError("process_mode must be a ProcessLimitMode")
    explicit = requested if requested is not None else ResourceBudget()
    for name, floor in _MINIMUMS.items():
        if getattr(effective, name) < floor:
            raise ResourcePolicyError(f"{name} is below the enforceable minimum of {floor}")
    for name in UNENFORCED_FIELDS:
        if getattr(explicit, name) is not None:
            raise ResourcePolicyError(f"{name} is not enforced yet; refusing to pretend it is")
    deferred = list(UNENFORCED_FIELDS)
    os_limits = {name: getattr(effective, name) for name in OS_ENFORCED_FIELDS}
    if process_mode is ProcessLimitMode.OS_PER_UID:
        os_limits["processes"] = effective.processes
    else:
        if explicit.processes is not None:
            raise ResourcePolicyError(
                "processes cannot be enforced per plugin; use ProcessLimitMode.OS_PER_UID "
                "to apply the per-UID RLIMIT_NPROC primitive"
            )
        deferred.append("processes")
    return ResourceEnforcementPlan(
        effective=effective,
        os_limits=MappingProxyType(os_limits),
        message_bytes=effective.message_bytes,
        deferred_fields=tuple(sorted(deferred)),
    )
