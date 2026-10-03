# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_differential_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 1: PySH-owned legacy-shell migration contract.

Every case below is SYNTHETIC: no Bash, Zsh or Fish is installed, located or
executed, and nothing here claims a legacy shell produced a result.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from scripts.run_language_conformance import load_corpus
from tests.differential import corpus as migration
from tests.differential.model import (
    Declared,
    Dimension,
    GuidanceKind,
    Observation,
    Outcome,
)
from tests.differential.oracle import StaleDivergenceError, build_evidence, classify

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md"
PACKAGE = REPO_ROOT / "tests" / "differential"

LANGUAGE = load_corpus()
CASE_IDS = frozenset(case["id"] for case in LANGUAGE["cases"])
SYNTHETIC_ANCHOR = "PYSH-MIG-DIV-SYNTHETIC-EXAMPLE"
ANCHORS = frozenset({SYNTHETIC_ANCHOR})
# Synthetic stand-in for a #48 case: status 7, exact stdout.
EXPECTED: dict[str, Any] = {
    "status": 7,
    "stdout": {"match": "exact", "value": "ok\n"},
    "stderr": {"match": "ignore", "value": ""},
    "diagnostic": "runtime",
}


def _metadata(**case_overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "case_id": "path-glob-sorted",
        "legacy_profile": "bash-debian13-amd64",
        "classification": "match",
        "compared_dimensions": ["status", "stdout"],
        "migration_anchor": None,
        "guidance": None,
        "rationale": "synthetic",
    }
    case.update(case_overrides)
    return {
        "schema_version": 1,
        "legacy_profiles": [
            {"profile_id": "bash-debian13-amd64", "legacy_shell": "bash",
             "platform": "debian13-amd64", "executable": "/usr/bin/bash",
             "startup_policy": "bash-noprofile-norc-v1", "version": None,
             "package_version": None, "version_status": "pending"},
        ],
        "cases": [case],
    }


def _parse(data: dict[str, Any]) -> migration.MigrationMetadata:
    return migration.parse_migration(
        data, language_case_ids=CASE_IDS, divergence_anchors=ANCHORS
    )


def _divergence(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "classification": "intended_divergence",
        "migration_anchor": SYNTHETIC_ANCHOR,
        "guidance": {
            "kind": "pysh_native_replacement",
            "legacy_construct": "synthetic legacy construct",
            "pysh_replacement": "synthetic PySH-native form",
        },
    }
    base.update(overrides)
    return base


def _case(declared: str = "match", dims: tuple[str, ...] = ("status", "stdout")) -> Any:
    extra = _divergence() if declared == "intended_divergence" else {}
    return _parse(_metadata(compared_dimensions=list(dims), **extra)).cases[0]


def _obs(status: int = 7, stdout: str = "ok\n", stderr: str = "") -> Observation:
    return Observation(status, stdout, stderr)


# --- metadata layer over #48 ------------------------------------------------------------------


def test_shipped_metadata_is_valid_layered_over_the_language_corpus() -> None:
    data = migration.load_migration()
    assert {p.legacy_shell for p in data.profiles.values()} == {"bash", "zsh", "fish"}
    assert {p.platform for p in data.profiles.values()} == {"debian13-amd64", "freebsd14.4-amd64"}
    assert len(data.profiles) == 6
    for profile in data.profiles.values():
        assert profile.profile_id == f"{profile.legacy_shell}-{profile.platform}"
        # A pending profile never masquerades as verified; a pinned one carries both versions.
        if profile.version_status == "pending":
            assert profile.version is None and profile.package_version is None
        else:
            assert profile.version and profile.package_version
    raw = json.loads(migration.DEFAULT_METADATA.read_text(encoding="utf-8"))
    assert "pysh_expected" not in json.dumps(raw)  # never a second normative corpus
    assert all(case.case_id in CASE_IDS for case in data.cases)


def test_valid_synthetic_match_and_divergence_parse() -> None:
    assert _case("match").declared is Declared.MATCH
    divergence = _case("intended_divergence")
    assert divergence.guidance is not None
    assert divergence.guidance.kind is GuidanceKind.PYSH_NATIVE_REPLACEMENT
    unsupported = _parse(_metadata(**_divergence(guidance={
        "kind": "intentionally_unsupported", "legacy_construct": "x", "reason": "y",
    }))).cases[0]
    assert unsupported.guidance.kind is GuidanceKind.INTENTIONALLY_UNSUPPORTED


