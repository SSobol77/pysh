# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_supply_chain_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #51 Slices 1-4: the repository-owned supply-chain contract and its checker.

Hermetic: no network, GitHub CLI, Docker, FreeBSD, signing or SBOM tool. Negative
cases mutate a temporary copy of the real documents, scripts and workflows.
"""
from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

import pytest

from scripts import check_supply_chain_contract as contract

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = Path("docs/security/supply-chain.md")
PACKAGING = Path("docs/development/packaging.md")
RELEASE_WF = Path(".github/workflows/release-artifacts.yml")
PUBLISH_WF = Path(".github/workflows/publish.yml")
SBOM_GENERATOR = Path("scripts/generate_release_sboms.py")
SUBJECT_HELPER = Path("scripts/prepare_attestation_subjects.py")
VERIFIER = Path("scripts/verify_release_attestations.py")
HARNESS = Path("scripts/measure_release_reproducibility.py")
EVIDENCE_VALIDATOR = Path("scripts/check_reproducibility_evidence.py")
ATTEST_SHA = "1e69f48acb82d1966a394da916b4c1698aa569d6"
ATTEST_USES = f"actions/attest@{ATTEST_SHA} # actions/attest v4.2.2"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of just the files the checker reads."""
    for relative in (
        DOC, PACKAGING, Path("scripts/check_release_artifacts.sh"), SBOM_GENERATOR, SUBJECT_HELPER, VERIFIER,
        HARNESS, EVIDENCE_VALIDATOR, Path("scripts/build_rpm.sh"),
        Path("pyproject.toml"), Path("uv.lock"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, target)
    shutil.copytree(REPO_ROOT / ".github" / "workflows", tmp_path / ".github" / "workflows")
    return tmp_path


def edit(root: Path, relative: Path, old: str, new: str, *, count: int = 1) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= 1, f"fixture drift: {old!r} not found in {relative}"
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def codes(root: Path) -> set[str]:
    return {v.code for v in contract.run_checks(root)}


# --- positive ---------------------------------------------------------------------------------


def test_the_real_repository_satisfies_the_contract() -> None:
    assert contract.run_checks(REPO_ROOT) == []


def test_slice_four_reports_reproducibility_implemented_and_only_the_final_evidence_deferred(repo: Path) -> None:
    assert contract.run_checks(repo) == []
    assert contract.future_status(repo) == [
        "implemented: SPDX 2.3 JSON SBOM generation (Slice 2)",
        "implemented: keyless provenance and SPDX SBOM attestations, verified before upload (Slice 3)",
        "implemented: per-artifact reproducibility measurement and evidence (Slice 4)",
        "deferred: final Tier-1 dry-run release evidence (Slice 5): not yet implemented",
    ]


def test_the_deferred_final_evidence_being_present_never_fails_the_checker(repo: Path) -> None:
    """The Slice 5 item is reported, not enforced."""
    extra = repo / ".github" / "workflows" / "future-final.yml"
    extra.write_text(
        "name: future\non: workflow_dispatch\npermissions:\n  contents: read\njobs:\n  final:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: echo tier-1 evidence\n",
        encoding="utf-8",
    )
    assert contract.run_checks(repo) == []
    assert contract.future_status(repo)[-1].endswith("present")


def test_the_artifact_family_model_matches_the_documents() -> None:
    ids = [f.family_id for f in contract.FAMILIES]
    assert ids == ["wheel", "sdist", "deb", "rpm", "freebsd_pkg", "checksums"]
    sbom = {f.family_id for f in contract.FAMILIES if f.requires_sbom}
    assert sbom == {"wheel", "sdist", "deb", "rpm", "freebsd_pkg"}
    assert all(f.requires_provenance for f in contract.FAMILIES)
    assert {f.family_id for f in contract.FAMILIES if f.reproducibility_required} == sbom
    text = (REPO_ROOT / DOC).read_text(encoding="utf-8")
    rows = contract._table_rows(contract.split_sections(text)["PYSH-SC-ARTIFACTS"])
    assert list(rows) == ids


def test_required_anchors_and_reproducibility_statuses_are_exact() -> None:
    assert len(contract.REQUIRED_ANCHORS) == len(set(contract.REQUIRED_ANCHORS)) == 14
    assert contract.REPRODUCIBILITY_STATUSES == {
        "REPRODUCIBLE", "NON_REPRODUCIBLE", "NOT_YET_MEASURED", "PLATFORM_BLOCKED",
    }
    assert contract.REPOSITORY_IDENTITY == "SSobol77/pysh"
    text = (REPO_ROOT / DOC).read_text(encoding="utf-8")
    sections = contract.split_sections(text)
    assert set(sections) == set(contract.REQUIRED_ANCHORS)
    # Version-specific file names belong to packaging, not to this policy.
    assert not re.search(r"\bX\.Y\.Z\b|pysh[-_]shell[-_]", text)


def test_the_policy_status_table_marks_slices_one_to_four_implemented() -> None:
    text = " ".join((REPO_ROOT / DOC).read_text(encoding="utf-8").split())
    assert "Policy, anchors and structural contract check | IMPLEMENTED (Slice 1)" in text
    assert "SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2)" in text
    assert "SBOM attestations, verified before upload | IMPLEMENTED (Slice 3)" in text
    assert "Reproducibility measurement | IMPLEMENTED (Slice 4)" in text
    assert "Final Tier-1 dry-run release evidence | DEFERRED (Slice 5)" in text
    assert "Not implemented" not in text


def test_the_checker_is_stdlib_only_offline_and_read_only() -> None:
    tree = ast.parse((REPO_ROOT / "scripts" / "check_supply_chain_contract.py").read_text(encoding="utf-8"))
    imported = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])
        if not (isinstance(n, ast.Import) and a is None)
    }
    assert not imported & {"subprocess", "socket", "urllib", "http", "requests", "yaml", "shutil", "os"}
    source = (REPO_ROOT / "scripts" / "check_supply_chain_contract.py").read_text(encoding="utf-8")
    assert ".write_text(" not in source and ".write_bytes(" not in source and "open(" not in source


