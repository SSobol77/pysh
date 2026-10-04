# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_candidate_docs.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #35: the 1.0.0 release-candidate documents are structurally complete and honest."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs" / "development"
VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

READINESS_HEADINGS = (
    "Candidate Identity", "Critical-Path Closure", "Release Blockers", "Non-Blocking Findings",
    "Accepted Limitations", "Public API Freeze", "Architecture Boundaries", "Security and Threat Model",
    "Plugin Isolation and Capabilities", "Diagnostics and Redaction", "Language Conformance",
    "Parser and Tokenizer Fuzzing", "Differential Migration", "Resource Governor", "Performance Budgets",
    "Platform Tier Matrix", "Packaging Matrix", "Supply-Chain Assurance", "Installation Validation",
    "Interactive Validation", "Documentation Audit", "Rollback and Yank Strategy", "Final Evidence",
    "Release Decision",
)


def readiness() -> str:
    return (DOCS / "v1.0.0-readiness.md").read_text(encoding="utf-8")


def test_the_readiness_report_has_every_required_section_in_order() -> None:
    headings = re.findall(r"^## (.+)$", readiness(), re.M)
    assert tuple(headings) == READINESS_HEADINGS
    assert readiness().startswith("<!--") and "# PySH v1.0.0 Readiness Audit" in readiness()


def test_every_critical_path_issue_is_traced() -> None:
    text = readiness()
    for number in range(43, 55):
        assert re.search(rf"^\| #{number} \| .+ \| CLOSED \| PR", text, re.M), number


def test_the_decision_is_not_written_as_go_before_the_final_evidence_exists() -> None:
    decision = readiness().split("## Release Decision", 1)[1]
    first = next(line for line in decision.splitlines() if line.strip())
    assert first == "PENDING FINAL CI AND SUPPLY-CHAIN VALIDATION"
    assert not re.search(r"^GO\b", decision, re.M) and "GO with a known blocker" not in decision.replace("no GO with a known blocker", "")


def test_no_release_blocker_remains_and_no_candidate_run_ids_are_recorded_in_the_report() -> None:
    text = readiness()
    assert "RELEASE_BLOCKER count: 0." in text
    assert not re.search(r"\|\s*RELEASE_BLOCKER\s*\|\s*[A-Z]", text.split("RELEASE_BLOCKER count: 0.", 1)[0].split("| ID |", 1)[1])
    assert not re.search(r"\b\d{11}\b", text), "run IDs belong in the Issue #35 comment, not in the candidate commit"


def test_the_changelog_has_a_finalized_section_for_the_current_version() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(VERSION)} - (\d{{4}}-\d{{2}}-\d{{2}})$", text, re.M)
    assert match, "the release section must carry a real date, not Unreleased"
    section = text[match.start():].split("\n## ", 1)[0].lower()
    for topic in (
        "public api", "semver", "architecture", "threat model", "isolated-plugin", "diagnostic", "redaction",
        "language specification", "conformance", "fuzz", "differential", "resource governor", "performance",
        "platform", "reproducib", "sbom", "provenance", "attestation", "quality gate",
    ):
        assert topic in section, topic
    assert "not a bash, zsh" in " ".join(section.split())


def test_the_release_notes_state_the_positioning_and_the_package_families() -> None:
    text = " ".join((DOCS / f"release-notes-{VERSION}.md").read_text(encoding="utf-8").split())
    for needle in (
        f"# PySH v{VERSION}", "CPython 3.13 or newer", "PySH is Python-first", "It is not `/bin/sh`",
        "not a Bash, Zsh, or Fish clone", "Legacy shells appear only as migration and differential test references",
        f"pysh_shell-{VERSION}-py3-none-any.whl", f"pysh_shell-{VERSION}.tar.gz", f"pysh-shell_{VERSION}-1_all.deb",
        f"pysh-shell-{VERSION}-1.noarch.rpm", f"pysh-shell-{VERSION}.pkg", "SHA256SUMS", "REPRODUCIBILITY.json",
        "SPDX 2.3", "gh attestation verify", "## Upgrade", "## Known limitations", "twelve public files",
        "not removed before PySH 1.2.0",
    ):
        assert needle in text, needle
    assert not re.search(r"<[A-Za-z][^>]*>", re.sub(r"`[^`]*`|<!--.*?-->|<https?://[^>]+>", "", text, flags=re.S).replace("<artifact>", "").replace("<package>", "").replace("<release-source-SHA>", "").replace("<artifact-basename>", ""))


def test_the_pypi_stability_classifier_matches_the_one_point_zero_contract() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    classifiers = project["classifiers"]
    if VERSION.split(".")[0] != "0":
        assert "Development Status :: 5 - Production/Stable" in classifiers
        assert not any(c.startswith("Development Status :: 3") for c in classifiers)
    assert project["requires-python"] == ">=3.13"
    assert "Operating System :: POSIX :: BSD :: FreeBSD" in classifiers  # a Tier 1 family in platform-tiers.md


def test_the_rollback_and_yank_policy_is_documented() -> None:
    text = " ".join((DOCS / "release.md").read_text(encoding="utf-8").split())
    for needle in (
        "Published release versions are immutable", "Never overwrite or re-upload the version", "Yank the release",
        "normally 1.0.1", "Do not silently substitute released bytes", "does not promise any rollback mechanism",
    ):
        assert needle in text, needle
