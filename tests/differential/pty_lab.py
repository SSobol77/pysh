# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/pty_lab.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Controlled-PTY migration evidence for a few interactive behaviors (Issue #54).

Interactive migration behavior is observed only through a controlled PTY: an explicit
absolute executable, a from-scratch environment with a private ``HOME`` holding hostile
startup files, the user-startup-isolation policy of the command-surface laboratory, a
fixed window size, bounded input, a hard wall-clock timeout, bounded output, and a
process group that is swept on every exit path (``scripts/pty_smoke.py``).

The corpus is small and PySH-owned: ``pty-cases-v1.json`` declares, per stable PTY case
ID and documentation anchor, the exact payload lines and exit status an interactive
session must produce. PySH must satisfy it first; a reference is then compared to the
same expectation and only a documented ``PYSH-MIG-DIV-*`` divergence may differ. Bash,
Zsh and Fish never define the expectation.

Normalization is exact and narrow. ANSI/OSC escape sequences are removed, CRLF becomes
LF, a carriage-return redraw keeps the text after the last CR, the configured prompt
(``PTY> ``) is stripped from the start of a line, and only lines beginning with the
sentinel ``PYSH-PTY:`` then count as output. Prompts, echoed input, line-editor
redraws and shell-specific decoration therefore never take part in a comparison.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.run_language_conformance import REPO_ROOT
from tests.differential import oracle
from tests.differential.executor import HermeticTree
from tests.differential.model import (
    Declared,
    Dimension,
    LegacyProfile,
    MigrationCase,
    Observation,
    Outcome,
)
from tests.differential.reference import (
    UNDECLARED_DIFFERENCE,
    LabError,
    case_tree,
    reference_environment,
)
from tests.differential.startup import HOSTILE_MARKER, POLICIES, hostile_home_files

DEFAULT_PTY_CASES = Path(__file__).with_name("pty-cases-v1.json")
SCHEMA_VERSION = 1
SENTINEL = "PYSH-PTY:"
PROMPT = "PTY> "
PTY_TIMEOUT_SECONDS = 25.0
PTY_MAX_OUTPUT_BYTES = 64 * 1024
PTY_MAX_INPUT_BYTES = 512
PTY_WINSIZE = (24, 200)  # rows, columns: wide enough that no line wraps
ENTER = b"\r"  # what a terminal sends for the Return key
EOF_BYTE = b"\x04"  # Ctrl-D
REFERENCE_TERM = "dumb"
PYSH_TERM = "xterm-256color"  # PySH's raw editor needs a capable TERM
DIMENSIONS = frozenset({Dimension.STATUS, Dimension.STDOUT})
#: Interactive flags added to each shell's isolation flags. Fish gets a fixed prompt function.
FISH_PROMPT = f"function fish_prompt; echo -n '{PROMPT}'; end"
INTERACTIVE_FLAGS: dict[str, tuple[str, ...]] = {
    "bash": ("-i",),
    "zsh": ("-i",),
    "fish": ("-i", "-C", FISH_PROMPT),
}

_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[()][A-Za-z0-9]"  # charset selection
    r"|\x1b[=>78]"  # keypad / save-restore cursor
)


class PtyError(LabError):
    """The PTY harness could not produce a trustworthy transcript."""


def load_pty_helper() -> Any:
    """The shared stdlib PTY helper, ``scripts/pty_smoke.py`` (reused, not reimplemented)."""
    name = "pty_smoke"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "pty_smoke.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module registered before exec
    spec.loader.exec_module(module)
    return module


# --- corpus -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PtyCase:
    case_id: str
    anchor: str
    shells: frozenset[str]
    send: tuple[str, ...]
    eof: bool
    payload: tuple[str, ...]
    status: int
    rationale: str

    def input_bytes(self) -> bytes:
        data = b"".join(line.encode() + ENTER for line in self.send)
        return data + (EOF_BYTE if self.eof else b"")

    def expected(self) -> dict[str, Any]:
        text = "".join(f"{line}\n" for line in self.payload)
        return {
            "status": self.status,
            "stdout": {"match": "exact", "value": text},
            "stderr": {"match": "ignore", "value": ""},
            "diagnostic": "none",
        }