def test_exit_code_contract(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert contract.main(["--root", str(repo)]) == 0
    out = capsys.readouterr()
    assert "supply-chain contract: PASS" in out.out and out.err == ""
    edit(repo, DOC, 'id="PYSH-SC-SBOM"', 'id="PYSH-SC-GONE"')
    assert contract.main(["--root", str(repo)]) == 1
    assert "supply-chain contract: FAIL [DOC-ANCHOR]" in capsys.readouterr().err
    with pytest.raises(SystemExit) as misuse:
        contract.main(["--no-such-option"])
    assert misuse.value.code == 2


def test_diagnostics_are_deterministic_and_sorted(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit(repo, DOC, 'id="PYSH-SC-SBOM"', 'id="PYSH-SC-GONE"')
    edit(repo, DOC, "--repo SSobol77/pysh", "--repo evil/pysh")
    edit(repo, PACKAGING, ".rpm", ".rp")
    runs = []
    for _ in range(2):
        contract.main(["--root", str(repo)])
        runs.append(capsys.readouterr().err)
    assert runs[0] == runs[1] != ""
    violations = contract.run_checks(repo)
    assert violations == sorted(violations) and len(violations) == len(set(violations))


def test_release_gate_runs_the_checker_without_reimplementing_it() -> None:
    gate = (REPO_ROOT / "scripts" / "release_gate.py").read_text(encoding="utf-8")
    assert "check_supply_chain_contract.py" in gate
    for logic in ("REQUIRED_ANCHORS", "RELEASE_UPLOAD_PATTERNS", "FAMILIES", "split_jobs"):
        assert logic not in gate


def test_headers_follow_repository_conventions() -> None:
    assert (REPO_ROOT / "scripts" / "check_supply_chain_contract.py").read_text(encoding="utf-8").startswith(
        "#!/usr/bin/env python3\n# SPDX-License-Identifier: GPL-2.0-only\n# File: scripts/check_supply_chain_contract.py\n"
    )
    assert (REPO_ROOT / DOC).read_text(encoding="utf-8").startswith("<!--\nSPDX-License-Identifier: GPL-2.0-only")


# --- negative: documentation --------------------------------------------------------------------


def test_missing_supply_chain_document_fails(repo: Path) -> None:
    (repo / DOC).unlink()
    assert "DOC-MISSING" in codes(repo)


@pytest.mark.parametrize("anchor", contract.REQUIRED_ANCHORS)
def test_every_missing_anchor_fails(repo: Path, anchor: str) -> None:
    edit(repo, DOC, f'<a id="{anchor}"></a>', "")
    assert "DOC-ANCHOR" in codes(repo)


def test_a_duplicated_anchor_fails(repo: Path) -> None:
    edit(repo, DOC, '<a id="PYSH-SC-SBOM"></a>', '<a id="PYSH-SC-SBOM"></a>\n<a id="PYSH-SC-SBOM"></a>')
    assert "DOC-ANCHOR" in codes(repo)


@pytest.mark.parametrize("family_row", ["`wheel`", "`sdist`", "`deb`", "`rpm`", "`freebsd_pkg`", "`checksums`"])
def test_a_missing_mandatory_artifact_family_fails(repo: Path, family_row: str) -> None:
    text = (repo / DOC).read_text(encoding="utf-8")
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(f"| {family_row}") or line.startswith("| `SHA256SUMS`") and family_row == "`checksums`")
    # remove the first (artifact-table) occurrence only
    del lines[index]
    (repo / DOC).write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "DOC-ARTIFACT-FAMILY" in codes(repo)


def test_an_unknown_artifact_family_fails(repo: Path) -> None:
    edit(repo, DOC, "| `checksums` |", "| `snap` | Snap package (`.snap`) | required | required |\n| `checksums` |")
    assert "DOC-ARTIFACT-FAMILY" in codes(repo)


def test_family_flags_must_agree_with_the_model(repo: Path) -> None:
    edit(repo, DOC, "| `wheel` | PyPI wheel (`.whl`) | required | required |", "| `wheel` | PyPI wheel (`.whl`) | not applicable | required |")
    assert "DOC-FAMILY-FLAGS" in codes(repo)


def test_incomplete_or_invalid_reproducibility_matrix_fails(repo: Path) -> None:
    edit(repo, DOC, "| `deb` | controlled Debian builder | NOT_YET_MEASURED |\n", "")
    assert "DOC-REPRODUCIBILITY" in codes(repo)


def test_an_invalid_reproducibility_status_fails(repo: Path) -> None:
    edit(repo, DOC, "| `rpm` | controlled Fedora/RPM builder | NOT_YET_MEASURED |", "| `rpm` | controlled Fedora/RPM builder | MOSTLY_REPRODUCIBLE |")
    assert "DOC-REPRODUCIBILITY" in codes(repo)


def test_a_missing_reproducibility_status_definition_fails(repo: Path) -> None:
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8").replace("`PLATFORM_BLOCKED`", "PLATFORM_BLOCKED"), encoding="utf-8")
    assert "DOC-REPRODUCIBILITY" in codes(repo)


@pytest.mark.parametrize(
    "line",
    [
        "- missing verification material -> DENY\n",
        "- invalid signature or attestation -> DENY\n",
        "- unexpected signer or repository identity -> DENY\n",
        "- subject or digest mismatch -> DENY\n",
    ],
)
def test_missing_fail_closed_rules_fail(repo: Path, line: str) -> None:
    edit(repo, DOC, line, "")
    assert "DOC-FAIL-CLOSED" in codes(repo)


def test_a_fail_open_rule_fails(repo: Path) -> None:
    edit(repo, DOC, "- missing verification material -> DENY", "- missing verification material -> ALLOW")
    assert "DOC-FAIL-CLOSED" in codes(repo)


def test_a_wrong_repository_verification_identity_fails(repo: Path) -> None:
    edit(repo, DOC, "--repo SSobol77/pysh", "--repo someone-else/pysh")
    assert "DOC-IDENTITY" in codes(repo)


def test_provenance_must_bind_the_repository_identity(repo: Path) -> None:
    section = contract.split_sections((repo / DOC).read_text(encoding="utf-8"))["PYSH-SC-PROVENANCE"]
    edit(repo, DOC, section, section.replace("SSobol77/pysh", "the repository"))
    assert "DOC-IDENTITY" in codes(repo)


@pytest.mark.parametrize(
    "sentence",
    [
        "\nRelease signing requires a long-lived private key stored in GitHub Secrets.\n",
        "\nThe workflow reads `secrets.COSIGN_PRIVATE_KEY` to sign every artifact.\n",
        "\nSigning requires a maintainer-held private key kept on a workstation.\n",
    ],
)
def test_a_private_key_or_signing_secret_requirement_fails(repo: Path, sentence: str) -> None:
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8") + sentence, encoding="utf-8")
    assert "DOC-KEYS" in codes(repo)


def test_the_trust_model_must_state_the_key_prohibition(repo: Path) -> None:
    edit(repo, DOC, "There\nis no long-lived private signing key", "There\nis a signing identity")
    assert "DOC-KEYS" in codes(repo)


def test_a_missing_future_pipeline_ordering_contract_fails(repo: Path) -> None:
    edit(repo, DOC, "4. SBOM generation\n5. reproducibility evidence (A/B measurement, combined into `REPRODUCIBILITY.json`)\n6. SHA256SUMS finalization\n", "")
    assert "DOC-PIPELINE" in codes(repo)


def test_a_reordered_pipeline_fails(repo: Path) -> None:
    edit(repo, DOC, "8. provenance and attestation generation\n9. attestation verification against the exact subjects\n10. upload of the validated release bundle", "8. upload of the validated release bundle\n9. provenance and attestation generation\n10. attestation verification against the exact subjects")
    assert "DOC-PIPELINE" in codes(repo)


def test_overclaiming_that_implementation_exists_fails(repo: Path) -> None:
    edit(repo, DOC, "is implemented in a later\nslice", "is implemented")
    assert "DOC-PIPELINE" in codes(repo)


def test_ecosystem_default_deny_and_trust_root_policy_are_required(repo: Path) -> None:
    edit(repo, DOC, "**default-deny**", "**optional**")
    assert "DOC-ECOSYSTEM" in codes(repo)
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8").replace("ffline", "therwise"), encoding="utf-8")
    assert "DOC-TRUST-ROOT" in codes(repo)


# --- negative: packaging agreement ---------------------------------------------------------------


def test_a_packaging_and_supply_chain_family_mismatch_fails(repo: Path) -> None:
    text = (repo / PACKAGING).read_text(encoding="utf-8").replace(".rpm", ".package")
    (repo / PACKAGING).write_text(text, encoding="utf-8")
    assert "PKG-FAMILY" in codes(repo)


def test_the_artifact_name_owner_must_still_cover_every_family(repo: Path) -> None:
    owner = repo / "scripts" / "check_release_artifacts.sh"
    owner.write_text(owner.read_text(encoding="utf-8").replace(".pkg", ".packg"), encoding="utf-8")
    assert "PKG-FAMILY" in codes(repo)


# --- negative: release workflow ------------------------------------------------------------------


def test_upload_that_no_longer_depends_on_validation_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "    needs: build-and-validate\n    if: github.event_name == 'release'", "    needs: freebsd-pkg\n    if: github.event_name == 'release'")
    assert "WF-RELEASE-GRAPH" in codes(repo)


