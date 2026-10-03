# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_parser_properties.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 1: deterministic property tests over the pure parser targets.

Expected behavior comes from ``docs/spec/pysh-language.md`` and the #48 corpus;
see ``tests/fuzz_support/properties.py`` for the anchor of each property.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import random
import re
from pathlib import Path

import pytest

import pysh.core.shell as shell_module
from pysh.contracts import block_syntax
from pysh.parsing import expansion, grammar, lexer, path_expansion, redirection
from pysh.parsing.ast import ChainElement
from tests.fuzz_support import engines
from tests.fuzz_support import properties as props
from tests.fuzz_support import targets as T
from tests.fuzz_support.corpus import load_seeds
from tests.fuzz_support.repro import (
    PropertyFailure,
    Reproduction,
    decode_text,
    encode_text,
    format_failure,
)

SEEDS = (1, 2, 3)
ITERATIONS = 100
SEEDS_FROM_CORPUS = load_seeds()


@pytest.fixture
def ctx(tmp_path: Path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    context = T.TargetContext(cwd=cwd)
    with T.hermetic(context):
        yield context


def _all_generated(profile=engines.GENERAL):
    for seed in SEEDS:
        yield from props.generated(seed, ITERATIONS, profile)


# --- registry ---------------------------------------------------------------


def test_registry_signatures_match_production() -> None:
    for target in T.TARGETS:
        assert str(inspect.signature(target.production)) == target.signature, target.name


def test_registry_expected_rejections_are_explicit_and_target_specific() -> None:
    assert len({t.name for t in T.TARGETS}) == len(T.TARGETS)
    for target in T.TARGETS:
        for rejection in target.rejections:
            assert rejection.exception is not Exception and rejection.exception is not BaseException
            if rejection.exception is ValueError:  # never a blanket ValueError
                assert rejection.pattern is not None, target.name
        assert target.nul_input in {"valid", "os_boundary"}
        assert target.surrogate_input in {"valid", "os_boundary"}
    tokenizer = T.TARGETS_BY_NAME["path_expansion.tokenize_and_glob_expand"]
    assert tokenizer.needs_cwd and tokenizer.nul_input == "os_boundary"
    assert T.TARGETS_BY_NAME["heredoc.collect_heredoc_bodies"].needs_fake_runner
    assert T.TARGETS_BY_NAME["expansion.expand_command_substitution"].needs_fake_runner


def test_unregistered_or_unjustified_exceptions_fail() -> None:
    ctx = T.TargetContext(cwd=Path("."))

    def boom(error: BaseException):
        def function(_text: str, _ctx: T.TargetContext):
            raise error
        return function

    base = dict(production=len, signature="")
    unlisted = T.Target("t", function=boom(KeyError("k")), **base)
    with pytest.raises(KeyError):
        T.evaluate(unlisted, "x", ctx)
    patterned = T.Target(
        "t", function=boom(ValueError("something else")),
        rejections=(T.Rejection(ValueError, T._rx(r"^known$")),), **base,
    )
    with pytest.raises(T.UnexpectedRejection):
        T.evaluate(patterned, "x", ctx)
    boundary = T.Target(
        "t", function=boom(ValueError("embedded null byte")),
        rejections=(T.Rejection(ValueError, boundary=True),), **base,
    )
    with pytest.raises(T.UnexpectedRejection):  # boundary outcome without NUL/surrogate input
        T.evaluate(boundary, "plain", ctx)
    assert T.evaluate(boundary, "a\x00b", ctx).kind == "boundary"
    with pytest.raises(T.HarnessError):
        T.evaluate(unlisted, b"bytes", ctx)  # type: ignore[arg-type]


def test_expected_rejections_are_exact_for_fixed_examples(ctx) -> None:
    by = T.TARGETS_BY_NAME
    assert T.evaluate(by["grammar.split_chain"], "a && &", ctx).kind == "rejected"
    assert T.evaluate(by["grammar.split_chain"], "&", ctx).message == "syntax error near unexpected '&'"
    assert T.evaluate(by["grammar.split_pipeline"], "a |", ctx).kind == "rejected"
    assert T.evaluate(by["redirection.parse_redirections"], "a >", ctx).kind == "rejected"
    assert T.evaluate(by["heredoc.parse_heredoc_specs"], "a <<", ctx).kind == "rejected"
    assert T.evaluate(by["heredoc.collect_heredoc_bodies"], "cat << EOF\nx", ctx).kind == "rejected"
    assert T.evaluate(by["multiline.iter_logical_lines"], "py {", ctx).exception == "UnterminatedBlockError"
    assert T.evaluate(by["grammar.validate_unsupported_syntax"], "echo $((1+2))", ctx).kind == "rejected"
    tokenizer = by["path_expansion.tokenize_and_glob_expand"]
    assert T.evaluate(tokenizer, "echo 'x", ctx).kind == "rejected"
    assert T.evaluate(tokenizer, 'echo "x', ctx).kind == "rejected"
    assert T.evaluate(tokenizer, "echo ~zq\x00", ctx).kind == "boundary"  # NUL reaches pwd lookup
    assert T.evaluate(tokenizer, "echo ~zq\ud800", ctx).kind == "boundary"  # unencodable lone surrogate
    assert T.evaluate(tokenizer, "echo zq\x00 \ud800", ctx).kind == "ok"  # plain words never reach the OS


# --- containment of the harness itself ---------------------------------------


def test_command_substitution_never_reaches_a_real_process(ctx) -> None:
    result = T.evaluate(T.TARGETS_BY_NAME["expansion.expand_command_substitution"], "x $(zq1) y", ctx)
    assert result.value == "x sub3 y" and ctx.runner.calls == ["zq1"]
    ctx.runner.calls.clear()
    # Heredoc expansion cannot be given a runner; the guarded default must be used.
    collected = T.evaluate(T.TARGETS_BY_NAME["heredoc.collect_heredoc_bodies"], "cat <<< $(zq2)", ctx)
    assert collected.kind == "ok" and ctx.runner.calls == ["zq2"]
    with pytest.raises(T.HarnessError):
        expansion.subprocess.run(["true"])
    with pytest.raises(T.HarnessError):
        expansion.subprocess.Popen(["true"])


def test_guarded_targets_refuse_to_run_outside_the_hermetic_context(tmp_path: Path) -> None:
    inactive = T.TargetContext(cwd=tmp_path)
    for name in ("heredoc.collect_heredoc_bodies", "expansion.expand_command_substitution",
                 "path_expansion.tokenize_and_glob_expand"):
        with pytest.raises(T.HarnessError):
            T.evaluate(T.TARGETS_BY_NAME[name], "x", inactive)


def test_tokenizer_runs_in_an_empty_cwd_with_pinned_home_and_cleared_environment(ctx) -> None:
    import os

    assert os.environ["HOME"] == str(ctx.cwd)
    assert set(os.environ) <= {"HOME", "PYTEST_CURRENT_TEST"}  # host environment is cleared
    assert list(ctx.cwd.iterdir()) == []
    tokenizer = T.TARGETS_BY_NAME["path_expansion.tokenize_and_glob_expand"]
    assert T.evaluate(tokenizer, "echo zq*", ctx).value == ["echo", "zq*"]  # no host files match
    (ctx.cwd / "zqfile").write_text("")
    assert path_expansion.tokenize_and_glob_expand("zq*", cwd=ctx.cwd) == ["zqfile"]  # fixed fixture glob
    (ctx.cwd / "zqfile").unlink()


def test_tokenizer_cannot_reach_the_host_filesystem_through_glob(ctx) -> None:
    # Found by the Atheris smoke: ``/**/`` walked the whole host filesystem (unbounded hang).
    tokenizer = T.TARGETS_BY_NAME["path_expansion.tokenize_and_glob_expand"]
    shim = path_expansion._glob_module
    assert isinstance(shim, T.ConfinedGlob)
    for text in ("/**/", "echo /**/ ../../**/ ~/**/ /etc/*", "../../../../*", "~root/**"):
        shim.patterns.clear()
        assert T.evaluate(tokenizer, text, ctx).kind == "ok", text
        assert shim.patterns and all(p.startswith(shim.root) for p in shim.patterns), shim.patterns


def test_nul_reaching_scandir_through_glob_is_a_classified_boundary_outcome(ctx) -> None:
    # Found by the Atheris smoke: NUL in a glob directory component -> os.scandir ValueError.
    tokenizer = T.TARGETS_BY_NAME["path_expansion.tokenize_and_glob_expand"]
    outcome = T.evaluate(tokenizer, "ei\x00\x00rn/t\x00cfixt\"\"*.txure-echo", ctx)
    assert outcome.kind == "boundary" and "embedded null character" in outcome.message


# --- generator --------------------------------------------------------------


def test_generator_is_deterministic_independent_of_global_random_and_replayable() -> None:
    first = list(engines.generated_cases(1, 60))
    random.seed(12345)
    random.random()
    assert first == list(engines.generated_cases(1, 60))
    for iteration, text in first:
        assert text == engines.case_at(1, iteration)
        assert len(text) <= engines.MAX_CASE_CHARS
    assert first != list(engines.generated_cases(2, 60))


def _digest(items) -> str:
    return hashlib.sha256("\n".join(ascii(item) for item in items).encode()).hexdigest()


def test_generator_output_is_pinned_across_platforms() -> None:
    # random.Random(str) seeds via SHA-512 and is portable; bump GENERATOR_VERSION on change.
    assert engines.GENERATOR_VERSION == "1"
    assert _digest(engines.case_at(1, i) for i in range(50)) == (
        "887bbf880c50b81ab5914b5be7059170976c17672b64c2db60a5287d4c17423f")
    assert _digest(engines.quoted_operator_line_at(1, i) for i in range(50)) == (
        "2f415cdf2ea1b54ef202e83cb261f12c2dfc9dc21df9677058901fa6443807df")
    assert _digest(engines.argv_case_at(1, i) for i in range(50)) == (
        "58887da5170d3864c28166d9b91823149b3e393d6463343f0491c3536cbcbaab")
    assert _digest(engines.case_at(7, i, engines.NO_BACKSLASH) for i in range(50)) == (
        "ecd619a6c181bd122d26d7383b69b469202a75c50e8015c53bf97f3ecf16127f")


def test_generator_covers_the_documented_input_domain() -> None:
    corpus = "".join(text for _, text in engines.generated_cases(1, 400))
    for needle in (";", "&&", "||", "|", "<", ">", ">>", "2>", "2>&1", "#", "$", "${", "$(", "`",
                   "\n", "\t", "'", '"', "\\", "\x00", "\udc80", "\ud800", "é", "日本"):
        assert needle in corpus, repr(needle)
    assert "\\" not in "".join(t for _, t in engines.generated_cases(1, 300, engines.NO_BACKSLASH))
    assert "/" not in corpus  # glob patterns can only be relative to the empty cwd


# --- reproduction formatting ---------------------------------------------------


def test_failure_report_is_sufficient_to_reproduce_the_case() -> None:
    text = engines.case_at(2, 17)
    report = format_failure(
        Reproduction("grammar.split_chain", "totality", text, "generated", 2, 17, "1", "boom"))
    for expected in ("grammar.split_chain", "totality", "seed:       2", "iteration:  17",
                     encode_text(text), ascii(text), "engines.case_at(2, 17)"):
        assert expected in report
    assert decode_text(encode_text(text)) == text
    for tricky in ("a\x00b", "𐃿", "日本\n\t'\"\\"):
        assert decode_text(encode_text(tricky)) == tricky


def test_run_turns_violations_into_reproducible_failures_and_keeps_harness_errors() -> None:
    def violated(text: str, _ctx: T.TargetContext) -> None:
        raise AssertionError("nope")

    with pytest.raises(PropertyFailure) as caught:
        props.run("always-fails", violated, props.generated(3, 5), None, target="t")  # type: ignore[arg-type]
    rep = caught.value.reproduction
    assert (rep.seed, rep.iteration, rep.property_name) == (3, 0, "always-fails")
    assert rep.text == engines.case_at(3, 0) and encode_text(rep.text) in str(caught.value)

    def harness(text: str, _ctx: T.TargetContext) -> None:
        raise T.HarnessError("harness bug")

    with pytest.raises(T.HarnessError):
        props.run("h", harness, props.generated(3, 1), None)  # type: ignore[arg-type]


# --- A/B: totality and determinism ---------------------------------------------


@pytest.mark.parametrize("target", T.TARGETS, ids=lambda t: t.name)
def test_totality_and_determinism_on_generated_input(target: T.Target, ctx) -> None:
    for check, name in ((props.totality(target), "totality"), (props.determinism(target), "determinism")):
        assert props.run(name, check, _all_generated(), ctx, target=target.name) == len(SEEDS) * ITERATIONS


@pytest.mark.parametrize("target", T.TARGETS, ids=lambda t: t.name)
def test_totality_and_determinism_on_corpus_seeds_and_mutations(target: T.Target, ctx) -> None:
    cases = list(props.from_corpus(SEEDS_FROM_CORPUS)) + list(props.mutated(SEEDS_FROM_CORPUS, 11, 80))
    for check, name in ((props.totality(target), "totality"), (props.determinism(target), "determinism")):
        assert props.run(name, check, cases, ctx, target=target.name) == len(cases)


# --- C: quote/operator containment ----------------------------------------------


def test_quoted_operators_are_inert_on_constructed_lines(ctx) -> None:
    for seed in SEEDS:
        assert props.run("quoted_operators_are_inert", props.quoted_operators_are_inert,
                         props.generated_quoted(seed, ITERATIONS), ctx) == ITERATIONS


def test_quoted_and_escaped_operators_follow_the_specification_on_fixed_examples() -> None:
    # PYSH-LANG-QUOTE-RULES / PIPE-STATUS: operators are recognized only when unquoted and unescaped.
    for line in ("a '; b'", 'a "&& b"', "a '| b'", 'a "> f"', r"a \; b", r"a \&\& b", r"a \| b"):
        assert grammar.split_chain(line) == [ChainElement(line, None)], line
        assert grammar.split_pipeline(line) == [line], line
    assert redirection.parse_redirections(r"a \> f")[1].is_empty()
    assert redirection.parse_redirections("a '>' f")[1].is_empty()
    # PYSH-LANG-COMMENT-BOUNDARY: quoted, escaped, or mid-word '#' is literal.
    assert lexer.strip_comments("a #x") == "a" and lexer.strip_comments("#x") == ""
    for literal in ("a#b", "a '#x'", 'a "#x"', r"a \#x"):
        assert lexer.strip_comments(literal) == literal
    assert path_expansion.tokenize_and_glob_expand("echo a\\ b", cwd=Path(".")) == ["echo", "a b"]


# --- D: scanner consistency -------------------------------------------------------


@pytest.mark.parametrize("scanner", sorted(props.SCANNER_SHAPES))
def test_scanner_consistency_with_the_quote_state_helper(scanner: str, ctx) -> None:
    check = props.scanner_consistency(scanner)
    assert props.run(f"scanner_consistency:{scanner}", check,
                     _all_generated(engines.NO_BACKSLASH), ctx) == len(SEEDS) * ITERATIONS
    seeds = [s for s in SEEDS_FROM_CORPUS if "\\" not in s.text]
    assert props.run(f"scanner_consistency:{scanner}", check, props.from_corpus(seeds), ctx) == len(seeds)


def test_tokenizer_consistency_with_the_quote_state_helper(ctx) -> None:
    assert props.run("tokenizer_consistency", props.tokenizer_consistency,
                     _all_generated(engines.NO_BACKSLASH), ctx) == len(SEEDS) * ITERATIONS


# --- E: restricted round trip -------------------------------------------------------


@pytest.mark.parametrize("builder", [engines.quote_for_pysh, engines.quote_with_shlex],
                         ids=["pysh-single-quote", "shlex-quote-builder"])
def test_tokenizer_round_trip_on_the_restricted_atom_subset(builder, ctx) -> None:
    check = props.tokenizer_round_trip(builder)
    for seed in SEEDS:
        for iteration in range(ITERATIONS):
            argv = engines.argv_case_at(seed, iteration)
            try:
                check(argv, ctx)
            except AssertionError as error:
                raise PropertyFailure(Reproduction(
                    "path_expansion.tokenize_and_glob_expand", "tokenizer_round_trip",
                    repr(argv), "generated:argv", seed, iteration, engines.GENERATOR_VERSION,
                    str(error))) from error


def test_tokenize_requote_tokenize_is_a_fixpoint(ctx) -> None:
    assert props.run("tokenizer_fixpoint", props.tokenizer_fixpoint, _all_generated(), ctx) == len(SEEDS) * ITERATIONS


# --- F: structural invariants ------------------------------------------------------


def test_split_structure_invariants(ctx) -> None:
    assert props.run("split_structure", props.split_structure,
                     _all_generated(engines.NO_BACKSLASH), ctx) == len(SEEDS) * ITERATIONS
    assert grammar.split_chain("a ; ; b") == [ChainElement("a", grammar.ChainOp.SEMI), ChainElement("b", None)]
    assert block_syntax.split_unquoted_pipe_stages("a || b | c") == ["a || b", "c"]


# --- production defect found by these properties (Issue #49 finding F1) ---------------
# parse_redirections() returns ``" ".join(clean.split())``, which collapses runs of
# whitespace INSIDE quotes (``echo 'a  b'`` -> ``echo 'a b'``), contradicting
# PYSH-LANG-QUOTE-RULES ("Single quotes preserve all enclosed characters"). The defect
# was fixed in this PR (d9e15c2) and these tests are now its permanent regression guard.


def test_f1_redirection_stage_preserves_whitespace_inside_quotes_fixed_examples(ctx) -> None:
    for line in ("echo 'a  b'", 'echo "a  b"', "echo 'a\tb'", 'echo "x   y" z'):
        props.redirection_preserves_quoted_content(line, ctx)


def test_f1_redirection_stage_preserves_quoted_content_on_generated_lines(ctx) -> None:
    for seed in SEEDS:
        assert props.run("redirection_preserves_quoted_content",
                         props.redirection_preserves_quoted_content,
                         props.generated_quoted(seed, ITERATIONS), ctx,
                         target="redirection.parse_redirections") == ITERATIONS


@pytest.mark.parametrize("builder", [engines.quote_for_pysh, engines.quote_with_shlex],
                         ids=["pysh-single-quote", "shlex-quote-builder"])
def test_f1_round_trip_survives_the_redirection_stage(builder, ctx) -> None:
    check = props.round_trip_survives_redirection_stage(builder)
    for seed in SEEDS:
        for iteration in range(ITERATIONS):
            check(engines.argv_case_at(seed, iteration), ctx)


# --- drift guard ---------------------------------------------------------------------

_SHELL_PATH = Path(shell_module.__file__)
FRONT_END_ORDER = (
    "join_backslash_continuations",
    "collect_heredoc_bodies",
    "strip_comments",
    "validate_unsupported_syntax",
    "expand_command_substitution",
    "split_chain",
)
#: Shell imports of parsing helpers that are deliberately not registered here.
UNREGISTERED_SHELL_IMPORTS = {
    "heredoc_line_matches": "needs a HereDocSpec argument; exercised through collect_heredoc_bodies",
    "parse_leading_env_assignments": "takes a token list produced by the tokenizer, not text",
    "expand_tilde": "host account database; exercised through the tokenizer boundary",
}


def _shell_tree() -> ast.Module:
    return ast.parse(_SHELL_PATH.read_text(encoding="utf-8"))


def _call_names(node: ast.AST) -> list[str]:
    calls = [
        (n.lineno, n.col_offset, n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    ]
    return [name for _, _, name in sorted(calls)]


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_shell_front_end_order_matches_the_documented_mapping() -> None:
    tree = _shell_tree()
    calls = _call_names(_method(tree, "_execute_impl"))
    positions = [calls.index(name) for name in FRONT_END_ORDER]
    assert positions == sorted(positions), "Shell._execute_impl parser order changed; review the fuzz mapping"
    stage_calls = _call_names(_method(tree, "_split_pipeline_stages"))
    assert "split_pipeline" in stage_calls
    owners = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and {"parse_redirections", "tokenize_and_glob_expand"} <= set(_call_names(n))
    ]
    assert owners, "no Shell method applies parse_redirections then tokenize_and_glob_expand"
    for owner in owners:
        names = _call_names(owner)
        assert names.index("parse_redirections") < names.index("tokenize_and_glob_expand"), owner.name


def test_every_parsing_function_the_shell_imports_is_registered_or_explained() -> None:
    registered = {target.production.__name__: target.production for target in T.TARGETS}
    imported: dict[str, object] = {}
    for node in _shell_tree().body:
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module.startswith("pysh.parsing") or node.module == "pysh.contracts.block_syntax"
        ):
            for alias in node.names:
                value = getattr(shell_module, alias.asname or alias.name)
                if inspect.isfunction(value):
                    imported[alias.name] = value
    assert imported, "drift guard found no Shell parsing imports"
    missing = sorted(set(imported) - set(registered) - set(UNREGISTERED_SHELL_IMPORTS))
    assert missing == [], f"Shell uses parsing functions the fuzz registry does not cover: {missing}"
    for name, function in imported.items():
        if name in registered:
            assert function is registered[name], f"{name}: Shell and the fuzz registry use different objects"
    for name in UNREGISTERED_SHELL_IMPORTS:
        assert name in imported, f"stale exclusion {name}"
    assert {t.production.__module__ for t in T.TARGETS} >= {
        "pysh.parsing.lexer", "pysh.parsing.grammar", "pysh.parsing.redirection",
        "pysh.parsing.heredoc", "pysh.parsing.multiline", "pysh.parsing.path_expansion",
        "pysh.parsing.expansion", "pysh.contracts.block_syntax",
    }
    assert re.fullmatch(r"[0-9]+", engines.GENERATOR_VERSION)
