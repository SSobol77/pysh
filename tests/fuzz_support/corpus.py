# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/corpus.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Adapter from the #48 language-conformance corpus to parser-level seeds.

There is exactly one validator and one corpus: ``load_corpus`` from
``scripts/run_language_conformance.py`` validates the closed schema and contract
references, and this module only *reads* its result. No case is copied into a
second file and no new schema is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.run_language_conformance import (
    ALLOWED_PLACEHOLDERS,
    DEFAULT_CORPUS,
    DEFAULT_SPEC,
    PLACEHOLDER_RE,
    load_corpus,
)

#: Inert, fixed, non-existent values for parser-level use. Seeds never execute,
#: so placeholders only need to be deterministic text. Adding a runner
#: placeholder without extending this map fails loudly at import time.
INERT_PLACEHOLDERS: dict[str, str] = {
    "FIXTURE_BIN": "/inert/fixture-bin",
    "NOEXEC": "/inert/noexec",
    "WORK": "/inert/work",
    "HOME": "/inert/home",
}
if set(INERT_PLACEHOLDERS) != set(ALLOWED_PLACEHOLDERS):  # pragma: no cover - drift guard
    raise RuntimeError("fuzz corpus adapter does not cover every #48 placeholder")


@dataclass(frozen=True, slots=True)
class CorpusSeed:
    """One #48 case viewed as parser-level seed text."""

    case_id: str
    category: str
    surface: str
    contract_ref: str
    raw_input: str
    text: str
    diagnostic: str

    @property
    def is_syntax_error(self) -> bool:
        """True for cases whose #48 expectation is a syntax diagnostic."""
        return self.diagnostic == "syntax"


def substitute_inert(text: str) -> str:
    """Replace ``{{PLACEHOLDER}}`` tokens with fixed inert values (deterministic)."""
    return PLACEHOLDER_RE.sub(lambda match: INERT_PLACEHOLDERS[match.group(1)], text)


def load_seeds(path: Path = DEFAULT_CORPUS, spec_path: Path = DEFAULT_SPEC) -> list[CorpusSeed]:
    """Load every #48 case, in corpus order, through the single validator."""
    data = load_corpus(path, spec_path)
    return [
        CorpusSeed(
            case_id=case["id"],
            category=case["category"],
            surface=case["surface"],
            contract_ref=case["contract_ref"],
            raw_input=case["input"],
            text=substitute_inert(case["input"]),
            diagnostic=case["pysh_expected"]["diagnostic"],
        )
        for case in data["cases"]
    ]