def test_upload_without_the_release_gate_fails(repo: Path) -> None:
    edit(
        repo, RELEASE_WF,
        "    needs: build-and-validate\n    if: github.event_name == 'release'\n",
        "    needs: build-and-validate\n",
    )
    assert "WF-UPLOAD-GATED" in codes(repo)


def test_a_broken_validation_dependency_chain_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "    needs: freebsd-pkg\n", "")
    assert "WF-RELEASE-GRAPH" in codes(repo)


def test_a_missing_staging_handoff_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "          name: release-assets\n          path: dist/release-assets/*", "          name: other\n          path: dist/other/*")
    assert "WF-STAGING" in codes(repo)


def test_release_upload_before_validation_fails(repo: Path) -> None:
    # The upload moves into the validation job, before the artifact is handed over.
    edit(repo, RELEASE_WF, "      - name: Upload validated release assets for the upload job", "      - name: early\n        run: gh release upload v1 dist/release-assets/*\n\n      - name: Upload validated release assets for the upload job")
    assert "WF-UPLOAD-BYPASS" in codes(repo)


def test_release_upload_command_before_the_artifact_download_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      - name: Download validated release assets\n", "      - name: premature\n        run: gh release upload v1 x\n\n      - name: Download validated release assets\n")
    assert "WF-UPLOAD-ORDER" in codes(repo)


@pytest.mark.parametrize(
    "step",
    [
        "      - run: gh release upload v1 dist/*\n",
        "      - uses: softprops/action-gh-release@v2\n",
        "      - uses: actions/upload-release-asset@v1\n",
        "      - run: gh api repos/SSobol77/pysh/releases/1/assets -F file=@x\n",
    ],
)
def test_a_direct_release_upload_bypass_in_another_workflow_fails(repo: Path, step: str) -> None:
    (repo / ".github" / "workflows" / "sbom.yml").write_text(
        "name: sbom\non: workflow_dispatch\njobs:\n  generate:\n    runs-on: ubuntu-latest\n    steps:\n" + step,
        encoding="utf-8",
    )
    assert "WF-UPLOAD-BYPASS" in codes(repo)


def test_a_release_upload_in_a_second_job_of_the_release_workflow_fails(repo: Path) -> None:
    path = repo / RELEASE_WF
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n  attest:\n    runs-on: ubuntu-latest\n    needs: build-and-validate\n    steps:\n      - run: gh release upload v1 x\n",
        encoding="utf-8",
    )
    assert "WF-UPLOAD-BYPASS" in codes(repo)


def test_comments_mentioning_upload_commands_do_not_fail(repo: Path) -> None:
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# docs: never run gh release upload here\n", encoding="utf-8")
    assert contract.run_checks(repo) == []


# --- negative: PyPI publication -----------------------------------------------------------------


def test_removing_pypi_trusted_publishing_fails(repo: Path) -> None:
    edit(repo, PUBLISH_WF, "pypa/gh-action-pypi-publish@release/v1", "actions/noop@v1")
    assert "WF-PYPI" in codes(repo)


def test_removing_the_pypi_id_token_permission_fails(repo: Path) -> None:
    edit(repo, PUBLISH_WF, "  id-token: write\n", "")
    assert "WF-PYPI" in codes(repo)


def test_an_independent_twine_upload_publication_path_fails(repo: Path) -> None:
    (repo / ".github" / "workflows" / "legacy-publish.yml").write_text(
        "name: legacy\non: workflow_dispatch\njobs:\n  p:\n    runs-on: ubuntu-latest\n    steps:\n      - run: twine upload dist/*\n",
        encoding="utf-8",
    )
    assert "WF-PYPI" in codes(repo)


def test_a_second_pypi_publisher_or_token_credentials_fail(repo: Path) -> None:
    (repo / ".github" / "workflows" / "second.yml").write_text(
        "name: second\non: workflow_dispatch\njobs:\n  p:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: pypa/gh-action-pypi-publish@release/v1\n        with:\n          password: ${{ secrets.PYPI_API_TOKEN }}\n",
        encoding="utf-8",
    )
    messages = " ".join(v.message for v in contract.run_checks(repo))
    assert "second PyPI publisher" in messages and "token-based PyPI credentials" in messages


def test_twine_check_is_not_a_publication_path(repo: Path) -> None:
    # ci.yml and release-artifacts.yml legitimately run `twine check`.
    assert "twine check" in (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "WF-PYPI" not in codes(repo)


def test_a_signing_secret_in_any_workflow_fails(repo: Path) -> None:
    (repo / ".github" / "workflows" / "sign.yml").write_text(
        "name: sign\non: workflow_dispatch\njobs:\n  s:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: sign\n        env:\n          KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}\n",
        encoding="utf-8",
    )
    assert "WF-SECRETS" in codes(repo)


# --- Slice 2: SBOM implementation checks ------------------------------------------------------------


def test_a_missing_generator_fails(repo: Path) -> None:
    (repo / SBOM_GENERATOR).unlink()
    assert "SBOM-GENERATOR" in codes(repo)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('SYFT_VERSION = "', 'SYFT_VERSION_UNPINNED = "', "SBOM-PIN"),
        ('SYFT_LINUX_AMD64_SHA256 = "', 'SYFT_DIGEST_GONE = "', "SBOM-PIN"),
        ('SPDX_VERSION = "SPDX-2.3"', 'SPDX_VERSION = "SPDX-2.2"', "SBOM-FORMAT"),
        ('SBOM_SUFFIX = ".spdx.json"', 'SBOM_SUFFIX = ".sbom.json"', "SBOM-NAMING"),
        ("return artifact_basename + SBOM_SUFFIX", "return artifact_basename.lower() + SBOM_SUFFIX", "SBOM-NAMING"),
        ('Family("deb"', 'Family("debian"', "SBOM-FAMILIES"),
        ("must not list itself", "may list itself", "SBOM-CHECKSUMS"),
    ],
)
def test_generator_contract_violations_fail(repo: Path, old: str, new: str, code: str) -> None:
    edit(repo, SBOM_GENERATOR, old, new)
    assert code in codes(repo)


def test_a_mutable_tool_reference_or_shell_or_upload_in_the_generator_fails(repo: Path) -> None:
    path = repo / SBOM_GENERATOR
    path.write_text(path.read_text(encoding="utf-8") + '\nBAD = "https://github.com/anchore/syft/releases/latest"\n', encoding="utf-8")
    assert "SBOM-PIN" in codes(repo)
    path.write_text(path.read_text(encoding="utf-8") + '\nsubprocess.run("x", shell=True)\n', encoding="utf-8")
    assert "SBOM-GENERATOR" in codes(repo)
    path.write_text(path.read_text(encoding="utf-8") + '\nsubprocess.run(["gh", "release", "upload", "v1"])\n', encoding="utf-8")
    assert "WF-UPLOAD-BYPASS" in codes(repo)


