# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/targets.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Registry of pure text-processing targets and their expected rejections.

Each target names one production callable, the exact rejection classes it is
allowed to raise (with message patterns where the class alone is too broad), and
the containment it needs. Anything not registered is a failure: there is no
broad ``except Exception`` here.
"""
from __future__ import annotations

import contextlib
import glob
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

from pysh.contracts import block_syntax
from pysh.parsing import expansion, grammar, heredoc, lexer, multiline, path_expansion, redirection
from pysh.parsing.errors import ParseError, UnsupportedSyntaxError
from pysh.parsing.multiline import NestedBlockError, UnterminatedBlockError

SLOW_CASE_SECONDS = 5.0


class HarnessError(RuntimeError):
    """The harness itself misbehaved (never a parser verdict)."""


class UnexpectedRejection(AssertionError):
    """A registered exception class was raised outside its registered contract."""


@dataclass(frozen=True, slots=True)
class Rejection:
    """One allowed exception: class, optional message pattern, boundary flag.

    ``boundary`` marks an OS/stdlib boundary outcome (for example NUL or an
    unencodable surrogate reaching ``os.path.expanduser``/``glob``) rather than a
    grammar rejection. A boundary outcome is only valid for inputs that actually
    contain NUL or a lone surrogate.
    """

    exception: type[BaseException]
    pattern: re.Pattern[str] | None = None
    boundary: bool = False

    def matches(self, error: BaseException) -> bool:
        if not isinstance(error, self.exception):
            return False
        return self.pattern is None or self.pattern.search(str(error)) is not None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.DOTALL)


@dataclass(frozen=True)
class Outcome:
    """Normalized result of one evaluation (comparable for determinism)."""

    kind: str  # "ok" | "rejected" | "boundary"
    value: object = None
    exception: str | None = None
    message: str | None = None


class ConfinedGlob:
    """Stand-in for the ``glob`` module that never leaves ``root``.

    The tokenizer composes patterns from untrusted text, so an absolute pattern
    (``/**/``) or ``..`` traversal would walk the host filesystem (observed:
    an unbounded hang from ``/**/``). Every pattern is therefore normalized and,
    if it falls outside ``root``, re-rooted under it. Production control flow
    (magic detection, no-match policy) still runs unchanged; only the directory
    tree it can see is the empty fixture.
    """

    def __init__(self, root: Path) -> None:
        self.root = os.path.normpath(str(root))
        self.patterns: list[str] = []

    def confine(self, pattern: str) -> str:
        joined = pattern if os.path.isabs(pattern) else os.path.join(self.root, pattern)
        candidate = os.path.normpath(joined)
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            parts = [p for p in candidate.split(os.sep) if p not in ("", ".", "..")]
            candidate = os.path.join(self.root, *parts)
        if pattern.endswith(os.sep) and not candidate.endswith(os.sep):
            candidate += os.sep
        return candidate

    def glob(self, pattern: str, *, recursive: bool = False) -> list[str]:
        confined = self.confine(pattern)
        self.patterns.append(confined)
        return glob.glob(confined, recursive=recursive)


class FakeSubstitutionRunner:
    """Deterministic, non-spawning command-substitution runner with call log."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, command: str, timeout: float) -> str:
        self.calls.append(command)
        return f"sub{len(command)}"


@dataclass
class TargetContext:
    """Per-test hermetic state: empty cwd, pinned HOME/env, fake runner."""

    cwd: Path
    runner: FakeSubstitutionRunner = field(default_factory=FakeSubstitutionRunner)
    active: bool = False


@contextlib.contextmanager
def hermetic(ctx: TargetContext) -> Iterator[TargetContext]:
    """Activate isolation: cleared env + pinned HOME, confined glob, fake substitution, tripwires.

    ``expansion._default_runner`` (reached by heredoc expansion, which cannot be
    given a runner) is replaced by the fake, and every route to a real process in
    the expansion module raises :class:`HarnessError` if it is ever reached.
    """

    def _tripwire(*_args: object, **_kwargs: object) -> Any:
        raise HarnessError("a real subprocess was reached from the fuzz harness")

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, {"HOME": str(ctx.cwd)}, clear=True))
        stack.enter_context(
            mock.patch.object(path_expansion, "_glob_module", ConfinedGlob(ctx.cwd))
        )
        stack.enter_context(mock.patch.object(expansion, "_default_runner", ctx.runner))
        stack.enter_context(mock.patch.object(expansion.subprocess, "run", _tripwire))
        stack.enter_context(mock.patch.object(expansion.subprocess, "Popen", _tripwire))
        ctx.active = True
        try:
            yield ctx
        finally:
            ctx.active = False


TargetFunction = Callable[[str, TargetContext], object]


