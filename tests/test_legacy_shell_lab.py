# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_legacy_shell_lab.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 3: contract tests for the legacy-shell differential laboratory.

Pure and always-on: every observation here is SYNTHETIC. No Bash, Zsh or Fish is
executed (real-shell checks live in ``test_legacy_shell_lab_integration.py`` and
run only in the dedicated CI jobs).
"""
from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from scripts.run_language_conformance import load_corpus
from tests.differential import corpus as migration
from tests.differential import reference as lab
from tests.differential.model import Declared, Dimension, LegacyProfile, MigrationCase, Observation
from tests.differential.oracle import StaleDivergenceError
from tests.differential.startup import (
    FORBIDDEN_REFERENCE_ENV,
    HOSTILE_MARKER,
    POLICIES,
    hostile_home_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LANGUAGE = load_corpus()
CASES48 = {case["id"]: case for case in LANGUAGE["cases"]}


def _job(name: str) -> str:
    text = CI.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", text)
    assert match is not None, name
    return match.group(0)


def _profile(**kw: Any) -> LegacyProfile:
    base: dict[str, Any] = dict(
        profile_id="bash-debian13-amd64", legacy_shell="bash", platform="debian13-amd64",
        executable="/usr/bin/bash", startup_policy="bash-noprofile-norc-v1",
        version=None, package_version=None, version_status="pending",
    )
    base.update(kw)
    return LegacyProfile(**base)


# --- profiles and startup policies -----------------------------------------------------------


def test_real_profiles_are_platform_specific_and_never_pending_masquerading_as_verified() -> None:
    data = migration.load_migration()
    assert sorted(data.profiles) == sorted(
        f"{shell}-{plat}" for plat in ("debian13-amd64", "freebsd14.4-amd64")
        for shell in ("bash", "zsh", "fish")
    )
    for profile in data.profiles.values():
        assert profile.executable.startswith("/")
        assert POLICIES[profile.startup_policy].shell == profile.legacy_shell
        if profile.version_status == "pending":
            assert profile.version is None and profile.package_version is None
        else:
            assert profile.version and profile.package_version


def _shipped_with_one_pending_profile() -> dict[str, Any]:
    """The shipped schema shape with a pending first profile and no mappings (schema tests only)."""
    raw = json.loads(migration.DEFAULT_METADATA.read_text(encoding="utf-8"))
    raw["cases"] = []
    raw["legacy_profiles"] = [dict(
        raw["legacy_profiles"][0], version=None, package_version=None, version_status="pending",
    )]
    return raw


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"platform": None}, "expected a non-empty string"),
        ({"platform": "Debian 13"}, "invalid platform ID"),
        ({"profile_id": "bash-freebsd14.4-amd64"}, "expected 'bash-debian13-amd64'"),
        ({"executable": "bash"}, "absolute path"),
        ({"executable": "/usr/../bin/bash"}, "absolute path"),
        ({"startup_policy": "zsh-no-rcs-v1"}, "not a bash policy"),
        ({"startup_policy": "made-up"}, "not a bash policy"),
        ({"version_status": "pinned"}, "needs version and package_version"),
        ({"version_status": "pinned", "version": "x"}, "needs version and package_version"),
        ({"version": "GNU bash, version 5"}, "carries no version evidence"),
        ({"package_version": "5"}, "carries no version evidence"),
        ({"version_status": "verified"}, "unknown value"),
    ],
)
def test_profile_schema_rejects_invalid_profiles(overrides: dict[str, Any], message: str) -> None:
    raw = _shipped_with_one_pending_profile()
    raw["legacy_profiles"] = [dict(raw["legacy_profiles"][0], **overrides)]
    with pytest.raises(migration.MigrationError, match=re.escape(message)):
        migration.parse_migration(
            raw, language_case_ids=frozenset(CASES48), divergence_anchors=frozenset()
        )


def test_a_pinned_profile_is_accepted_when_it_carries_both_versions() -> None:
    raw = _shipped_with_one_pending_profile()
    raw["legacy_profiles"] = [dict(
        raw["legacy_profiles"][0], version_status="pinned", version="GNU bash, version 0.0",
        package_version="0.0-1",
    )]
    parsed = migration.parse_migration(
        raw, language_case_ids=frozenset(CASES48), divergence_anchors=frozenset()
    )
    assert next(iter(parsed.profiles.values())).version_status == "pinned"


def test_startup_policies_are_closed_deterministic_and_put_command_last() -> None:
    assert set(POLICIES) == {"bash-noprofile-norc-v1", "zsh-no-rcs-v1", "fish-no-config-v1"}
    assert POLICIES["bash-noprofile-norc-v1"].argv("echo x") == ["--noprofile", "--norc", "-c", "echo x"]
    assert POLICIES["zsh-no-rcs-v1"].argv("echo x") == ["-f", "-c", "echo x"]
    assert POLICIES["fish-no-config-v1"].argv("echo x") == ["--no-config", "-c", "echo x"]
    for policy in POLICIES.values():
        assert policy.argv("c")[-2:] == ["-c", "c"]
        assert policy.isolated_control_argv("c")[: len(policy.isolation_flags)] == list(policy.isolation_flags)
        files = hostile_home_files(policy)
        assert files and all(HOSTILE_MARKER.encode() in body for body in files.values())


# --- case selection ----------------------------------------------------------------------------


def test_selected_cases_are_a_small_shell_aware_subset_of_the_48_corpus() -> None:
    selected = lab.load_reference_cases()
    assert 8 <= len(selected) <= 15
    ids = [c.case_id for c in selected]
    assert len(ids) == len(set(ids)) and set(ids) <= set(CASES48)
    for case in selected:
        assert CASES48[case.case_id]["surface"] == "command"
        assert case.shells <= {"bash", "zsh", "fish"} and "bash" in case.shells
        assert case.rationale
    # Not every case applies to every shell: applicability is explicit.
    assert any("fish" not in c.shells for c in selected)
    covered = set(ids)
    assert {"lexical-unquoted-words", "pipelines-data-flow", "redirection-output-and-append",
            "substitution-dollar-paren", "variables-environment", "exit-general-failure"} <= covered


def test_the_selection_never_copies_expectations() -> None:
    raw = json.loads(lab.DEFAULT_CASES.read_text(encoding="utf-8"))
    assert "pysh_expected" not in json.dumps(raw)
    assert all(set(c) == {"case_id", "shells", "compared_dimensions", "rationale"} for c in raw["cases"])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(extra=1), "root"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d["cases"][0].update(case_id="no-such-case"), "unknown #48 case"),
        (lambda d: d["cases"][0].update(case_id="script-exit-stops-execution"), "command-surface"),
        (lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "duplicate case"),
        (lambda d: d["cases"][0].update(shells=["sh"]), "subset of bash/zsh/fish"),
        (lambda d: d["cases"][0].update(shells=[]), "non-empty unique"),
        (lambda d: d["cases"][0].update(compared_dimensions=["fuzzy"]), "compared_dimensions"),
        (lambda d: d["cases"][0].update(compared_dimensions=[]), "compared_dimensions"),
        (lambda d: d["cases"][0].update(rationale=" "), "rationale"),
        (lambda d: d["cases"][0].update(extra=1), "unexpected fields"),
        (lambda d: d.update(cases=[]), "non-empty list"),
    ],
)
def test_reference_case_schema_is_closed(mutate, message: str) -> None:
    raw = json.loads(lab.DEFAULT_CASES.read_text(encoding="utf-8"))
    mutate(raw)
    with pytest.raises(lab.ReferenceCaseError, match=re.escape(message)):
        lab.parse_reference_cases(raw, LANGUAGE)


# --- platform and version drift ---------------------------------------------------------------


def test_platform_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = tmp_path / "os-release"
    release.write_text('ID=debian\nVERSION_ID="13"\n', encoding="utf-8")
    monkeypatch.setattr(lab.platform, "system", lambda: "Linux")
    monkeypatch.setattr(lab.platform, "machine", lambda: "x86_64")
    assert lab.detect_platform_id(release) == "debian13-amd64"
    monkeypatch.setattr(lab.platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(lab.platform, "machine", lambda: "amd64")
    monkeypatch.setattr(lab.platform, "release", lambda: "14.4-RELEASE-p1")
    assert lab.detect_platform_id() == "freebsd14.4-amd64"
    assert lab.platform_family("freebsd14.4-amd64") == "freebsd"
    assert lab.platform_family("debian13-amd64") == "debian"


def test_version_drift_fails_with_expected_actual_platform_and_profile() -> None:
    pinned = _profile(version_status="pinned", version="GNU bash, version 5.2.37", package_version="5.2.37-2")
    lab.check_version(pinned, lab.Probe("GNU bash, version 5.2.37", "5.2.37-2"))  # no drift
    with pytest.raises(lab.VersionDriftError) as error:
        lab.check_version(pinned, lab.Probe("GNU bash, version 5.3.0", "5.2.37-2"))
    text = str(error.value)
    assert "bash-debian13-amd64" in text and "debian13-amd64" in text
    assert "'GNU bash, version 5.2.37'" in text and "'GNU bash, version 5.3.0'" in text
    with pytest.raises(lab.VersionDriftError, match="package_version"):
        lab.check_version(pinned, lab.Probe("GNU bash, version 5.2.37", "5.2.38-1"))
    with pytest.raises(lab.VersionDriftError, match="package_version"):
        lab.check_version(pinned, lab.Probe("GNU bash, version 5.2.37", None))
    lab.check_version(_profile(), lab.Probe("anything", None))  # pending: discovery only


def test_executable_resolution_is_absolute_and_never_uses_path(monkeypatch, tmp_path: Path) -> None:
    profile = _profile(executable=str(tmp_path / "missing-bash"))
    with pytest.raises(lab.ReferenceUnavailable, match="not installed"):
        lab.resolve_executable(profile, {})
    fake = tmp_path / "bash"
    fake.write_text("#!/bin/true\n", encoding="utf-8")
    fake.chmod(0o755)
    assert lab.resolve_executable(profile, {"PYSH_REFERENCE_BASH": str(fake)}) == fake
    with pytest.raises(lab.LabError, match="absolute"):
        lab.resolve_executable(profile, {"PYSH_REFERENCE_BASH": "bash"})


# --- classification pipeline (synthetic observations) -----------------------------------------


EXPECTED_CASE = "lexical-unquoted-words"  # fixture-echo alpha beta -> "alpha beta\n", status 0
SELECTED = next(c for c in lab.load_reference_cases() if c.case_id == EXPECTED_CASE)
GOOD = Observation(0, "alpha beta\n", "")


def _classify(pysh: Observation, ref: Observation | None, declared: MigrationCase | None = None):
    return lab.classify_pair(SELECTED, CASES48[EXPECTED_CASE], _profile(), pysh, ref, declared)


def test_pysh_is_checked_against_48_first_and_no_reference_can_excuse_a_violation() -> None:
    bad = Observation(0, "WRONG\n", "")
    record = _classify(bad, None)
    assert record.classification == "REGRESSION" and record.reference_observation is None
    # Even a reference that happens to equal the wrong PySH output is not consulted or excused.
    assert _classify(bad, bad).classification == "REGRESSION"


def test_unreviewed_states_are_reported_without_forcing_a_pass() -> None:
    assert _classify(GOOD, GOOD).classification == "MATCH"
    differing = _classify(GOOD, Observation(0, "alpha  beta\n", ""))
    assert differing.classification == lab.UNDECLARED_DIFFERENCE and "unreviewed" in differing.detail


def _declared(kind: str) -> MigrationCase:
    anchor = "PYSH-MIG-DIV-SYNTHETIC" if kind == "intended_divergence" else None
    return MigrationCase(
        EXPECTED_CASE, "bash-debian13-amd64", Declared(kind), SELECTED.dimensions, anchor, None, "synthetic",
    )


def test_declared_states_use_the_slice_one_oracle() -> None:
    differing = Observation(0, "alpha  beta\n", "")
    assert _classify(GOOD, GOOD, _declared("match")).classification == "MATCH"
    assert _classify(GOOD, differing, _declared("match")).classification == "REGRESSION"
    # intended divergence needs guidance in real metadata; the oracle only needs the declared kind.
    declared = MigrationCase(
        EXPECTED_CASE, "bash-debian13-amd64", Declared.INTENDED_DIVERGENCE, SELECTED.dimensions,
        "PYSH-MIG-DIV-SYNTHETIC", None, "synthetic",
    )
    assert _classify(GOOD, differing, declared).classification == "INTENDED_DIVERGENCE"
    with pytest.raises(StaleDivergenceError):
        _classify(GOOD, GOOD, declared)


def test_only_the_declared_dimensions_are_compared() -> None:
    status_only = lab.ReferenceCase(EXPECTED_CASE, frozenset({"bash"}), frozenset({Dimension.STATUS}), "x")
    record = lab.classify_pair(
        status_only, CASES48[EXPECTED_CASE], _profile(), GOOD, Observation(0, "totally different", "noise"), None,
    )
    assert record.classification == "MATCH"


# --- run_lab flow with a fake probing layer ----------------------------------------------------


@pytest.fixture
def fake_lab(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: dict[str, list[str]] = {"pysh": [], "reference": []}
    fake_exe = tmp_path / "bash"
    fake_exe.write_text("#!/bin/true\n", encoding="utf-8")
    fake_exe.chmod(0o755)
    state: dict[str, Any] = {
        "profile": _profile(), "pysh_obs": GOOD, "ref_obs": GOOD, "probe": lab.Probe("GNU bash, version 1", "1-1"),
        "declared": [], "isolation_ok": True,
    }

    def metadata_loader():
        return migration.MigrationMetadata({state["profile"].profile_id: state["profile"]}, tuple(state["declared"]))

    def observe_pysh(command: str) -> Observation:
        calls["pysh"].append(command)
        return state["pysh_obs"]

    def observe_reference(profile, executable, command: str) -> Observation:
        calls["reference"].append(command)
        return state["ref_obs"]

    def isolation_checks(profile, executable):
        return [lab.Check("synthetic", state["isolation_ok"])]

    monkeypatch.setattr(lab, "load_migration", metadata_loader)
    monkeypatch.setattr(lab, "resolve_executable", lambda profile, environ=None: fake_exe)
    monkeypatch.setattr(lab, "probe_reference", lambda profile, executable: state["probe"])
    monkeypatch.setattr(lab, "isolation_checks", isolation_checks)
    monkeypatch.setattr(lab, "observe_pysh", observe_pysh)
    monkeypatch.setattr(lab, "observe_reference", observe_reference)
    monkeypatch.setattr(lab, "load_reference_cases", lambda path=lab.DEFAULT_CASES: (SELECTED,))
    return state, calls


def test_discovery_run_reports_the_pin_proposal_and_runs_pysh_before_the_reference(fake_lab) -> None:
    state, calls = fake_lab
    document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert problems == []
    profile = document["profiles"][0]
    assert profile["observed_version"] == "GNU bash, version 1" and profile["version_status"] == "pending"
    assert [r["classification"] for r in profile["records"]] == ["MATCH"]
    assert len(calls["pysh"]) == 1 and len(calls["reference"]) == 1


def test_pysh_violation_is_a_regression_and_the_reference_is_never_run(fake_lab) -> None:
    state, calls = fake_lab
    state["pysh_obs"] = Observation(0, "WRONG\n", "")
    document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert calls["reference"] == []
    assert any(p.startswith("REGRESSION lexical-unquoted-words/bash-debian13-amd64") for p in problems)
    assert document["profiles"][0]["records"][0]["reference_observation"] is None


def test_drift_fails_before_any_semantic_result_is_interpreted(fake_lab) -> None:
    state, calls = fake_lab
    state["profile"] = _profile(version_status="pinned", version="GNU bash, version 2", package_version="1-1")
    document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert any("version drift" in p and "expected 'GNU bash, version 2'" in p for p in problems)
    assert calls == {"pysh": [], "reference": []}
    assert document["profiles"][0]["records"] == []


def test_failed_isolation_blocks_semantic_results(fake_lab) -> None:
    state, calls = fake_lab
    state["isolation_ok"] = False
    _document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert any("startup isolation failed" in p for p in problems) and calls["reference"] == []


def test_pinned_profile_requires_a_reviewed_entry_for_every_selected_case(fake_lab) -> None:
    state, _calls = fake_lab
    state["profile"] = _profile(version_status="pinned", version="GNU bash, version 1", package_version="1-1")
    _document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert any(p.startswith("UNREVIEWED") for p in problems)
    state["declared"] = [_declared("match")]
    assert lab.run_lab(platform_id="debian13-amd64")[1] == []


def test_strict_mode_makes_unreviewed_differences_fail(fake_lab) -> None:
    state, _calls = fake_lab
    state["ref_obs"] = Observation(0, "alpha  beta\n", "")
    assert lab.run_lab(platform_id="debian13-amd64")[1] == []  # discovery: reported, not accepted
    assert any(p.startswith("UNREVIEWED") for p in lab.run_lab(platform_id="debian13-amd64", strict=True)[1])


def test_missing_reference_is_skipped_locally_but_fails_when_required(fake_lab, monkeypatch) -> None:
    def missing(profile, environ=None):
        raise lab.ReferenceUnavailable("reference shell for profile bash-debian13-amd64 is not installed at /x")

    monkeypatch.setattr(lab, "resolve_executable", missing)
    document, problems = lab.run_lab(platform_id="debian13-amd64")
    assert problems == [] and document["profiles"][0]["skipped_reason"]
    assert lab.run_lab(platform_id="debian13-amd64", require_all=True)[1]
    assert lab.run_lab(platform_id="unknown1-amd64")[1][0].startswith("no legacy reference profiles")


# --- evidence ---------------------------------------------------------------------------------


def test_evidence_is_canonical_deterministic_and_sanitized(fake_lab) -> None:
    state, _calls = fake_lab
    first = lab.canonical_json(lab.run_lab(platform_id="debian13-amd64", commit="abc")[0])
    second = lab.canonical_json(lab.run_lab(platform_id="debian13-amd64", commit="abc")[0])
    assert first == second
    document = json.loads(first)
    assert set(document) == {"schema_version", "pysh_version", "pysh_commit", "platform", "profiles"}
    record = document["profiles"][0]["records"][0]
    assert set(record) == {
        "case_id", "profile_id", "compared_dimensions", "pysh_observation", "reference_observation",
        "classification", "contract_ref", "migration_anchor", "detail",
    }
    for forbidden in ("HOME", "environ", "timestamp", "/home/", "/tmp/", "USER"):
        assert forbidden not in first
    assert list(json.loads(first)) == sorted(json.loads(first))


def test_observed_paths_are_normalized_to_placeholders() -> None:
    from tests.differential.executor import HermeticTree

    root = Path("/x/pysh-differential-abc")
    tree = HermeticTree(root, root / "home", root / "work", root / "bin", root / "tmp")
    placeholders = {"WORK": str(root / "work"), "HOME": str(root / "home")}
    text = f"{root / 'work'}/a {root / 'home'} {root}/other"
    assert lab._normalize(text, tree, placeholders) == "{{WORK}}/a {{HOME}} {{TREE}}/other"


# --- dependency boundary and CI contract -------------------------------------------------------


def test_reference_shells_are_ci_equipment_not_dependencies() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []
    everything = json.dumps(project)
    assert not re.search(r'"(bash|zsh|fish)[^"]*"', everything.replace("pysh-shell", ""))
    for control in ("packaging/debian/control", "packaging/rpm/pysh-shell.spec"):
        for line in (REPO_ROOT / control).read_text(encoding="utf-8").splitlines():
            if re.match(r"(Depends|Pre-Depends|Recommends|Suggests|Requires|BuildRequires):", line):
                assert not re.search(r"\b(bash|zsh|fish)\b", line), (control, line)
    for path in (REPO_ROOT / "src").rglob("*.py"):
        assert "tests.differential" not in path.read_text(encoding="utf-8"), path


def test_reference_shells_are_installed_only_by_the_dedicated_ci_jobs() -> None:
    text = CI.read_text(encoding="utf-8")
    debian, freebsd = _job("legacy-shell-evidence-debian"), _job("legacy-shell-evidence-freebsd")
    assert re.search(r"apt-get install[^\n]*\\\n\s+bash[^\n]*zsh fish", debian)
    assert "pkg install -y bash python313 uv git zsh fish" in freebsd
    outside = text.replace(debian, "").replace(freebsd, "")
    assert not re.search(r"(apt-get|pkg) install[^\n]*\b(zsh|fish)\b", outside)
    assert "pip install" not in "".join(re.findall(r"[^\n]*\b(?:zsh|fish)\b[^\n]*", text))


@pytest.mark.parametrize(
    ("job", "marker"),
    [("legacy-shell-evidence-debian", "debian-13"), ("legacy-shell-evidence-freebsd", "freebsd-14.4")],
)
def test_tier1_ci_jobs_require_all_profiles_and_upload_evidence(job: str, marker: str) -> None:
    body = _job(job)
    assert f"legacy-shell differential evidence ({marker}" in body
    assert "--require-all" in body and "--evidence-dir artifacts/legacy-shell-differential" in body
    assert "PYSH_LEGACY_LAB=required" in body and "tests/test_legacy_shell_lab_integration.py" in body
    assert "scripts/run_legacy_shell_differential.py" in body
    assert "continue-on-error" not in body
    assert "if: ${{ always() }}" in body and "actions/upload-artifact@v4" in body
    assert "retention-days:" in body
    assert "compatibility" not in body.split("steps:")[0].lower()
    assert "contents: write" not in body


def test_debian_and_freebsd_jobs_use_the_existing_tier1_conventions() -> None:
    debian, freebsd = _job("legacy-shell-evidence-debian"), _job("legacy-shell-evidence-freebsd")
    assert "image: debian:13-slim" in debian and 'test "${VERSION_ID}" = "13"' in debian
    assert 'test "$(dpkg --print-architecture)" = "amd64"' in debian
    assert "python3.13 -m venv" in debian
    assert "vmactions/freebsd-vm@v1" in freebsd and 'release: "14.4"' in freebsd
    assert 'test "$(uname -m)" = "amd64"' in freebsd and "uv venv --python python3.13" in freebsd


def test_the_normal_suite_and_other_jobs_never_need_the_reference_shells() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "PYSH_LEGACY_LAB" not in text.replace(_job("legacy-shell-evidence-debian"), "").replace(
        _job("legacy-shell-evidence-freebsd"), ""
    )
    assert lab.lab_mode() in {"off", "available", "required"}


def test_lab_tooling_never_uses_shell_true_or_path_lookup() -> None:
    import ast

    for name in ("reference.py", "startup.py", "executor.py"):
        tree = ast.parse((REPO_ROOT / "tests" / "differential" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False
            assert not (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and (node.value.id, node.attr) in {("shutil", "which"), ("os", "system"), ("os", "popen")}
            )


def test_shebang_delegation_is_not_the_comparison_mechanism() -> None:
    source = (REPO_ROOT / "tests" / "differential" / "reference.py").read_text(encoding="utf-8")
    assert "run_script" not in source and "shebang" not in source.lower().replace("startup", "")


def test_migration_document_describes_the_real_laboratory() -> None:
    text = " ".join((REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md").read_text(encoding="utf-8").split())
    for phrase in (
        "Bash, Zsh and Fish are used **only** as reference equipment",
        "no runtime or package dependency exists",
        "A violation is a `REGRESSION` that no reference result can excuse",
        "Version drift fails CI",
        "a missing shell fails the job",
        "Legacy output is never an oracle",
        "`PYSH_LEGACY_LAB`",
        "positive control",
        "`bash-debian13-amd64`",
    ):
        assert phrase in text, phrase


# --- startup-isolation hardening ----------------------------------------------------------------

FAKE_SHELL = REPO_ROOT / "tests" / "fixtures" / "fake_reference_shell.py"
PYTHON = __import__("sys").executable


@pytest.fixture
def fake_shells(tmp_path: Path):
    """Executable fake shells named bash/zsh/fish plus defective variants."""
    source = FAKE_SHELL.read_text(encoding="utf-8")
    body = source.split("\n", 1)[1] if source.startswith("#!") else source

    def make(name: str) -> Path:
        path = tmp_path / name
        path.write_text(f"#!{PYTHON}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path

    return make


def _profile_for(shell: str, platform: str = "debian13-amd64") -> LegacyProfile:
    return _profile(
        profile_id=f"{shell}-{platform}", legacy_shell=shell, platform=platform,
        executable=f"/usr/bin/{shell}", startup_policy=POLICIES_BY_SHELL[shell],
    )


POLICIES_BY_SHELL = {"bash": "bash-noprofile-norc-v1", "zsh": "zsh-no-rcs-v1", "fish": "fish-no-config-v1"}


def _failed(shell: str, fake: Path) -> set[str]:
    return {c.name for c in lab.isolation_checks(_profile_for(shell), fake) if not c.ok}


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_isolation_checks_all_pass_for_a_correct_fake_shell(shell: str, fake_shells) -> None:
    checks = lab.isolation_checks(_profile_for(shell), fake_shells(shell))
    assert [c.name for c in checks if not c.ok] == []
    names = {c.name for c in checks}
    assert "platform-startup-baseline-is-silent" in names
    for hook in POLICIES[POLICIES_BY_SHELL[shell]].startup_env_hooks:
        assert f"host-{hook}-is-not-inherited-or-executed" in names
        assert f"explicit-{hook}-is-rejected-by-the-laboratory" in names


def test_bash_env_is_proven_not_inherited_and_a_forced_hook_does_execute(fake_shells) -> None:
    checks = {c.name: c.ok for c in lab.isolation_checks(_profile_for("bash"), fake_shells("bash"))}
    assert checks["host-BASH_ENV-is-not-inherited-or-executed"]
    assert checks["explicit-BASH_ENV-is-rejected-by-the-laboratory"]
    # The control bypasses the guard on purpose: BASH_ENV runs even with --noprofile --norc.
    assert checks["BASH_ENV-positive-control-would-execute-hostile-code"]


def test_defective_shells_are_caught(fake_shells) -> None:
    assert "isolated-run-ignores-hostile-startup-files" in _failed("bash", fake_shells("bash_leaky"))
    assert "isolated-run-ignores-hostile-startup-files" in _failed("zsh", fake_shells("zsh_leaky"))
    assert "isolated-run-ignores-hostile-startup-files" in _failed("fish", fake_shells("fish_confd"))


def test_platform_global_zsh_startup_noise_or_state_changes_fail_the_profile(fake_shells) -> None:
    assert "platform-startup-baseline-is-silent" in _failed("zsh", fake_shells("zsh_noisy"))
    assert "global-startup-left-controlled-state-intact" in _failed("zsh", fake_shells("zsh_pathmut"))


def test_zsh_guarantee_is_user_startup_only_and_the_global_limitation_is_explicit() -> None:
    zsh = POLICIES["zsh-no-rcs-v1"]
    assert zsh.guarantee == "user startup configuration"
    assert zsh.global_startup_limitation and "installation-wide zshenv" in zsh.global_startup_limitation
    assert "ZDOTDIR" in zsh.startup_env_hooks
    assert POLICIES["bash-noprofile-norc-v1"].global_startup_limitation is None
    assert "BASH_ENV" in POLICIES["bash-noprofile-norc-v1"].startup_env_hooks
    report = lab.ProfileReport(_profile_for("zsh")).to_dict()
    assert report["startup_isolation_scope"] == "user startup configuration"
    assert "zshenv" in report["global_startup_limitation"]


def test_fish_isolation_covers_config_fish_and_conf_d() -> None:
    fish = POLICIES["fish-no-config-v1"]
    assert ".config/fish/config.fish" in fish.hostile_files
    assert ".config/fish/conf.d/hostile.fish" in fish.hostile_files
    assert set(fish.control_must_fire) == set(fish.hostile_files)
    assert {"XDG_CONFIG_HOME"} <= set(fish.startup_env_hooks)


@pytest.mark.parametrize("hook", sorted(FORBIDDEN_REFERENCE_ENV))
def test_startup_hook_variables_never_reach_a_reference_shell(hook: str) -> None:
    with pytest.raises(lab.LabError, match="startup-hook variables"):
        lab.reference_environment({"HOME": "/h", hook: "x"})
    assert lab.reference_environment({"HOME": "/h", "PYTHONPATH": "/p"}) == {"HOME": "/h"}


def test_the_executor_builds_from_scratch_so_a_host_bash_env_cannot_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_shells
) -> None:
    hostile = tmp_path / "hostile-bash-env"
    hostile.write_text("echo HOSTILE-BASH-ENV-EXECUTED\n", encoding="utf-8")
    monkeypatch.setenv("BASH_ENV", str(hostile))
    from tests.differential.executor import run_hermetic

    result = run_hermetic(fake_shells("bash"), ["--noprofile", "--norc", "-c", "echo ok"])
    assert result.stdout == "ok\n" and "HOSTILE" not in result.stderr


def test_evidence_is_published_before_a_later_semantic_or_isolation_failure(fake_lab) -> None:
    state, _calls = fake_lab
    state["isolation_ok"] = False
    published: list[dict[str, object]] = []
    document, problems = lab.run_lab(platform_id="debian13-amd64", progress=published.append)
    assert problems
    first = published[0]["profiles"][0]
    assert first["observed_version"] == "GNU bash, version 1" and first["observed_package_version"] == "1-1"
    final = document["profiles"][0]
    assert final["observed_version"] == first["observed_version"]
    assert [c["ok"] for c in final["isolation_checks"]] == [False]


def test_the_command_line_entry_point_writes_evidence_even_when_the_run_fails(
    fake_lab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import run_legacy_shell_differential as cli

    monkeypatch.setattr(lab, "detect_platform_id", lambda *a, **k: "debian13-amd64")
    state, _calls = fake_lab
    state["pysh_obs"] = Observation(0, "WRONG\n", "")
    original = lab.run_lab
    monkeypatch.setattr(lab, "run_lab", lambda **kw: original(platform_id="debian13-amd64", **kw))
    rc = cli.main(["--require-all", "--evidence-dir", str(tmp_path / "evidence")])
    written = json.loads((tmp_path / "evidence" / "legacy-shell-differential-debian13-amd64.json").read_text())
    assert rc == 1 and written["profiles"][0]["observed_version"] == "GNU bash, version 1"


@pytest.mark.parametrize("job", ["legacy-shell-evidence-debian", "legacy-shell-evidence-freebsd"])
def test_ci_writes_evidence_first_and_always_uploads_it(job: str) -> None:
    body = _job(job)
    script = body.index("scripts/run_legacy_shell_differential.py")
    pytest_step = body.index("tests/test_legacy_shell_lab_integration.py")
    assert script < pytest_step, "evidence must be produced before the integration tests can fail"
    assert body.count("|| status=$?") == 2 and 'exit "${status}"' in body
    assert body.index('exit "${status}"') > pytest_step
    upload = body[body.index("Upload legacy-shell differential evidence"):]
    assert "if: ${{ always() }}" in upload and "actions/upload-artifact@v4" in upload


def test_startup_wording_does_not_overclaim() -> None:
    doc = " ".join((REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md").read_text(encoding="utf-8").split())
    for phrase in (
        "user-startup isolation",
        "Platform-global Zsh startup is an explicit baseline limitation",
        "not complete system startup isolation",
        "installation-wide `zshenv` before `-f` can suppress",
        "A clean probe does not prove the global file did not execute",
        "`BASH_ENV`",
        "`conf.d/*.fish`",
    ):
        assert phrase in doc, phrase
    assert "Hermetic execution." not in doc
    guarantee = POLICIES["zsh-no-rcs-v1"].global_startup_limitation
    assert guarantee and "hermetic" not in guarantee.lower()


# --- reviewed Tier-1 baseline (v1 corpus contract) ------------------------------------------------


def _applicable(profile: LegacyProfile):
    return [c for c in lab.load_reference_cases() if profile.legacy_shell in c.shells]


def test_every_pinned_profile_has_exactly_one_reviewed_mapping_per_applicable_case() -> None:
    data = migration.load_migration()
    by_pair: dict[tuple[str, str], list[MigrationCase]] = {}
    for mapping in data.cases:
        by_pair.setdefault((mapping.case_id, mapping.legacy_profile), []).append(mapping)
    for profile in data.profiles.values():
        if profile.version_status != "pinned":
            continue
        for case in _applicable(profile):
            found = by_pair.get((case.case_id, profile.profile_id), [])
            assert len(found) == 1, f"{profile.profile_id}/{case.case_id}: {len(found)} mappings"
            assert found[0].compared_dimensions == case.dimensions, (
                f"{profile.profile_id}/{case.case_id}: compared dimensions differ from the selection"
            )
    # And no mapping exists for a case that does not apply to that profile's shell.
    applicable = {(c.case_id, p.profile_id) for p in data.profiles.values() for c in _applicable(p)}
    assert {(m.case_id, m.legacy_profile) for m in data.cases} <= applicable


def test_the_v1_reviewed_baseline_has_six_pinned_profiles_and_84_mappings() -> None:
    data = migration.load_migration()
    assert len(data.profiles) == 6
    assert all(p.version_status == "pinned" for p in data.profiles.values())
    derived = sum(len(_applicable(p)) for p in data.profiles.values())
    assert derived == 84 and len(data.cases) == 84
    per_profile = {
        pid: sum(1 for m in data.cases if m.legacy_profile == pid) for pid in data.profiles
    }
    for pid, count in per_profile.items():
        shell = data.profiles[pid].legacy_shell
        assert count == {"bash": 15, "zsh": 15, "fish": 12}[shell], pid


def test_reviewed_mappings_are_plain_matches_that_copy_no_observation() -> None:
    raw = json.loads(migration.DEFAULT_METADATA.read_text(encoding="utf-8"))
    assert len(raw["cases"]) == 84
    for mapping in raw["cases"]:
        assert set(mapping) == migration.CASE_FIELDS  # no stdout/stderr/status/pysh_expected
        assert mapping["classification"] == "match"
        assert mapping["migration_anchor"] is None and mapping["guidance"] is None
        text = mapping["rationale"]
        assert "#48 remains normative" in text and "define PySH semantics" not in text
    data = migration.load_migration()
    assert all(m.declared is Declared.MATCH for m in data.cases)


def test_pins_are_exact_strings_and_any_drift_fails_before_acceptance() -> None:
    data = migration.load_migration()
    bash = data.profiles["bash-debian13-amd64"]
    exact = lab.Probe(bash.version, bash.package_version)
    lab.check_version(bash, exact)  # matching pin -> accepted
    drifted = [
        lab.Probe(bash.version.replace("5.2.37", "5.2.38"), bash.package_version),
        lab.Probe(bash.version + " ", bash.package_version),
        lab.Probe(bash.version.lower(), bash.package_version),
        lab.Probe(bash.version, "5.2.37-2+b11"),
        lab.Probe(bash.version, "5.2.37-2"),  # no revision normalization
        lab.Probe(bash.version, "1:" + bash.package_version),  # no epoch normalization
        lab.Probe(bash.version, None),
    ]
    for probe in drifted:
        with pytest.raises(lab.VersionDriftError):
            lab.check_version(bash, probe)
    fish = data.profiles["fish-freebsd14.4-amd64"]
    assert fish.package_version == "4.9.1_1"
    with pytest.raises(lab.VersionDriftError):
        lab.check_version(fish, lab.Probe(fish.version, "4.9.1"))  # no FreeBSD suffix normalization


def test_pinned_values_are_the_reviewed_tier1_baseline() -> None:
    data = migration.load_migration()
    expected = {
        "bash-debian13-amd64": ("/usr/bin/bash", "GNU bash, version 5.2.37(1)-release (x86_64-pc-linux-gnu)", "5.2.37-2+b10"),
        "zsh-debian13-amd64": ("/usr/bin/zsh", "zsh 5.9 (x86_64-debian-linux-gnu)", "5.9-8+b24"),
        "fish-debian13-amd64": ("/usr/bin/fish", "fish, version 4.0.2", "4.0.2-1"),
        "bash-freebsd14.4-amd64": ("/usr/local/bin/bash", "GNU bash, version 5.3.20(0)-release (amd64-portbld-freebsd14.4)", "5.3.20"),
        "zsh-freebsd14.4-amd64": ("/usr/local/bin/zsh", "zsh 5.9.2 (amd64-portbld-freebsd14.4)", "5.9.2"),
        "fish-freebsd14.4-amd64": ("/usr/local/bin/fish", "fish, version 4.9.1", "4.9.1_1"),
    }
    assert {pid: (p.executable, p.version, p.package_version) for pid, p in data.profiles.items()} == expected
    startup = {pid: p.startup_policy for pid, p in data.profiles.items()}
    assert set(startup.values()) == {"bash-noprofile-norc-v1", "zsh-no-rcs-v1", "fish-no-config-v1"}


def test_documentation_records_the_reviewed_pins_without_overclaiming() -> None:
    text = " ".join((REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md").read_text(encoding="utf-8").split())
    for phrase in (
        "Reviewed Tier-1 baseline",
        "37138273140",
        "test-reference pins only",
        "merge-blocking until it is reviewed",
        "All 84 applicable case/profile pairs",
        "no `INTENDED_DIVERGENCE` was needed",
        "external shells still do not define PySH semantics",
        "does not prove the global `zshenv` did not run",
        "requires exactly one reviewed mapping",
    ):
        assert phrase in text, phrase


def test_an_executor_error_during_discovery_is_a_problem_and_the_run_continues(
    fake_lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.differential.executor import ExecutorError

    state, calls = fake_lab
    second = _profile(
        profile_id="zsh-debian13-amd64", legacy_shell="zsh", platform="debian13-amd64",
        executable="/usr/bin/zsh", startup_policy="zsh-no-rcs-v1",
    )
    first = state["profile"]
    zsh_case = lab.ReferenceCase(EXPECTED_CASE, frozenset({"bash", "zsh"}), SELECTED.dimensions, "x")
    monkeypatch.setattr(lab, "load_reference_cases", lambda path=lab.DEFAULT_CASES: (zsh_case,))
    monkeypatch.setattr(
        lab, "load_migration",
        lambda: migration.MigrationMetadata({first.profile_id: first, second.profile_id: second}, ()),
    )

    def probe(profile, executable):
        if profile.legacy_shell == "bash":
            raise ExecutorError("cannot execute bash: EACCES")  # infrastructure failure, not LabError
        return lab.Probe("zsh 5.9", "5.9-1")

    monkeypatch.setattr(lab, "probe_reference", probe)
    published: list[dict[str, object]] = []
    document, problems = lab.run_lab(platform_id="debian13-amd64", progress=published.append)
    assert any("cannot execute bash" in p for p in problems)
    assert published, "evidence must still be published"
    profiles = {p["profile_id"]: p for p in document["profiles"]}
    assert profiles["bash-debian13-amd64"]["records"] == []
    # The run continued with the next profile and produced its records.
    assert [r["classification"] for r in profiles["zsh-debian13-amd64"]["records"]] == ["MATCH"]
    assert calls["reference"], "the subsequent profile was exercised"


def test_unrelated_programming_errors_in_discovery_are_not_swallowed(
    fake_lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(profile, executable):
        raise KeyError("a programming error")

    monkeypatch.setattr(lab, "probe_reference", broken)
    with pytest.raises(KeyError):
        lab.run_lab(platform_id="debian13-amd64")
