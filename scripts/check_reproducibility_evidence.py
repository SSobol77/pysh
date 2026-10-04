#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_reproducibility_evidence.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Validate release reproducibility evidence (Issue #51, Slice 4).

Stdlib-only, offline and read-only. It owns the evidence schema (version 1) and the
classification semantics that ``scripts/measure_release_reproducibility.py`` produces
and that the release workflow publishes as ``REPRODUCIBILITY.json``.

An artifact is REPRODUCIBLE only when two independent clean builds of the same source
commit under the same declared build contract produce byte-for-byte identical public
artifacts (SHA-256 equality). Semantic equivalence is never reproducibility.

Classifications are exactly REPRODUCIBLE, NON_REPRODUCIBLE, NOT_YET_MEASURED and
PLATFORM_BLOCKED. Two modes exist:

* ``local``: a developer or CI measurement. Any non-empty subset of families is accepted
  and PLATFORM_BLOCKED / NOT_YET_MEASURED are allowed, each with a diagnostic.
* ``final``: release evidence. All five families must be measured (REPRODUCIBLE or
  NON_REPRODUCIBLE) on their required platform and bound to the shipped bytes (the
  already-staged public artifact hashes to build A or build B); PLATFORM_BLOCKED and
  NOT_YET_MEASURED are rejected. A NON_REPRODUCIBLE result is valid measured evidence when it carries a
  documented reason; its release impact is reviewed in the readiness audit (#35).

Exit codes: 0 valid, 1 invalid, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import generate_release_sboms as sboms  # noqa: E402

SCHEMA_VERSION = 1
EVIDENCE_FILENAME = sboms.EVIDENCE

REPRODUCIBLE = "REPRODUCIBLE"
NON_REPRODUCIBLE = "NON_REPRODUCIBLE"
NOT_YET_MEASURED = "NOT_YET_MEASURED"
PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
CLASSIFICATIONS = (REPRODUCIBLE, NON_REPRODUCIBLE, NOT_YET_MEASURED, PLATFORM_BLOCKED)
MEASURED = frozenset({REPRODUCIBLE, NON_REPRODUCIBLE})

#: Canonical family order of every evidence document.
FAMILY_ORDER = tuple(f.family_id for f in sboms.FAMILIES)
#: The repository builder each family is measured with (never an alternative format).
BUILDERS = {
    "wheel": "scripts/build_pysh_package.sh",
    "sdist": "scripts/build_pysh_package.sh",
    "deb": "scripts/build_deb.sh",
    "rpm": "scripts/build_rpm.sh",
    "freebsd_pkg": "scripts/build_freebsd_pkg.sh",
}
#: Tool metadata a measured result must carry (real tooling, not a placeholder).
REQUIRED_TOOLS = {
    "wheel": ("python", "build", "hatchling"),
    "sdist": ("python", "build", "hatchling"),
    "deb": ("dpkg-deb",),
    "rpm": ("rpmbuild",),
    "freebsd_pkg": ("pkg", "python"),
}
#: The build backend whose RESOLVED version a wheel/sdist measurement must carry.
BACKEND = "hatchling"
#: Platform that must have produced a measured result in final evidence.
REQUIRED_PLATFORM = {
    "wheel": "Linux", "sdist": "Linux", "deb": "Linux", "rpm": "Linux", "freebsd_pkg": "FreeBSD",
}
#: A FreeBSD package is only valid evidence from a native FreeBSD builder, in every mode.
NATIVE_ONLY = {"freebsd_pkg": "FreeBSD"}
#: The declared build contract every measured build runs under: environment variables and the
#: umask (package directory modes depend on it; GitHub-hosted runners use 022 as well).
BUILD_VARIABLES = {"LC_ALL": "C.UTF-8", "TZ": "UTC"}
BUILD_UMASK = 0o022
BUILD_ENVIRONMENT = {**BUILD_VARIABLES, "umask": f"{BUILD_UMASK:04o}"}
SDE_ORIGIN = "commit-timestamp"

SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
VERSION_RE = re.compile(r"[0-9][0-9A-Za-z.+!-]*")
#: An EXACT tool version ("1.32.4", "4.19.1.1", "2.0.6_1"), never a requirement such as ">=1.27.0".
EXACT_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)*(?:[+~_-][0-9A-Za-z.+~_-]+)?")
EPOCH_RE = re.compile(r"[0-9]{1,12}")

