# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_artifact_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Dynamic regression tests for the Issue #33 RQG-C artifact-contract gate.

``scripts/check_release_artifacts.sh --contract-only <dir>`` validates
artifact naming, presence, non-zero size, and checksum completeness for an
arbitrary artifact directory tree, without performing (or claiming to
perform) any native package installation. See
``docs/architecture/release-quality-gate-2-audit.md`` for the design this
implements.

These tests build small, clearly-labeled fixture artifact trees under
``tmp_path`` and invoke the real script as a subprocess, asserting exit
codes and diagnostic text. No fixture ever touches the repository's real
``dist/`` directory, and no fixture is ever a genuine installable package.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_release_artifacts.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"

VERSION = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]

WHEEL_NAME = f"pysh_shell-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"pysh_shell-{VERSION}.tar.gz"
DEB_NAME = f"pysh-shell_{VERSION}-1_all.deb"
RPM_NAME = f"pysh-shell-{VERSION}-1.noarch.rpm"
PKG_NAME = f"pysh-shell-{VERSION}.pkg"


def _write_fixture(path: Path, content: bytes = b"FIXTURE ARTIFACT CONTENT\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_valid_artifact_set(root: Path) -> None:
    """Populate *root* with a complete, correctly-named, non-empty artifact set."""
    _write_fixture(root / WHEEL_NAME, b"FIXTURE WHEEL - NOT A REAL PYTHON PACKAGE\n")
    _write_fixture(root / SDIST_NAME, b"FIXTURE SDIST - NOT A REAL PYTHON PACKAGE\n")
    _write_fixture(root / "os" / "deb" / DEB_NAME, b"FIXTURE DEB - NOT A REAL DEBIAN PACKAGE\n")
    _write_fixture(root / "os" / "rpm" / RPM_NAME, b"FIXTURE RPM - NOT A REAL RPM PACKAGE\n")
    _write_fixture(
        root / "os" / "freebsd" / PKG_NAME,
        b"FIXTURE PKG - NOT A REAL FREEBSD PACKAGE\n",
    )


def _run_contract(artifact_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--contract-only", str(artifact_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


# --------------------------------------------------------------- 1. PASS


def test_complete_canonical_artifact_set_passes(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    result = _run_contract(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Artifact contract PASSED (contract-only mode)" in result.stdout
    # The staged flat release-assets dir must live only inside the fixture
    # tree the test controls, never inside the real repository dist/.
    assert (tmp_path / "release-assets" / "SHA256SUMS").exists()


# ------------------------------------------------------- 2-6. missing artifact


def test_missing_wheel_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / WHEEL_NAME).unlink()
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / WHEEL_NAME}" in result.stderr


def test_missing_sdist_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / SDIST_NAME).unlink()
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert "missing sdist" in result.stderr


def test_missing_deb_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "deb" / DEB_NAME).unlink()
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / 'os' / 'deb' / DEB_NAME}" in result.stderr


def test_missing_rpm_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "rpm" / RPM_NAME).unlink()
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / 'os' / 'rpm' / RPM_NAME}" in result.stderr


def test_missing_freebsd_pkg_fails(tmp_path: Path) -> None:
    """The exact scenario this slice exists to close: no live FreeBSD builder."""
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "freebsd" / PKG_NAME).unlink()
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / 'os' / 'freebsd' / PKG_NAME}" in result.stderr


# --------------------------------------------------- 7. wrong version in name


def test_wrong_version_in_wheel_filename_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / WHEEL_NAME).unlink()
    _write_fixture(tmp_path / f"pysh_shell-{VERSION}.dev0-py3-none-any.whl", b"WRONG VERSION\n")
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / WHEEL_NAME}" in result.stderr


def test_wrong_version_in_deb_filename_fails(tmp_path: Path) -> None:
    """A deb named for a different version must be rejected as missing.

    ``check_present`` looks for the exact version-derived path first, so a
    single wrongly-versioned file (no correctly-named sibling) surfaces as
    "missing artifact", not as the sibling-naming-drift diagnostic.
    """
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "deb" / DEB_NAME).unlink()
    _write_fixture(tmp_path / "os" / "deb" / "pysh-shell_9.9.9-1_all.deb", b"WRONG VERSION\n")
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / 'os' / 'deb' / DEB_NAME}" in result.stderr


# --------------------------------------------------- 8. wrong package basename


def test_wrong_package_basename_only_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "rpm" / RPM_NAME).unlink()
    _write_fixture(
        tmp_path / "os" / "rpm" / f"totally-wrong-name-{VERSION}-1.noarch.rpm",
        b"WRONG BASENAME\n",
    )
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing artifact: {tmp_path / 'os' / 'rpm' / RPM_NAME}" in result.stderr


# --------------------------------- 12. unexpected sibling / extra artifact naming


