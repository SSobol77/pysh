# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resource_governor_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #53 Slice 4: the published resource-governor contract matches the code."""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

import pytest

from pysh.plugins.isolated import launcher
from pysh.plugins.isolated.protocol import MAX_FRAME_BYTES
from pysh.plugins.isolated.resources import (
    DEFAULT_RESOURCE_CLASS,
    DEFAULT_RESOURCE_PROFILES,
    HARD_RESOURCE_CEILINGS,
    RESOURCE_CONTRACT_VERSION,
    ResourceBudget,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "security" / "resource-governor.md"
FIELDS = tuple(f.name for f in dataclasses.fields(ResourceBudget))
_UNITS = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def _text() -> str:
    return " ".join(DOC.read_text(encoding="utf-8").split())


def _section(heading: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index(heading)
    nxt = re.search(r"^#{2,3} ", text[start + len(heading):], re.MULTILINE)
    return text[start : start + len(heading) + (nxt.start() if nxt else len(text))]


def _number(cell: str) -> int:
    cell = cell.replace("`MAX_FRAME_BYTES`", "").strip().strip("()")
    match = re.search(r"(\d+)\s*(KiB|MiB|GiB)?", cell)
    assert match, cell
    return int(match.group(1)) * _UNITS.get(match.group(2) or "", 1)


def _rows(section: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"`\w+`", cells[0]) and cells[0].strip("`") in FIELDS:
            rows[cells[0].strip("`")] = cells[1:]
    return rows


def test_documented_hard_ceilings_match_the_constants() -> None:
    rows = _rows(_section("### Hard ceilings"))
    assert set(rows) == set(FIELDS)
    for field, cells in rows.items():
        assert _number(cells[0]) == getattr(HARD_RESOURCE_CEILINGS, field), field


@pytest.mark.parametrize(("column", "name"), [(0, "small"), (1, "standard"), (2, "large")])
def test_documented_profiles_match_the_constants(column: int, name: str) -> None:
    rows = _rows(_section("### Production profiles"))
    assert set(rows) == set(FIELDS)
    for field, cells in rows.items():
        assert _number(cells[column]) == getattr(DEFAULT_RESOURCE_PROFILES[name].budget, field)


def test_contract_is_versioned_and_default_class_is_documented() -> None:
    text = _text()
    assert f"contract version `{RESOURCE_CONTRACT_VERSION}`" in text
    assert RESOURCE_CONTRACT_VERSION == 1
    assert f"`{DEFAULT_RESOURCE_CLASS}`" in text
    assert HARD_RESOURCE_CEILINGS.message_bytes == MAX_FRAME_BYTES


def test_documentation_makes_only_truthful_claims() -> None:
    text = _text()
    for required in (
        "virtual address-space",
        "not a resident-memory meter",
        "per-real-UID",
        "FreeBSD execution evidence is pending",
        "Issue #53 is not complete",
        "no cgroup",
    ):
        assert required in text, required
    assert "Issue #53 is complete" not in text


def test_documented_exit_codes_and_mappings_match_the_launcher() -> None:
    text = _text()
    assert f"`{launcher.EXIT_POLICY_REJECTED}`" in text
    assert f"`{launcher.EXIT_APPLY_FAILED}`" in text
    for primitive in ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_VMEM", "RLIMIT_NOFILE", "RLIMIT_NPROC"):
        assert primitive in text


def test_definition_of_done_audit_lists_every_roadmap_criterion() -> None:
    audit = _section("## Definition-of-Done audit")
    for criterion in (
        "stopped without taking down the session",
        "timeout / OOM / fork-bomb",
        "hard ceilings enforced over user config",
        "Limits documented and versioned",
        "reported through Issue #50",
    ):
        assert criterion in audit, criterion


@pytest.mark.skipif(not sys.platform.startswith(("linux", "freebsd")), reason="Tier 1 only")
def test_tier_1_platform_exposes_the_required_rlimit_primitives() -> None:
    assert launcher.resource is not None
    names = launcher._rlimit_names()
    for field in ("cpu_seconds", "memory_bytes", "file_descriptors"):
        assert names[field] is not None, f"{field} has no rlimit primitive on {sys.platform}"
    launcher.check_platform_support(("cpu_seconds", "memory_bytes", "file_descriptors"))
