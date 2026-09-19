# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_workflow_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RQG-G release-asset workflow contract.

``scripts/check_release_workflow.py`` validates two distinct things:

1. Structural facts about ``.github/workflows/release-artifacts.yml`` and
   ``.github/workflows/publish.yml`` (job ``needs:``/``if:`` wiring, step
   ordering, absence of ``continue-on-error``) that can only be checked as
   text -- GitHub-specific dependency wiring this suite cannot execute
   locally.
2. The real pre-upload validation sequence
   (``check_release_metadata.sh`` then ``check_release_artifacts.sh
   --contract-only``) executed dynamically against fixture artifact
   directories, reusing the existing RQG-B/RQG-C scripts rather than
   reimplementing their logic.

No test here invokes the GitHub API, requires credentials, tags git,
publishes anything, or replaces the real FreeBSD VM build with a fixture
in the actual release path -- fixtures are used exclusively to exercise
the *validation sequence*, never presented as, or substituted for, a real
release artifact.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_release_workflow.py"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_release_workflow", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHECK = _load_module()


def _run(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _build_valid_fixture(root: Path, version: str = "0.8.2") -> None:
    (root / "os" / "deb").mkdir(parents=True)
    (root / "os" / "rpm").mkdir(parents=True)
    (root / "os" / "freebsd").mkdir(parents=True)
    (root / f"pysh_shell-{version}-py3-none-any.whl").write_bytes(b"FIXTURE WHEEL\n")
    (root / f"pysh_shell-{version}.tar.gz").write_bytes(b"FIXTURE SDIST\n")
    (root / "os" / "deb" / f"pysh-shell_{version}-1_all.deb").write_bytes(b"FIXTURE DEB\n")
    (root / "os" / "rpm" / f"pysh-shell-{version}-1.noarch.rpm").write_bytes(b"FIXTURE RPM\n")
    (root / "os" / "freebsd" / f"pysh-shell-{version}.pkg").write_bytes(b"FIXTURE PKG\n")


# ------------------------------------------------------------- 1-6. required assets


def test_real_workflow_requires_all_five_artifact_families_and_checksums() -> None:
    """release-artifacts.yml's gate step enforces all 5 families + SHA256SUMS.

    Delegated to scripts/check_release_artifacts.sh (RQG-C), which is the
    single source of truth for this naming/presence contract; this test
    proves the workflow actually calls it rather than re-deriving a second
    independent naming registry in YAML.
    """
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "bash scripts/check_release_artifacts.sh" in text
    artifacts_text = (REPO_ROOT / "scripts" / "check_release_artifacts.sh").read_text(
        encoding="utf-8"
    )
    for marker in (
        "EXPECTED_WHEEL_NAME",
        "EXPECTED_SDIST",
        "EXPECTED_DEB",
        "EXPECTED_RPM",
        "EXPECTED_FREEBSD_PKG",
        "SHA256SUMS",
    ):
        assert marker in artifacts_text


# ------------------------------------------- 7-11. dynamic pre-upload sequence


def test_complete_fixture_passes_pre_upload_sequence(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    errors = CHECK.simulate_pre_upload_sequence(tmp_path)
    assert errors == []


def test_missing_wheel_fails_pre_upload_sequence(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    (tmp_path / "pysh_shell-0.8.2-py3-none-any.whl").unlink()
    errors = CHECK.simulate_pre_upload_sequence(tmp_path)
    assert errors
    assert any("artifact gate failed" in e for e in errors)


def test_missing_pkg_fails_pre_upload_sequence(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    (tmp_path / "os" / "freebsd" / "pysh-shell-0.8.2.pkg").unlink()
    errors = CHECK.simulate_pre_upload_sequence(tmp_path)
    assert errors
    assert any("artifact gate failed" in e for e in errors)


def test_corrupt_checksum_fails_pre_upload_sequence(tmp_path: Path) -> None:
    import hashlib

    _build_valid_fixture(tmp_path)
    lines = []
    for relative in (
        "pysh_shell-0.8.2-py3-none-any.whl",
        "pysh_shell-0.8.2.tar.gz",
        "os/deb/pysh-shell_0.8.2-1_all.deb",
        "os/rpm/pysh-shell-0.8.2-1.noarch.rpm",
        "os/freebsd/pysh-shell-0.8.2.pkg",
    ):
        digest = hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        if relative.endswith(".whl"):
            digest = ("f" if digest[0] != "f" else "0") + digest[1:]
        lines.append(f"{digest}  {relative}")
    (tmp_path / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    errors = CHECK.simulate_pre_upload_sequence(tmp_path)
    assert errors
    assert any("artifact gate failed" in e for e in errors)


def test_wrong_version_filename_fails_pre_upload_sequence(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    (tmp_path / "pysh_shell-0.8.2-py3-none-any.whl").unlink()
    (tmp_path / "pysh_shell-9.9.9-py3-none-any.whl").write_bytes(b"WRONG VERSION\n")
    errors = CHECK.simulate_pre_upload_sequence(tmp_path)
    assert errors
    assert any("artifact gate failed" in e for e in errors)


def test_release_mode_unfinalized_changelog_fails_pre_upload_sequence(tmp_path: Path) -> None:
    """The metadata gate step must also be part of the simulated sequence."""
    _build_valid_fixture(tmp_path)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 0.9.0 - Unreleased\n\n- wip\n\n## 0.8.2 - 2026-06-08\n\n- released\n",
        encoding="utf-8",
    )
    errors = CHECK.simulate_pre_upload_sequence(
        tmp_path, changelog=changelog, target_version="0.9.0"
    )
    assert errors
    assert any("metadata gate failed" in e for e in errors)
    # The artifact gate must never run once the metadata gate has failed.
    assert not any("artifact gate failed" in e for e in errors)


# --------------------------------------------------- 12-14. gate ordering


def test_structural_check_detects_correct_step_ordering() -> None:
    errors = CHECK.check_release_artifacts_workflow_structure(
        RELEASE_WORKFLOW.read_text(encoding="utf-8")
    )
    assert errors == []


def test_structural_check_flags_out_of_order_steps() -> None:
    """Prove the ordering check is load-bearing, not a tautology."""
    scrambled = (
        "gh release upload\n"
        "bash scripts/check_release_metadata.sh --release-mode\n"
        "bash scripts/check_release_artifacts.sh\n"
        "needs: freebsd-pkg\nneeds: build-and-validate\n"
        "if: github.event_name == 'release'\n"
        "actions/upload-artifact\nactions/download-artifact\n"
        "name: release-assets\nvmactions/freebsd-vm\n"
    )
    errors = CHECK.check_release_artifacts_workflow_structure(scrambled)
    assert any("out of order" in e for e in errors)


def test_structural_check_flags_continue_on_error() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8") + "\n      continue-on-error: true\n"
    errors = CHECK.check_release_artifacts_workflow_structure(text)
    assert any("continue-on-error" in e for e in errors)


def test_structural_check_flags_contract_only_in_real_workflow() -> None:
    """A --contract-only fixture must never be substituted in the real release path."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8") + "\n--contract-only\n"
    errors = CHECK.check_release_artifacts_workflow_structure(text)
    assert any("--contract-only" in e for e in errors)


# --------------------------------------------------- 15/16. tag requirement


def test_release_event_passes_tag_to_metadata_gate() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    idx = text.index("if: github.event_name == 'release'")
    following = text[idx : idx + 400]
    assert "--tag" in following
    assert "github.event.release.tag_name" in following


def test_workflow_dispatch_branch_omits_tag_requirement() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    idx = text.index("if: github.event_name != 'release'")
    following = text[idx : idx + 300]
    assert "--tag" not in following


# ----------------------------------------------- 17/18. upload gating


def test_upload_job_depends_on_validate_job() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "needs: build-and-validate" in text


def test_no_continue_on_error_anywhere_in_release_workflow() -> None:
    assert "continue-on-error" not in RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in PUBLISH_WORKFLOW.read_text(encoding="utf-8")


# --------------------------------------------------- 19/20. upload contents


def test_upload_step_uses_the_validated_flat_assets_directory() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "dist/release-assets/*" in text
    # The upload job downloads exactly what build-and-validate staged and
    # uploaded -- no separate/duplicate artifact path is introduced.
    upload_job_idx = text.index("upload:\n")
    upload_job_text = text[upload_job_idx:]
    assert "dist/release-assets" in upload_job_text


# ------------------------------------------------------- 21. publish.yml


def test_publish_workflow_gates_on_metadata_and_never_uploads_release_assets() -> None:
    errors = CHECK.check_publish_workflow_structure(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    assert errors == []


def test_publish_workflow_would_be_flagged_if_it_duplicated_release_assets() -> None:
    """Prove the anti-duplication check is load-bearing, not a tautology."""
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8") + "\ngh release upload\n"
    errors = CHECK.check_publish_workflow_structure(text)
    assert any("must not upload GitHub Release assets" in e for e in errors)


# ------------------------------------------------------- 22. freebsd-pkg.yml


def test_freebsd_pkg_workflow_was_retired() -> None:
    assert not (REPO_ROOT / ".github" / "workflows" / "freebsd-pkg.yml").exists()
    assert CHECK.check_no_dead_freebsd_workflow() == []


# ------------------------------------------------- 23/24. real FreeBSD build


def test_release_workflow_still_has_real_freebsd_vm_build() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "vmactions/freebsd-vm" in text
    assert "sh scripts/build_freebsd_pkg.sh" in text
    assert 'release: "14.3"' in text


def test_release_workflow_never_uses_contract_only_fixture() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "--contract-only" not in text


# ------------------------------------------------------------- CLI surface


def test_cli_passes_on_real_repository() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "all release workflow checks passed" in result.stdout


def test_cli_simulate_flag_fails_on_incomplete_fixture(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    (tmp_path / "pysh_shell-0.8.2-py3-none-any.whl").unlink()
    result = _run("--simulate", str(tmp_path))
    assert result.returncode != 0
    assert "artifact gate failed" in result.stderr


def test_cli_simulate_flag_passes_on_complete_fixture(tmp_path: Path) -> None:
    _build_valid_fixture(tmp_path)
    result = _run("--simulate", str(tmp_path))
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------- 25. RQG-B/C/D/F intact


def test_rqg_bcdf_test_modules_still_present() -> None:
    for name in (
        "test_release_metadata_contract.py",
        "test_release_artifact_contract.py",
        "test_debian_package_smoke_contract.py",
        "test_installation_docs_contract.py",
    ):
        assert (REPO_ROOT / "tests" / name).is_file()


def test_no_network_or_credentials_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module's own checks must never touch GH_TOKEN or the network."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = _run()
    assert result.returncode == 0, result.stderr