def test_unexpected_extra_deb_naming_fails_deterministically(tmp_path: Path) -> None:
    """A correctly-named deb plus an extra, wrongly-named sibling must fail.

    This exercises the naming-drift loop distinctly from ``check_present``:
    the canonical file is present (so the presence gate passes), but an
    extra sibling with drifted naming must still fail the gate.
    """
    _build_valid_artifact_set(tmp_path)
    _write_fixture(
        tmp_path / "os" / "deb" / f"pysh-shell_{VERSION}-2_all.deb",
        b"UNEXPECTED SIBLING\n",
    )
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert "unexpected .deb filename" in result.stderr
    assert "canonical name must be" in result.stderr


# ------------------------------------------------------- 9. zero-byte artifact


def test_zero_byte_required_artifact_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / "os" / "rpm" / RPM_NAME).write_bytes(b"")
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert "empty (0 bytes)" in result.stderr
    assert RPM_NAME in result.stderr


def test_zero_byte_sdist_fails(tmp_path: Path) -> None:
    _build_valid_artifact_set(tmp_path)
    (tmp_path / SDIST_NAME).write_bytes(b"")
    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert "empty (0 bytes)" in result.stderr


# --------------------------------------------- 10. missing SHA256SUMS entry


def test_missing_sha256sums_entry_fails(tmp_path: Path) -> None:
    """A pre-supplied SHA256SUMS omitting one artifact must fail completeness."""
    _build_valid_artifact_set(tmp_path)
    import hashlib

    lines = []
    for relative in (WHEEL_NAME, SDIST_NAME, f"os/deb/{DEB_NAME}", f"os/rpm/{RPM_NAME}"):
        digest = hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    # Deliberately omit the FreeBSD .pkg entry.
    (tmp_path / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert f"missing expected artifact: os/freebsd/{PKG_NAME}" in result.stderr


# -------------------------------------------------------- 11. corrupted checksum


def test_corrupted_checksum_fails(tmp_path: Path) -> None:
    """A pre-supplied SHA256SUMS with one wrong digest must fail verification."""
    _build_valid_artifact_set(tmp_path)
    import hashlib

    lines = []
    for relative in (
        WHEEL_NAME,
        SDIST_NAME,
        f"os/deb/{DEB_NAME}",
        f"os/rpm/{RPM_NAME}",
        f"os/freebsd/{PKG_NAME}",
    ):
        digest = hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        if relative == WHEEL_NAME:
            # Flip the leading hex digit to guarantee a mismatch.
            flipped = "f" if digest[0] != "f" else "0"
            digest = flipped + digest[1:]
        lines.append(f"{digest}  {relative}")
    (tmp_path / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run_contract(tmp_path)
    assert result.returncode != 0
    assert "FAILED" in result.stdout


# ------------------------------------------------- 13. native/full mode intact


def test_full_release_gate_does_not_use_contract_only_mode() -> None:
    """check_release_quality.sh must keep invoking the strict, native path."""
    text = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")
    assert "check_release_artifacts.sh" in text
    assert "--contract-only" not in text


def test_build_release_artifacts_script_does_not_use_contract_only_mode() -> None:
    text = (REPO_ROOT / "scripts" / "build_release_artifacts.sh").read_text(encoding="utf-8")
    assert "check_release_artifacts.sh" in text
    assert "--contract-only" not in text


def test_release_artifacts_workflow_does_not_use_contract_only_mode() -> None:
    """release-artifacts.yml must keep requiring the real, full artifact set."""
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "check_release_artifacts.sh" in text
    assert "--contract-only" not in text


def test_default_invocation_still_targets_real_dist_directory() -> None:
    """No-args invocation must still resolve to the repository's real dist/."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'DIST_DIR="${1:-${REPO_ROOT}/dist}"' in text


# --------------------------------------------------- 14. CI wiring, no impossible gate


def test_ci_workflow_runs_contract_gate_unconditionally() -> None:
    """ci.yml must invoke the contract gate without an unreachable FreeBSD guard."""
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check_release_artifacts.sh --contract-only" in text
    # The old impossible precondition (full artifact set including a real
    # FreeBSD .pkg) must be gone -- that was always false on ubuntu-latest.
    assert "dist/os/freebsd/*.pkg" not in text
    assert "Skipping check_release_artifacts.sh" not in text


def test_ci_workflow_contract_fixture_is_isolated_and_labeled() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'CONTRACT_DIR="$(mktemp -d)"' in text
    assert "NOT A REAL FREEBSD PACKAGE" in text
    assert 'rm -rf "${CONTRACT_DIR}"' in text


def test_ci_workflow_contract_gate_runs_after_native_builds() -> None:
    """The contract gate must run after real deb/rpm are built, not before."""
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deb_index = text.index("Build Debian .deb")
    rpm_index = text.index("Build RPM .rpm")
    contract_index = text.index("Verify artifact contract")
    assert deb_index < contract_index
    assert rpm_index < contract_index


# --------------------------------------------------------------- CLI hygiene


def test_extra_positional_argument_is_rejected(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--contract-only", str(tmp_path), "unexpected"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_default_mode_label_and_contract_only_label_differ(tmp_path: Path) -> None:
    """Contract-only runs must never be confused with a full/native validation."""
    _build_valid_artifact_set(tmp_path)
    result = _run_contract(tmp_path)
    assert "(contract-only mode)" in result.stdout
    assert "does not perform" in result.stdout.lower() or "did not perform" in result.stdout.lower()
