# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_attestations.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #51 Slice 3: attestation subjects and verification before upload.

Hermetic: a repository-owned fake ``gh`` stands in for the GitHub CLI and the Artifact
Attestations service. No network, no real attestation, no signing.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import check_reproducibility_evidence as repro_checker
from scripts import generate_release_sboms as sboms
from scripts import prepare_attestation_subjects as prep
from scripts import verify_release_attestations as ver
from tests.repro_support import final_document

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_GH = REPO_ROOT / "tests" / "fixtures" / "fake_gh.py"
VERSION = "9.8.7"
SOURCE = "0123456789abcdef0123456789abcdef01234567"
OTHER_SOURCE = "f" * 40


canonical_json = repro_checker.canonical_json


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    """A final twelve-file bundle: five packages, five SBOMs, REPRODUCIBILITY.json and SHA256SUMS."""
    directory = tmp_path / "release-assets"
    directory.mkdir()
    for family in sboms.FAMILIES:
        name = family.names[0].format(v=VERSION)
        (directory / name).write_bytes(f"bytes of {name}".encode())
        document = {"spdxVersion": "SPDX-2.3", "name": name, "packages": [{"name": name, "SPDXID": "SPDXRef-1"}]}
        (directory / sboms.sbom_name(name)).write_text(json.dumps(document), encoding="utf-8")
    (directory / sboms.EVIDENCE).write_text(canonical_json(final_document(version=VERSION, commit=SOURCE)), encoding="utf-8")
    write_manifest(directory)
    return directory


