# SPDX-License-Identifier: GPL-2.0-only
# File: tests/repro_support.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Builders of valid reproducibility-evidence documents for the release-assurance tests."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from scripts import check_reproducibility_evidence as repro
from scripts import generate_release_sboms as sboms

VERSION = "9.8.7"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
TOOLS = {
    "wheel": {"python": "3.13.5", "build": "1.6.1", "twine": "7.0.0", "hatchling": "1.32.4"},
    "sdist": {"python": "3.13.5", "build": "1.6.1", "twine": "7.0.0", "hatchling": "1.32.4"},
    "deb": {"dpkg-deb": "1.22.22", "fakeroot": "1.37.1.1"},
    "rpm": {"rpmbuild": "4.19.1.1"},
    "freebsd_pkg": {"pkg": "2.0.6", "python": "3.13.5"},
}
DECLARED = {"wheel": ["hatchling>=1.27.0"], "sdist": ["hatchling>=1.27.0"]}


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def result(family: str, classification: str = repro.REPRODUCIBLE, *, version: str = VERSION,
           commit: str = COMMIT) -> dict[str, Any]:
    """One valid result entry of the given classification."""
    entry = next(f for f in sboms.FAMILIES if f.family_id == family)
    base: dict[str, Any] = {
        "family": family, "artifact": entry.names[0].format(v=version), "builder": repro.BUILDERS[family],
        "classification": classification, "platform": repro.REQUIRED_PLATFORM[family],
        "platform_release": "6.12.0", "architecture": "x86_64", "python": "3.13.5",
        "tools": dict(TOOLS[family]), "declared_requirements": list(DECLARED.get(family, [])),
        "source_date_epoch": "1791065736",
        "source_date_epoch_origin": repro.SDE_ORIGIN,
        "build_a_sha256": digest(family + "a"), "build_b_sha256": digest(family + "a"), "equal": True,
        "build_a_source_commit": commit, "build_b_source_commit": commit,
        "build_a_source_tree_sha256": digest("tree"), "build_b_source_tree_sha256": digest("tree"),
        "separate_source_roots": True, "separate_output_files": True,
        "release_sha256": digest(family + "a"), "release_matches_build_a": True, "release_matches_build_b": True,
        "diagnostic": "",
    }
    if classification == repro.NON_REPRODUCIBLE:
        base.update(build_b_sha256=digest(family + "b"), equal=False, release_matches_build_b=False,
                    diagnostic="archive members differ: data.tar.xz")
    elif classification in {repro.PLATFORM_BLOCKED, repro.NOT_YET_MEASURED}:
        for key in ("build_a_sha256", "build_b_sha256", "equal", "build_a_source_commit", "build_b_source_commit",
                    "build_a_source_tree_sha256", "build_b_source_tree_sha256", "separate_source_roots",
                    "separate_output_files", "source_date_epoch", "source_date_epoch_origin", "release_sha256",
                    "release_matches_build_a", "release_matches_build_b"):
            base[key] = None
        base.update(tools={}, declared_requirements=[], diagnostic="rpmbuild was not found on PATH")
    return base


def document(results: list[dict[str, Any]], *, version: str = VERSION, commit: str = COMMIT) -> dict[str, Any]:
    return {
        "schema_version": repro.SCHEMA_VERSION, "source_commit": commit, "version": version,
        "build_environment": dict(repro.BUILD_ENVIRONMENT), "results": deepcopy(results),
    }


def final_document(*, version: str = VERSION, commit: str = COMMIT) -> dict[str, Any]:
    """Valid FINAL evidence: all five families measured on their required platform."""
    return document([result(f, version=version, commit=commit) for f in repro.FAMILY_ORDER], version=version, commit=commit)