def _mut(**kw: Any):
    return lambda: _parse(_metadata(**kw))


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (_mut(case_id="no-such-48-case"), "unknown #48 case"),
        (_mut(classification="regression"), "unknown classification"),
        (_mut(classification="bogus"), "unknown classification"),
        (_mut(compared_dimensions=["status", "fuzzy"]), "compared_dimensions"),
        (_mut(compared_dimensions=[]), "compared_dimensions"),
        (_mut(compared_dimensions=["status", "status"]), "compared_dimensions"),
        (_mut(legacy_profile="fish-debian13-amd64"), "unknown profile"),
        (_mut(extra_field=1), "unknown fields"),
        (_mut(migration_anchor="PYSH-MIG-DIV-SYNTHETIC-EXAMPLE"), "carries no anchor"),
        (_mut(**_divergence(migration_anchor="TODO")), "PYSH-MIG-DIV-"),
        (_mut(**_divergence(migration_anchor="unspecified")), "PYSH-MIG-DIV-"),
        (_mut(**_divergence(migration_anchor="legacy-difference")), "PYSH-MIG-DIV-"),
        (_mut(**_divergence(migration_anchor=None)), "PYSH-MIG-DIV-"),
        (_mut(**_divergence(migration_anchor="PYSH-MIG-DIV-NOT-DOCUMENTED")), "not documented"),
        (_mut(**_divergence(migration_anchor="PYSH-MIG-POSITIONING")), "PYSH-MIG-DIV-"),
        (_mut(**_divergence(guidance=None)), "guidance"),
        (_mut(**_divergence(guidance={"kind": "pysh_native_replacement",
                                      "legacy_construct": "x", "pysh_replacement": ""})), "non-empty"),
        (_mut(**_divergence(guidance={"kind": "intentionally_unsupported",
                                      "legacy_construct": "x"})), "missing fields"),
        (_mut(**_divergence(guidance={"kind": "other", "legacy_construct": "x"})), "guidance kind"),
    ],
)
def test_invalid_metadata_is_rejected(builder, message: str) -> None:
    with pytest.raises(migration.MigrationError, match=re.escape(message)):
        builder()


def test_duplicate_case_profile_pairs_and_profiles_and_versions_are_rejected() -> None:
    data = _metadata()
    data["cases"].append(copy.deepcopy(data["cases"][0]))
    with pytest.raises(migration.MigrationError, match="duplicate case/profile"):
        _parse(data)
    data = _metadata()
    data["legacy_profiles"].append(copy.deepcopy(data["legacy_profiles"][0]))
    with pytest.raises(migration.MigrationError, match="duplicate legacy profile"):
        _parse(data)
    data = _metadata()
    data["legacy_profiles"][0]["version"] = "1.0"
    with pytest.raises(migration.MigrationError, match="pending"):
        _parse(data)
    data = _metadata()
    data["legacy_profiles"][0]["legacy_shell"] = "sh"
    with pytest.raises(migration.MigrationError, match="unknown shell"):
        _parse(data)
    data = _metadata()
    data["schema_version"] = 2
    with pytest.raises(migration.MigrationError, match="schema_version"):
        _parse(data)


def test_real_document_anchors_resolve_and_fake_anchors_cannot() -> None:
    text = DOC.read_text(encoding="utf-8")
    for anchor in ("PYSH-MIG-POSITIONING", "PYSH-MIG-AUTHORITY", "PYSH-MIG-NON-GOALS",
                   "PYSH-MIG-OUTCOMES", "PYSH-MIG-METADATA", "PYSH-MIG-LAB"):
        assert f'<a id="{anchor}"></a>' in text
    # None are registered yet; a divergence against the real document must fail.
    assert migration.documented_divergence_anchors() == frozenset()
    with pytest.raises(migration.MigrationError, match="not documented"):
        migration.parse_migration(
            _metadata(**_divergence()), language_case_ids=CASE_IDS,
            divergence_anchors=migration.documented_divergence_anchors(),
        )