TOP_KEYS = {"schema_version", "source_commit", "version", "build_environment", "results"}
RESULT_KEYS = {
    "family", "artifact", "classification", "builder", "platform", "platform_release", "architecture",
    "python", "tools", "declared_requirements", "source_date_epoch", "source_date_epoch_origin", "build_a_sha256", "build_b_sha256",
    "equal", "build_a_source_commit", "build_b_source_commit", "build_a_source_tree_sha256",
    "build_b_source_tree_sha256", "separate_source_roots", "separate_output_files", "release_sha256",
    "release_matches_build_a", "release_matches_build_b", "diagnostic",
}
RELEASE_KEYS = ("release_sha256", "release_matches_build_a", "release_matches_build_b")


def expected_artifact(family: str, version: str) -> tuple[str, ...]:
    """Accepted canonical basenames of ``family`` (owned by the SBOM generator's family table)."""
    for entry in sboms.FAMILIES:
        if entry.family_id == family:
            return tuple(name.format(v=version) for name in entry.names)
    return ()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_result(result: object, version: str, source_commit: str, mode: str) -> list[str]:
    """Problems of one result entry (empty when valid)."""
    if not isinstance(result, dict):
        return ["a result entry must be an object"]
    family = result.get("family")
    label = str(family) if isinstance(family, str) else "?"
    problems: list[str] = []

    def bad(message: str) -> None:
        problems.append(f"{label}: {message}")

    if set(result) != RESULT_KEYS:
        bad(f"fields must be exactly {sorted(RESULT_KEYS)}: missing={sorted(RESULT_KEYS - set(result))} "
            f"extra={sorted(set(result) - RESULT_KEYS)}")
        return problems
    if family not in FAMILY_ORDER:
        bad("unknown family")
        return problems
    assert isinstance(family, str)
    classification = result["classification"]
    if classification not in CLASSIFICATIONS:
        bad(f"classification must be one of {list(CLASSIFICATIONS)}")
        return problems
    if result["artifact"] not in expected_artifact(family, version):
        bad(f"artifact must be a canonical basename for version {version}: {result['artifact']!r}")
    if result["builder"] != BUILDERS[family]:
        bad(f"builder must be the repository builder {BUILDERS[family]}")
    for key in ("platform", "platform_release", "architecture", "python"):
        if not _text(result[key]):
            bad(f"{key} metadata is required")
    tools = result["tools"]
    if not isinstance(tools, dict) or not all(_text(k) and _text(v) for k, v in tools.items()):
        bad("tools must map tool names to version strings")
        tools = {}
    if not isinstance(result["diagnostic"], str):
        bad("diagnostic must be a string")
    sha_a, sha_b = result["build_a_sha256"], result["build_b_sha256"]

    if classification in MEASURED:
        _check_measured(result, classification, family, source_commit, tools, mode, bad)
        if classification == REPRODUCIBLE and not (sha_a == sha_b and result["equal"] is True):
            bad("REPRODUCIBLE requires two identical SHA-256 digests and equal=true")
        if classification == NON_REPRODUCIBLE:
            if sha_a == sha_b or result["equal"] is not False:
                bad("NON_REPRODUCIBLE requires two different SHA-256 digests and equal=false")
            if not _text(result["diagnostic"]):
                bad("NON_REPRODUCIBLE requires a documented reason in diagnostic")
    else:
        for key in ("build_a_sha256", "build_b_sha256", "equal", "build_a_source_commit", "build_b_source_commit",
                    "build_a_source_tree_sha256", "build_b_source_tree_sha256", "separate_source_roots",
                    "separate_output_files", *RELEASE_KEYS):
            if result[key] is not None:
                bad(f"{classification} must not claim a build outcome ({key} must be null)")
        if not _text(result["diagnostic"]):
            bad(f"{classification} requires a diagnostic naming the reason")
        if mode == "final":
            bad(f"{classification} is not accepted in final evidence")
    native = NATIVE_ONLY.get(family)
    if native and classification in MEASURED and result["platform"] != native:
        bad(f"a measured {family} result is only valid from a native {native} builder (found {result['platform']!r})")
    if mode == "final" and classification in MEASURED and result["platform"] != REQUIRED_PLATFORM[family]:
        bad(f"final evidence requires the {family} measurement on {REQUIRED_PLATFORM[family]} (found {result['platform']!r})")
    return problems


