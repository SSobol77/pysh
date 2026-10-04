# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/corpus.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Strict loader for the Issue #54 migration metadata (a layer over the #48 corpus).

The #48 corpus stays the only language oracle: this module validates that every
mapping names an existing #48 case and never stores ``pysh_expected``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.run_language_conformance import load_corpus
from tests.differential.model import (
    Declared,
    Dimension,
    Guidance,
    GuidanceKind,
    LegacyProfile,
    MigrationCase,
)
from tests.differential.startup import POLICIES

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METADATA = Path(__file__).with_name("migration-v1.json")
DEFAULT_DOC = REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md"
SCHEMA_VERSION = 1

TOP_FIELDS = frozenset({"schema_version", "legacy_profiles", "cases"})
PROFILE_FIELDS = frozenset({
    "profile_id", "legacy_shell", "platform", "executable", "startup_policy",
    "version", "package_version", "version_status",
})
CASE_FIELDS = frozenset({
    "case_id", "legacy_profile", "classification", "compared_dimensions",
    "migration_anchor", "guidance", "rationale",
})
LEGACY_SHELLS = frozenset({"bash", "zsh", "fish"})
VERSION_STATUSES = frozenset({"pending", "pinned"})
PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9.]*(?:-[a-z0-9.]+)*\Z")
PLATFORM_RE = re.compile(r"[a-z]+[0-9][0-9.]*-[a-z0-9_]+\Z")
DIVERGENCE_ANCHOR_RE = re.compile(r"PYSH-MIG-DIV-[A-Z0-9]+(?:-[A-Z0-9]+)*\Z")
ANCHOR_DEFINITION_RE = re.compile(r'<a id="(PYSH-MIG-[A-Z0-9-]+)"></a>')


class MigrationError(ValueError):
    """The migration metadata violates its closed contract."""


@dataclass(frozen=True, slots=True)
class MigrationMetadata:
    profiles: dict[str, LegacyProfile]
    cases: tuple[MigrationCase, ...]


def _exact(value: object, allowed: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MigrationError(f"{context}: expected an object")
    missing, unknown = sorted(allowed - set(value)), sorted(set(value) - allowed)
    if missing or unknown:
        raise MigrationError(f"{context}: missing fields {missing!r}; unknown fields {unknown!r}")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"{context}: expected a non-empty string")
    return value


def _optional_text(value: object, context: str) -> str | None:
    return None if value is None else _text(value, context)


def _guidance(value: object, context: str) -> Guidance:
    if not isinstance(value, dict):
        raise MigrationError(f"{context}: expected an object")
    kind_text = _text(value.get("kind"), f"{context}.kind")
    try:
        kind = GuidanceKind(kind_text)
    except ValueError as error:
        raise MigrationError(f"{context}.kind: unknown guidance kind {kind_text!r}") from error
    detail_field = (
        "pysh_replacement" if kind is GuidanceKind.PYSH_NATIVE_REPLACEMENT else "reason"
    )
    _exact(value, frozenset({"kind", "legacy_construct", detail_field}), context)
    return Guidance(
        kind,
        _text(value["legacy_construct"], f"{context}.legacy_construct"),
        _text(value[detail_field], f"{context}.{detail_field}"),
    )


