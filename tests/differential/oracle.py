# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/oracle.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure three-valued migration oracle (no process is ever executed here).

PySH semantics come from the #48 ``pysh_expected`` block; a legacy observation
is judged against that same expectation with the #48 matcher semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scripts.run_language_conformance import _compare_stream, _expand_input
from tests.differential.model import (
    Declared,
    Dimension,
    Evidence,
    MigrationCase,
    Observation,
    Outcome,
)


class StaleDivergenceError(AssertionError):
    """A declared intended divergence no longer differs: remove the obsolete exception."""


@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Outcome
    detail: str


def mismatches(
    expected: Mapping[str, Any],
    observed: Observation,
    dimensions: frozenset[Dimension],
    placeholders: Mapping[str, str],
) -> list[str]:
    """Differences between an observation and a #48 ``pysh_expected`` block."""
    found: list[str] = []
    if Dimension.STATUS in dimensions and observed.status != expected["status"]:
        found.append(f"status: expected {expected['status']}, observed {observed.status}")
    for dimension, actual in ((Dimension.STDOUT, observed.stdout), (Dimension.STDERR, observed.stderr)):
        if dimension not in dimensions:
            continue
        stream = dict(expected[dimension.value])
        stream["value"] = _expand_input(stream["value"], dict(placeholders))
        problem = _compare_stream(actual, stream, dimension.value)
        if problem:
            found.append(problem)
    return found


def classify(
    case: MigrationCase,
    pysh_expected: Mapping[str, Any],
    pysh_observation: Observation,
    legacy_observation: Observation,
    placeholders: Mapping[str, str] | None = None,
) -> Verdict:
    """Classify one case; raises :class:`StaleDivergenceError` for an obsolete divergence."""
    fill = placeholders or {}
    dims = case.compared_dimensions
    own = mismatches(pysh_expected, pysh_observation, dims, fill)
    if own:
        return Verdict(Outcome.REGRESSION, "PySH violates its own #48 expectation: " + "; ".join(own))
    legacy = mismatches(pysh_expected, legacy_observation, dims, fill)
    if not legacy:
        if case.declared is Declared.INTENDED_DIVERGENCE:
            raise StaleDivergenceError(
                f"{case.case_id}/{case.legacy_profile}: declared divergence "
                f"{case.migration_anchor} no longer differs; remove the exception"
            )
        return Verdict(Outcome.MATCH, "legacy observation satisfies the #48 expectation")
    if case.declared is Declared.INTENDED_DIVERGENCE:
        return Verdict(Outcome.INTENDED_DIVERGENCE, "documented: " + "; ".join(legacy))
    return Verdict(
        Outcome.REGRESSION, "declared match no longer holds on legacy side: " + "; ".join(legacy)
    )


def build_evidence(
    case: MigrationCase,
    verdict: Verdict,
    *,
    pysh_version: str,
    platform: str,
    legacy_tool_version: str | None,
    contract_ref: str,
    pysh_observation: Observation,
    legacy_observation: Observation,
) -> Evidence:
    """Assemble the deterministic evidence record for one classified case."""
    return Evidence(
        pysh_version, platform, case.case_id, case.legacy_profile, legacy_tool_version,
        pysh_observation, legacy_observation, verdict.outcome, contract_ref,
        case.migration_anchor,
    )