def _check_measured(
    result: Mapping[str, Any], classification: str, family: str, source_commit: str,
    tools: Mapping[str, str], mode: str, bad: Any,
) -> None:
    for key in ("build_a_sha256", "build_b_sha256", "build_a_source_tree_sha256", "build_b_source_tree_sha256"):
        value = result[key]
        if not (isinstance(value, str) and SHA256_RE.fullmatch(value)):
            bad(f"{key} must be a lowercase hexadecimal SHA-256")
    if not isinstance(result["equal"], bool):
        bad("equal must be a boolean for a measured result")
    for key in ("build_a_source_commit", "build_b_source_commit"):
        if result[key] != source_commit:
            bad(f"{key} must equal the evidence source commit {source_commit[:12]}")
    if result["build_a_source_tree_sha256"] != result["build_b_source_tree_sha256"]:
        bad("builds A and B were not made from an identical source tree")
    if result["separate_source_roots"] is not True:
        bad("builds A and B must use separate source/build roots")
    if result["separate_output_files"] is not True:
        bad("builds A and B must produce separate output files (no reuse of an output)")
    epoch = result["source_date_epoch"]
    if not (isinstance(epoch, str) and EPOCH_RE.fullmatch(epoch)):
        bad("source_date_epoch must be the commit timestamp as decimal seconds")
    if result["source_date_epoch_origin"] != SDE_ORIGIN:
        bad(f"source_date_epoch_origin must be {SDE_ORIGIN!r}, never wall-clock time")
    for tool in REQUIRED_TOOLS[family]:
        if tool not in tools:
            bad(f"tool metadata for {tool} is required (a measured result needs the real tooling)")
    for tool, version in sorted(tools.items()):
        if not EXACT_VERSION_RE.fullmatch(version):
            bad(f"tool {tool} must record its exact resolved version, not {version!r}")
    declared = result["declared_requirements"]
    if not (isinstance(declared, list) and all(_text(item) for item in declared)):
        bad("declared_requirements must be a list of requirement strings")
    elif family in {"wheel", "sdist"}:
        if not any(item.startswith(BACKEND) for item in declared):
            bad(f"declared_requirements must record the declared {BACKEND} requirement (separate from its resolved version)")
    elif declared:
        bad("declared_requirements applies only to wheel and sdist")
    _check_release_binding(result, mode, bad)


def _check_release_binding(result: Mapping[str, Any], mode: str, bad: Any) -> None:
    """The evidence must describe the shipped bytes: the staged public artifact equals build A or B."""
    release, in_a, in_b = (result[key] for key in RELEASE_KEYS)
    if release is None and in_a is None and in_b is None:
        if mode == "final":
            bad("final evidence requires the release-byte binding (release_sha256 and the release_matches flags)")
        return
    if not (isinstance(release, str) and SHA256_RE.fullmatch(release)):
        bad("release_sha256 must be a lowercase hexadecimal SHA-256")
        return
    if not (isinstance(in_a, bool) and isinstance(in_b, bool)):
        bad("release_matches_build_a and release_matches_build_b must be booleans when release_sha256 is present")
        return
    if in_a != (release == result["build_a_sha256"]) or in_b != (release == result["build_b_sha256"]):
        bad("the release_matches flags contradict the recorded digests")
    if not (release == result["build_a_sha256"] or release == result["build_b_sha256"]):
        bad("the release artifact matches neither measured build, so the evidence does not describe the shipped bytes")


