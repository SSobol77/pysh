# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Command classification foundation used by the ``plan`` builtin.

``plan`` is advisory only. It inspects a command line, classifies how PySH
would route it (builtin, external, pipeline, chain, python, zsh delegation,
script, unknown) and assigns a coarse risk level. No execution and no state
mutation happens. Policy enforcement is intentionally out of scope here and
is planned for a later release.
"""
from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import IO

from pysh.diagnostics.trace import DEFAULT_REDACTION_POLICY
from pysh.parsing.multiline import PY_BLOCK_OPENER, is_block_opener
from pysh.parsing.parser import ChainOp, split_chain, split_pipeline

ZSH_DELEGATION_BUILTINS: frozenset[str] = frozenset({"zsh", "zsh_fallback"})
SCRIPT_BUILTINS: frozenset[str] = frozenset({"run_script", "source", ".", "source_zsh"})

RISKY_COMMANDS: frozenset[str] = frozenset({"sudo", "eval"})
RISKY_SYSTEM_DIRS: tuple[str, ...] = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/lib")


@dataclass(frozen=True)
class CommandPlan:
    """Plan result for one command line."""

    original: str
    kind: str
    execution: str
    risk: str
    reason: str

    def format(self) -> str:
        """Return a multi-line, deterministic text rendering of the plan."""
        return (
            f"original={self.original}\n"
            f"kind={self.kind}\n"
            f"execution={self.execution}\n"
            f"risk={self.risk}\n"
            f"reason={self.reason}"
        )


def classify(line: str, *, builtins: Iterable[str] = ()) -> CommandPlan:
    """Classify ``line`` into a :class:`CommandPlan`. No execution happens."""
    text = line.rstrip("\n").rstrip("\r")
    display_text = DEFAULT_REDACTION_POLICY.redact_text(text)
    if not text.strip():
        return CommandPlan(
            original=display_text,
            kind="unknown",
            execution="none",
            risk="low",
            reason="empty input",
        )
    builtin_set = frozenset(builtins)

    if is_block_opener(text):
        return CommandPlan(
            original=display_text,
            kind="python",
            execution="python-runtime",
            risk="low",
            reason="multiline py { ... } block opener",
        )

    stripped = text.lstrip()
    if stripped.startswith("py ") or stripped == "py" or stripped.startswith(PY_BLOCK_OPENER):
        return CommandPlan(
            original=display_text,
            kind="python",
            execution="python-runtime",
            risk="low",
            reason="py builtin executes Python in PySH runtime",
        )

    chain = split_chain(text)
    if len(chain) > 1:
        kinds = [classify(elem.command, builtins=builtin_set) for elem in chain]
        risk = _max_risk(p.risk for p in kinds)
        ops = ", ".join(_op_name(elem.operator) for elem in chain if elem.operator)
        return CommandPlan(
            original=display_text,
            kind="chain",
            execution="native",
            risk=risk,
            reason=f"chain joined by {ops}",
        )

    pipeline = split_pipeline(text)
    if len(pipeline) > 1:
        stages = [classify(stage, builtins=builtin_set) for stage in pipeline]
        risk = _max_risk(stage.risk for stage in stages)
        return CommandPlan(
            original=display_text,
            kind="pipeline",
            execution="native",
            risk=risk,
            reason=f"pipeline with {len(pipeline)} stages",
        )

    head = _first_word(text)
    if not head:
        return CommandPlan(
            original=display_text,
            kind="unknown",
            execution="none",
            risk="low",
            reason="no command word",
        )

    if head in ZSH_DELEGATION_BUILTINS:
        return CommandPlan(
            original=display_text,
            kind="zsh-delegation",
            execution="zsh",
            risk="medium",
            reason=f"{head} delegates to real zsh -lc",
        )

    if head == "run_script":
        return CommandPlan(
            original=display_text,
            kind="script",
            execution="subprocess",
            risk="medium",
            reason="run_script delegates to interpreter or runs as PySH script",
        )

    if head in {"source", ".", "source_zsh", "source_zsh_profile", "source_sh_aliases"}:
        return CommandPlan(
            original=display_text,
            kind="script",
            execution="native",
            risk="low",
            reason=f"{head} reads file via PySH static loader",
        )

    risk, reason = _command_risk(text, head)

    if head in builtin_set:
        return CommandPlan(
            original=display_text,
            kind="builtin",
            execution="native",
            risk=risk,
            reason=reason or f"{head} is a PySH builtin",
        )

    return CommandPlan(
        original=display_text,
        kind="external",
        execution="subprocess",
        risk=risk,
        reason=reason or f"{head} resolved through PATH lookup",
    )


def plan(
    args: list[str],
    *,
    builtins: Iterable[str] = (),
    stream: IO[str] | None = None,
) -> int:
    """Run ``plan <command...>``. Returns 0 on success and 2 when args are missing."""
    out = stream if stream is not None else sys.stdout
    if not args:
        print("plan: usage: plan <command...>", file=sys.stderr)
        return 2
    line = " ".join(args)
    result = classify(line, builtins=builtins)
    print(result.format(), file=out)
    return 0


# ---------------------------------------------------------------- helpers


def _first_word(text: str) -> str:
    stripped = text.lstrip()
    word: list[str] = []
    for c in stripped:
        if c in (" ", "\t"):
            break
        word.append(c)
    return "".join(word)


def _op_name(op: ChainOp | None) -> str:
    if op is ChainOp.AND:
        return "&&"
    if op is ChainOp.OR:
        return "||"
    if op is ChainOp.SEMI:
        return ";"
    return ""


_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _max_risk(levels: Iterable[str]) -> str:
    best = "low"
    for level in levels:
        if _RISK_ORDER.get(level, 0) > _RISK_ORDER.get(best, 0):
            best = level
    return best


def _command_risk(text: str, head: str) -> tuple[str, str]:
    if head in RISKY_COMMANDS:
        return "high", f"{head} is a privileged or expansion-style command"
    if "$(" in text or "`" in text:
        return "medium", "command substitution detected"
    redirect_target = _detect_system_redirect(text)
    if redirect_target is not None:
        return "high", f"redirection targets system path {redirect_target}"
    return "low", ""


def _detect_system_redirect(text: str) -> str | None:
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            continue
        if c == ">":
            j = i + 1
            if j < n and text[j] == ">":
                j += 1
            while j < n and text[j] in " \t":
                j += 1
            target_start = j
            while j < n and text[j] not in " \t|;&":
                j += 1
            target = text[target_start:j]
            if any(target.startswith(prefix) for prefix in RISKY_SYSTEM_DIRS):
                return target
        i += 1
    return None