def test_documented_divergence_anchor_in_a_document_is_discovered(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(f'<a id="{SYNTHETIC_ANCHOR}"></a>\n<a id="PYSH-MIG-OUTCOMES"></a>\n', encoding="utf-8")
    assert migration.documented_divergence_anchors(doc) == ANCHORS
    doc.write_text(f'<a id="{SYNTHETIC_ANCHOR}"></a>\n<a id="{SYNTHETIC_ANCHOR}"></a>\n', encoding="utf-8")
    with pytest.raises(migration.MigrationError, match="duplicate anchor"):
        migration.documented_divergence_anchors(doc)


# --- three-valued oracle ----------------------------------------------------------------------


def test_match_when_pysh_and_legacy_both_satisfy_the_pysh_expectation() -> None:
    verdict = classify(_case("match"), EXPECTED, _obs(), _obs())
    assert verdict.outcome is Outcome.MATCH


def test_intended_divergence_when_legacy_differs_and_pysh_conforms() -> None:
    verdict = classify(_case("intended_divergence"), EXPECTED, _obs(), _obs(status=0, stdout="x\n"))
    assert verdict.outcome is Outcome.INTENDED_DIVERGENCE


def test_regression_when_pysh_violates_its_own_expectation_whatever_legacy_did() -> None:
    bad = _obs(stdout="WRONG\n")
    for declared in ("match", "intended_divergence"):
        for legacy in (_obs(), _obs(status=0, stdout="x\n"), bad):
            assert classify(_case(declared), EXPECTED, bad, legacy).outcome is Outcome.REGRESSION


def test_a_difference_from_legacy_alone_is_not_a_regression_when_documented() -> None:
    legacy = _obs(status=0, stdout="different\n")
    assert classify(_case("intended_divergence"), EXPECTED, _obs(), legacy).outcome is (
        Outcome.INTENDED_DIVERGENCE
    )


def test_declared_match_that_no_longer_holds_is_a_regression_of_the_migration_contract() -> None:
    verdict = classify(_case("match"), EXPECTED, _obs(), _obs(status=0))
    assert verdict.outcome is Outcome.REGRESSION
    assert "declared match" in verdict.detail


def test_stale_divergence_fails() -> None:
    with pytest.raises(StaleDivergenceError, match="no longer differs"):
        classify(_case("intended_divergence"), EXPECTED, _obs(), _obs())


def test_exit_status_oracle_keeps_pysh_status_defined_by_the_48_expectation() -> None:
    dims = ("status",)
    # legacy status differs + PySH agrees with #48 + documented divergence => INTENDED_DIVERGENCE
    ok = classify(_case("intended_divergence", dims), EXPECTED, _obs(status=7), _obs(status=0))
    assert ok.outcome is Outcome.INTENDED_DIVERGENCE
    # PySH violates #48 => REGRESSION even when legacy happens to equal the PySH output
    bad = classify(_case("intended_divergence", dims), EXPECTED, _obs(status=0), _obs(status=0))
    assert bad.outcome is Outcome.REGRESSION
    assert "own #48 expectation" in bad.detail


def test_only_compared_dimensions_are_judged() -> None:
    different_stdout = _obs(stdout="other\n")
    assert classify(_case("match", ("status",)), EXPECTED, _obs(), different_stdout).outcome is Outcome.MATCH
    assert classify(_case("match", ("stdout",)), EXPECTED, _obs(), different_stdout).outcome is Outcome.REGRESSION


def test_48_matcher_semantics_are_reused_not_reimplemented() -> None:
    expected = {**EXPECTED, "stdout": {"match": "contains", "value": "needle"}}
    case = _case("match", ("stdout",))
    assert classify(case, expected, _obs(stdout="a needle b"), _obs(stdout="needle")).outcome is Outcome.MATCH
    ignored = {**EXPECTED, "stdout": {"match": "ignore", "value": ""}}
    assert classify(case, ignored, _obs(stdout="anything"), _obs(stdout="else")).outcome is Outcome.MATCH
    placeholder = {**EXPECTED, "stdout": {"match": "exact", "value": "{{WORK}}/f\n"}}
    assert classify(case, placeholder, _obs(stdout="/w/f\n"), _obs(stdout="/w/f\n"),
                    {"WORK": "/w"}).outcome is Outcome.MATCH


def test_evidence_record_is_deterministic_and_carries_no_environment_or_timestamp() -> None:
    case = _case("intended_divergence")
    pysh, legacy = _obs(), _obs(status=0, stdout="x\n")
    verdict = classify(case, EXPECTED, pysh, legacy)
    first = build_evidence(case, verdict, pysh_version="1.0.0", platform="linux-x86_64",
                           legacy_tool_version=None, contract_ref="PYSH-LANG-SYNTHETIC",
                           pysh_observation=pysh, legacy_observation=legacy).to_dict()
    second = build_evidence(case, verdict, pysh_version="1.0.0", platform="linux-x86_64",
                            legacy_tool_version=None, contract_ref="PYSH-LANG-SYNTHETIC",
                            pysh_observation=pysh, legacy_observation=legacy).to_dict()
    assert first == second
    assert set(first) == {
        "pysh_version", "platform", "case_id", "legacy_profile", "legacy_tool_version",
        "pysh_observation", "legacy_observation", "outcome", "contract_ref", "migration_anchor",
    }
    assert first["outcome"] == "INTENDED_DIVERGENCE"
    assert Dimension.STATUS.value == "status"
    text = json.dumps(first)
    assert "HOME" not in text and "environ" not in text and "time" not in text


# --- product independence ---------------------------------------------------------------------


def test_legacy_shells_are_not_declared_dependencies_of_the_package() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(project["project"].get("dependencies", []))
    for group in project["project"].get("optional-dependencies", {}).values():
        declared += group
    for group in project.get("dependency-groups", {}).values():
        declared += [item for item in group if isinstance(item, str)]
    assert project["project"].get("dependencies", []) == []  # stdlib-only runtime
    for requirement in declared:
        name = re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].lower()
        assert name not in {"bash", "zsh", "fish"}, requirement

    for control in ("packaging/debian/control", "packaging/rpm/pysh-shell.spec"):
        for line in (REPO_ROOT / control).read_text(encoding="utf-8").splitlines():
            if re.match(r"(Depends|Pre-Depends|Recommends|Requires|BuildRequires):", line):
                assert not re.search(r"\b(bash|zsh|fish)\b", line), (control, line)


