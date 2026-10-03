# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/model.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Immutable data model for the PySH-owned migration contract."""
from __future__ import annotations

import enum
from dataclasses import dataclass


class Outcome(enum.Enum):
    """Observed migration outcome, from PySH's perspective."""

    MATCH = "MATCH"
    INTENDED_DIVERGENCE = "INTENDED_DIVERGENCE"
    REGRESSION = "REGRESSION"


class Declared(enum.Enum):
    """Classifications metadata may declare. ``REGRESSION`` is never declarable."""

    MATCH = "match"
    INTENDED_DIVERGENCE = "intended_divergence"


class Dimension(enum.Enum):
    """Observable dimensions a case may compare."""

    STATUS = "status"
    STDOUT = "stdout"
    STDERR = "stderr"


class GuidanceKind(enum.Enum):
    PYSH_NATIVE_REPLACEMENT = "pysh_native_replacement"
    INTENTIONALLY_UNSUPPORTED = "intentionally_unsupported"


@dataclass(frozen=True, slots=True)
class LegacyProfile:
    """Reference identity: test metadata, never a dependency.

    ``version`` and ``platform`` stay ``None`` (``version_status == "pending"``)
    until established from a controlled Tier-1 reference environment.
    """

    profile_id: str
    legacy_shell: str
    version: str | None
    version_status: str
    platform: str | None


@dataclass(frozen=True, slots=True)
class Guidance:
    """Migration guidance for an intended divergence."""

    kind: GuidanceKind
    legacy_construct: str
    detail: str  # the PySH-native replacement, or the reason it is unsupported


@dataclass(frozen=True, slots=True)
class MigrationCase:
    """One migration mapping layered over a #48 case (``case_id``)."""

    case_id: str
    legacy_profile: str
    declared: Declared
    compared_dimensions: frozenset[Dimension]
    migration_anchor: str | None
    guidance: Guidance | None
    rationale: str


@dataclass(frozen=True, slots=True)
class Observation:
    """Observed status/stdout/stderr (already placeholder-expanded, deterministic)."""

    status: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class Evidence:
    """Deterministic future release-evidence record (no HOME, env, secrets, timestamps)."""

    pysh_version: str
    platform: str
    case_id: str
    legacy_profile: str
    legacy_tool_version: str | None
    pysh_observation: Observation
    legacy_observation: Observation
    outcome: Outcome
    contract_ref: str
    migration_anchor: str | None

    def to_dict(self) -> dict[str, object]:
        def obs(value: Observation) -> dict[str, object]:
            return {"status": value.status, "stdout": value.stdout, "stderr": value.stderr}

        return {
            "pysh_version": self.pysh_version,
            "platform": self.platform,
            "case_id": self.case_id,
            "legacy_profile": self.legacy_profile,
            "legacy_tool_version": self.legacy_tool_version,
            "pysh_observation": obs(self.pysh_observation),
            "legacy_observation": obs(self.legacy_observation),
            "outcome": self.outcome.value,
            "contract_ref": self.contract_ref,
            "migration_anchor": self.migration_anchor,
        }
