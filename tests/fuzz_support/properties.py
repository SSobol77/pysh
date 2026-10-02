# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/properties.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Engine-neutral properties over the pure parser/tokenizer targets.

Properties are plain functions of ``(text, ctx)`` that raise ``AssertionError``
on violation; engines (the stdlib generator, corpus replay, corpus mutation)
only decide which text to feed them. Expected behavior is anchored in
``docs/spec/pysh-language.md`` (cited per property) and the #48 corpus; the
only oracle consulted besides the specification is the production quote-state
helper :func:`pysh.parsing.lexer.is_unquoted_at`, used for *consistency*
between scanners, never as a substitute for the spec.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from pysh.contracts import block_syntax
from pysh.parsing import grammar, heredoc, lexer, path_expansion, redirection
from pysh.parsing.ast import ChainElement
from pysh.parsing.errors import ParseError
from tests.fuzz_support import engines
from tests.fuzz_support.corpus import CorpusSeed
from tests.fuzz_support.repro import PropertyFailure, Reproduction
from tests.fuzz_support.targets import (
    TARGETS_BY_NAME,
    HarnessError,
    Outcome,
    Target,
    TargetContext,
    UnexpectedRejection,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class Case:
    """One input plus the information needed to reproduce it."""

    source: str
    text: str
    seed: int | None = None
    iteration: int | None = None


Property = Callable[[str, TargetContext], None]


def generated(seed: int, count: int, profile: engines.GeneratorProfile = engines.GENERAL) -> Iterator[Case]:
    for iteration, text in engines.generated_cases(seed, count, profile):
        yield Case("generated", text, seed, iteration)


def generated_quoted(seed: int, count: int) -> Iterator[Case]:
    for iteration in range(count):
        yield Case("generated:quoted", engines.quoted_operator_line_at(seed, iteration), seed, iteration)


def from_corpus(seeds: Iterable[CorpusSeed]) -> Iterator[Case]:
    for seed in seeds:
        yield Case(f"corpus:{seed.case_id}", seed.text)


def mutated(seeds: Sequence[CorpusSeed], seed: int, count: int) -> Iterator[Case]:
    texts = [item.text for item in seeds]
    for iteration in range(count):
        index, text = engines.mutated_case_at(texts, seed, iteration)
        yield Case(f"mutated:{seeds[index].case_id}", text, seed, iteration)


def run(
    property_name: str,
    check: Property,
    cases: Iterable[Case],
    ctx: TargetContext,
    *,
    target: str = "-",
) -> int:
    """Apply ``check`` to every case; any violation becomes a reproducible failure.

    Harness defects (:class:`HarnessError`) are never reported as property
    failures and are never swallowed. Returns the number of cases evaluated.
    """
    count = 0
    for case in cases:
        count += 1
        try:
            check(case.text, ctx)
        except HarnessError:
            raise
        except Exception as error:  # re-raised with reproduction data, never swallowed
            raise PropertyFailure(
                Reproduction(
                    target=target,
                    property_name=property_name,
                    text=case.text,
                    source=case.source,
                    seed=case.seed,
                    iteration=case.iteration,
                    generator_version=engines.GENERATOR_VERSION,
                    detail=f"{type(error).__name__}: {error}",
                )
            ) from error
    return count


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# --- A/B: totality and determinism -------------------------------------------


def totality(target: Target) -> Property:
    """Result or an explicitly registered rejection; anything else fails."""

    def check(text: str, ctx: TargetContext) -> None:
        evaluate(target, text, ctx)

    return check


def _comparable(outcome: Outcome) -> tuple[object, ...]:
    return (outcome.kind, outcome.value, outcome.exception, outcome.message)


def determinism(target: Target) -> Property:
    """Two evaluations of the same input give the same value or rejection."""

    def check(text: str, ctx: TargetContext) -> None:
        ctx.runner.calls.clear()
        first = evaluate(target, text, ctx)
        first_calls = list(ctx.runner.calls)
        ctx.runner.calls.clear()
        second = evaluate(target, text, ctx)
        _require(_comparable(first) == _comparable(second), f"nondeterministic: {first!r} vs {second!r}")
        _require(first_calls == list(ctx.runner.calls), "nondeterministic substitution calls")

    return check


# --- C: quote/operator containment (PYSH-LANG-QUOTE-RULES, PIPE-STATUS, COMMENT-BOUNDARY)


def quoted_operators_are_inert(text: str, ctx: TargetContext) -> None:
    """A line whose operators all sit inside valid quotes is one plain command."""
    stripped = text.strip()
    chain = grammar.split_chain(text)
    _require(chain == [ChainElement(stripped, None)], f"chain split a quoted operator: {chain!r}")
    _require(grammar.split_pipeline(text) == [stripped], "pipeline split a quoted '|'")
    _require(block_syntax.split_unquoted_pipe_stages(text) == [stripped], "stage split a quoted '|'")
    _require(lexer.strip_comments(text) == text.rstrip(), "quoted '#' was treated as a comment")
    _clean, spec = redirection.parse_redirections(text)
    _require(spec.is_empty(), f"quoted redirection was parsed: {spec.actions!r}")
    _require(heredoc.parse_heredoc_specs(text) == [], "quoted heredoc operator was parsed")


def _tokens_or_error(line: str, ctx: TargetContext) -> tuple[str, object]:
    try:
        return "ok", path_expansion.tokenize_and_glob_expand(line, cwd=ctx.cwd)
    except (ValueError, UnicodeEncodeError) as error:
        return "error", (type(error).__name__, str(error))


def redirection_preserves_quoted_content(text: str, ctx: TargetContext) -> None:
    """When no redirection is present, the cleaned command tokenizes like the input.

    PYSH-LANG-QUOTE-RULES: "Single quotes preserve all enclosed characters";
    double quotes preserve word grouping and enclosed text. The redirection
    stage hands its cleaned command to the tokenizer, so cleaning must not alter
    quoted text. Single-line input only (newline handling is a separate surface).
    """
    _require("\n" not in text, "defined for single-line input")
    clean, spec = redirection.parse_redirections(text)
    if not spec.is_empty():
        return
    _require(
        _tokens_or_error(clean, ctx) == _tokens_or_error(text, ctx),
        f"redirection cleaning changed tokens: {clean!r} vs {text!r}",
    )


# --- D: scanner consistency against the production quote-state helper --------


def neutralize(text: str) -> str:
    """Replace each operator character that ``is_unquoted_at`` reports as quoted by ``x``."""
    return "".join(
        "x" if char in engines.OPERATOR_CHARS and not lexer.is_unquoted_at(text, index) else char
        for index, char in enumerate(text)
    )


_OPERATOR_RE = re.compile(r"[;&|<>#]")


def _shape_or_rejection(function: Callable[[str], object], text: str) -> tuple[str, object]:
    # Rejection messages echo input fragments, which differ only by neutralization.
    try:
        return "ok", function(text)
    except ParseError as error:
        return "rejected", _OPERATOR_RE.sub("x", str(error))
    except ValueError as error:
        return "value-error", _OPERATOR_RE.sub("x", str(error))


def _chain_shape(line: str) -> object:
    chain = grammar.split_chain(line)
    return [(neutralize(element.command), element.operator) for element in chain]


def _pipeline_shape(line: str) -> object:
    return [neutralize(stage) for stage in grammar.split_pipeline(line)]


def _stage_shape(line: str) -> object:
    return [neutralize(stage) for stage in block_syntax.split_unquoted_pipe_stages(line)]


def _redirection_shape(line: str) -> object:
    clean, spec = redirection.parse_redirections(line)
    actions = [
        (a.fd, a.kind, a.append, a.source_fd, len(a.path or ""), len(a.data or b""))
        for a in spec.actions
    ]
    return neutralize(clean), actions


def _heredoc_shape(line: str) -> object:
    return [
        (s.operator, s.quoted_delimiter, s.expansion_mode, s.start_index, s.end_index)
        for s in heredoc.parse_heredoc_specs(line)
    ]


def _comment_shape(line: str) -> object:
    return neutralize(lexer.strip_comments(line))


SCANNER_SHAPES: dict[str, Callable[[str], object]] = {
    "split_chain": _chain_shape,
    "split_pipeline": _pipeline_shape,
    "split_unquoted_pipe_stages": _stage_shape,
    "parse_redirections": _redirection_shape,
    "parse_heredoc_specs": _heredoc_shape,
    "strip_comments": _comment_shape,
}


def scanner_consistency(scanner: str) -> Property:
    """Quoted operator characters must not change a scanner's structure.

    ``text`` and ``neutralize(text)`` differ only in characters the production
    quote helper reports as quoted; every scanner must see the same structure.
    Backslash-free inputs only (``is_unquoted_at`` does not model escapes).
    """
    shape = SCANNER_SHAPES[scanner]

    def check(text: str, ctx: TargetContext) -> None:
        _require("\\" not in text, "consistency is defined for backslash-free input")
        original = _shape_or_rejection(shape, text)
        neutral_text = neutralize(text)
        neutral = _shape_or_rejection(lambda t: shape(t), neutral_text)
        _require(original == neutral, f"{scanner}: {original!r} != {neutral!r} for neutralized input")

    return check


def tokenizer_consistency(text: str, ctx: TargetContext) -> None:
    """Quoted operators do not change token count or token lengths."""
    _require("\\" not in text, "consistency is defined for backslash-free input")

    def tokens(line: str) -> tuple[str, object]:
        try:
            return "ok", [len(t) for t in path_expansion.tokenize_and_glob_expand(line, cwd=ctx.cwd)]
        except (ValueError, UnicodeEncodeError) as error:
            return "error", (type(error).__name__, str(error))

    _require(tokens(text) == tokens(neutralize(text)), "tokenizer is sensitive to quoted operators")


# --- E: restricted round trip --------------------------------------------------

#: Allowed atom subset: non-empty NUL-free strings over ``engines._ARGV_ALPHABET``
#: (letters, digits, space/tab, quotes, backslash, shell punctuation, a few
#: non-ASCII letters). Empty strings are excluded because PYSH-LANG-LEX-WORDS
#: leaves empty quoted arguments unspecified. ``shlex.quote`` is only a builder.


def tokenizer_round_trip(builder: Callable[[str], str]) -> Callable[[list[str], TargetContext], None]:
    def check(argv: list[str], ctx: TargetContext) -> None:
        line = " ".join(builder(argument) for argument in argv)
        tokens = path_expansion.tokenize_and_glob_expand(line, cwd=ctx.cwd)
        _require(tokens == argv, f"round trip changed argv: {tokens!r} != {argv!r} for {line!r}")
        stripped = line.strip()
        _require(grammar.split_chain(line) == [ChainElement(stripped, None)], "chain split quoted atoms")
        _require(grammar.split_pipeline(line) == [stripped], "pipeline split quoted atoms")
        _require(lexer.strip_comments(line) == line.rstrip(), "comment cut quoted atoms")
        _clean, spec = redirection.parse_redirections(line)
        _require(spec.is_empty(), f"redirection parsed quoted atoms: {spec.actions!r}")

    return check


def round_trip_survives_redirection_stage(
    builder: Callable[[str], str],
) -> Callable[[list[str], TargetContext], None]:
    """The quoted line tokenizes to the same argv after the redirection stage."""

    def check(argv: list[str], ctx: TargetContext) -> None:
        line = " ".join(builder(argument) for argument in argv)
        clean, spec = redirection.parse_redirections(line)
        _require(spec.is_empty(), "redirection parsed quoted atoms")
        tokens = path_expansion.tokenize_and_glob_expand(clean, cwd=ctx.cwd)
        _require(tokens == argv, f"redirection stage changed argv: {tokens!r} != {argv!r}")

    return check


def tokenizer_fixpoint(text: str, ctx: TargetContext) -> None:
    """tokenize -> requote -> tokenize reproduces the same tokens (when it succeeds)."""
    try:
        first = path_expansion.tokenize_and_glob_expand(text, cwd=ctx.cwd)
    except (ValueError, UnicodeEncodeError):
        return  # rejection/boundary outcomes are covered by totality
    requoted = " ".join(engines.quote_for_pysh(token) for token in first)
    second = path_expansion.tokenize_and_glob_expand(requoted, cwd=ctx.cwd)
    _require(second == first, f"tokenization is not a fixpoint: {second!r} != {first!r}")


# --- F: structural invariants of successful splits ---------------------------


def split_structure(text: str, ctx: TargetContext) -> None:
    """Non-empty stripped elements; rejoining a backslash-free line re-splits identically."""
    _require("\\" not in text, "rejoin is defined for backslash-free input")
    try:
        chain = grammar.split_chain(text)
    except ParseError:
        chain = None
    if chain is not None:
        for element in chain:
            _require(bool(element.command) and element.command == element.command.strip(),
                     f"impossible chain element {element!r}")
        rejoined = " ".join(
            element.command if element.operator is None else f"{element.command} {element.operator.value}"
            for element in chain
        )
        _require(grammar.split_chain(rejoined) == chain, f"chain rejoin changed segmentation: {rejoined!r}")
    stages = block_syntax.split_unquoted_pipe_stages(text)
    _require(bool(stages) == bool(text.strip()), "syntactic stages disagree with blank-ness")
    for stage in stages:
        _require(stage == stage.strip(), f"unstripped stage {stage!r}")
    if stages:
        _require(block_syntax.split_unquoted_pipe_stages(" | ".join(stages)) == stages,
                 "pipeline rejoin changed segmentation")
    try:
        pipeline = grammar.split_pipeline(text)
    except ParseError:
        pipeline = None
    if pipeline is not None:
        _require(all(pipeline), "empty pipeline stage accepted")
        _require(pipeline == stages, "split_pipeline disagrees with the syntactic splitter")


__all__ = [
    "TARGETS_BY_NAME",
    "Case",
    "UnexpectedRejection",
]