def check_document(document: object, *, mode: str, source_commit: str | None = None) -> list[str]:
    """All problems of an evidence document, in a deterministic order (empty when valid)."""
    if mode not in {"local", "final"}:
        return [f"unknown mode {mode!r}"]
    if not isinstance(document, dict):
        return ["the evidence must be a JSON object"]
    problems: list[str] = []
    if set(document) != TOP_KEYS:
        return [f"top-level fields must be exactly {sorted(TOP_KEYS)}: missing={sorted(TOP_KEYS - set(document))} "
                f"extra={sorted(set(document) - TOP_KEYS)}"]
    if document["schema_version"] != SCHEMA_VERSION or isinstance(document["schema_version"], bool):
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    commit = document["source_commit"]
    if not (isinstance(commit, str) and COMMIT_RE.fullmatch(commit)):
        problems.append("source_commit must be a full lowercase 40-hex commit SHA")
        commit = ""
    elif source_commit is not None and commit != source_commit:
        problems.append(f"source_commit {commit[:12]} does not match the expected commit {source_commit[:12]}")
    version = document["version"]
    if not (isinstance(version, str) and VERSION_RE.fullmatch(version)):
        problems.append("version must be the release version")
        version = ""
    if document["build_environment"] != BUILD_ENVIRONMENT:
        problems.append(f"build_environment must be exactly {BUILD_ENVIRONMENT}")
    results = document["results"]
    if not isinstance(results, list) or not results:
        problems.append("results must be a non-empty list")
        return problems
    families = [r.get("family") if isinstance(r, dict) else None for r in results]
    seen: set[object] = set()
    for family in families:
        if family in seen:
            problems.append(f"duplicate family: {family}")
        seen.add(family)
    known = [f for f in families if f in FAMILY_ORDER]
    if known != sorted(known, key=FAMILY_ORDER.index) and len(set(known)) == len(known):
        problems.append(f"results must be in canonical family order {list(FAMILY_ORDER)}")
    for result in results:
        problems.extend(check_result(result, version, commit, mode))
    if mode == "final":
        for family in FAMILY_ORDER:
            if family not in families:
                problems.append(f"final evidence must measure every family: {family} is missing")
    return problems


def load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read evidence {path.name}: {error}") from error


def canonical_json(document: object) -> str:
    """The one serialization: sorted keys, two-space indent, trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("evidence", type=Path, help="path of the evidence JSON document")
    parser.add_argument("--mode", choices=("local", "final"), default="local")
    parser.add_argument("--source-commit", help="the exact commit SHA the evidence must be bound to")
    args = parser.parse_args(argv)
    if args.source_commit is not None and not COMMIT_RE.fullmatch(args.source_commit):
        print("check_reproducibility_evidence: --source-commit must be a full lowercase 40-hex SHA", file=sys.stderr)
        return 2
    try:
        document = load(args.evidence)
    except ValueError as error:
        print(f"check_reproducibility_evidence: FAIL: {error}", file=sys.stderr)
        return 1
    problems = check_document(document, mode=args.mode, source_commit=args.source_commit)
    for problem in problems:
        print(f"check_reproducibility_evidence: FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    assert isinstance(document, dict)
    for result in document["results"]:
        print(f"classification {result['family']}: {result['classification']}")
    print(f"check_reproducibility_evidence: PASS ({args.mode} mode, {len(document['results'])} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
