# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Compatibility contract documentation tests (Issue #4).

Verifies:
A. All required compatibility documents exist.
B. The feature matrix contains all required feature-area section headers.
C. No broad unqualified compatibility claims appear in root README.md or
   key compatibility documents.
D. The shell-compatibility-contract.md contains the required category
   definitions.

These tests are deterministic, file-system-only, and do not import pysh
runtime modules.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DOCS = REPO_ROOT / "docs"
COMPAT_DIR = DOCS / "compatibility"

# ---------------------------------------------------------------------------
# A. Required compatibility documents
# ---------------------------------------------------------------------------

REQUIRED_COMPAT_DOCS: list[str] = [
    "README.md",
    "shell-compatibility-contract.md",
    "feature-matrix.md",
    "posix-sh-scope.md",
    "zsh-scope.md",
    "bash-scope.md",
    "unsupported-constructs.md",
    "validation-matrix.md",
]


@pytest.mark.parametrize("filename", REQUIRED_COMPAT_DOCS)
def test_required_compatibility_doc_exists(filename: str) -> None:
    """Gate A: every required compatibility document must exist."""
    path = COMPAT_DIR / filename
    assert path.exists(), (
        f"Required compatibility document not found: docs/compatibility/{filename}\n"
        "This file must be created as part of Issue #4."
    )
    assert path.stat().st_size > 0, (
        f"Compatibility document is empty: docs/compatibility/{filename}"
    )


# ---------------------------------------------------------------------------
# B. Feature matrix section headers
# ---------------------------------------------------------------------------

# Each entry is the section heading text that must appear in feature-matrix.md.
REQUIRED_MATRIX_AREAS: list[str] = [
    "Command execution",
    "Builtins",
    "Aliases",
    "Variables",
    "Environment",
    "Quoting",
    "Escapes",
    "Operators",
    "Pipelines",
    "Redirection",
    "Command substitution",
    "Comments",
    "Temporary environment assignment",
    "Multiline paste",
    "Python runtime",
    "Python block",
    "Source",
    "Directory stack",
    "Completion",
    "History",
    "Globbing",
    "Heredocs",
    "Functions",
    "Arithmetic",
    "Parameter expansion",
    "Arrays",
    "Traps",
    "Job control",
    "Process substitution",
    "Brace expansion",
    "zsh",
    "bash",
    "Fallback",
    "Script mode",
]


def test_feature_matrix_contains_required_areas() -> None:
    """Gate B: feature-matrix.md must contain all required feature area headings."""
    matrix_path = COMPAT_DIR / "feature-matrix.md"
    if not matrix_path.exists():
        pytest.skip("feature-matrix.md does not exist (covered by test_required_compatibility_doc_exists)")

    text = matrix_path.read_text(encoding="utf-8")
    missing = [area for area in REQUIRED_MATRIX_AREAS if area not in text]
    assert not missing, (
        "feature-matrix.md is missing the following required area coverage:\n"
        + "\n".join(f"  - {a}" for a in missing)
    )


# ---------------------------------------------------------------------------
# C. Broad unqualified compatibility claim audit
# ---------------------------------------------------------------------------

# Files to audit for broad claims.
_AUDIT_FILES: list[Path] = [
    REPO_ROOT / "README.md",
    COMPAT_DIR / "shell-compatibility-contract.md",
    COMPAT_DIR / "README.md",
]

# Patterns that constitute a broad unqualified compatibility claim.
# Each pattern must NOT appear as an affirmative statement.
# We check that when such a phrase appears, a negation word is nearby.
_BROAD_CLAIM_PATTERNS: list[str] = [
    # Order matters: more specific first
    r"/bin/sh " + r"replacement",
    r"drop-in " + r"replacement",
]

# Phrases checked with context: these must appear with a negation word
# ("not", "no", "never", "isn't", "don't", "cannot") within the same
# sentence or immediately before the phrase.
_NEGATION_WORDS: re.Pattern[str] = re.compile(
    r"\b(not|no|never|isn'?t|don'?t|cannot|does not|is not|are not|must not|"
    r"will not|without|none)\b",
    re.IGNORECASE,
)


def _sentence_containing(text: str, match: re.Match[str]) -> str:
    """Return the sentence (or nearby context) containing the match."""
    start = max(0, match.start() - 120)
    end = min(len(text), match.end() + 120)
    return text[start:end].replace("\n", " ").strip()


def _has_nearby_negation(text: str, match: re.Match[str]) -> bool:
    """Return True if a negation word appears within 120 chars of the match."""
    context = _sentence_containing(text, match)
    return bool(_NEGATION_WORDS.search(context))


@pytest.mark.parametrize("doc_path", _AUDIT_FILES)
def test_no_broad_unqualified_compatibility_claims(doc_path: Path) -> None:
    """Gate C: no broad unqualified compatibility claims in audited documents.

    The forbidden patterns are only disallowed when they appear WITHOUT a
    nearby negation word. Qualified forms like "not an sh provider"
    are permitted.
    """
    if not doc_path.exists():
        pytest.skip(f"Audit target not found: {doc_path}")

    text = doc_path.read_text(encoding="utf-8")
    violations: list[str] = []

    for pattern in _BROAD_CLAIM_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not _has_nearby_negation(text, match):
                context = _sentence_containing(text, match)
                violations.append(
                    f"  [{doc_path.name}] unqualified claim: '{match.group()}'\n"
                    f"    Context: ...{context}..."
                )

    assert not violations, (
        "Unqualified broad compatibility claims found.\n"
        "Add a negation ('not a ...') or qualification, or move the phrase to\n"
        "docs/compatibility/shell-compatibility-contract.md under a forbidden-patterns"
        " section.\n\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# D. Contract category definitions
# ---------------------------------------------------------------------------

REQUIRED_CATEGORIES: list[str] = [
    "Native",
    "Transition",
    "Delegated",
    "Planned",
    "Unsupported",
    "Forbidden by default",
]


def test_contract_defines_all_categories() -> None:
    """Gate D: shell-compatibility-contract.md must define all six categories."""
    contract = COMPAT_DIR / "shell-compatibility-contract.md"
    if not contract.exists():
        pytest.skip("shell-compatibility-contract.md not found")

    text = contract.read_text(encoding="utf-8")
    missing = [cat for cat in REQUIRED_CATEGORIES if cat not in text]
    assert not missing, (
        "shell-compatibility-contract.md is missing category definitions:\n"
        + "\n".join(f"  - {c}" for c in missing)
    )


# ---------------------------------------------------------------------------
# E. docs/README.md has a Compatibility section
# ---------------------------------------------------------------------------


def test_docs_readme_has_compatibility_section() -> None:
    """docs/README.md must contain a Compatibility section."""
    readme = DOCS / "README.md"
    assert readme.exists(), "docs/README.md not found"
    text = readme.read_text(encoding="utf-8")
    assert "Compatibility" in text, (
        "docs/README.md must contain a 'Compatibility' section linking to "
        "docs/compatibility/README.md"
    )
    assert "compatibility/README.md" in text or "compatibility/" in text, (
        "docs/README.md must link to the docs/compatibility/ directory"
    )
