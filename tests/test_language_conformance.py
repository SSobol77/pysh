# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_language_conformance.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the versioned PySH v1 language conformance oracle."""
from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.run_language_conformance import (
    DEFAULT_CORPUS,
    DEFAULT_SPEC,
    SCHEMA_VERSION,
    CorpusError,
    load_corpus,
    run_corpus,
)


def _write_corpus(tmp_path: Path, data: dict[str, object]) -> Path:
    """Write one malformed-corpus fixture without executable serialization."""
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_language_corpus_closed_schema_and_contract_references() -> None:
    """The canonical corpus must parse and resolve its closed schema."""
    data = load_corpus()
    assert data["schema_version"] == SCHEMA_VERSION == 1
    assert data["language_version"] == "1"
    case_ids = [case["id"] for case in data["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert all(case["contract_ref"].startswith("PYSH-LANG-") for case in data["cases"])


def test_required_semantic_categories_have_conformance_evidence() -> None:
    """Every declared semantic category must retain at least one case."""
    data = load_corpus()
    counts = Counter(case["category"] for case in data["cases"])
    assert set(counts) == set(data["required_categories"])
    assert all(counts[category] > 0 for category in data["required_categories"])


def test_intrinsic_language_corpus_passes() -> None:
    """All canonical cases must match deterministic PySH intrinsic results."""
    results = run_corpus(load_corpus())
    failures = [f"{result.case_id}: {result.detail}" for result in results if not result.passed]
    assert not failures, "Language conformance failures:\n" + "\n".join(failures)


def test_representative_case_is_repeatable() -> None:
    """A fixture-dependent case must produce the same expectation repeatedly."""
    data = load_corpus()
    selected = next(case for case in data["cases"] if case["id"] == "path-glob-sorted")
    first = run_corpus({**data, "cases": [selected]})
    second = run_corpus({**data, "cases": [selected]})
    assert first == second
    assert first[0].passed


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=999), "unsupported schema_version"),
        (lambda data: data["cases"][0].update(extra=True), "unknown fields"),
        (
            lambda data: data["cases"][1].update(id=data["cases"][0]["id"]),
            "duplicate case ID",
        ),
        (lambda data: data["cases"][0].update(surface="tty"), "unsupported surface"),
        (
            lambda data: data["cases"][0].update(contract_ref="PYSH-LANG-NOT-REAL"),
            "unresolved contract ID",
        ),
        (
            lambda data: data["cases"][0].update(input="{{ARBITRARY_COMMAND}}"),
            "unknown placeholders",
        ),
        (lambda data: data.update(required_categories=["absent"]), "undeclared category"),
    ],
)
def test_malformed_corpus_is_rejected(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    """Malformed or capability-expanding corpus records must fail closed."""
    data = copy.deepcopy(load_corpus())
    mutation(data)
    with pytest.raises(CorpusError, match=message):
        load_corpus(_write_corpus(tmp_path, data), DEFAULT_SPEC)


def test_canonical_artifacts_use_documented_paths() -> None:
    """The reusable oracle artifacts must remain at their stable paths."""
    assert DEFAULT_CORPUS.name == "pysh-language-v1.json"
    assert DEFAULT_CORPUS.exists()
    assert DEFAULT_SPEC.name == "pysh-language.md"
    assert DEFAULT_SPEC.exists()