def test_a_generator_comment_mentioning_upload_does_not_fail(repo: Path) -> None:
    path = repo / SBOM_GENERATOR
    path.write_text(path.read_text(encoding="utf-8") + "\n# never runs gh release upload\n", encoding="utf-8")
    assert contract.run_checks(repo) == []


@pytest.mark.parametrize(
    "step",
    [
        "generate_release_sboms.py fetch-syft",
        "generate_release_sboms.py generate",
        "generate_release_sboms.py validate --dir",
        "check_release_artifacts.sh --finalize-release-assets",
        "generate_release_sboms.py validate-bundle",
    ],
)
def test_a_missing_sbom_workflow_step_fails(repo: Path, step: str) -> None:
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(re.escape(step), "echo skipped", text), encoding="utf-8")
    assert "SBOM-WORKFLOW" in codes(repo)


def test_swapping_generate_and_finalize_is_an_ordering_violation(repo: Path) -> None:
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    text = text.replace("generate_release_sboms.py validate --dir", "@@V@@").replace(
        "check_release_artifacts.sh --finalize-release-assets", "generate_release_sboms.py validate --dir"
    ).replace("@@V@@", "check_release_artifacts.sh --finalize-release-assets")
    path.write_text(text, encoding="utf-8")
    assert "SBOM-WORKFLOW" in codes(repo)


def test_generating_from_a_directory_other_than_the_staged_assets_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--input dist/release-assets", "--input dist")
    assert "SBOM-WORKFLOW" in codes(repo)


def test_sbom_tooling_in_the_upload_job_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "gh release upload", "python scripts/generate_release_sboms.py generate\n          gh release upload")
    assert "SBOM-WORKFLOW" in codes(repo)


def test_an_unpinned_sbom_or_attestation_action_fails(repo: Path) -> None:
    extra = repo / ".github" / "workflows" / "sbom-action.yml"
    extra.write_text(
        "name: x\non: workflow_dispatch\njobs:\n  s:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: anchore/sbom-action@v0\n",
        encoding="utf-8",
    )
    assert "SBOM-PIN" in codes(repo)
    extra.write_text(extra.read_text(encoding="utf-8").replace("@v0", "@" + "b" * 40), encoding="utf-8")
    assert "SBOM-PIN" not in codes(repo)


def test_downloading_the_tool_outside_fetch_syft_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "python scripts/generate_release_sboms.py fetch-syft",
         "curl -sSfL https://example.invalid/anchore/syft.tar.gz -o x\n          python scripts/generate_release_sboms.py fetch-syft")
    assert "SBOM-PIN" in codes(repo)


def test_a_checksum_finalizer_that_hashes_itself_is_rejected_at_the_contract_level(repo: Path) -> None:
    edit(repo, Path("scripts/check_release_artifacts.sh"), "grep -vx SHA256SUMS", "cat")
    assert "SBOM-CHECKSUMS" in codes(repo)


def test_the_documented_checksum_policy_is_required(repo: Path) -> None:
    edit(repo, DOC, "every published release file except `SHA256SUMS` itself", "the package files")
    assert "SBOM-CHECKSUMS" in codes(repo)


def test_the_status_table_must_mark_sboms_implemented_and_the_rest_deferred(repo: Path) -> None:
    edit(repo, DOC, "| SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2) |", "| SPDX 2.3 JSON SBOM generation | DEFERRED (Slice 2) |")
    assert "DOC-STATUS" in codes(repo)


def test_an_sbom_tool_declared_as_a_dependency_fails(repo: Path) -> None:
    path = repo / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("dependencies = [", 'dependencies = [\n  "syft>=1",', 1), encoding="utf-8")
    assert "SBOM-DEPENDENCY" in codes(repo)


def test_an_sbom_package_in_the_lockfile_fails(repo: Path) -> None:
    path = repo / "uv.lock"
    path.write_text(path.read_text(encoding="utf-8") + '\n[[package]]\nname = "cyclonedx-python-lib"\nversion = "1"\n', encoding="utf-8")
    assert "SBOM-DEPENDENCY" in codes(repo)


def test_runtime_code_using_the_sbom_tooling_fails(repo: Path) -> None:
    runtime = repo / "src" / "pysh"
    runtime.mkdir(parents=True)
    (runtime / "bad.py").write_text("import generate_release_sboms\n", encoding="utf-8")
    assert "SBOM-DEPENDENCY" in codes(repo)


# --- Slice 3: keyless attestations and verification before upload -----------------------------------------------------

STEP = "      - name: "
FINALIZE = "Finalize SHA256SUMS over the complete published set"
BUNDLE = "Validate the complete release bundle (packages, SBOMs, SHA256SUMS)"
VERIFY = "Verify every attestation before the hand-off (fail closed)"
HANDOFF = "Upload validated release assets for the upload job"
SELF_PROVENANCE = "Attest provenance for SHA256SUMS itself"
SUBJECTS = "Prepare exact attestation subjects (from the final SHA256SUMS)"


def _step_bounds(text: str, name: str) -> tuple[int, int]:
    start = text.index(STEP + name)
    following = text.find("\n" + STEP, start)
    job_end = text.find("\n  upload:", start)
    ends = [e + 1 for e in (following, job_end) if e != -1]
    return start, min(ends)


def move_step(root: Path, name: str, before: str | None) -> None:
    """Move one build-and-validate step before another step (``None``: to the end of the job)."""
    path = root / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    start, end = _step_bounds(text, name)
    chunk = text[start:end]
    if not chunk.endswith("\n"):
        chunk += "\n"
    text = text[:start] + text[end:]
    target = text.index(STEP + before) if before else text.index("\n  upload:") + 1
    path.write_text(text[:target] + chunk + text[target:], encoding="utf-8")


def remove_step(root: Path, name: str) -> None:
    path = root / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    start, end = _step_bounds(text, name)
    path.write_text(text[:start] + text[end:], encoding="utf-8")


def duplicate_step(root: Path, name: str) -> None:
    path = root / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    start, end = _step_bounds(text, name)
    path.write_text(text[:end] + "\n" + text[start:end] + text[end:], encoding="utf-8")


def test_the_real_workflow_satisfies_every_attestation_rule(repo: Path) -> None:
    assert [v for v in contract.run_checks(repo) if v.code.startswith("ATT-")] == []
    text = (repo / RELEASE_WF).read_text(encoding="utf-8")
    assert text.count("uses: actions/attest@") == 7 and text.count(ATTEST_USES) == 7
    assert "attest-build-provenance" not in text and "attest-sbom" not in text


# -- action pin (negatives 1-3) --


def test_a_mutable_attest_tag_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, f"actions/attest@{ATTEST_SHA}", "actions/attest@v4")
    assert {"ATT-PIN", "SBOM-PIN"} <= codes(repo)


def test_a_wrong_attest_sha_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, f"actions/attest@{ATTEST_SHA}", "actions/attest@" + "0" * 40)
    assert "ATT-PIN" in codes(repo)


def test_a_missing_version_comment_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, f"actions/attest@{ATTEST_SHA} # actions/attest v4.2.2", f"actions/attest@{ATTEST_SHA}")
    assert "ATT-PIN" in codes(repo)


