# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/engines.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deterministic stdlib case generator (no Hypothesis, no global random state).

Every case is derived from ``random.Random(f"{GENERATOR_VERSION}:{seed}:{iteration}")``.
``random.Random`` seeds ``str`` values through SHA-512, which is specified to be
stable across platforms and Python versions, so the same ``(seed, iteration)``
yields the same input on Debian and FreeBSD and any single case can be replayed
in O(1) with :func:`case_at`. Changing any atom table requires bumping
``GENERATOR_VERSION``.

Input domain (all ``str``; the parser never receives raw bytes):

* word atoms are ``zq``-prefixed so ``~word`` can never name a real account and
  ``$word`` can never name a real environment variable;
* ``/`` is deliberately absent, so glob patterns stay relative to the empty
  temporary cwd and can never reach the host filesystem;
* NUL and lone surrogates are included; targets that cross an OS boundary with
  them are classified explicitly in ``targets.py``;
* length is bounded by ``MAX_CASE_CHARS``.
"""
from __future__ import annotations

import random
import shlex
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

GENERATOR_VERSION = "1"
MAX_CASE_CHARS = 240
MAX_ATOMS = 40

# Operator characters that the PySH grammar recognizes only when unquoted.
OPERATOR_CHARS = frozenset(";&|<>#")

_WORDS = ("zqa", "zqb", "zqfoo", "zq1", "zq_x")
_SPACES = (" ", " ", "\t")
_OPERATORS = (";", "&&", "||", "|", "&")
_REDIRECTS = ("<", ">", ">>", "2>", "2>&1", "1>&2", ">&2", "&>", "&>>", "<<", "<<-", "<<<")
_QUOTES = ("'", '"')
_MISC = ("#", "$", "${", "$(", ")", "`", "*", "?", "[", "~", "=", "\n", "py {", "}", "EOF")
_UNICODE = ("é", "日本", "\U0001f600")
_SURROGATES = ("\udc80", "\udcff", "\ud800")
_NUL = ("\x00",)
_BACKSLASH = ("\\",)


@dataclass(frozen=True, slots=True)
class GeneratorProfile:
    """Which atom families a generated case may contain."""

    backslash: bool = True
    nul: bool = True
    surrogates: bool = True


GENERAL = GeneratorProfile()
#: Profile for properties whose oracle (``is_unquoted_at``) does not model
#: backslash escapes; escaped operators are covered by fixed examples instead.
NO_BACKSLASH = GeneratorProfile(backslash=False)


def _atoms(profile: GeneratorProfile) -> tuple[str, ...]:
    atoms = _WORDS + _SPACES + _OPERATORS + _REDIRECTS + _QUOTES + _MISC + _UNICODE
    if profile.backslash:
        atoms += _BACKSLASH
    if profile.nul:
        atoms += _NUL
    if profile.surrogates:
        atoms += _SURROGATES
    return atoms


def _rng(seed: int, iteration: int, stream: str) -> random.Random:
    return random.Random(f"{GENERATOR_VERSION}:{stream}:{seed}:{iteration}")


def case_at(seed: int, iteration: int, profile: GeneratorProfile = GENERAL) -> str:
    """Return the generated case for ``(seed, iteration)`` without iterating."""
    rng = _rng(seed, iteration, "general")
    atoms = _atoms(profile)
    count = rng.randint(0, MAX_ATOMS)
    return "".join(rng.choice(atoms) for _ in range(count))[:MAX_CASE_CHARS]


def generated_cases(
    seed: int, count: int, profile: GeneratorProfile = GENERAL
) -> Iterator[tuple[int, str]]:
    """Yield ``(iteration, text)`` for ``count`` iterations of ``seed``."""
    for iteration in range(count):
        yield iteration, case_at(seed, iteration, profile)


def quoted_operator_line_at(seed: int, iteration: int) -> str:
    """Return a backslash-free line whose operators sit inside valid quotes.

    Built from words and single/double quoted segments whose bodies contain only
    operator characters and word text, so by PYSH-LANG-QUOTE-RULES none of the
    operator characters is an unquoted operator.
    """
    rng = _rng(seed, iteration, "quoted")
    segments: list[str] = []
    for _ in range(rng.randint(1, 6)):
        body = "".join(
            rng.choice(("; ", "&&", "||", "|", "&", "<", ">", ">>", "2>&1", "#", " ", *_WORDS))
            for _ in range(rng.randint(1, 5))
        )
        quote = rng.choice(("'", '"'))
        segments.append(f"{quote}{body}{quote}")
        if rng.random() < 0.5:
            segments.append(rng.choice(_WORDS))
    return " ".join(segments)


_ARGV_ALPHABET = (
    "abcXYZ019 \t'\"\\$`;&|<>#*?[]~(){}=!,.:@%+-^éü日"
)


def argv_case_at(seed: int, iteration: int) -> list[str]:
    """Return a non-empty argv of non-empty NUL-free strings.

    Empty strings are excluded because PYSH-LANG-LEX-WORDS makes an empty quoted
    argument intentionally unspecified.
    """
    rng = _rng(seed, iteration, "argv")
    return [
        "".join(rng.choice(_ARGV_ALPHABET) for _ in range(rng.randint(1, 12)))
        for _ in range(rng.randint(1, 5))
    ]


def quote_for_pysh(argument: str) -> str:
    """Single-quote ``argument`` using only PYSH-LANG-LEX/QUOTE-RULES constructs.

    ``'`` inside the text is written as ``'\\''`` (close quote, escaped quote,
    reopen), relying on "an unquoted backslash quotes the next character".
    """
    return "'" + argument.replace("'", "'\\''") + "'"


def quote_with_shlex(argument: str) -> str:
    """``shlex.quote`` as a *builder* on the restricted :data:`_ARGV_ALPHABET`.

    Used only because for that alphabet single-quote preservation makes PySH and
    POSIX agree; it is never an oracle for arbitrary strings.
    """
    return shlex.quote(argument)


def mutated_case_at(seed_texts: Sequence[str], seed: int, iteration: int) -> tuple[int, str]:
    """Deterministically mutate one corpus text; returns ``(source_index, text)``."""
    rng = _rng(seed, iteration, "mutate")
    index = rng.randrange(len(seed_texts))
    text = seed_texts[index]
    atoms = _atoms(GENERAL)
    for _ in range(rng.randint(1, 3)):
        operation = rng.choice(("insert", "delete", "duplicate", "swap"))
        position = rng.randint(0, len(text))
        if operation == "insert":
            text = text[:position] + rng.choice(atoms) + text[position:]
        elif operation == "delete" and text:
            position = min(position, len(text) - 1)
            text = text[:position] + text[position + 1 :]
        elif operation == "duplicate" and text:
            start = min(position, len(text) - 1)
            end = min(len(text), start + rng.randint(1, 8))
            text = text[:end] + text[start:end] + text[end:]
        elif operation == "swap" and len(text) > 1:
            start = min(position, len(text) - 2)
            text = text[:start] + text[start + 1] + text[start] + text[start + 2 :]
    return index, text[:MAX_CASE_CHARS]


# --- structured execution cases (Issue #49 slice 3) ---------------------------------
#
# Execution/fd robustness never receives arbitrary bytes: cases are bounded
# pipelines of known-safe commands over tmp-dir file names, plus one
# deterministic injected failure. ``fault`` is ``(operation, call_index)``.

SAFE_STAGES = (
    "echo zq",
    "cat",
    "true",
    "cat < in.txt",
    "cat > out.txt",
    "cat >> out.txt",
    "echo zq 2>&1",
    "cat 2> err.txt",
    "pwd > cwd.txt",
)
FAULT_OPERATIONS = {"fork": 4, "pipe": 3, "dup": 7, "dup2": 5, "open": 3}


@dataclass(frozen=True, slots=True)
class PipelineCase:
    """A bounded pipeline plus an optional injected failure."""

    stages: tuple[str, ...]
    fault: tuple[str, int] | None = None

    @property
    def command(self) -> str:
        return " | ".join(self.stages)


def pipeline_case_at(seed: int, iteration: int) -> PipelineCase:
    rng = _rng(seed, iteration, "pipeline")
    stages = tuple(rng.choice(SAFE_STAGES) for _ in range(rng.randint(1, 4)))
    fault: tuple[str, int] | None = None
    if rng.random() < 0.75:
        operation = rng.choice(sorted(FAULT_OPERATIONS))
        fault = (operation, rng.randrange(FAULT_OPERATIONS[operation]))
    return PipelineCase(stages, fault)