@dataclass(frozen=True)
class Target:
    """One registered pure target."""

    name: str
    production: Callable[..., object]
    signature: str
    function: TargetFunction
    rejections: tuple[Rejection, ...] = ()
    needs_cwd: bool = False
    needs_fake_runner: bool = False
    nul_input: str = "valid"  # "valid" or "os_boundary"
    surrogate_input: str = "valid"  # "valid" or "os_boundary"

    def classify(self, error: BaseException) -> Rejection | None:
        for rejection in self.rejections:
            if rejection.matches(error):
                return rejection
        return None

    @property
    def rejection_classes(self) -> tuple[type[BaseException], ...]:
        return tuple(r.exception for r in self.rejections)


def _has_boundary_input(text: str) -> bool:
    return "\x00" in text or any("\ud800" <= ch <= "\udfff" for ch in text)


def evaluate(target: Target, text: str, ctx: TargetContext) -> Outcome:
    """Run ``target`` once. Registered rejections become outcomes; all else raises."""
    if not isinstance(text, str):
        raise HarnessError(f"fuzz input must be str, got {type(text).__name__}")
    if (target.needs_fake_runner or target.needs_cwd) and not ctx.active:
        raise HarnessError(f"{target.name} requires an active hermetic() context")
    started = time.perf_counter()
    try:
        outcome = Outcome("ok", target.function(text, ctx))
    except target.rejection_classes as error:
        rejection = target.classify(error)
        if rejection is None:
            raise UnexpectedRejection(
                f"{target.name}: {type(error).__name__} outside its registered contract: {error}"
            ) from error
        if rejection.boundary and not _has_boundary_input(text):
            raise UnexpectedRejection(
                f"{target.name}: boundary outcome {type(error).__name__} without NUL/surrogate input"
            ) from error
        kind = "boundary" if rejection.boundary else "rejected"
        outcome = Outcome(kind, None, type(error).__name__, str(error))
    elapsed = time.perf_counter() - started
    if elapsed > SLOW_CASE_SECONDS:
        raise UnexpectedRejection(f"{target.name}: case took {elapsed:.1f}s (> {SLOW_CASE_SECONDS}s)")
    if target.needs_cwd and any(ctx.cwd.iterdir()):
        raise UnexpectedRejection(f"{target.name}: modified the supposedly empty cwd")
    return outcome


# --- adapters (verified against current production signatures) ---------------


def _unquoted_map(text: str, _ctx: TargetContext) -> tuple[bool, ...]:
    return tuple(lexer.is_unquoted_at(text, i) for i in range(-1, len(text) + 1))


def _logical_lines(text: str, _ctx: TargetContext) -> list[str]:
    return list(multiline.iter_logical_lines(text.split("\n")))


def _tokenize(text: str, ctx: TargetContext) -> list[str]:
    return path_expansion.tokenize_and_glob_expand(text, cwd=ctx.cwd)


def _substitute(text: str, ctx: TargetContext) -> str:
    return expansion.expand_command_substitution(text, runner=ctx.runner)


_PARSE_ERROR = Rejection(ParseError)
_UNTERMINATED_QUOTE = _rx(r"^unterminated (single|double) quote$")