def test_the_deprecated_attest_build_provenance_action_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "actions/attest@", "actions/attest-build-provenance@")
    assert "ATT-ALTERNATIVE" in codes(repo)


def test_the_separate_attest_sbom_action_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "actions/attest@", "actions/attest-sbom@")
    assert "ATT-ALTERNATIVE" in codes(repo)


def test_another_workflow_using_a_different_attest_pin_fails(repo: Path) -> None:
    extra = repo / ".github" / "workflows" / "other.yml"
    extra.write_text(
        "name: x\non: workflow_dispatch\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/attest@" + "1" * 40 + "\n",
        encoding="utf-8",
    )
    assert "ATT-PIN" in codes(repo)


# -- permission split (negatives 4-8) --


def test_a_missing_id_token_permission_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      id-token: write\n", "")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_a_missing_attestations_permission_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      attestations: write\n", "")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_a_missing_artifact_metadata_permission_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      artifact-metadata: write\n", "")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_the_build_job_holding_contents_write_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      contents: read\n      id-token: write", "      contents: write\n      id-token: write")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_the_build_job_holding_an_extra_write_scope_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "      artifact-metadata: write\n", "      artifact-metadata: write\n      packages: write\n")
    assert "ATT-PERMISSIONS" in codes(repo)


@pytest.mark.parametrize("scope", ["id-token", "attestations", "artifact-metadata"])
def test_the_upload_job_holding_a_signing_permission_fails(repo: Path, scope: str) -> None:
    edit(repo, RELEASE_WF, "    permissions:\n      contents: write\n", f"    permissions:\n      contents: write\n      {scope}: write\n")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_a_workflow_wide_write_permission_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "permissions:\n  contents: read\n\njobs:", "permissions:\n  contents: read\n  id-token: write\n\njobs:")
    assert "ATT-PERMISSIONS" in codes(repo)
    edit(repo, RELEASE_WF, "  contents: read\n  id-token: write\n\njobs:", "  contents: write\n\njobs:")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_an_unrelated_job_holding_a_write_permission_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "    timeout-minutes: 20\n", "    timeout-minutes: 20\n    permissions:\n      contents: write\n")
    assert "ATT-PERMISSIONS" in codes(repo)


def test_the_upload_job_without_explicit_permissions_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "    permissions:\n      contents: write\n", "")
    assert "ATT-PERMISSIONS" in codes(repo)


# -- ordering (negatives 9-11) --


def test_provenance_before_the_final_checksums_fails(repo: Path) -> None:
    move_step(repo, FINALIZE, VERIFY)
    assert "ATT-ORDER" in codes(repo)


def test_provenance_before_the_validated_bundle_fails(repo: Path) -> None:
    move_step(repo, BUNDLE, VERIFY)
    assert "ATT-ORDER" in codes(repo)


def test_subjects_prepared_after_the_first_attestation_fails(repo: Path) -> None:
    move_step(repo, SUBJECTS, VERIFY)
    assert "ATT-ORDER" in codes(repo)


def test_verification_before_an_attestation_fails(repo: Path) -> None:
    move_step(repo, VERIFY, SELF_PROVENANCE)
    assert "ATT-ORDER" in codes(repo)


def test_verification_after_the_workflow_artifact_handoff_fails(repo: Path) -> None:
    move_step(repo, VERIFY, None)
    assert "ATT-ORDER" in codes(repo)


def test_the_handoff_before_verification_fails(repo: Path) -> None:
    move_step(repo, HANDOFF, VERIFY)
    assert "ATT-ORDER" in codes(repo)


def test_a_release_upload_in_the_build_job_before_verification_fails(repo: Path) -> None:
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    early = f'{STEP}Early upload\n        run: gh release upload "$TAG" dist/release-assets/*\n\n'
    target = text.index(STEP + VERIFY)
    path.write_text(text[:target] + early + text[target:], encoding="utf-8")
    assert "WF-UPLOAD-BYPASS" in codes(repo)


def test_an_upload_job_that_no_longer_waits_for_the_build_job_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "    needs: build-and-validate\n    if: github.event_name == 'release'", "    needs: freebsd-pkg\n    if: github.event_name == 'release'")
    assert "WF-RELEASE-GRAPH" in codes(repo)


# -- subjects (negatives 12-15) --


def test_missing_provenance_for_sha256sums_fails(repo: Path) -> None:
    remove_step(repo, SELF_PROVENANCE)
    assert "ATT-SUBJECTS" in codes(repo)


def test_missing_provenance_for_the_manifest_subjects_fails(repo: Path) -> None:
    remove_step(repo, "Attest provenance for the SHA256SUMS subjects (packages, SBOM files and REPRODUCIBILITY.json)")
    assert "ATT-SUBJECTS" in codes(repo)


def test_provenance_taking_subjects_from_another_file_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "subject-checksums: dist/release-assets/SHA256SUMS", "subject-checksums: dist/SHA256SUMS")
    assert "ATT-SUBJECTS" in codes(repo)


@pytest.mark.parametrize("family", ["wheel", "sdist", "deb", "rpm", "freebsd_pkg"])
def test_a_missing_package_sbom_attestation_fails(repo: Path, family: str) -> None:
    remove_step(repo, f"Attest SPDX SBOM ({family})")
    assert "ATT-SBOM-PAIR" in codes(repo)


def test_a_duplicate_package_sbom_attestation_fails(repo: Path) -> None:
    duplicate_step(repo, "Attest SPDX SBOM (wheel)")
    assert "ATT-SBOM-PAIR" in codes(repo)


def test_a_wrong_package_sbom_pair_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "outputs.deb_sbom_path", "outputs.rpm_sbom_path")
    assert "ATT-SBOM-PAIR" in codes(repo)


def test_an_sbom_attestation_for_the_sbom_file_itself_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "subject-name: ${{ steps.subjects.outputs.wheel_name }}", "subject-name: ${{ steps.subjects.outputs.wheel_sbom_path }}")
    assert "ATT-SBOM-PAIR" in codes(repo)


@pytest.mark.parametrize("extra", ["subject-path: dist/release-assets/*", "predicate-type: https://example.invalid/x", "push-to-registry: true"])
def test_attestation_inputs_that_bypass_the_prepared_subjects_fail(repo: Path, extra: str) -> None:
    edit(repo, RELEASE_WF, "          subject-checksums: dist/release-assets/SHA256SUMS\n", f"          subject-checksums: dist/release-assets/SHA256SUMS\n          {extra}\n")
    assert "ATT-SUBJECTS" in codes(repo)


def test_a_missing_subject_helper_step_fails(repo: Path) -> None:
    remove_step(repo, SUBJECTS)
    assert "ATT-WORKFLOW" in codes(repo)


# -- verifier pins (negatives 16-19, 27-28) --


def test_a_missing_verification_step_fails(repo: Path) -> None:
    remove_step(repo, VERIFY)
    assert "ATT-VERIFY" in codes(repo)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("--repo SSobol77/pysh", "--repo attacker/pysh"),
        ("--signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml", "--signer-workflow SSobol77/pysh/.github/workflows/ci.yml"),
        ('--source-digest "${GITHUB_SHA}"', "--source-digest main"),
        ("--assets-dir dist/release-assets", "--assets-dir dist"),
    ],
)
def test_the_verification_step_must_pin_repo_workflow_and_source(repo: Path, old: str, new: str) -> None:
    anchor = "verify_release_attestations.py \\\n"
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    start = text.index(anchor)
    head, tail = text[:start], text[start:]
    assert f"            {old}" in tail
    path.write_text(head + tail.replace(f"            {old}", f"            {new}", 1), encoding="utf-8")
    assert "ATT-VERIFY" in codes(repo)


