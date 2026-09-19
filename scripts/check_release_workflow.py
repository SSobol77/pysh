#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_release_workflow.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""GitHub release-asset workflow completeness gate for Issue #33 (RQG-G).

Validates two things, deliberately kept separate:

1. Structural facts about ``.github/workflows/release-artifacts.yml`` and
   ``.github/workflows/publish.yml`` that can only be checked as text (job
   ``needs:``/``if:`` wiring, absence of ``continue-on-error``, upload step
   ordering) -- this is exactly the "GitHub-specific dependency wiring that
   cannot be executed locally" the design explicitly allows string checks
   for. This module does not parse full GitHub Actions semantics and is
   not a YAML dependency: it uses plain stdlib text/regex matching, the
   same approach already used by tests/test_docs_consistency.py for these
   same files.

2. The REAL pre-upload validation sequence the workflow performs --
   ``scripts/check_release_metadata.sh --release-mode [--tag ...]``
   followed by ``scripts/check_release_artifacts.sh --contract-only
   <dir>`` -- executed against a caller-supplied artifact directory. This
   reuses the exact existing scripts (RQG-B, RQG-C) rather than
   reimplementing their logic, and never touches the real ``dist/`` or a
   real GitHub release.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
METADATA_SCRIPT = REPO_ROOT / "scripts" / "check_release_metadata.sh"
ARTIFACTS_SCRIPT = REPO_ROOT / "scripts" / "check_release_artifacts.sh"


class WorkflowContractError(Exception):
    pass


# ------------------------------------------------------- structural checks


def check_release_artifacts_workflow_structure(text: str) -> list[str]:
    """Static facts about release-artifacts.yml's job graph and gating."""
    errors: list[str] = []

    required_substrings = (
        "needs: freebsd-pkg",
        "needs: build-and-validate",
        "if: github.event_name == 'release'",
        "bash scripts/check_release_metadata.sh --release-mode",
        "bash scripts/check_release_artifacts.sh",
        "actions/upload-artifact",
        "actions/download-artifact",
        "name: release-assets",
        "gh release upload",
    )
    for substring in required_substrings:
        if substring not in text:
            errors.append(f"release-artifacts.yml: missing required text: {substring!r}")

    if "continue-on-error" in text:
        errors.append("release-artifacts.yml: must never use continue-on-error")

    # The upload step must textually follow the artifact-validation step,
    # and the artifact-validation step must follow the metadata gate --
    # proving validation precedes publishing, not just that both exist.
    try:
        metadata_idx = text.index("check_release_metadata.sh --release-mode")
        artifacts_idx = text.index("check_release_artifacts.sh")
        upload_idx = text.index("gh release upload")
    except ValueError as exc:
        errors.append(f"release-artifacts.yml: could not locate expected step: {exc}")
    else:
        if not (metadata_idx < artifacts_idx < upload_idx):
            errors.append(
                "release-artifacts.yml: steps are out of order; expected metadata "
                "gate, then artifact validation, then upload"
            )

    # A fake/contract-only FreeBSD artifact must never enter the real
    # release path -- that fixture technique is exclusive to ci.yml's
    # portable contract gate (RQG-C).
    if "--contract-only" in text:
        errors.append(
            "release-artifacts.yml: must never use --contract-only; the real "
            "release path requires the genuine FreeBSD VM-built .pkg"
        )
    if "vmactions/freebsd-vm" not in text and "cross-platform-actions/action" not in text:
        errors.append("release-artifacts.yml: missing the real FreeBSD VM build action")

    return errors