TARGETS: tuple[Target, ...] = (
    Target("lexer.scan_quote_state", lexer.scan_quote_state, "(text: 'str') -> 'QuoteState'",
           lambda t, _c: lexer.scan_quote_state(t)),
    Target("lexer.strip_comments", lexer.strip_comments, "(line: 'str') -> 'str'",
           lambda t, _c: lexer.strip_comments(t)),
    Target("lexer.has_unbalanced_quotes", lexer.has_unbalanced_quotes, "(line: 'str') -> 'bool'",
           lambda t, _c: lexer.has_unbalanced_quotes(t)),
    Target("lexer.is_unquoted_at", lexer.is_unquoted_at, "(text: 'str', index: 'int') -> 'bool'",
           _unquoted_map),
    Target("grammar.split_chain", grammar.split_chain, "(line: 'str') -> 'list[ChainElement]'",
           lambda t, _c: grammar.split_chain(t),
           rejections=(Rejection(ParseError, _rx(r"^syntax error near unexpected '&'$")),)),
    Target("grammar.split_pipeline", grammar.split_pipeline, "(command: 'str') -> 'list[str]'",
           lambda t, _c: grammar.split_pipeline(t),
           rejections=(Rejection(ParseError, _rx(r"^syntax error near unexpected '\|'$")),)),
    Target("block_syntax.split_unquoted_pipe_stages", block_syntax.split_unquoted_pipe_stages,
           "(command: 'str') -> 'list[str]'",
           lambda t, _c: block_syntax.split_unquoted_pipe_stages(t)),
    Target("block_syntax.is_block_opener", block_syntax.is_block_opener, "(line: 'str') -> 'bool'",
           lambda t, _c: block_syntax.is_block_opener(t)),
    Target("block_syntax.is_block_closer", block_syntax.is_block_closer, "(line: 'str') -> 'bool'",
           lambda t, _c: block_syntax.is_block_closer(t)),
    Target("redirection.parse_redirections", redirection.parse_redirections,
           "(command: 'str', heredoc_bodies: 'list[HereDocBody] | None' = None) "
           "-> 'tuple[str, RedirectionSpec]'",
           lambda t, _c: redirection.parse_redirections(t),
           rejections=(Rejection(ParseError, _rx(
               r"^missing (redirection target after|heredoc delimiter after|heredoc body for)")),)),
    Target("heredoc.parse_heredoc_specs", heredoc.parse_heredoc_specs,
           "(command_line: 'str') -> 'list[HereDocSpec]'",
           lambda t, _c: heredoc.parse_heredoc_specs(t),
           rejections=(Rejection(ParseError, _rx(r"^missing heredoc delimiter after ")),)),
    Target("heredoc.pending_heredoc_specs", heredoc.pending_heredoc_specs,
           "(command_line: 'str') -> 'list[HereDocSpec]'",
           lambda t, _c: heredoc.pending_heredoc_specs(t),
           rejections=(Rejection(ParseError, _rx(r"^missing heredoc delimiter after ")),)),
    Target("heredoc.collect_heredoc_bodies", heredoc.collect_heredoc_bodies,
           "(text: 'str', local_vars: 'dict[str, str]', *, "
           "special_vars: 'dict[str, str] | None' = None) -> 'tuple[str, list[HereDocBody]]'",
           lambda t, _c: heredoc.collect_heredoc_bodies(t, {}),
           rejections=(Rejection(ParseError, _rx(
               r"^missing heredoc (delimiter after|terminator:)")),),
           needs_fake_runner=True),
    Target("multiline.continuation_state", multiline.continuation_state,
           "(text: 'str') -> 'ContinuationState'",
           lambda t, _c: multiline.continuation_state(t)),
    Target("multiline.join_backslash_continuations", multiline.join_backslash_continuations,
           "(text: 'str') -> 'str'",
           lambda t, _c: multiline.join_backslash_continuations(t)),
    Target("multiline.split_paste_commands", multiline.split_paste_commands,
           "(text: 'str') -> 'list[str]'",
           lambda t, _c: multiline.split_paste_commands(t)),
    Target("multiline.iter_logical_lines", multiline.iter_logical_lines,
           "(lines: 'Iterable[str]') -> 'Iterator[str]'",
           _logical_lines,
           rejections=(
               Rejection(ParseError, _rx(r"^missing heredoc delimiter after ")),
               Rejection(UnterminatedBlockError, _rx(r"^unterminated py \{ \.\.\. \} block")),
               Rejection(NestedBlockError, _rx(r"^nested py \{ \.\.\. \} block")),
           )),
    Target("path_expansion.tokenize_and_glob_expand", path_expansion.tokenize_and_glob_expand,
           "(text: 'str', *, cwd: 'Path | None' = None, "
           "options: 'PathExpansionOptions | None' = None) -> 'list[str]'",
           _tokenize,
           rejections=(
               Rejection(ValueError, _UNTERMINATED_QUOTE),
               # OS/stdlib boundary: tilde/glob hand the word to pwd/os.scandir.
               # (``pwd`` lookup says "byte"; ``os.scandir`` via glob says "character in path".)
               Rejection(ValueError, _rx(
                   r"^(?:scandir: )?embedded null (?:byte|character(?: in path)?)$"), boundary=True),
               Rejection(UnicodeEncodeError, boundary=True),
           ),
           needs_cwd=True, nul_input="os_boundary", surrogate_input="os_boundary"),
    Target("grammar.validate_unsupported_syntax", grammar.validate_unsupported_syntax,
           "(line: 'str') -> 'None'",
           lambda t, _c: grammar.validate_unsupported_syntax(t),
           rejections=(Rejection(UnsupportedSyntaxError, _rx(r"^unsupported syntax: ")),)),
    Target("grammar.parse_assignment", grammar.parse_assignment,
           "(line: 'str') -> 'tuple[str, str] | None'",
           lambda t, _c: grammar.parse_assignment(t)),
    Target("expansion.expand_variables", expansion.expand_variables,
           "(text: 'str', local_vars: 'dict[str, str]', env_vars: 'dict[str, str] | None' = None, "
           "*, special_vars: 'dict[str, str] | None' = None) -> 'str'",
           lambda t, _c: expansion.expand_variables(t, {}, {})),
    Target("expansion.expand_command_substitution", expansion.expand_command_substitution,
           "(text: 'str', *, runner: 'Callable[[str, float], str] | None' = None, "
           "timeout: 'float' = 5.0) -> 'str'",
           _substitute, needs_fake_runner=True),
)

TARGETS_BY_NAME: dict[str, Target] = {target.name: target for target in TARGETS}
if len(TARGETS_BY_NAME) != len(TARGETS):  # pragma: no cover - registry integrity
    raise RuntimeError("duplicate fuzz target name")