def test_a_conditional_or_non_fatal_verification_step_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, f"{STEP}{VERIFY}\n", f"{STEP}{VERIFY}\n        continue-on-error: true\n")
    assert "ATT-VERIFY" in codes(repo)
    edit(repo, RELEASE_WF, "        continue-on-error: true\n", "        if: ${{ false }}\n")
    assert "ATT-VERIFY" in codes(repo)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('PINNED_REPO = "SSobol77/pysh"', 'PINNED_REPO = "attacker/pysh"'),
        ('PINNED_SIGNER_WORKFLOW = "SSobol77/pysh/.github/workflows/release-artifacts.yml"', 'PINNED_SIGNER_WORKFLOW = "SSobol77/pysh/.github/workflows/ci.yml"'),
        ('SPDX_PREDICATE_TYPE = "https://spdx.dev/Document/v2.3"', 'SPDX_PREDICATE_TYPE = "https://spdx.dev/Document/v2.2"'),
        ('"--source-digest", source_digest', '"--no-source-digest", source_digest'),
        ('"--signer-workflow", signer_workflow', '"--no-signer-workflow", signer_workflow'),
        ('"--repo", repo', '"--no-repo", repo'),
        ('"--predicate-type", predicate_type', '"--no-predicate-type", predicate_type'),
    ],
)
def test_the_verifier_must_pin_its_identities(repo: Path, old: str, new: str) -> None:
    edit(repo, VERIFIER, old, new)
    assert "ATT-VERIFY" in codes(repo)


def test_an_unbounded_retry_fails(repo: Path) -> None:
    edit(repo, VERIFIER, "MAX_ATTEMPTS = 6", "MAX_ATTEMPTS = 1000000")
    assert "ATT-RETRY" in codes(repo)
    edit(repo, VERIFIER, "MAX_ATTEMPTS = 1000000", "MAX_ATTEMPTS = 6")
    path = repo / VERIFIER
    path.write_text(path.read_text(encoding="utf-8") + "\n\ndef spin():\n    while True:\n        pass\n", encoding="utf-8")
    assert "ATT-RETRY" in codes(repo)


def test_a_retry_that_would_hide_identity_or_signature_failures_fails(repo: Path) -> None:
    edit(repo, VERIFIER, 'NOT_VISIBLE_PATTERN = r"\\bno attestations? found\\b"', 'NOT_VISIBLE_PATTERN = r".*"')
    assert "ATT-VERIFY" in codes(repo)


def test_a_verifier_with_a_shell_or_signing_logic_fails(repo: Path) -> None:
    path = repo / VERIFIER
    path.write_text(path.read_text(encoding="utf-8") + '\nrun(["cosign", "sign-blob"], shell=True)\n', encoding="utf-8")
    assert {"ATT-VERIFY", "ATT-ALTERNATIVE"} <= codes(repo)


def test_a_missing_verifier_or_helper_fails(repo: Path) -> None:
    (repo / VERIFIER).unlink()
    assert "ATT-VERIFY" in codes(repo)
    (repo / SUBJECT_HELPER).unlink()
    assert "ATT-SUBJECTS" in codes(repo)


def test_a_network_or_subprocess_subject_helper_fails(repo: Path) -> None:
    path = repo / SUBJECT_HELPER
    path.write_text(path.read_text(encoding="utf-8") + "\nimport subprocess\n", encoding="utf-8")
    assert "ATT-SUBJECTS" in codes(repo)


# -- keys and alternative signers (negatives 29-30) --


def test_a_signing_private_key_secret_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, "        env:\n          GH_TOKEN: ${{ github.token }}\n", "        env:\n          GH_TOKEN: ${{ github.token }}\n          SIGNING_KEY: ${{ secrets.RELEASE_SIGNING_PRIVATE_KEY }}\n")
    assert "WF-SECRETS" in codes(repo)


@pytest.mark.parametrize(
    "step",
    [
        "      - run: cosign sign-blob dist/release-assets/SHA256SUMS\n",
        "      - uses: sigstore/cosign-installer@" + "2" * 40 + "\n",
        "      - run: gpg --detach-sign dist/release-assets/SHA256SUMS\n",
        "      - uses: slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml@" + "3" * 40 + "\n",
    ],
)
def test_a_second_signing_mechanism_fails(repo: Path, step: str) -> None:
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    target = text.index(STEP + VERIFY)
    path.write_text(text[:target] + step + text[target:], encoding="utf-8")
    assert "ATT-ALTERNATIVE" in codes(repo)


# -- documentation --


@pytest.mark.parametrize(
    "needle",
    [
        "actions/attest v4.2.2",
        ATTEST_SHA,
        "--signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml",
        "--source-digest",
        "--predicate-type https://spdx.dev/Document/v2.3",
        "gh attestation trusted-root",
        "sha256sum -c SHA256SUMS",
    ],
)
def test_the_user_verification_documentation_is_required(repo: Path, needle: str) -> None:
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8").replace(needle, "REDACTED"), encoding="utf-8")
    assert "ATT-DOC" in codes(repo)


def test_slice_three_status_must_read_implemented(repo: Path) -> None:
    edit(repo, DOC, "SBOM attestations, verified before upload | IMPLEMENTED (Slice 3)", "SBOM attestations, verified before upload | DEFERRED (Slice 3)")
    assert "DOC-STATUS" in codes(repo)


# --- Slice 4: reproducibility measurement and evidence ---------------------------------------------------------------

MEASURE = "Measure Linux reproducibility (A/B builds of wheel, sdist, deb and rpm)"
DOWNLOAD = "Download native FreeBSD reproducibility evidence"
MERGE = "Combine platform evidence into REPRODUCIBILITY.json"
FINAL_CHECK = "Validate the final reproducibility evidence"
EPOCH = "Derive SOURCE_DATE_EPOCH from the release source commit"
VALIDATE_SBOM = "Validate SBOM completeness"


def test_the_real_repository_satisfies_every_reproducibility_rule(repo: Path) -> None:
    assert [v for v in contract.run_checks(repo) if v.code.startswith("REPRO-")] == []
    text = (repo / RELEASE_WF).read_text(encoding="utf-8")
    assert "git log -1 --format=%ct" in text and "date +%s" not in text
    assert text.index(MEASURE) < text.index(MERGE) < text.index(FINAL_CHECK) < text.index(FINALIZE)


@pytest.mark.parametrize("script", [HARNESS, EVIDENCE_VALIDATOR])
def test_a_missing_reproducibility_script_fails(repo: Path, script: Path) -> None:
    (repo / script).unlink()
    assert {"REPRO-HARNESS", "REPRO-VALIDATOR"} & codes(repo)


# -- ordering: evidence before the checksums and the attestations (negatives 21-22) --


def test_evidence_generated_after_the_final_checksums_fails(repo: Path) -> None:
    move_step(repo, MEASURE, "Validate the complete release bundle (packages, SBOMs, SHA256SUMS)")
    assert "REPRO-ORDER" in codes(repo)


def test_evidence_merged_after_the_final_checksums_fails(repo: Path) -> None:
    move_step(repo, MERGE, "Validate the complete release bundle (packages, SBOMs, SHA256SUMS)")
    assert "REPRO-ORDER" in codes(repo)


