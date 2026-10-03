#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/verify_release_attestations.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Verify the release attestations before the bundle may reach the upload job (Issue #51, Slice 3).

An ONLINE CI verifier. It contains no signing logic and creates nothing: it invokes the
GitHub CLI (``gh attestation verify``) with explicit argv lists, never a shell, and fails
closed. Identities are pinned in this file:

* repository ``SSobol77/pysh``;
* signer workflow ``SSobol77/pysh/.github/workflows/release-artifacts.yml``;
* the exact source commit (``--source-digest``, the Actions ``GITHUB_SHA``).

For every one of the eleven public release files it verifies the SLSA provenance
attestation. For each of the five package artifacts it additionally verifies the signed
SPDX 2.3 SBOM attestation and requires the attested predicate to equal the local
``.spdx.json`` document that will be published.

Attestations are written before they are queried, so a *narrowly classified* "not visible
yet" answer is retried a bounded number of times within a bounded wall-clock budget.
Signature, identity, digest or predicate failures are never retried.

Exit codes: 0 everything verified, 1 verification failed, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import generate_release_sboms as sboms  # noqa: E402
from scripts import prepare_attestation_subjects as subjects  # noqa: E402

PINNED_REPO = "SSobol77/pysh"
PINNED_SIGNER_WORKFLOW = "SSobol77/pysh/.github/workflows/release-artifacts.yml"
PROVENANCE_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
SPDX_PREDICATE_TYPE = "https://spdx.dev/Document/v2.3"
SOURCE_DIGEST_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

#: The ONLY condition that is retried: GitHub does not list the attestation (yet).
NOT_VISIBLE_PATTERN = r"\bno attestations? found\b"
#: Hard bounds. Attempts per verification, delay between them, and a shared wall-clock budget.
MAX_ATTEMPTS = 6
RETRY_DELAY_SECONDS = 5.0
MAX_RETRY_WALL_SECONDS = 120.0
GH_TIMEOUT_SECONDS = 120
MAX_ERROR_CHARS = 600


class AttestationError(Exception):
    """A verification failure; the message names the file concerned."""


@dataclass(frozen=True)
class GhResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], GhResult]