def check_publish_workflow_structure(text: str) -> list[str]:
    """publish.yml must gate PyPI publication on the same metadata contract."""
    errors: list[str] = []
    required_substrings = (
        "bash scripts/check_release_metadata.sh --release-mode",
        "github.event.release.tag_name",
        "pypa/gh-action-pypi-publish",
    )
    for substring in required_substrings:
        if substring not in text:
            errors.append(f"publish.yml: missing required text: {substring!r}")

    if "continue-on-error" in text:
        errors.append("publish.yml: must never use continue-on-error")

    try:
        metadata_idx = text.index("check_release_metadata.sh --release-mode")
        publish_idx = text.index("pypa/gh-action-pypi-publish")
    except ValueError as exc:
        errors.append(f"publish.yml: could not locate expected step: {exc}")
    else:
        if not (metadata_idx < publish_idx):
            errors.append(
                "publish.yml: metadata gate must precede the PyPI publish step"
            )

    # publish.yml must never duplicate GitHub release asset publication --
    # that responsibility belongs exclusively to release-artifacts.yml.
    if "gh release upload" in text:
        errors.append(
            "publish.yml: must not upload GitHub Release assets; that is "
            "release-artifacts.yml's exclusive responsibility"
        )
    for forbidden in ("dist/os/deb", "dist/os/rpm", "dist/os/freebsd", "build_deb.sh", "build_rpm.sh"):
        if forbidden in text:
            errors.append(
                f"publish.yml: must not build/reference OS packages ({forbidden!r}); "
                "PyPI publication is wheel/sdist only"
            )

    return errors


def check_no_dead_freebsd_workflow() -> list[str]:
    dead = REPO_ROOT / ".github" / "workflows" / "freebsd-pkg.yml"
    if dead.exists():
        return [
            f"{dead}: must not exist -- retired as a byte-for-byte duplicate of "
            "release-artifacts.yml's freebsd-pkg job (RQG-G decision)"
        ]
    return []


def run_structural_checks() -> list[str]:
    errors: list[str] = []
    errors += check_release_artifacts_workflow_structure(
        RELEASE_WORKFLOW.read_text(encoding="utf-8")
    )
    errors += check_publish_workflow_structure(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    errors += check_no_dead_freebsd_workflow()
    return errors


# -------------------------------------------------- dynamic pre-upload sequence


def simulate_pre_upload_sequence(
    artifact_dir: Path,
    *,
    release_mode: bool = True,
    tag: str | None = None,
    changelog: Path | None = None,
    target_version: str | None = None,
) -> list[str]:
    """Run the exact sequence release-artifacts.yml runs before uploading.

    1. scripts/check_release_metadata.sh [--release-mode] [--tag TAG]
    2. scripts/check_release_artifacts.sh --contract-only <artifact_dir>

    Both are the real scripts (RQG-B, RQG-C); nothing here reimplements
    their validation logic. Returns the combined error list; empty means
    the sequence would allow an upload to proceed.
    """
    errors: list[str] = []

    metadata_args = [str(METADATA_SCRIPT)]
    if release_mode:
        metadata_args.append("--release-mode")
    if tag:
        metadata_args += ["--tag", tag]
    if changelog:
        metadata_args += ["--changelog", str(changelog)]
    if target_version:
        metadata_args += ["--target-version", target_version]

    metadata_result = subprocess.run(
        ["bash", *metadata_args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if metadata_result.returncode != 0:
        errors.append(f"metadata gate failed: {metadata_result.stderr.strip()}")
        # The real workflow's steps run sequentially and stop at the first
        # failure -- a failed metadata gate means the artifact gate (and
        # the upload after it) never runs.
        return errors

    artifacts_result = subprocess.run(
        ["bash", str(ARTIFACTS_SCRIPT), "--contract-only", str(artifact_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if artifacts_result.returncode != 0:
        errors.append(f"artifact gate failed: {artifacts_result.stderr.strip()}")

    return errors


# ------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulate",
        type=Path,
        metavar="ARTIFACT_DIR",
        help="also run the real pre-upload validation sequence against this directory",
    )
    parser.add_argument("--tag", default=None, help="tag to validate in the simulated sequence")
    args = parser.parse_args(argv)

    errors = run_structural_checks()

    if args.simulate is not None:
        errors += simulate_pre_upload_sequence(args.simulate, tag=args.tag)

    if errors:
        for error in errors:
            print(f"check_release_workflow.py: {error}", file=sys.stderr)
        return 1

    print("check_release_workflow.py: all release workflow checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