def write_manifest(directory: Path) -> None:
    lines = [
        f"{sha(p.read_bytes())}  {p.name}\n"
        for p in sorted(directory.iterdir()) if p.name != "SHA256SUMS"
    ]
    (directory / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


def good_scenario(directory: Path) -> dict[str, Any]:
    bundle = prep.prepare(directory, VERSION)
    listed = [[s.name, s.sha256] for s in bundle.manifest_subjects()]
    identity = {"repo": ver.PINNED_REPO, "workflow": ver.PINNED_SIGNER_WORKFLOW, "source_digest": SOURCE}
    attestations: list[dict[str, Any]] = [
        {"subjects": listed, "predicateType": ver.PROVENANCE_PREDICATE_TYPE, "predicate": {"buildType": "x"}, **identity},
        {"subjects": [[bundle.checksums.name, bundle.checksums.sha256]],
         "predicateType": ver.PROVENANCE_PREDICATE_TYPE, "predicate": {"buildType": "x"}, **identity},
    ]
    for entry in bundle.packages:
        document = json.loads((directory / entry.sbom.name).read_text(encoding="utf-8"))
        attestations.append({
            "subjects": [[entry.package.name, entry.package.sha256]],
            "predicateType": ver.SPDX_PREDICATE_TYPE, "predicate": document, **identity,
        })
    return {"attestations": attestations, "hidden": {}, "malformed": [], "slow": []}


class World:
    """Fake gh + deterministic time for one test."""

    def __init__(self, tmp_path: Path, directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.directory = directory
        self.state = tmp_path / "gh-state"
        self.state.mkdir()
        self.gh = tmp_path / "bin" / "gh"
        self.gh.parent.mkdir()
        source = FAKE_GH.read_text(encoding="utf-8")
        self.gh.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        self.gh.chmod(0o755)
        monkeypatch.setenv("FAKE_GH_STATE", str(self.state))
        self.scenario = good_scenario(directory)
        self.sleeps: list[float] = []
        self.now = 1000.0
        self.lines: list[str] = []

    def write(self) -> None:
        (self.state / "scenario.json").write_text(json.dumps(self.scenario), encoding="utf-8")

    def calls(self) -> list[list[str]]:
        path = self.state / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def verifier(self, **overrides: Any) -> ver.Verifier:
        self.write()
        options: dict[str, Any] = {
            "repo": ver.PINNED_REPO, "signer_workflow": ver.PINNED_SIGNER_WORKFLOW, "source_digest": SOURCE,
            "sleep": self.sleep, "clock": self.clock, "out": self.lines.append,
        }
        options.update(overrides)
        return ver.Verifier(self.gh, **options)

    def verify(self, **overrides: Any) -> int:
        return self.verifier(**overrides).verify_bundle(self.directory, VERSION)


@pytest.fixture
def world(tmp_path: Path, assets: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, assets, monkeypatch)


# --- subjects: positive ----------------------------------------------------------------------------------------


def test_twelve_subjects_are_derived_from_the_final_manifest(assets: Path) -> None:
    bundle = prep.prepare(assets, VERSION)
    assert [e.family_id for e in bundle.packages] == ["wheel", "sdist", "deb", "rpm", "freebsd_pkg"]
    names = [s.name for s in bundle.all_subjects()]
    assert len(names) == len(set(names)) == prep.SUBJECT_COUNT == 12
    assert len(bundle.manifest_subjects()) == 11 and bundle.evidence.name == "REPRODUCIBILITY.json"
    assert bundle.evidence.sha256 == sha((assets / "REPRODUCIBILITY.json").read_bytes())
    assert names[-1] == "SHA256SUMS" and "SHA256SUMS" not in names[:-1]
    assert bundle.checksums.sha256 == sha((assets / "SHA256SUMS").read_bytes())
    for entry in bundle.packages:
        assert entry.sbom.name == entry.package.name + ".spdx.json"
        assert entry.package.sha256 == sha((assets / entry.package.name).read_bytes())


def test_step_outputs_are_deterministic_and_complete(assets: Path) -> None:
    first = prep.outputs(prep.prepare(assets, VERSION), assets)
    assert first == prep.outputs(prep.prepare(assets, VERSION), assets)
    expected = {f"{f}_{k}" for f in ("wheel", "sdist", "deb", "rpm", "freebsd_pkg") for k in ("name", "sha256", "sbom_path")}
    assert set(first) == expected | {
        "checksums_name", "checksums_sha256", "evidence_name", "evidence_sha256", "subject_count",
    }
    assert first["checksums_name"] == "SHA256SUMS" and first["subject_count"] == "12"
    assert first["evidence_name"] == "REPRODUCIBILITY.json"
    assert first["wheel_sbom_path"] == f"{assets.as_posix()}/pysh_shell-{VERSION}-py3-none-any.whl.spdx.json"
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for k, v in first.items() if k.endswith("_sha256"))


def test_the_helper_cli_appends_to_github_output(assets: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "github_output"
    out.write_text("earlier=1\n", encoding="utf-8")
    assert prep.main(["--assets-dir", str(assets), "--version", VERSION, "--github-output", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "earlier=1" and "checksums_name=SHA256SUMS" in lines
    assert prep.main(["--assets-dir", str(assets), "--version", VERSION]) == 0
    assert "deb_name=pysh-shell_9.8.7-1_all.deb" in capsys.readouterr().out


# --- subjects: negative -------------------------------------------------------------------------------------------


def edit_manifest(directory: Path, transform) -> None:
    path = directory / "SHA256SUMS"
    path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")


def test_a_manifest_that_lists_itself_is_rejected(assets: Path) -> None:
    edit_manifest(assets, lambda t: t + f"{'a' * 64}  SHA256SUMS\n")
    with pytest.raises(prep.SubjectError, match="must not list itself"):
        prep.prepare(assets, VERSION)


def test_a_subject_basename_with_a_directory_is_rejected(assets: Path) -> None:
    edit_manifest(assets, lambda t: t.replace("  pysh-shell_", "  dist/os/pysh-shell_", 1))
    with pytest.raises(prep.SubjectError):
        prep.prepare(assets, VERSION)
    with pytest.raises(prep.SubjectError, match="plain basename"):
        prep.check_basename("../x")
    with pytest.raises(prep.SubjectError, match="plain basename"):
        prep.check_basename("/abs")


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_a_bad_sha256_is_rejected(assets: Path, bad: str) -> None:
    edit_manifest(assets, lambda t: bad + t[64:] if bad else t[64:])
    with pytest.raises(prep.SubjectError):
        prep.prepare(assets, VERSION)


def test_a_duplicate_subject_is_rejected() -> None:
    text = f"{'a' * 64}  one.whl\n{'b' * 64}  one.whl\n"
    with pytest.raises(prep.SubjectError, match="duplicate subject"):
        prep.parse_manifest(text)


def test_a_missing_family_is_rejected(assets: Path) -> None:
    for path in assets.glob("*.rpm*"):
        path.unlink()
    write_manifest(assets)
    with pytest.raises(prep.SubjectError, match="missing mandatory rpm"):
        prep.prepare(assets, VERSION)


def test_a_missing_sbom_subject_is_rejected(assets: Path) -> None:
    edit_manifest(assets, lambda t: "".join(line for line in t.splitlines(keepends=True) if ".whl.spdx.json" not in line))
    with pytest.raises(prep.SubjectError, match="must cover every published file"):
        prep.prepare(assets, VERSION)


def test_an_unknown_release_subject_is_rejected(assets: Path) -> None:
    (assets / "notes.txt").write_text("x", encoding="utf-8")
    write_manifest(assets)
    with pytest.raises(prep.SubjectError, match="unknown release subjects"):
        prep.prepare(assets, VERSION)


def test_a_file_changed_after_the_manifest_was_written_is_rejected(assets: Path) -> None:
    (assets / f"pysh-shell-{VERSION}.pkg").write_bytes(b"tampered")
    with pytest.raises(prep.SubjectError, match="digest mismatch"):
        prep.prepare(assets, VERSION)


def test_the_helper_cli_reports_invalid_bundles(assets: Path, capsys) -> None:
    (assets / "SHA256SUMS").unlink()
    assert prep.main(["--assets-dir", str(assets), "--version", VERSION]) == 1
    assert "prepare_attestation_subjects:" in capsys.readouterr().err


# --- the published reproducibility evidence (Slice 4) -------------------------------------------------------------


def rewrite_evidence(directory: Path, document: dict) -> None:
    (directory / sboms.EVIDENCE).write_text(canonical_json(document), encoding="utf-8")
    write_manifest(directory)


def test_a_manifest_that_omits_the_published_evidence_is_rejected(assets: Path) -> None:
    edit_manifest(assets, lambda t: "".join(line for line in t.splitlines(keepends=True) if "REPRODUCIBILITY.json" not in line))
    with pytest.raises(prep.SubjectError, match="must cover every published file"):
        prep.prepare(assets, VERSION)


def test_the_evidence_must_be_listed_even_if_the_file_set_is_consistent(assets: Path) -> None:
    (assets / sboms.EVIDENCE).unlink()
    write_manifest(assets)
    with pytest.raises(prep.SubjectError, match="does not list the reproducibility evidence"):
        prep.prepare(assets, VERSION)


@pytest.mark.parametrize("blocked", ["rpm", "freebsd_pkg"])
def test_non_final_evidence_is_not_a_provenance_subject(assets: Path, blocked: str) -> None:
    from tests.repro_support import result

    document = final_document(version=VERSION, commit=SOURCE)
    document["results"] = [result(f, "PLATFORM_BLOCKED", version=VERSION, commit=SOURCE) if f == blocked else r
                           for f, r in zip(repro_checker.FAMILY_ORDER, document["results"], strict=True)]
    rewrite_evidence(assets, document)
    with pytest.raises(prep.SubjectError, match="not valid final evidence"):
        prep.prepare(assets, VERSION)


def test_evidence_for_another_source_commit_is_rejected(assets: Path) -> None:
    rewrite_evidence(assets, final_document(version=VERSION, commit="f" * 40))
    prep.prepare(assets, VERSION)  # self-consistent evidence is fine without a pin ...
    with pytest.raises(prep.SubjectError, match="does not match the expected commit"):
        prep.prepare(assets, VERSION, SOURCE)  # ... but must match the release commit when pinned


def test_the_verifier_binds_the_evidence_to_the_source_digest(world: World) -> None:
    rewrite_evidence(world.directory, final_document(version=VERSION, commit="f" * 40))
    world.scenario = good_scenario(world.directory)
    with pytest.raises(prep.SubjectError, match="does not match the expected commit"):
        world.verify()
    assert world.calls() == []


def test_provenance_that_omits_the_published_evidence_fails(world: World) -> None:
    digest = sha((world.directory / sboms.EVIDENCE).read_bytes())
    world.scenario["attestations"][0]["subjects"] = [
        s for s in world.scenario["attestations"][0]["subjects"] if s[1] != digest
    ]
    with pytest.raises(ver.AttestationError, match="partial subject set|no attestations found"):
        world.verify()


def test_a_stale_eleven_subject_provenance_set_fails(world: World) -> None:
    """The pre-evidence layout (five packages, five SBOMs, SHA256SUMS) is no longer enough."""
    world.scenario["attestations"] = [
        a for a in world.scenario["attestations"]
        if not any(s[0] == sboms.EVIDENCE for s in a["subjects"])
    ]
    with pytest.raises(ver.AttestationError):
        world.verify()


def test_the_evidence_itself_has_provenance_verified(world: World) -> None:
    world.verify()
    verified = [Path(c[2]).name for c in world.calls() if ver.PROVENANCE_PREDICATE_TYPE in c]
    assert sboms.EVIDENCE in verified and "SHA256SUMS" in verified
    spdx = [Path(c[2]).name for c in world.calls() if ver.SPDX_PREDICATE_TYPE in c]
    assert sboms.EVIDENCE not in spdx  # an SBOM attestation exists only for the five packages


def test_the_subject_counts_are_twelve_with_eleven_checksum_entries(assets: Path) -> None:
    assert prep.SUBJECT_COUNT == 12
    entries = (assets / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(entries) == 11 and not any(line.endswith("  SHA256SUMS") for line in entries)


# --- verification: positive --------------------------------------------------------------------------------------------


def test_all_twelve_provenance_and_five_sbom_attestations_are_verified(world: World) -> None:
    assert world.verify() == 12
    calls = world.calls()
    assert len(calls) == 17
    provenance = [c for c in calls if c[c.index("--predicate-type") + 1] == ver.PROVENANCE_PREDICATE_TYPE]
    spdx = [c for c in calls if c[c.index("--predicate-type") + 1] == ver.SPDX_PREDICATE_TYPE]
    assert len(provenance) == 12 and len(spdx) == 5
    assert {Path(c[2]).name for c in provenance} == {p.name for p in world.directory.iterdir()}
    assert {Path(c[2]).name for c in spdx} == {p.name for p in world.directory.iterdir() if not p.name.endswith(".spdx.json") and p.name not in {"SHA256SUMS", "REPRODUCIBILITY.json"}}
    assert sum(line.startswith("verified provenance:") for line in world.lines) == 12
    assert sum(line.startswith("verified SPDX SBOM attestation:") for line in world.lines) == 5


def test_every_call_pins_repo_signer_workflow_and_source_digest(world: World) -> None:
    world.verify()
    for call in world.calls():
        assert call[:2] == ["attestation", "verify"]
        flags = dict(zip(call[3::2], call[4::2], strict=True))
        assert flags["--repo"] == "SSobol77/pysh"
        assert flags["--signer-workflow"] == "SSobol77/pysh/.github/workflows/release-artifacts.yml"
        assert flags["--source-digest"] == SOURCE
        assert flags["--format"] == "json"
        assert flags["--predicate-type"] in {"https://slsa.dev/provenance/v1", "https://spdx.dev/Document/v2.3"}


def test_the_attested_sbom_is_compared_semantically_not_byte_for_byte(world: World) -> None:
    sbom = next(world.directory.glob("*.whl.spdx.json"))
    document = json.loads(sbom.read_text(encoding="utf-8"))
    sbom.write_text(json.dumps(dict(reversed(list(document.items()))), indent=4), encoding="utf-8")
    write_manifest(world.directory)
    world.scenario = good_scenario(world.directory)
    for attestation in world.scenario["attestations"]:
        if attestation["predicateType"] == ver.SPDX_PREDICATE_TYPE and attestation["subjects"][0][0].endswith(".whl"):
            attestation["predicate"] = document  # the attested document has different key order
    assert world.verify() == 12


def test_a_bounded_consistency_retry_can_succeed(world: World) -> None:
    wheel = f"pysh_shell-{VERSION}-py3-none-any.whl"
    world.scenario["hidden"] = {wheel: 2}
    assert world.verify() == 12
    wheel_calls = [c for c in world.calls() if Path(c[2]).name == wheel and ver.PROVENANCE_PREDICATE_TYPE in c]
    assert len(wheel_calls) == 3
    # the wheel is queried twice (provenance and SPDX), each answer hidden twice
    assert world.sleeps == [ver.RETRY_DELAY_SECONDS] * 4
    assert any("not visible yet" in line for line in world.lines)


def test_the_cli_passes_with_an_explicit_gh_and_verifies_before_returning(world: World, capsys) -> None:
    world.write()
    code = ver.main(["--assets-dir", str(world.directory), "--version", VERSION, "--source-digest", SOURCE, "--gh", str(world.gh)])
    assert code == 0 and "PASS: 12 provenance attestations and 5 SPDX SBOM attestations" in capsys.readouterr().out


def test_the_cli_defaults_the_pinned_identities(world: World) -> None:
    world.write()
    assert ver.main(["--assets-dir", str(world.directory), "--version", VERSION, "--source-digest", SOURCE,
                     "--gh", str(world.gh), "--repo", "SSobol77/pysh",
                     "--signer-workflow", "SSobol77/pysh/.github/workflows/release-artifacts.yml"]) == 0


# --- verification: identity pins -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags",
    [
        ["--repo", "attacker/pysh"],
        ["--repo", "SSobol77/pysh-fork"],
        ["--signer-workflow", "SSobol77/pysh/.github/workflows/ci.yml"],
        ["--signer-workflow", "attacker/pysh/.github/workflows/release-artifacts.yml"],
        ["--source-digest", "main"],
        ["--source-digest", "ABCDEF0123456789ABCDEF0123456789ABCDEF01"],
        ["--source-digest", "abc"],
    ],
)
def test_the_cli_refuses_other_identities_before_calling_gh(world: World, flags: list[str], capsys) -> None:
    base = ["--assets-dir", str(world.directory), "--version", VERSION, "--source-digest", SOURCE, "--gh", str(world.gh)]
    world.write()
    assert ver.main([*base, *flags]) == 2
    assert world.calls() == []
    assert "verify_release_attestations:" in capsys.readouterr().err


def test_a_relative_or_missing_gh_is_a_usage_or_verification_error(world: World, capsys) -> None:
    base = ["--assets-dir", str(world.directory), "--version", VERSION, "--source-digest", SOURCE]
    assert ver.main([*base, "--gh", "gh"]) == 2
    assert ver.main([*base, "--gh", str(world.gh.parent / "absent")]) == 1
    assert "cannot execute the GitHub CLI" in capsys.readouterr().err


def test_an_attestation_for_another_repository_fails_without_retry(world: World) -> None:
    for attestation in world.scenario["attestations"]:
        attestation["repo"] = "attacker/pysh"
    with pytest.raises(ver.AttestationError, match="certificate"):
        world.verify()
    assert len(world.calls()) == 1 and world.sleeps == []


def test_an_attestation_from_another_signer_workflow_fails_without_retry(world: World) -> None:
    for attestation in world.scenario["attestations"]:
        attestation["workflow"] = "SSobol77/pysh/.github/workflows/ci.yml"
    with pytest.raises(ver.AttestationError, match="failed to verify certificate identity"):
        world.verify()
    assert len(world.calls()) == 1 and world.sleeps == []


def test_an_attestation_for_another_source_commit_fails_without_retry(world: World) -> None:
    for attestation in world.scenario["attestations"]:
        attestation["source_digest"] = OTHER_SOURCE
    with pytest.raises(ver.AttestationError, match="failed to verify certificate identity"):
        world.verify()
    assert len(world.calls()) == 1 and world.sleeps == []


def test_an_invalid_signature_fails_without_retry(world: World) -> None:
    world.scenario["attestations"][0]["invalid_signature"] = True
    with pytest.raises(ver.AttestationError, match="invalid signature"):
        world.verify()
    assert len(world.calls()) == 1 and world.sleeps == []


# --- verification: missing / partial / mismatching evidence -------------------------------------------------------------------------


def test_a_missing_package_provenance_fails(world: World) -> None:
    deb = f"pysh-shell_{VERSION}-1_all.deb"
    digest = sha((world.directory / deb).read_bytes())
    for attestation in world.scenario["attestations"]:
        attestation["subjects"] = [s for s in attestation["subjects"] if s[1] != digest]
    with pytest.raises(ver.AttestationError, match=r"\(provenance\)"):
        world.verify()


def test_a_missing_sha256sums_provenance_fails(world: World) -> None:
    checksums = sha((world.directory / "SHA256SUMS").read_bytes())
    world.scenario["attestations"] = [
        a for a in world.scenario["attestations"] if not any(s[1] == checksums for s in a["subjects"])
    ]
    with pytest.raises(ver.AttestationError, match=r"SHA256SUMS \(provenance\)"):
        world.verify()


def test_a_missing_sbom_attestation_fails_after_bounded_retries(world: World) -> None:
    rpm = f"pysh-shell-{VERSION}-1.noarch.rpm"
    world.scenario["attestations"] = [
        a for a in world.scenario["attestations"]
        if not (a["predicateType"] == ver.SPDX_PREDICATE_TYPE and a["subjects"][0][0] == rpm)
    ]
    with pytest.raises(ver.AttestationError, match=r"\(SPDX SBOM\).*no attestations found"):
        world.verify()
    spdx_calls = [c for c in world.calls() if Path(c[2]).name == rpm and ver.SPDX_PREDICATE_TYPE in c]
    assert len(spdx_calls) == ver.MAX_ATTEMPTS
    assert world.sleeps == [ver.RETRY_DELAY_SECONDS] * (ver.MAX_ATTEMPTS - 1)


def test_a_partial_provenance_subject_set_fails(world: World) -> None:
    manifest_statement = world.scenario["attestations"][0]
    manifest_statement["subjects"] = manifest_statement["subjects"][:-1]  # nine of the ten manifest subjects
    with pytest.raises(ver.AttestationError, match="partial subject set|no attestations found"):
        world.verify()


def test_a_complete_but_wrong_subject_set_is_a_partial_set(world: World) -> None:
    world.scenario["attestations"][0]["subjects"][0][0] = "renamed.whl"
    with pytest.raises(ver.AttestationError, match="subject mismatch|partial subject set"):
        world.verify()


def test_a_package_attested_against_another_sbom_pair_fails(world: World) -> None:
    sboms_by_family = [a for a in world.scenario["attestations"] if a["predicateType"] == ver.SPDX_PREDICATE_TYPE]
    sboms_by_family[0]["predicate"], sboms_by_family[1]["predicate"] = sboms_by_family[1]["predicate"], sboms_by_family[0]["predicate"]
    with pytest.raises(ver.AttestationError, match="attested predicate differs"):
        world.verify()


def test_a_verified_predicate_that_differs_from_the_local_sbom_fails(world: World) -> None:
    sbom = next(a for a in world.scenario["attestations"] if a["predicateType"] == ver.SPDX_PREDICATE_TYPE)
    sbom["predicate"] = {**sbom["predicate"], "extra": "tampered"}
    with pytest.raises(ver.AttestationError, match="attested predicate differs from the published"):
        world.verify()


def test_a_local_sbom_edited_after_attestation_fails(world: World) -> None:
    sbom = next(world.directory.glob("*.deb.spdx.json"))
    sbom.write_text(sbom.read_text(encoding="utf-8").replace("SPDX-2.3", "SPDX-2.4"), encoding="utf-8")
    with pytest.raises(prep.SubjectError, match="digest mismatch"):
        world.verify()  # SHA256SUMS no longer matches the file, before gh is asked anything
    assert world.calls() == []


def test_malformed_gh_json_fails(world: World) -> None:
    world.scenario["malformed"] = [f"pysh-shell_{VERSION}-1_all.deb"]
    with pytest.raises(ver.AttestationError, match="malformed gh JSON"):
        world.verify()


@pytest.mark.parametrize("output", ["[]", "{}", "[1]", '[{"verificationResult": {}}]', '[{"verificationResult": {"statement": []}}]', ""])
def test_unexpected_gh_json_shapes_fail_closed(output: str) -> None:
    with pytest.raises(ver.AttestationError, match="malformed gh JSON"):
        ver.parse_results("x", output)


def statement(predicate_type: str, name: str, digest: str) -> dict[str, Any]:
    return {"predicateType": predicate_type, "subject": [{"name": name, "digest": {"sha256": digest}}], "predicate": {}}


def test_a_statement_with_the_wrong_predicate_type_or_subject_fails() -> None:
    good = statement(ver.SPDX_PREDICATE_TYPE, "a.whl", "a" * 64)
    ver.check_statement("x", good, ver.SPDX_PREDICATE_TYPE, "a.whl", "a" * 64)
    with pytest.raises(ver.AttestationError, match="wrong predicate type"):
        ver.check_statement("x", good, ver.PROVENANCE_PREDICATE_TYPE, "a.whl", "a" * 64)
    with pytest.raises(ver.AttestationError, match="subject mismatch"):
        ver.check_statement("x", good, ver.SPDX_PREDICATE_TYPE, "b.whl", "a" * 64)
    with pytest.raises(ver.AttestationError, match="subject mismatch"):
        ver.check_statement("x", good, ver.SPDX_PREDICATE_TYPE, "a.whl", "b" * 64)


def test_a_runner_answer_with_the_wrong_predicate_type_fails(world: World) -> None:
    world.write()
    verifier = world.verifier(runner=lambda argv: ver.GhResult(0, json.dumps([{
        "verificationResult": {"statement": statement("https://spdx.dev/Document/v2.2", Path(argv[3]).name, "0" * 64)},
    }]), ""))
    with pytest.raises(ver.AttestationError, match="wrong predicate type"):
        verifier.verify_bundle(world.directory, VERSION)


# --- verification: bounded consistency retry -----------------------------------------------------------------------------------------------


def test_the_retry_policy_is_finite() -> None:
    assert 1 <= ver.MAX_ATTEMPTS <= 10
    assert 0 < ver.RETRY_DELAY_SECONDS <= 30
    assert ver.MAX_ATTEMPTS * ver.RETRY_DELAY_SECONDS <= 300
    assert 0 < ver.MAX_RETRY_WALL_SECONDS <= 300
    assert ver.GH_TIMEOUT_SECONDS <= 300
    assert re.search(ver.NOT_VISIBLE_PATTERN, "Error: no attestations found for subject sha256:x", re.I)
    for text in ("failed to verify signature", "failed to verify certificate identity", "no attestations were verified"):
        assert re.search(ver.NOT_VISIBLE_PATTERN, text, re.I) is None


def test_the_shared_wall_clock_budget_stops_retries_early(world: World) -> None:
    world.scenario["attestations"] = []
    verifier = world.verifier()
    world.now += ver.MAX_RETRY_WALL_SECONDS  # the budget is already spent
    with pytest.raises(ver.AttestationError, match="no attestations found"):
        verifier.verify_bundle(world.directory, VERSION)
    assert len(world.calls()) == 1 and world.sleeps == []


def test_a_retry_never_turns_a_failure_into_a_pass(world: World) -> None:
    world.scenario["attestations"] = []
    with pytest.raises(ver.AttestationError):
        world.verify()


def test_a_hanging_or_unrunnable_gh_is_a_deterministic_failure(world: World) -> None:
    world.write()

    def hang(argv):
        raise ver.AttestationError("the GitHub CLI timed out after 120s")

    with pytest.raises(ver.AttestationError, match="timed out"):
        world.verifier(runner=hang).verify_bundle(world.directory, VERSION)


# --- verifier source properties ---------------------------------------------------------------------------------------------------------------------


def code_of(name: str) -> str:
    source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))


def test_the_verifier_has_no_signing_logic_shell_or_unbounded_loop() -> None:
    code = code_of("verify_release_attestations.py")
    assert "shell=True" not in code and "os.system" not in code
    assert not re.search(r"cosign|sigstore|gpg|private[_ ]key|attestation\", \"(?:create|sign)|attest-build", code, re.I)
    assert "while True" not in code and not re.search(r"\bwhile\b", code)
    tree = ast.parse(code)
    assert not any(isinstance(n, ast.While) for n in ast.walk(tree))
    assert 'PINNED_REPO = "SSobol77/pysh"' in code
    assert 'PINNED_SIGNER_WORKFLOW = "SSobol77/pysh/.github/workflows/release-artifacts.yml"' in code
    assert 'SPDX_PREDICATE_TYPE = "https://spdx.dev/Document/v2.3"' in code


def test_the_helpers_are_stdlib_only_offline_and_read_only() -> None:
    for name in ("prepare_attestation_subjects.py", "verify_release_attestations.py"):
        tree = ast.parse(code_of(name))
        imported = {
            (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
            for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (n.names if isinstance(n, ast.Import) else [None])
        }
        assert not imported & {"requests", "urllib", "socket", "http", "yaml", "cryptography", "sigstore", "gnupg"}
    assert "subprocess" not in code_of("prepare_attestation_subjects.py")
    assert ".write_text(" not in code_of("prepare_attestation_subjects.py")
    assert ".write_bytes(" not in code_of("verify_release_attestations.py")