def test_evidence_generated_after_the_attestations_fails(repo: Path) -> None:
    move_step(repo, MERGE, VERIFY)
    assert "REPRO-ORDER" in codes(repo)
    move_step(repo, MEASURE, VERIFY)
    assert "REPRO-ORDER" in codes(repo)


def test_evidence_validated_after_the_subjects_were_prepared_fails(repo: Path) -> None:
    move_step(repo, FINAL_CHECK, SELF_PROVENANCE)
    assert "REPRO-ORDER" in codes(repo)


def test_evidence_measured_before_the_sboms_exist_fails(repo: Path) -> None:
    move_step(repo, MEASURE, "Fetch pinned SBOM tool (CI-only, digest-verified)")
    assert "REPRO-ORDER" in codes(repo)


def test_merging_before_the_native_evidence_is_downloaded_fails(repo: Path) -> None:
    move_step(repo, DOWNLOAD, FINAL_CHECK)
    assert "REPRO-ORDER" in codes(repo)


# -- the workflow structure --


@pytest.mark.parametrize("step", [MEASURE, DOWNLOAD, MERGE, FINAL_CHECK])
def test_a_missing_evidence_step_fails(repo: Path, step: str) -> None:
    remove_step(repo, step)
    assert "REPRO-WORKFLOW" in codes(repo)


@pytest.mark.parametrize("family", ["wheel", "sdist", "deb", "rpm"])
def test_the_linux_measurement_must_cover_every_linux_family(repo: Path, family: str) -> None:
    edit(repo, RELEASE_WF, f"--family {family}", "--family nothing")
    assert "REPRO-WORKFLOW" in codes(repo)


