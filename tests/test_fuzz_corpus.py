# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fuzz_corpus.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 1: the #48 corpus adapter (single corpus, single validator)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import scripts.run_language_conformance as runner
from tests.fuzz_support import corpus as corpus_module
from tests.fuzz_support import engines
from tests.fuzz_support.corpus import INERT_PLACEHOLDERS, load_seeds, substitute_inert

REPO = Path(__file__).resolve().parents[1]
CANONICAL = runner.DEFAULT_CORPUS


def _raw_cases() -> list[dict]:
    return json.loads(CANONICAL.read_text(encoding="utf-8"))["cases"]


def test_every_conformance_case_loads_through_the_adapter() -> None:
    seeds = load_seeds()
    raw = _raw_cases()
    assert len(seeds) == len(raw) == 64
    assert {seed.case_id for seed in seeds} == {case["id"] for case in raw}


def test_seed_ids_are_unique() -> None:
    ids = [seed.case_id for seed in load_seeds()]
    assert len(ids) == len(set(ids))


def test_contract_refs_categories_and_surfaces_are_preserved() -> None:
    raw = {case["id"]: case for case in _raw_cases()}
    anchors = set(runner.CONTRACT_ANCHOR_RE.findall(runner.DEFAULT_SPEC.read_text(encoding="utf-8")))
    for seed in load_seeds():
        case = raw[seed.case_id]
        assert seed.contract_ref == case["contract_ref"]
        assert seed.contract_ref in anchors
        assert seed.category == case["category"]
        assert seed.surface == case["surface"]
        assert seed.raw_input == case["input"]


def test_syntax_error_cases_remain_identifiable_seeds() -> None:
    expected = {c["id"] for c in _raw_cases() if c["pysh_expected"]["diagnostic"] == "syntax"}
    seeds = load_seeds()
    assert expected  # the corpus does contain malformed-input cases
    assert {s.case_id for s in seeds if s.is_syntax_error} == expected
    assert expected <= {s.case_id for s in seeds}  # still ordinary seeds, not dropped


def test_source_corpus_is_not_mutated() -> None:
    before_bytes = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    before_data = copy.deepcopy(runner.load_corpus())
    load_seeds()
    load_seeds()
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == before_bytes
    assert runner.load_corpus() == before_data


def test_adapter_output_is_deterministic() -> None:
    assert load_seeds() == load_seeds()


def test_placeholder_replacement_is_deterministic_inert_and_complete() -> None:
    assert set(INERT_PLACEHOLDERS) == set(runner.ALLOWED_PLACEHOLDERS)
    assert substitute_inert("a {{FIXTURE_BIN}} {{WORK}}") == "a /inert/fixture-bin /inert/work"
    assert substitute_inert("{{HOME}}") == substitute_inert("{{HOME}}")
    seeds = load_seeds()
    assert all("{{" not in seed.text and "}}" not in seed.text for seed in seeds)
    assert any(seed.raw_input != seed.text for seed in seeds)  # placeholders do occur
    assert all(seed.text == substitute_inert(seed.raw_input) for seed in seeds)


def test_adapter_uses_the_single_conformance_validator(tmp_path: Path) -> None:
    assert corpus_module.load_corpus is runner.load_corpus
    broken = json.loads(CANONICAL.read_text(encoding="utf-8"))
    broken["cases"][0]["unexpected_field"] = "x"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(runner.CorpusError):
        load_seeds(path)


def test_no_secondary_language_corpus_exists() -> None:
    others = [
        path
        for path in (REPO / "tests").rglob("*.json")
        if path != CANONICAL and "contract_ref" in path.read_text(encoding="utf-8")
    ]
    assert others == []


def test_corpus_mutation_is_deterministic_and_bounded() -> None:
    texts = [seed.text for seed in load_seeds()]
    for iteration in range(50):
        first = engines.mutated_case_at(texts, 5, iteration)
        assert first == engines.mutated_case_at(texts, 5, iteration)
        assert len(first[1]) <= engines.MAX_CASE_CHARS
        assert 0 <= first[0] < len(texts)
    assert texts == [seed.text for seed in load_seeds()]  # inputs untouched
