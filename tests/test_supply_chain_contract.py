# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_supply_chain_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #51 Slices 1-2: the repository-owned supply-chain contract and its checker.

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of just the files the checker reads."""
    for relative in (
        DOC, PACKAGING, Path("scripts/check_release_artifacts.sh"), SBOM_GENERATOR,
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


def test_slice_two_reports_sboms_implemented_and_the_rest_deferred(repo: Path) -> None:
    assert contract.run_checks(repo) == []
    status = contract.future_status(repo)
    assert status[0] == "implemented: SPDX 2.3 JSON SBOM generation (Slice 2)"
    assert all("not yet implemented" in line for line in status[1:])
    assert not any("sbom" in line.lower() for line in status[1:])


def test_deferred_attestation_features_being_present_never_fail_the_checker(repo: Path) -> None:
    """Attestation and reproducibility are reported, not enforced, whichever way they are wired."""
    extra = repo / ".github" / "workflows" / "future-attest.yml"
    extra.write_text(
        "name: future\non: workflow_dispatch\njobs:\n  attest:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/attest-build-provenance@" + "a" * 40 + "\n",
        encoding="utf-8",
    )
    assert contract.run_checks(repo) == []
    assert any(line.endswith("present") for line in contract.future_status(repo))


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


def test_the_policy_claims_sboms_but_not_attestations_exist() -> None:
    text = " ".join((REPO_ROOT / DOC).read_text(encoding="utf-8").split())
    assert "SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2)" in text
    assert "attestations and verification before upload | DEFERRED (Slice 3)" in text
    assert "Reproducibility measurement | DEFERRED (Slice 4)" in text
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
    edit(repo, DOC, "- `PLATFORM_BLOCKED`\n", "")
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
    edit(repo, DOC, "4. SBOM generation\n5. SHA256SUMS finalization\n", "")
    assert "DOC-PIPELINE" in codes(repo)


def test_a_reordered_pipeline_fails(repo: Path) -> None:
    edit(repo, DOC, "7. provenance and attestation generation\n8. attestation verification against the exact subjects\n9. upload of the validated release bundle", "7. upload of the validated release bundle\n8. provenance and attestation generation\n9. attestation verification against the exact subjects")
    assert "DOC-PIPELINE" in codes(repo)


def test_overclaiming_that_implementation_exists_fails(repo: Path) -> None:
    edit(repo, DOC, "are implemented in later slices", "are implemented")
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
    assert codes(repo) == {"SBOM-GENERATOR"}


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