class PtyCaseError(ValueError):
    pass


CASE_ID_RE = re.compile(r"pty-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ANCHOR_RE = re.compile(r"PYSH-MIG-PTY-[A-Z0-9]+(?:-[A-Z0-9]+)*\Z")
CASE_FIELDS = frozenset({"case_id", "anchor", "shells", "send", "eof", "expected", "rationale"})


def parse_pty_cases(data: object, documented_anchors: frozenset[str]) -> tuple[PtyCase, ...]:
    """Validate the closed PTY corpus schema; anchors must exist in the migration document."""
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases", "divergences"}:
        raise PtyCaseError("root: expected exactly schema_version, cases and divergences")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise PtyCaseError("unsupported schema_version")
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise PtyCaseError("cases: expected a non-empty list")
    seen: set[str] = set()
    cases: list[PtyCase] = []
    for index, raw in enumerate(data["cases"]):
        context = f"cases[{index}]"
        if not isinstance(raw, dict) or set(raw) != CASE_FIELDS:
            raise PtyCaseError(f"{context}: unexpected fields")
        case_id = raw["case_id"]
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            raise PtyCaseError(f"{context}.case_id: invalid stable ID {case_id!r}")
        if case_id in seen:
            raise PtyCaseError(f"{context}: duplicate case {case_id!r}")
        seen.add(case_id)
        anchor = raw["anchor"]
        if not isinstance(anchor, str) or not ANCHOR_RE.fullmatch(anchor) or anchor not in documented_anchors:
            raise PtyCaseError(f"{context}.anchor: {anchor!r} is not a documented PYSH-MIG-PTY-* anchor")
        shells = raw["shells"]
        if (not isinstance(shells, list) or not shells or len(set(shells)) != len(shells)
                or not set(shells) <= {"bash", "zsh", "fish"}):
            raise PtyCaseError(f"{context}.shells: expected a non-empty unique subset of bash/zsh/fish")
        send = raw["send"]
        if (not isinstance(send, list) or any(not isinstance(s, str) or not s or "\r" in s or "\n" in s
                                              or "\x1b" in s or "\x04" in s for s in send)):
            raise PtyCaseError(f"{context}.send: expected plain single-line strings")
        if not isinstance(raw["eof"], bool) or not (send or raw["eof"]):
            raise PtyCaseError(f"{context}: needs input or eof")
        expected = raw["expected"]
        if (not isinstance(expected, dict) or set(expected) != {"payload", "status"}
                or not isinstance(expected["payload"], list)
                or any(not isinstance(p, str) or not p.startswith(SENTINEL) for p in expected["payload"])
                or not isinstance(expected["status"], int) or isinstance(expected["status"], bool)
                or not 0 <= expected["status"] <= 255):
            raise PtyCaseError(f"{context}.expected: expected sentinel payload lines and a 0..255 status")
        rationale = raw["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise PtyCaseError(f"{context}.rationale: expected a non-empty string")
        case = PtyCase(
            case_id, anchor, frozenset(shells), tuple(send), raw["eof"],
            tuple(expected["payload"]), expected["status"], rationale,
        )
        if len(case.input_bytes()) > PTY_MAX_INPUT_BYTES:
            raise PtyCaseError(f"{context}: input exceeds {PTY_MAX_INPUT_BYTES} bytes")
        cases.append(case)
    return tuple(cases)


def documented_pty_anchors(doc: Path) -> frozenset[str]:
    text = doc.read_text(encoding="utf-8")
    return frozenset(re.findall(r'<a id="(PYSH-MIG-PTY-[A-Z0-9-]+)"></a>', text))


def load_pty_corpus(
    path: Path = DEFAULT_PTY_CASES, doc: Path | None = None
) -> tuple[tuple[PtyCase, ...], dict[str, Any]]:
    from tests.differential.corpus import DEFAULT_DOC

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PtyCaseError(f"cannot load {path}: {error}") from error
    return parse_pty_cases(data, documented_pty_anchors(doc or DEFAULT_DOC)), data


def declared_divergences(data: Mapping[str, Any], cases: tuple[PtyCase, ...]) -> dict[tuple[str, str], MigrationCase]:
    """Reviewed PTY divergences, validated with the same closed schema as command mappings."""
    from tests.differential.corpus import (
        DEFAULT_DOC,
        DEFAULT_METADATA,
        documented_divergence_anchors,
        parse_migration,
    )

    profiles = json.loads(DEFAULT_METADATA.read_text(encoding="utf-8"))["legacy_profiles"]
    entries = []
    for raw in data["divergences"]:
        entries.append({**raw, "classification": "intended_divergence", "compared_dimensions": ["status", "stdout"]})
    parsed = parse_migration(
        {"schema_version": 1, "legacy_profiles": profiles, "cases": entries},
        language_case_ids=frozenset(c.case_id for c in cases),
        divergence_anchors=documented_divergence_anchors(DEFAULT_DOC),
    )
    return {(m.case_id, m.legacy_profile): m for m in parsed.cases}


# --- normalization ------------------------------------------------------------------------------


def normalize_transcript(raw: str) -> tuple[str, ...]:
    """Exact, narrow normalization: only sentinel-prefixed lines survive (see module docstring)."""
    text = _ANSI.sub("", raw).replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        visible = line.split("\r")[-1]  # a carriage-return redraw keeps the final text
        while visible.startswith(PROMPT):  # the configured prompt may precede typed-ahead output
            visible = visible[len(PROMPT):]
        if visible.startswith(SENTINEL):
            lines.append(visible.rstrip())
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class PtyObservation:
    status: int
    payload: tuple[str, ...]

    def as_observation(self) -> Observation:
        return Observation(self.status, "".join(f"{line}\n" for line in self.payload), "")


# --- running ------------------------------------------------------------------------------------


def _run_session(
    argv: list[str], env: dict[str, str], ready: bytes, case: PtyCase, tree: HermeticTree
) -> PtyObservation:
    helper = load_pty_helper()
    result = helper.run_pty_command(
        argv, "", timeout=PTY_TIMEOUT_SECONDS, ready_marker=ready, env=env,
        input_bytes=case.input_bytes(), cwd=str(tree.work), controlling_tty=True,
        max_output_bytes=PTY_MAX_OUTPUT_BYTES, winsize=PTY_WINSIZE,
    )
    if result.output_limited:
        raise PtyError(f"{case.case_id}: PTY output exceeded {PTY_MAX_OUTPUT_BYTES} bytes")
    if result.timed_out or not result.ready or not result.input_sent:
        raise PtyError(
            f"{case.case_id}: PTY session did not complete (ready={result.ready}, "
            f"input_sent={result.input_sent}, timed_out={result.timed_out})"
        )
    if "Traceback" in result.output:
        raise PtyError(f"{case.case_id}: Python traceback in the PTY transcript")
    if HOSTILE_MARKER in result.output:
        raise PtyError(f"{case.case_id}: a hostile startup file was executed")
    if result.returncode is None:
        raise PtyError(f"{case.case_id}: no exit status")
    return PtyObservation(result.returncode, normalize_transcript(result.output))


def observe_pysh_pty(case: PtyCase) -> PtyObservation:
    """Run one PTY case under interactive PySH (``--no-rc``)."""
    helper = load_pty_helper()
    with case_tree() as (tree, env, _placeholders):
        child_env = dict(env)
        child_env["TERM"] = PYSH_TERM
        argv = [sys.executable, "-P", "-m", "pysh", "--no-rc"]
        return _run_session(argv, child_env, helper.BRACKETED_PASTE_READY_MARKER, case, tree)


def observe_reference_pty(profile: LegacyProfile, executable: Path, case: PtyCase) -> PtyObservation:
    """Run one PTY case under a reference shell with its isolation policy and a fixed prompt."""
    policy = POLICIES[profile.startup_policy]
    with case_tree() as (tree, env, _placeholders):
        for name, content in hostile_home_files(policy).items():
            target = tree.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        child_env = reference_environment(env)
        child_env.update({"TERM": REFERENCE_TERM, "PS1": PROMPT})
        argv = [str(executable), *policy.isolation_flags, *INTERACTIVE_FLAGS[profile.legacy_shell]]
        return _run_session(argv, child_env, PROMPT.encode(), case, tree)


# --- classification ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PtyRecord:
    case_id: str
    profile_id: str
    anchor: str
    pysh: PtyObservation
    reference: PtyObservation | None
    classification: str
    migration_anchor: str | None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        def obs(value: PtyObservation | None) -> dict[str, object] | None:
            return None if value is None else {"status": value.status, "payload": list(value.payload)}

        return {
            "case_id": self.case_id,
            "profile_id": self.profile_id,
            "contract_anchor": self.anchor,
            "compared_dimensions": sorted(d.value for d in DIMENSIONS),
            "pysh_observation": obs(self.pysh),
            "reference_observation": obs(self.reference),
            "classification": self.classification,
            "migration_anchor": self.migration_anchor,
            "detail": self.detail,
        }


def classify_pty(
    case: PtyCase, profile: LegacyProfile, pysh: PtyObservation,
    reference: PtyObservation | None, declared: MigrationCase | None,
) -> PtyRecord:
    """PySH against its PTY expectation first; a reference is compared only afterwards."""
    expected = case.expected()
    base = dict(case_id=case.case_id, profile_id=profile.profile_id, anchor=case.anchor, pysh=pysh,
                migration_anchor=declared.migration_anchor if declared else None)
    own = oracle.mismatches(expected, pysh.as_observation(), DIMENSIONS, {})
    if own:
        return PtyRecord(reference=None, classification=Outcome.REGRESSION.value,
                         detail="PySH violates its PTY expectation: " + "; ".join(own), **base)
    if reference is None:
        raise PtyError("a reference observation is required once PySH satisfies the PTY expectation")
    if declared is not None:
        if declared.declared is not Declared.INTENDED_DIVERGENCE:
            raise PtyError("PTY mappings may only declare intended divergences")
        verdict = oracle.classify(declared, expected, pysh.as_observation(), reference.as_observation(), {})
        return PtyRecord(reference=reference, classification=verdict.outcome.value, detail=verdict.detail, **base)
    differences = oracle.mismatches(expected, reference.as_observation(), DIMENSIONS, {})
    if not differences:
        return PtyRecord(reference=reference, classification=Outcome.MATCH.value, **base)
    return PtyRecord(
        reference=reference, classification=UNDECLARED_DIFFERENCE,
        detail="unreviewed PTY difference; document a divergence or fix PySH: " + "; ".join(differences), **base,
    )


def evaluate_profile(
    profile: LegacyProfile, executable: Path, cache: dict[str, PtyObservation] | None = None,
    cases: tuple[PtyCase, ...] | None = None, divergences: dict[tuple[str, str], MigrationCase] | None = None,
) -> tuple[list[PtyRecord], list[str]]:
    """Run the applicable PTY cases for one profile; returns (records, problems)."""
    if cases is None:
        cases, data = load_pty_corpus()
        divergences = declared_divergences(data, cases)
    divergences = divergences or {}
    cache = {} if cache is None else cache
    records: list[PtyRecord] = []
    problems: list[str] = []
    for case in cases:
        if profile.legacy_shell not in case.shells:
            continue
        try:
            if case.case_id not in cache:
                cache[case.case_id] = observe_pysh_pty(case)
            pysh = cache[case.case_id]
            own = oracle.mismatches(case.expected(), pysh.as_observation(), DIMENSIONS, {})
            reference = None if own else observe_reference_pty(profile, executable, case)
            record = classify_pty(case, profile, pysh, reference, divergences.get((case.case_id, profile.profile_id)))
        except oracle.StaleDivergenceError as error:
            problems.append(str(error))
            continue
        except LabError as error:
            problems.append(f"PTY {case.case_id}/{profile.profile_id}: {error}")
            continue
        records.append(record)
        if record.classification == Outcome.REGRESSION.value:
            problems.append(f"REGRESSION PTY {case.case_id}/{profile.profile_id}: {record.detail}")
        elif record.classification == UNDECLARED_DIFFERENCE:
            problems.append(f"UNREVIEWED PTY {case.case_id}/{profile.profile_id}: {record.detail}")
    return records, problems