def test_migration_harness_is_test_only_and_not_imported_by_the_product() -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if re.search(r"(?m)^\s*(import|from)\s+(tests|scripts)\b", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert PACKAGE.is_dir() and PACKAGE.parent.name == "tests"


def test_only_the_executor_module_may_spawn_a_process_and_none_may_locate_one() -> None:
    forbidden_modules = {"pty", "shutil", "multiprocessing"}
    forbidden_calls = {"system", "popen", "spawn", "execv", "execvp", "which", "fork", "forkpty"}
    for path in sorted(PACKAGE.glob("*.py")):
        banned = forbidden_modules | (set() if path.name == "executor.py" else {"subprocess"})
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & banned, path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned, path
            elif isinstance(node, ast.Attribute):
                owner = node.value.id if isinstance(node.value, ast.Name) else None
                if owner != "platform":  # platform.system() only names the OS
                    assert node.attr not in forbidden_calls, (path, node.attr)
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False, path


def test_migration_metadata_does_not_become_a_second_language_corpus() -> None:
    raw = json.loads(migration.DEFAULT_METADATA.read_text(encoding="utf-8"))
    assert set(raw) == {"schema_version", "legacy_profiles", "cases"}
    for case in raw["cases"]:
        assert set(case) == migration.CASE_FIELDS
    # The #48 corpus keeps its own closed schema untouched by this layer.
    assert LANGUAGE["schema_version"] == 1 and len(LANGUAGE["cases"]) == 64


def test_migration_document_pins_the_replacement_and_non_goal_contract() -> None:
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    for phrase in (
        "PySH is a standalone, Python-native shell",
        "intended to replace legacy shells for normal interactive and automation use",
        "are **not** runtime dependencies, package dependencies",
        "does not promise Bash, Zsh or Fish emulation",
        "The #48 corpus is the only normative language oracle",
        "PySH specification → PySH expected behavior",
        "never *Bash behavior → PySH expected behavior*",
        "POSIX-shell emulation",
        "arbitrary legacy scripts running unchanged",
        "preservation of historical quirks",
        "runtime fallback to a legacy shell",
        "Intentional incompatibility is allowed",
        "A difference from a legacy shell alone is **never** sufficient for `REGRESSION`",
        "startup files disabled",
        "Exact versions are `pending`",
    ):
        assert phrase in text, phrase
    index = (REPO_ROOT / "docs" / "compatibility" / "README.md").read_text(encoding="utf-8")
    assert "legacy-shell-migration.md" in index
