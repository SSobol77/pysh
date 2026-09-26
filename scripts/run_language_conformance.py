# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/run_language_conformance.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Run the versioned PySH language conformance corpus.

The corpus is declarative JSON. This runner owns the only fixture expansion and
execution logic: metadata cannot select an executable, inject runner-side
Python, or invoke a reference shell.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "tests" / "conformance" / "pysh-language-v1.json"
DEFAULT_SPEC = REPO_ROOT / "docs" / "spec" / "pysh-language.md"

TOP_LEVEL_FIELDS = frozenset(
    {"schema_version", "language_version", "required_categories", "cases"}
)
CASE_FIELDS = frozenset(
    {"id", "category", "surface", "input", "pysh_expected", "reference_behavior", "contract_ref"}
)
EXPECTED_FIELDS = frozenset({"status", "stdout", "stderr", "diagnostic"})
STREAM_FIELDS = frozenset({"match", "value"})
REFERENCE_FIELDS = frozenset({"classification", "note"})
SURFACES = frozenset({"command", "script"})
STREAM_MATCHERS = frozenset({"exact", "contains", "ignore"})
REFERENCE_CLASSIFICATIONS = frozenset(
    {"equivalent", "different", "not_applicable", "not_captured"}
)
DIAGNOSTIC_CLASSES = frozenset(
    {"none", "runtime", "syntax", "cannot_execute", "command_not_found", "signal"}
)
CASE_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
CONTRACT_ID_RE = re.compile(r"PYSH-LANG-[A-Z0-9]+(?:-[A-Z0-9]+)+\Z")
CONTRACT_ANCHOR_RE = re.compile(r'<a id="(PYSH-LANG-[A-Z0-9-]+)"></a>')
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")
ALLOWED_PLACEHOLDERS = frozenset({"FIXTURE_BIN", "NOEXEC", "WORK", "HOME"})


class CorpusError(ValueError):
    """Raised when the corpus does not satisfy its closed schema."""


@dataclass(frozen=True)
class CaseResult:
    """Observed result for one intrinsic conformance case."""

    case_id: str
    passed: bool
    detail: str = ""