def gh_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The host environment (``gh`` needs its token) with interactive features disabled."""
    env = dict(os.environ if environ is None else environ)
    env.update({"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"})
    return env


def subprocess_runner(argv: Sequence[str]) -> GhResult:
    """Run ``argv`` (an explicit list, never a shell) with a hard timeout."""
    try:
        done = subprocess.run(  # noqa: S603 - explicit argv, no shell
            list(argv), capture_output=True, text=True, check=False,
            env=gh_environment(), timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise AttestationError(f"the GitHub CLI timed out after {GH_TIMEOUT_SECONDS}s") from error
    except OSError as error:
        raise AttestationError(f"cannot execute the GitHub CLI: {error.strerror or error}") from error
    return GhResult(done.returncode, done.stdout, done.stderr)


def verify_argv(
    gh: Path, target: Path, *, repo: str, signer_workflow: str, source_digest: str, predicate_type: str
) -> list[str]:
    """The exact ``gh attestation verify`` command line (identity flags are always present)."""
    return [
        str(gh), "attestation", "verify", str(target),
        "--repo", repo,
        "--signer-workflow", signer_workflow,
        "--source-digest", source_digest,
        "--predicate-type", predicate_type,
        "--format", "json",
    ]


class Verifier:
    """Verifies provenance and SBOM attestations through an injectable ``gh`` runner."""

    def __init__(
        self,
        gh: Path,
        *,
        repo: str,
        signer_workflow: str,
        source_digest: str,
        runner: Runner = subprocess_runner,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        out: Callable[[str], None] = print,
    ) -> None:
        if repo != PINNED_REPO:
            raise AttestationError(f"the repository identity is pinned to {PINNED_REPO}, not {repo!r}")
        if signer_workflow != PINNED_SIGNER_WORKFLOW:
            raise AttestationError(f"the signer workflow is pinned to {PINNED_SIGNER_WORKFLOW}, not {signer_workflow!r}")
        if SOURCE_DIGEST_RE.fullmatch(source_digest) is None:
            raise AttestationError("the source digest must be the exact lowercase hexadecimal commit SHA")
        self.gh = gh
        self.repo = repo
        self.signer_workflow = signer_workflow
        self.source_digest = source_digest
        self.runner = runner
        self.sleep = sleep
        self.clock = clock
        self.out = out
        self.deadline = clock() + MAX_RETRY_WALL_SECONDS

    # -- one verification, with bounded consistency retry ---------------------------------------

    def _run(self, label: str, target: Path, predicate_type: str) -> list[dict[str, Any]]:
        argv = verify_argv(
            self.gh, target, repo=self.repo, signer_workflow=self.signer_workflow,
            source_digest=self.source_digest, predicate_type=predicate_type,
        )
        result = self.runner(argv)
        for attempt in range(1, MAX_ATTEMPTS):
            if result.returncode == 0:
                break
            if re.search(NOT_VISIBLE_PATTERN, f"{result.stdout}\n{result.stderr}", re.I) is None:
                break  # a signature, identity, digest or predicate failure is final
            if self.clock() + RETRY_DELAY_SECONDS > self.deadline:
                break  # the shared wall-clock budget is spent
            self.out(f"verify_release_attestations: {label}: attestation not visible yet (attempt {attempt}/{MAX_ATTEMPTS})")
            self.sleep(RETRY_DELAY_SECONDS)
            result = self.runner(argv)
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout).split())[:MAX_ERROR_CHARS]
            raise AttestationError(f"{label}: gh attestation verify failed (exit {result.returncode}): {detail}")
        return parse_results(label, result.stdout)

    # -- provenance ---------------------------------------------------------------------------------

    def verify_provenance(self, path: Path, digest: str, expected: Sequence[subjects.Subject]) -> None:
        """SLSA provenance for one release file, whose statement must list the full subject set."""
        label = f"{path.name} (provenance)"
        statements = self._run(label, path, PROVENANCE_PREDICATE_TYPE)
        wanted = {(s.name, s.sha256) for s in expected}
        for statement in statements:
            check_statement(label, statement, PROVENANCE_PREDICATE_TYPE, path.name, digest)
        if not any(statement_subjects(statement) == wanted for statement in statements):
            raise AttestationError(f"{label}: no verified statement covers the complete subject set (partial subject set)")

    # -- SBOM -------------------------------------------------------------------------------------------

    def verify_sbom(self, package: Path, digest: str, sbom: Path) -> None:
        """Signed SPDX attestation of a package; its predicate must equal the local SBOM."""
        label = f"{package.name} (SPDX SBOM)"
        statements = self._run(label, package, SPDX_PREDICATE_TYPE)
        try:
            local = json.loads(sbom.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise AttestationError(f"{label}: cannot read the local SBOM {sbom.name}") from error
        for statement in statements:
            check_statement(label, statement, SPDX_PREDICATE_TYPE, package.name, digest)
        if not any(statement.get("predicate") == local for statement in statements):
            raise AttestationError(f"{label}: the attested predicate differs from the published {sbom.name}")

    # -- whole bundle ---------------------------------------------------------------------------------------

    def verify_bundle(self, assets_dir: Path, version: str) -> int:
        """All eleven provenance attestations and all five SBOM attestations; fail fast."""
        bundle = subjects.prepare(assets_dir, version)
        manifest_subjects = bundle.manifest_subjects()
        for subject in manifest_subjects:
            self.verify_provenance(assets_dir / subject.name, subject.sha256, manifest_subjects)
            self.out(f"verified provenance: {subject.name}")
        self.verify_provenance(assets_dir / bundle.checksums.name, bundle.checksums.sha256, (bundle.checksums,))
        self.out(f"verified provenance: {bundle.checksums.name}")
        for entry in bundle.packages:
            self.verify_sbom(assets_dir / entry.package.name, entry.package.sha256, assets_dir / entry.sbom.name)
            self.out(f"verified SPDX SBOM attestation: {entry.package.name}")
        return subjects.SUBJECT_COUNT


# --- verified-output parsing (pure functions) -------------------------------------------------------------


def parse_results(label: str, stdout: str) -> list[dict[str, Any]]:
    """The verified statements of ``gh attestation verify --format json`` output."""
    try:
        document = json.loads(stdout)
    except ValueError as error:
        raise AttestationError(f"{label}: malformed gh JSON output") from error
    if not isinstance(document, list) or not document:
        raise AttestationError(f"{label}: malformed gh JSON output (expected a non-empty list of verification results)")
    statements: list[dict[str, Any]] = []
    for item in document:
        result = item.get("verificationResult") if isinstance(item, dict) else None
        statement = result.get("statement") if isinstance(result, dict) else None
        if not isinstance(statement, dict):
            raise AttestationError(f"{label}: malformed gh JSON output (no verified statement)")
        statements.append(statement)
    return statements


def statement_subjects(statement: Mapping[str, Any]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for item in statement.get("subject") or ():
        digest = item.get("digest") if isinstance(item, dict) else None
        name = item.get("name") if isinstance(item, dict) else None
        sha = digest.get("sha256") if isinstance(digest, dict) else None
        if isinstance(name, str) and isinstance(sha, str):
            found.add((name, sha))
    return found


def check_statement(label: str, statement: Mapping[str, Any], predicate_type: str, name: str, digest: str) -> None:
    """A verified statement must have the expected predicate type and name this exact file."""
    if statement.get("predicateType") != predicate_type:
        raise AttestationError(f"{label}: wrong predicate type {statement.get('predicateType')!r}, expected {predicate_type}")
    if (name, digest) not in statement_subjects(statement):
        raise AttestationError(f"{label}: the verified statement does not name {name} at sha256:{digest[:12]}... (subject mismatch)")


# --- command line ------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None, runner: Runner = subprocess_runner) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--assets-dir", type=Path, required=True, help="the final dist/release-assets directory")
    parser.add_argument("--repo", default=PINNED_REPO, help=f"pinned to {PINNED_REPO}")
    parser.add_argument("--signer-workflow", default=PINNED_SIGNER_WORKFLOW, help=f"pinned to {PINNED_SIGNER_WORKFLOW}")
    parser.add_argument("--source-digest", required=True, help="the exact release source commit (GITHUB_SHA)")
    parser.add_argument("--gh", type=Path, help="absolute path of the GitHub CLI (default: gh from PATH)")
    parser.add_argument("--version", help="release version (default: pyproject.toml)")
    args = parser.parse_args(argv)
    gh = args.gh
    if gh is None:
        found = next(
            (Path(d) / "gh" for d in os.environ.get("PATH", "").split(os.pathsep)
             if d and os.access(Path(d) / "gh", os.X_OK)),
            None,
        )
        if found is None:
            print("verify_release_attestations: the GitHub CLI (gh) was not found on PATH", file=sys.stderr)
            return 2
        gh = found
    if not gh.is_absolute():
        print("verify_release_attestations: --gh must be an absolute path", file=sys.stderr)
        return 2
    try:
        verifier = Verifier(
            gh, repo=args.repo, signer_workflow=args.signer_workflow,
            source_digest=args.source_digest, runner=runner,
        )
    except AttestationError as error:
        print(f"verify_release_attestations: {error}", file=sys.stderr)
        return 2
    try:
        version = args.version or sboms.project_version()
        count = verifier.verify_bundle(args.assets_dir, version)
    except (AttestationError, subjects.SubjectError, sboms.SbomError, OSError) as error:
        print(f"verify_release_attestations: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"verify_release_attestations: PASS: {count} provenance attestations and 5 SPDX SBOM attestations verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