def test_the_linux_job_must_not_claim_the_freebsd_measurement(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--family wheel --family sdist --family deb --family rpm", "--all")
    assert "REPRO-WORKFLOW" in codes(repo)


def test_the_merge_must_publish_reproducibility_json_and_pin_the_commit(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--output dist/release-assets/REPRODUCIBILITY.json", "--output dist/reproducibility/REPRODUCIBILITY.json")
    assert "REPRO-WORKFLOW" in codes(repo)


def test_the_final_check_must_be_final_mode(repo: Path) -> None:
    edit(repo, RELEASE_WF, "            --mode final \\\n", "            --mode local \\\n")
    assert "REPRO-WORKFLOW" in codes(repo)


@pytest.mark.parametrize("step", [MEASURE, DOWNLOAD, MERGE, FINAL_CHECK])
def test_evidence_steps_must_fail_closed(repo: Path, step: str) -> None:
    edit(repo, RELEASE_WF, f"{STEP}{step}\n", f"{STEP}{step}\n        continue-on-error: true\n")
    assert "REPRO-WORKFLOW" in codes(repo)


def test_the_attestation_subjects_must_be_bound_to_the_release_commit(repo: Path) -> None:
    edit(repo, RELEASE_WF, '            --source-commit "${GITHUB_SHA}" \\\n            --github-output', "            --github-output")
    assert "REPRO-WORKFLOW" in codes(repo)


# -- the native FreeBSD measurement (negatives 14, 28) --


def test_the_native_freebsd_measurement_is_required_in_the_reference_job(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--family freebsd_pkg", "--family nothing")
    assert "REPRO-NATIVE" in codes(repo)


def test_the_freebsd_measurement_must_be_reference_only_and_uploaded(repo: Path) -> None:
    edit(repo, RELEASE_WF, "name: freebsd-reproducibility-evidence", "name: something-else", count=1)
    assert "REPRO-NATIVE" in codes(repo)


def test_the_freebsd_job_must_not_measure_other_families(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--family freebsd_pkg", "--family freebsd_pkg --family wheel")
    assert "REPRO-NATIVE" in codes(repo)


def test_the_freebsd_job_needs_the_commit_epoch(repo: Path) -> None:
    edit(repo, RELEASE_WF, 'echo "SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)" >> "${GITHUB_ENV}"\n          echo "PYSH_SOURCE_COMMIT', 'echo "PYSH_SOURCE_COMMIT')
    assert "REPRO-EPOCH" in codes(repo)


# -- the epoch policy (negative 27) --


def test_a_wall_clock_epoch_in_a_workflow_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, 'echo "SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)" >> "${GITHUB_ENV}"\n\n      - name: Set up', 'echo "SOURCE_DATE_EPOCH=$(date +%s)" >> "${GITHUB_ENV}"\n\n      - name: Set up')
    assert "REPRO-EPOCH" in codes(repo)


def test_an_epoch_that_is_not_derived_from_the_commit_fails(repo: Path) -> None:
    edit(repo, RELEASE_WF, 'echo "SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)" >> "${GITHUB_ENV}"\n\n      - name: Set up', 'echo "SOURCE_DATE_EPOCH=0" >> "${GITHUB_ENV}"\n\n      - name: Set up')
    assert "REPRO-EPOCH" in codes(repo)


def test_the_epoch_must_be_set_before_the_first_build(repo: Path) -> None:
    move_step(repo, EPOCH, "Build Debian .deb")
    assert "REPRO-EPOCH" in codes(repo)


def test_a_wall_clock_epoch_in_the_harness_fails(repo: Path) -> None:
    path = repo / HARNESS
    path.write_text(path.read_text(encoding="utf-8") + "\nEPOCH = str(int(time.time()))\n", encoding="utf-8")
    assert "REPRO-EPOCH" in codes(repo)


# -- no post-build normalization (negative 26) --


@pytest.mark.parametrize(
    "step",
    [
        "      - run: strip-nondeterminism dist/os/deb/*.deb\n",
        "      - run: touch -d @0 dist/release-assets/*\n",
        "      - run: add-determinism dist/*.whl\n",
    ],
)
def test_post_build_normalization_in_the_workflow_fails(repo: Path, step: str) -> None:
    path = repo / RELEASE_WF
    text = path.read_text(encoding="utf-8")
    target = text.index(STEP + MEASURE)
    path.write_text(text[:target] + step + text[target:], encoding="utf-8")
    assert "REPRO-NORMALIZE" in codes(repo)


@pytest.mark.parametrize("script", [HARNESS, EVIDENCE_VALIDATOR])
def test_post_build_normalization_in_the_scripts_fails(repo: Path, script: Path) -> None:
    path = repo / script
    path.write_text(path.read_text(encoding="utf-8") + "\nos.utime(artifact, (0, 0))\n", encoding="utf-8")
    assert "REPRO-NORMALIZE" in codes(repo)


# -- the harness and the validator --


@pytest.mark.parametrize(
    ("script", "old", "new", "code"),
    [
        (HARNESS, "start_new_session=True", "start_new_session=False", "REPRO-HARNESS"),
        (HARNESS, "separate_output_files", "separate_outputs", "REPRO-HARNESS"),
        (HARNESS, "%ct", "%at", "REPRO-HARNESS"),
        (EVIDENCE_VALIDATOR, 'REPRODUCIBLE = "REPRODUCIBLE"', 'REPRODUCIBLE = "MOSTLY"', "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, "is not accepted in final evidence", "is accepted in final evidence", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, '"rpm": ("rpmbuild",)', '"rpm": ()', "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, 'NATIVE_ONLY = {"freebsd_pkg": "FreeBSD"}', "NATIVE_ONLY = {}", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, '"deb": "scripts/build_deb.sh"', '"deb": "scripts/make_deb.sh"', "REPRO-VALIDATOR"),
    ],
)
def test_the_harness_and_validator_contracts_are_enforced(repo: Path, script: Path, old: str, new: str, code: str) -> None:
    path = repo / script
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture drift: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")  # every occurrence, not just the first
    assert code in codes(repo)


def test_the_harness_must_not_use_a_shell(repo: Path) -> None:
    path = repo / HARNESS
    path.write_text(path.read_text(encoding="utf-8") + "\nsubprocess.run('x', shell=True)\n", encoding="utf-8")
    assert "REPRO-HARNESS" in codes(repo)


def test_the_harness_must_never_upload(repo: Path) -> None:
    path = repo / HARNESS
    path.write_text(path.read_text(encoding="utf-8") + '\nsubprocess.run(["gh release upload", "v1"])\n', encoding="utf-8")
    assert "WF-UPLOAD-BYPASS" in codes(repo)


# -- publication: REPRODUCIBILITY.json in the public set (negatives 23-25) --


def test_the_published_evidence_must_be_known_to_the_artifact_checker(repo: Path) -> None:
    path = repo / "scripts/check_release_artifacts.sh"
    path.write_text(path.read_text(encoding="utf-8").replace("REPRODUCIBILITY.json", "evidence.json"), encoding="utf-8")
    assert "REPRO-CHECKSUMS" in codes(repo)


def test_a_provenance_helper_that_omits_the_evidence_subject_fails(repo: Path) -> None:
    path = repo / SUBJECT_HELPER
    path.write_text(path.read_text(encoding="utf-8").replace("EVIDENCE", "OTHER"), encoding="utf-8")
    assert "ATT-SUBJECTS" in codes(repo)


def test_a_stale_eleven_subject_count_fails(repo: Path) -> None:
    edit(repo, SUBJECT_HELPER, "SUBJECT_COUNT = 12", "SUBJECT_COUNT = 11")
    assert "ATT-SUBJECTS" in codes(repo)


def test_the_sbom_generator_must_know_the_published_evidence(repo: Path) -> None:
    path = repo / SBOM_GENERATOR
    path.write_text(path.read_text(encoding="utf-8").replace("REPRODUCIBILITY.json", "evidence.json"), encoding="utf-8")
    assert "REPRO-SUBJECTS" in codes(repo)


# -- the documentation --


@pytest.mark.parametrize(
    "needle",
    [
        "byte-for-byte", "SHA-256", "SOURCE_DATE_EPOCH", "commit timestamp", "REPRODUCIBILITY.json", "native FreeBSD",
        "rpmbuild", "check_reproducibility_evidence.py", "independent controls", "NOT_YET_MEASURED",
    ],
)
def test_the_reproducibility_documentation_is_required(repo: Path, needle: str) -> None:
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8").replace(needle, "REDACTED"), encoding="utf-8")
    assert {"REPRO-DOC", "DOC-REPRODUCIBILITY", "ATT-DOC", "DOC-STATUS"} & codes(repo)


def test_the_documentation_does_not_claim_blanket_reproducibility() -> None:
    text = " ".join((REPO_ROOT / DOC).read_text(encoding="utf-8").split()).lower()
    assert "all pysh artifacts are reproducible" not in text
    assert "no claim that pysh artifacts are reproducible is made beyond what the recorded measurements show" in text


# --- Slice 4 hardening: release-byte binding and the resolved toolchain ----------------------------------------------------


def test_the_linux_measurement_must_bind_to_the_staged_public_artifacts(repo: Path) -> None:
    edit(repo, RELEASE_WF, "            --release-dir dist/release-assets \\\n            --output dist/reproducibility/linux.json", "            --output dist/reproducibility/linux.json")
    assert "REPRO-RELEASE-BINDING" in codes(repo)


def test_the_merge_must_bind_to_the_staged_public_artifacts(repo: Path) -> None:
    edit(repo, RELEASE_WF, "            --release-dir dist/release-assets \\\n            --output dist/release-assets/REPRODUCIBILITY.json", "            --output dist/release-assets/REPRODUCIBILITY.json")
    assert "REPRO-RELEASE-BINDING" in codes(repo)


def test_the_binding_must_not_point_at_another_directory(repo: Path) -> None:
    edit(repo, RELEASE_WF, "--release-dir dist/release-assets", "--release-dir dist/reproducibility", count=2)
    assert "REPRO-RELEASE-BINDING" in codes(repo)


@pytest.mark.parametrize(
    ("script", "old", "code"),
    [
        (HARNESS, "release_matches_build_a", "REPRO-HARNESS"),
        (HARNESS, "release_matches_build_b", "REPRO-HARNESS"),
        (HARNESS, "matches neither measured build", "REPRO-HARNESS"),
        (HARNESS, "def bind_release", "REPRO-HARNESS"),
        (HARNESS, "PIP_LOG", "REPRO-HARNESS"),
        (HARNESS, "def resolved_backend", "REPRO-HARNESS"),
        (HARNESS, "def wheel_generator", "REPRO-HARNESS"),
        (HARNESS, "umask=evidence.BUILD_UMASK", "REPRO-HARNESS"),
        (EVIDENCE_VALIDATOR, "requires the release-byte binding", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, "matches neither measured build", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, "EXACT_VERSION_RE", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, "declared_requirements", "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, '"wheel": ("python", "build", "hatchling")', "REPRO-VALIDATOR"),
        (EVIDENCE_VALIDATOR, '"freebsd_pkg": ("pkg", "python")', "REPRO-VALIDATOR"),
    ],
)
def test_the_binding_and_toolchain_contracts_are_enforced(repo: Path, script: Path, old: str, code: str) -> None:
    path = repo / script
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture drift: {old!r}"
    path.write_text(text.replace(old, "removed_contract_marker"), encoding="utf-8")
    assert code in codes(repo)


@pytest.mark.parametrize("needle", ["release_sha256", "resolved version", "umask"])
def test_the_binding_and_toolchain_documentation_is_required(repo: Path, needle: str) -> None:
    path = repo / DOC
    path.write_text(path.read_text(encoding="utf-8").replace(needle, "REDACTED"), encoding="utf-8")
    assert "REPRO-DOC" in codes(repo)


def test_the_documentation_states_the_non_reproducible_release_consequence() -> None:
    text = " ".join((REPO_ROOT / DOC).read_text(encoding="utf-8").split())
    assert "a shipped artifact that still equals a measured build" in text
    assert "The release artifact must equal build A or build B" in text


# --- the RPM builder's epoch contract (first real dry run) ---------------------------------------------------------------------


@pytest.mark.parametrize("macro", ["use_source_date_epoch_as_buildtime", "clamp_mtime_to_source_date_epoch"])
def test_the_rpm_builder_must_enable_the_epoch_macros(repo: Path, macro: str) -> None:
    path = repo / "scripts/build_rpm.sh"
    path.write_text(path.read_text(encoding="utf-8").replace(macro, "removed_macro"), encoding="utf-8")
    assert "REPRO-RPM" in codes(repo)


def test_the_rpm_builder_must_not_rewrite_the_package(repo: Path) -> None:
    path = repo / "scripts/build_rpm.sh"
    path.write_text(path.read_text(encoding="utf-8") + "\nstrip-nondeterminism \"${EXPECTED_PATH}\"\n", encoding="utf-8")
    assert "REPRO-NORMALIZE" in codes(repo)