def parse_migration(
    data: object,
    *,
    language_case_ids: frozenset[str],
    divergence_anchors: frozenset[str],
) -> MigrationMetadata:
    """Validate decoded metadata against the closed schema and its references."""
    root = _exact(data, TOP_FIELDS, "metadata root")
    if root["schema_version"] != SCHEMA_VERSION or isinstance(root["schema_version"], bool):
        raise MigrationError(f"unsupported schema_version {root['schema_version']!r}")

    profiles: dict[str, LegacyProfile] = {}
    if not isinstance(root["legacy_profiles"], list) or not root["legacy_profiles"]:
        raise MigrationError("legacy_profiles: expected a non-empty list")
    for index, raw in enumerate(root["legacy_profiles"]):
        context = f"legacy_profiles[{index}]"
        item = _exact(raw, PROFILE_FIELDS, context)
        profile_id = _text(item["profile_id"], f"{context}.profile_id")
        if not PROFILE_ID_RE.fullmatch(profile_id):
            raise MigrationError(f"{context}.profile_id: invalid ID {profile_id!r}")
        if profile_id in profiles:
            raise MigrationError(f"duplicate legacy profile: {profile_id}")
        shell = _text(item["legacy_shell"], f"{context}.legacy_shell")
        if shell not in LEGACY_SHELLS:
            raise MigrationError(f"{context}.legacy_shell: unknown shell {shell!r}")
        status = _text(item["version_status"], f"{context}.version_status")
        if status not in VERSION_STATUSES:
            raise MigrationError(f"{context}.version_status: unknown value {status!r}")
        platform = _text(item["platform"], f"{context}.platform")
        if not PLATFORM_RE.fullmatch(platform):
            raise MigrationError(f"{context}.platform: invalid platform ID {platform!r}")
        if profile_id != f"{shell}-{platform}":
            raise MigrationError(f"{context}.profile_id: expected '{shell}-{platform}'")
        executable = _text(item["executable"], f"{context}.executable")
        if not executable.startswith("/") or ".." in executable.split("/"):
            raise MigrationError(f"{context}.executable: expected a normalized absolute path")
        policy_id = _text(item["startup_policy"], f"{context}.startup_policy")
        policy = POLICIES.get(policy_id)
        if policy is None or policy.shell != shell:
            raise MigrationError(f"{context}.startup_policy: {policy_id!r} is not a {shell} policy")
        version = _optional_text(item["version"], f"{context}.version")
        package_version = _optional_text(item["package_version"], f"{context}.package_version")
        if status == "pending" and (version is not None or package_version is not None):
            raise MigrationError(f"{context}: a pending profile carries no version evidence")
        if status == "pinned" and (version is None or package_version is None):
            raise MigrationError(f"{context}: a pinned profile needs version and package_version")
        profiles[profile_id] = LegacyProfile(
            profile_id, shell, platform, executable, policy_id, version, package_version, status
        )

    if not isinstance(root["cases"], list):
        raise MigrationError("cases: expected a list")
    cases: list[MigrationCase] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(root["cases"]):
        context = f"cases[{index}]"
        item = _exact(raw, CASE_FIELDS, context)
        case_id = _text(item["case_id"], f"{context}.case_id")
        if case_id not in language_case_ids:
            raise MigrationError(f"{context}.case_id: unknown #48 case {case_id!r}")
        profile_id = _text(item["legacy_profile"], f"{context}.legacy_profile")
        if profile_id not in profiles:
            raise MigrationError(f"{context}.legacy_profile: unknown profile {profile_id!r}")
        if (case_id, profile_id) in seen:
            raise MigrationError(f"duplicate case/profile mapping: {case_id}/{profile_id}")
        seen.add((case_id, profile_id))
        declared_text = _text(item["classification"], f"{context}.classification")
        try:
            declared = Declared(declared_text)
        except ValueError as error:
            raise MigrationError(
                f"{context}.classification: unknown classification {declared_text!r}"
            ) from error
        raw_dims = item["compared_dimensions"]
        if not isinstance(raw_dims, list) or not raw_dims or len(set(map(str, raw_dims))) != len(raw_dims):
            raise MigrationError(f"{context}.compared_dimensions: expected a non-empty unique list")
        try:
            dimensions = frozenset(Dimension(d) for d in raw_dims)
        except ValueError as error:
            raise MigrationError(f"{context}.compared_dimensions: {error}") from error
        anchor = _optional_text(item["migration_anchor"], f"{context}.migration_anchor")
        guidance_raw = item["guidance"]
        if declared is Declared.INTENDED_DIVERGENCE:
            if anchor is None or not DIVERGENCE_ANCHOR_RE.fullmatch(anchor):
                raise MigrationError(
                    f"{context}.migration_anchor: a divergence needs a PYSH-MIG-DIV-* anchor"
                )
            if anchor not in divergence_anchors:
                raise MigrationError(f"{context}.migration_anchor: anchor {anchor!r} is not documented")
            guidance: Guidance | None = _guidance(guidance_raw, f"{context}.guidance")
        else:
            if anchor is not None or guidance_raw is not None:
                raise MigrationError(f"{context}: a match carries no anchor or guidance")
            guidance = None
        cases.append(MigrationCase(
            case_id, profile_id, declared, dimensions, anchor, guidance,
            _text(item["rationale"], f"{context}.rationale"),
        ))
    return MigrationMetadata(profiles, tuple(cases))


def documented_divergence_anchors(doc: Path = DEFAULT_DOC) -> frozenset[str]:
    """``PYSH-MIG-DIV-*`` anchors defined in the migration document."""
    found = ANCHOR_DEFINITION_RE.findall(doc.read_text(encoding="utf-8"))
    if len(found) != len(set(found)):
        raise MigrationError("migration document defines a duplicate anchor")
    return frozenset(a for a in found if DIVERGENCE_ANCHOR_RE.fullmatch(a))


def load_migration(
    path: Path = DEFAULT_METADATA, doc: Path = DEFAULT_DOC
) -> MigrationMetadata:
    """Load the metadata, validating it against the #48 corpus and the document."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"cannot load {path}: {error}") from error
    language = load_corpus()
    return parse_migration(
        data,
        language_case_ids=frozenset(case["id"] for case in language["cases"]),
        divergence_anchors=documented_divergence_anchors(doc),
    )