def _require_exact_fields(value: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    """Reject missing or unknown fields in a closed-schema object."""
    actual = set(value)
    missing = sorted(allowed - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        raise CorpusError(f"{context}: missing fields {missing!r}; unknown fields {unknown!r}")


def _require_string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise CorpusError(f"{context}: expected {'a' if allow_empty else 'a non-empty'} string")
    return value


def _validate_placeholders(text: str, context: str) -> None:
    placeholders = set(PLACEHOLDER_RE.findall(text))
    unknown_placeholders = sorted(placeholders - ALLOWED_PLACEHOLDERS)
    if unknown_placeholders:
        raise CorpusError(f"{context}: unknown placeholders {unknown_placeholders!r}")
    residual = PLACEHOLDER_RE.sub("", text)
    if "{{" in residual or "}}" in residual:
        raise CorpusError(f"{context}: malformed placeholder")


def _validate_stream(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise CorpusError(f"{context}: expected an object")
    _require_exact_fields(value, STREAM_FIELDS, context)
    matcher = _require_string(value["match"], f"{context}.match")
    if matcher not in STREAM_MATCHERS:
        raise CorpusError(f"{context}.match: unsupported matcher {matcher!r}")
    text = _require_string(value["value"], f"{context}.value", allow_empty=True)
    _validate_placeholders(text, f"{context}.value")
    if matcher == "ignore" and text:
        raise CorpusError(f"{context}: ignored streams must use an empty value")


def load_corpus(path: Path = DEFAULT_CORPUS, spec_path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    """Load and fully validate a language conformance corpus."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot load corpus {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError("corpus root: expected an object")
    _require_exact_fields(data, TOP_LEVEL_FIELDS, "corpus root")
    if data["schema_version"] != SCHEMA_VERSION:
        raise CorpusError(
            f"unsupported schema_version {data['schema_version']!r}; expected {SCHEMA_VERSION}"
        )
    if data["language_version"] != "1":
        raise CorpusError("language_version: expected '1'")
    required_categories = data["required_categories"]
    if (
        not isinstance(required_categories, list)
        or not required_categories
        or any(not isinstance(item, str) or not item for item in required_categories)
        or len(set(required_categories)) != len(required_categories)
    ):
        raise CorpusError("required_categories: expected a non-empty unique string list")
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise CorpusError("cases: expected a non-empty list")

    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorpusError(f"cannot load specification {spec_path}: {exc}") from exc
    contract_ids = CONTRACT_ANCHOR_RE.findall(spec_text)
    duplicate_contracts = sorted(
        contract_id for contract_id, count in Counter(contract_ids).items() if count > 1
    )
    if duplicate_contracts:
        raise CorpusError(f"specification has duplicate contract IDs: {duplicate_contracts!r}")
    known_contracts = set(contract_ids)

    seen_ids: set[str] = set()
    represented_categories: set[str] = set()
    for index, case in enumerate(cases):
        context = f"cases[{index}]"
        if not isinstance(case, dict):
            raise CorpusError(f"{context}: expected an object")
        _require_exact_fields(case, CASE_FIELDS, context)
        case_id = _require_string(case["id"], f"{context}.id")
        if not CASE_ID_RE.fullmatch(case_id):
            raise CorpusError(f"{context}.id: invalid stable ID {case_id!r}")
        if case_id in seen_ids:
            raise CorpusError(f"duplicate case ID: {case_id}")
        seen_ids.add(case_id)
        category = _require_string(case["category"], f"{context}.category")
        if category not in required_categories:
            raise CorpusError(f"{context}.category: undeclared category {category!r}")
        represented_categories.add(category)
        surface = _require_string(case["surface"], f"{context}.surface")
        if surface not in SURFACES:
            raise CorpusError(f"{context}.surface: unsupported surface {surface!r}")
        input_text = _require_string(case["input"], f"{context}.input", allow_empty=True)
        _validate_placeholders(input_text, f"{context}.input")

        expected = case["pysh_expected"]
        if not isinstance(expected, dict):
            raise CorpusError(f"{context}.pysh_expected: expected an object")
        _require_exact_fields(expected, EXPECTED_FIELDS, f"{context}.pysh_expected")
        if (
            not isinstance(expected["status"], int)
            or isinstance(expected["status"], bool)
            or not 0 <= expected["status"] <= 255
        ):
            raise CorpusError(f"{context}.pysh_expected.status: expected integer 0..255")
        _validate_stream(expected["stdout"], f"{context}.pysh_expected.stdout")
        _validate_stream(expected["stderr"], f"{context}.pysh_expected.stderr")
        diagnostic = _require_string(
            expected["diagnostic"], f"{context}.pysh_expected.diagnostic"
        )
        if diagnostic not in DIAGNOSTIC_CLASSES:
            raise CorpusError(f"{context}.pysh_expected.diagnostic: unknown class {diagnostic!r}")

        reference = case["reference_behavior"]
        if not isinstance(reference, dict):
            raise CorpusError(f"{context}.reference_behavior: expected an object")
        _require_exact_fields(reference, REFERENCE_FIELDS, f"{context}.reference_behavior")
        classification = _require_string(
            reference["classification"], f"{context}.reference_behavior.classification"
        )
        if classification not in REFERENCE_CLASSIFICATIONS:
            raise CorpusError(
                f"{context}.reference_behavior.classification: unknown value {classification!r}"
            )
        _require_string(reference["note"], f"{context}.reference_behavior.note")

        contract_ref = _require_string(case["contract_ref"], f"{context}.contract_ref")
        if not CONTRACT_ID_RE.fullmatch(contract_ref):
            raise CorpusError(f"{context}.contract_ref: invalid contract ID {contract_ref!r}")
        if contract_ref not in known_contracts:
            raise CorpusError(f"{context}.contract_ref: unresolved contract ID {contract_ref!r}")

    missing_categories = sorted(set(required_categories) - represented_categories)
    if missing_categories:
        raise CorpusError(f"required categories have no cases: {missing_categories!r}")
    return data


def _write_fixture_command(path: Path) -> None:
    """Create one deterministic executable used by corpus commands."""
    source = f"""#!{sys.executable}
import os
import signal
import sys

name = os.path.basename(sys.argv[0])
if name == "fixture-echo":
    print(" ".join(sys.argv[1:]))
elif name == "fixture-cat":
    sys.stdout.buffer.write(sys.stdin.buffer.read())
elif name == "fixture-status":
    raise SystemExit(int(sys.argv[1]))
elif name == "fixture-both":
    print("OUT")
    print("ERR", file=sys.stderr)
elif name == "fixture-signal":
    signum = int(sys.argv[1])
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
elif name == "fixture-env":
    print(os.environ.get(sys.argv[1], ""))
else:
    print(f"unknown fixture command: {{name}}", file=sys.stderr)
    raise SystemExit(2)
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fixture_environment(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Build a bounded environment and fixed placeholder map."""
    home = root / "home"
    work = root / "work"
    fixture_bin = root / "bin"
    home.mkdir()
    work.mkdir()
    fixture_bin.mkdir()
    command = fixture_bin / "fixture-command"
    _write_fixture_command(command)
    for name in (
        "fixture-echo",
        "fixture-cat",
        "fixture-status",
        "fixture-both",
        "fixture-signal",
        "fixture-env",
    ):
        (fixture_bin / name).symlink_to(command.name)
    noexec = work / "fixture-noexec"
    noexec.write_text("not executable\n", encoding="utf-8")
    (work / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (work / "beta.txt").write_text("beta\n", encoding="utf-8")
    (work / ".hidden.txt").write_text("hidden\n", encoding="utf-8")
    (work / "stdin.txt").write_text("FILE\n", encoding="utf-8")
    (home / ".pyshrc.py").write_text('print("RC-LOADED")\n', encoding="utf-8")
    env = {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(fixture_bin),
        "PYSH_CONFORMANCE": "value",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    placeholders = {
        "FIXTURE_BIN": str(fixture_bin),
        "NOEXEC": str(noexec),
        "WORK": str(work),
        "HOME": str(home),
    }
    return env, placeholders


def _expand_input(text: str, placeholders: dict[str, str]) -> str:
    """Replace validated fixed-string placeholders without evaluation."""
    return PLACEHOLDER_RE.sub(lambda match: placeholders[match.group(1)], text)


def _diagnostic_class(status: int, stderr: str) -> str:
    if status == 0:
        return "none"
    if status == 2:
        return "syntax"
    if status == 126:
        return "cannot_execute"
    if status == 127:
        return "command_not_found"
    if status >= 128:
        return "signal"
    return "runtime" if stderr else "none"


def _compare_stream(actual: str, expectation: dict[str, str], label: str) -> str | None:
    matcher = expectation["match"]
    expected = expectation["value"]
    if matcher == "ignore":
        return None
    if matcher == "exact" and actual != expected:
        return f"{label}: expected exact {expected!r}, observed {actual!r}"
    if matcher == "contains" and expected not in actual:
        return f"{label}: expected substring {expected!r}, observed {actual!r}"
    return None


def run_case(
    case: dict[str, Any],
    *,
    env: dict[str, str],
    placeholders: dict[str, str],
    work: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CaseResult:
    """Execute one validated case using only PySH intrinsic surfaces."""
    case_id = case["id"]
    input_text = _expand_input(case["input"], placeholders)
    if case["surface"] == "command":
        argv = [sys.executable, "-m", "pysh", "--no-rc", "-c", input_text]
    else:
        script = work / f"case-{case_id}.pysh"
        script.write_text(input_text, encoding="utf-8")
        argv = [sys.executable, "-m", "pysh", "--no-rc", str(script)]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and PySH module
            argv,
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CaseResult(case_id, False, f"execution exceeded {timeout:g}s timeout")
    expected = case["pysh_expected"]
    failures: list[str] = []
    if completed.returncode != expected["status"]:
        failures.append(
            f"status: expected {expected['status']}, observed {completed.returncode}"
        )
    for stream_name, actual in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        stream_expected = dict(expected[stream_name])
        stream_expected["value"] = _expand_input(stream_expected["value"], placeholders)
        mismatch = _compare_stream(actual, stream_expected, stream_name)
        if mismatch:
            failures.append(mismatch)
    diagnostic = _diagnostic_class(completed.returncode, completed.stderr)
    if diagnostic != expected["diagnostic"]:
        failures.append(
            f"diagnostic: expected {expected['diagnostic']!r}, observed {diagnostic!r}"
        )
    return CaseResult(case_id, not failures, "; ".join(failures))


def run_corpus(data: dict[str, Any], *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> list[CaseResult]:
    """Run every validated case in a fresh isolated fixture tree."""
    results: list[CaseResult] = []
    for case in data["cases"]:
        with tempfile.TemporaryDirectory(prefix="pysh-language-") as temp_dir:
            root = Path(temp_dir)
            env, placeholders = _fixture_environment(root)
            results.append(
                run_case(
                    case,
                    env=env,
                    placeholders=placeholders,
                    work=root / "work",
                    timeout=timeout,
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    """Validate and execute the intrinsic PySH language corpus."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        print("FAIL schema: --timeout must be greater than zero")
        return 2
    try:
        data = load_corpus(args.corpus, args.spec)
    except CorpusError as exc:
        print(f"FAIL schema: {exc}")
        return 2
    results = run_corpus(data, timeout=args.timeout)
    for result in results:
        if result.passed:
            print(f"PASS {result.case_id}")
        else:
            print(f"FAIL {result.case_id}: {result.detail}")
    failures = sum(not result.passed for result in results)
    print(f"RESULT {len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
