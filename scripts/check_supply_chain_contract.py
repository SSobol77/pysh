#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_supply_chain_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structural supply-chain contract check for Issue #51 (Slices 1-5).

Read-only, deterministic and offline: it validates the repository-owned policy
(``docs/security/supply-chain.md``), its agreement with the packaging contract, and
the structure of the release and publication workflows. It performs no
cryptographic verification, calls no external tool and touches neither the network
nor the repository.

Two classes of requirements are kept apart:

* CURRENT structural invariants must hold now; a violation fails the check. Since
  Slice 2 they include real SBOM generation (the generator, its pinned tool, its
  position in the release workflow and the checksum policy); since Slice 3 they include
  keyless provenance and SBOM attestations with verification before upload (the pinned
  attestation action, the permission split, the step ordering and the verifier pins).
  Since Slice 4 they include per-artifact reproducibility measurement (the A/B harness,
  the evidence validator, the published ``REPRODUCIBILITY.json``, the commit-timestamp
  epoch policy and the evidence-before-checksums ordering).
  Since Slice 5 they include the permanent Tier-1 evidence record
  (``docs/security/supply-chain-evidence.md``): the record is pinned offline, so the checker
  never queries GitHub and fast mode stays offline.

Exit codes: 0 contract holds, 1 contract violation, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REPOSITORY_IDENTITY = "SSobol77/pysh"
REPRODUCIBILITY_STATUSES = frozenset(
    {"REPRODUCIBLE", "NON_REPRODUCIBLE", "NOT_YET_MEASURED", "PLATFORM_BLOCKED"}
)


@dataclass(frozen=True)
class ArtifactFamily:
    """One mandatory release artifact family. File names stay owned by packaging."""

    family_id: str
    role: str
    requires_sbom: bool
    requires_provenance: bool
    reproducibility_required: bool
    #: Substring that must appear in the packaging contract and the artifact checker.
    naming_marker: str


FAMILIES: tuple[ArtifactFamily, ...] = (
    ArtifactFamily("wheel", "PyPI wheel", True, True, True, ".whl"),
    ArtifactFamily("sdist", "PyPI source distribution", True, True, True, ".tar.gz"),
    ArtifactFamily("deb", "Debian package", True, True, True, ".deb"),
    ArtifactFamily("rpm", "RPM package", True, True, True, ".rpm"),
    ArtifactFamily("freebsd_pkg", "FreeBSD reference package", True, True, True, ".pkg"),
    ArtifactFamily("checksums", "SHA256SUMS integrity manifest", False, True, False, "SHA256SUMS"),
)

REQUIRED_ANCHORS = (
    "PYSH-SC-SCOPE", "PYSH-SC-ARTIFACTS", "PYSH-SC-TRUST", "PYSH-SC-SBOM",
    "PYSH-SC-PROVENANCE", "PYSH-SC-INTEGRITY", "PYSH-SC-VERIFY", "PYSH-SC-FAIL-CLOSED",
    "PYSH-SC-TRUST-ROOT", "PYSH-SC-REPRODUCIBILITY", "PYSH-SC-PIPELINE", "PYSH-SC-PYPI",
    "PYSH-SC-ECOSYSTEM", "PYSH-SC-RELEASE-EVIDENCE",
)
#: Fail-closed conditions, each of which must be an explicit DENY line.
FAIL_CLOSED_CONDITIONS = ("missing", "invalid", "unexpected", "mismatch", "infrastructure")
#: Ordered future pipeline stages (matched case-insensitively in order).
PIPELINE_STAGES = (
    "build", "smoke", "stage", "sbom", "sha256sums", "artifact-set", "provenance",
    "verification", "upload",
)

DOC = Path("docs/security/supply-chain.md")
PACKAGING_DOC = Path("docs/development/packaging.md")
ARTIFACT_CHECKER = Path("scripts/check_release_artifacts.sh")
SBOM_GENERATOR = Path("scripts/generate_release_sboms.py")
SUBJECT_HELPER = Path("scripts/prepare_attestation_subjects.py")
ATTESTATION_VERIFIER = Path("scripts/verify_release_attestations.py")
REPRO_HARNESS = Path("scripts/measure_release_reproducibility.py")
REPRO_VALIDATOR = Path("scripts/check_reproducibility_evidence.py")
EVIDENCE_DOC = Path("docs/security/supply-chain-evidence.md")
RELEASE_DOC = Path("docs/development/release.md")
WORKFLOWS = Path(".github/workflows")
RELEASE_WORKFLOW = WORKFLOWS / "release-artifacts.yml"
PUBLISH_WORKFLOW = WORKFLOWS / "publish.yml"

#: Anything that attaches or edits GitHub Release assets.
RELEASE_UPLOAD_PATTERNS = (
    r"\bgh\s+release\s+(?:upload|create|edit)\b",
    r"softprops/action-gh-release",
    r"actions/upload-release-asset",
    r"ncipollo/release-action",
    r"svenstaro/upload-release-action",
    r"marvinpinto/action-automatic-releases",
    r"\bgh\s+api\b[^\n]*releases",
)
SIGNING_SECRET_RE = re.compile(r"secrets\.(?!GITHUB_TOKEN\b)\w*(?:KEY|SIGN|GPG|COSIGN|PRIVATE|PASSPHRASE)\w*", re.I)
PYPI_TOKEN_RE = re.compile(r"PYPI_API_TOKEN|TWINE_PASSWORD|TWINE_USERNAME|secrets\.PYPI", re.I)
NEGATION_RE = re.compile(r"\b(no|not|never|without|nor|neither|must not|does not|do not)\b", re.I)
KEY_REQUIREMENT_RE = re.compile(
    r"(?:requires?|needs?|stored in|uploaded to)\b[^.\n]*\b(?:private|long-lived|maintainer)\b[^.\n]*\bkey\b", re.I
)
SECRET_KEY_TOKEN_RE = re.compile(r"\b(?:COSIGN|GPG|SIGNING|PRIVATE)_[A-Z_]*KEY\b|secrets\.[A-Z_]*(?:KEY|GPG|COSIGN)\b")


#: The one reviewed attestation action: actions/attest v4.2.2 at an immutable commit.
ATTEST_ACTION = "actions/attest"
ATTEST_SHA = "1e69f48acb82d1966a394da916b4c1698aa569d6"
ATTEST_VERSION = "v4.2.2"
SIGNER_WORKFLOW = "SSobol77/pysh/.github/workflows/release-artifacts.yml"
SPDX_PREDICATE_TYPE = "https://spdx.dev/Document/v2.3"
#: Permissions of build-and-validate (the only job that signs) and of upload (the only job that writes).
BUILD_PERMISSIONS = {
    "contents": "read", "id-token": "write", "attestations": "write", "artifact-metadata": "write",
}
UPLOAD_PERMISSIONS = {"contents": "write"}
#: Any other signing mechanism, deprecated attestation action or key-based path.
ALTERNATIVE_SIGNING_RE = re.compile(
    r"cosign|sigstore/|slsa-framework/|attest-build-provenance|attest-sbom|minisign"
    r"|\bgpg\b[^\n]*--(?:detach-)?sign|ssh-keygen\s+-Y\s+sign|openssl\s+(?:dgst|pkeyutl)[^\n]*-sign",
    re.I,
)
#: Inputs that would let an attestation step bypass the repository-owned subject derivation.
FORBIDDEN_ATTEST_INPUTS_RE = re.compile(
    r"^\s+(?:subject-path|predicate-type|predicate-path|predicate|push-to-registry):", re.M
)


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    message: str


def _read(root: Path, relative: Path) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _code(text: str) -> str:
    """Workflow text without comment lines, so prose cannot satisfy or violate a check."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


# --- documentation ---------------------------------------------------------------------------


def split_sections(text: str) -> dict[str, str]:
    """Map each ``PYSH-SC-*`` anchor to the text up to the next anchor."""
    matches = list(re.finditer(r'<a id="(PYSH-SC-[A-Z-]+)"></a>', text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.setdefault(match.group(1), text[match.end():end])
    return sections


def _table_rows(section: str) -> dict[str, list[str]]:
    """Rows of a markdown table keyed by the backticked first cell (header/separator skipped)."""
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        match = re.fullmatch(r"`([a-z_]+)`", cells[0])
        if match:
            rows[match.group(1)] = cells
        elif cells[0].startswith("`SHA256SUMS`"):
            rows["checksums"] = cells
    return rows


def _negation_context(lines: list[str], index: int) -> str:
    """The sentence context that can negate ``lines[index]``.

    A bullet is negated by the paragraph that introduces its list ("This contract
    does not: - require ..."); any other line only by its own paragraph.
    """
    start = index
    is_bullet = lines[index].lstrip().startswith(("- ", "* "))
    while start > 0 and index - start < 12:
        previous = lines[start - 1]
        if is_bullet:
            if previous.strip() and not previous.lstrip().startswith(("- ", "* ")):
                start -= 1
                break  # the introducing paragraph line
        elif not previous.strip():
            break
        start -= 1
    return " ".join(lines[start:index + 1])


def check_documentation(root: Path) -> list[Violation]:
    text = _read(root, DOC)
    if text is None:
        return [Violation("DOC-MISSING", f"{DOC} is missing")]
    out: list[Violation] = []
    sections = split_sections(text)
    for anchor in REQUIRED_ANCHORS:
        if text.count(f'<a id="{anchor}"></a>') != 1:
            out.append(Violation("DOC-ANCHOR", f"anchor {anchor} must be defined exactly once in {DOC}"))

    rows = _table_rows(sections.get("PYSH-SC-ARTIFACTS", ""))
    for family in FAMILIES:
        row = rows.get(family.family_id)
        if row is None or len(row) < 4:
            out.append(Violation("DOC-ARTIFACT-FAMILY", f"artifact family {family.family_id!r} is not in the artifact table"))
            continue
        if family.naming_marker not in row[1]:
            out.append(Violation("DOC-ARTIFACT-FAMILY", f"family {family.family_id!r} must name {family.naming_marker!r}"))
        if ("required" in row[2].lower() and "not" not in row[2].lower()) != family.requires_sbom:
            out.append(Violation("DOC-FAMILY-FLAGS", f"SBOM requirement of {family.family_id!r} disagrees with the contract model"))
        if ("required" in row[3].lower()) != family.requires_provenance:
            out.append(Violation("DOC-FAMILY-FLAGS", f"provenance requirement of {family.family_id!r} disagrees with the contract model"))
    extra = sorted(set(rows) - {f.family_id for f in FAMILIES})
    if extra:
        out.append(Violation("DOC-ARTIFACT-FAMILY", f"artifact table lists unknown families: {extra}"))

    repro = sections.get("PYSH-SC-REPRODUCIBILITY", "")
    for status in sorted(REPRODUCIBILITY_STATUSES):
        if f"`{status}`" not in repro:
            out.append(Violation("DOC-REPRODUCIBILITY", f"status {status} is not defined"))
    repro_rows = _table_rows(repro)
    for family in FAMILIES:
        if not family.reproducibility_required:
            continue
        row = repro_rows.get(family.family_id)
        if row is None or row[-1] not in REPRODUCIBILITY_STATUSES:
            out.append(Violation("DOC-REPRODUCIBILITY", f"family {family.family_id!r} has no valid reproducibility status"))

    closed = sections.get("PYSH-SC-FAIL-CLOSED", "")
    for condition in FAIL_CLOSED_CONDITIONS:
        if not any(condition in line.lower() and "DENY" in line for line in closed.splitlines()):
            out.append(Violation("DOC-FAIL-CLOSED", f"fail-closed policy lacks a DENY rule for: {condition}"))

    verify_identities = re.findall(r"--repo[ =]+(\S+)", text)
    if REPOSITORY_IDENTITY not in verify_identities or any(i != REPOSITORY_IDENTITY for i in verify_identities):
        out.append(Violation("DOC-IDENTITY", f"verification must name exactly the repository {REPOSITORY_IDENTITY}: found {sorted(set(verify_identities))}"))
    if REPOSITORY_IDENTITY not in sections.get("PYSH-SC-PROVENANCE", ""):
        out.append(Violation("DOC-IDENTITY", f"provenance policy must bind the repository identity {REPOSITORY_IDENTITY}"))

    trust = sections.get("PYSH-SC-TRUST", "").lower()
    if "no long-lived private signing key" not in " ".join(trust.split()):
        out.append(Violation("DOC-KEYS", "the trust model must state there is no long-lived private signing key"))
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if SECRET_KEY_TOKEN_RE.search(line) or (
            KEY_REQUIREMENT_RE.search(line) and not NEGATION_RE.search(_negation_context(lines, number - 1))
        ):
            out.append(Violation("DOC-KEYS", f"{DOC}:{number}: a private signing key or signing secret must not be required"))

    steps = [
        line.lower() for line in sections.get("PYSH-SC-PIPELINE", "").splitlines()
        if re.match(r"\d+\.\s", line)
    ]
    position = -1
    for stage in PIPELINE_STAGES:
        found = next((i for i, step in enumerate(steps) if stage in step), -1)
        if found <= position:
            out.append(Violation("DOC-PIPELINE", f"the numbered future ordering must contain stage {stage!r} after the previous stage"))
            break
        position = found
    scope = " ".join(sections.get("PYSH-SC-SCOPE", "").replace("*", "").split())
    for needle, why in (
        ("supply-chain-evidence.md", "link the permanent evidence record"),
        ("is not the final v1.0.0 release attestation", "say that the evidence is not the final v1.0.0 release attestation"),
        ("must rerun the same assurance pipeline on its final release SHA", "require the v1.0.0 release to rerun the pipeline on its final SHA"),
    ):
        if needle not in scope:
            out.append(Violation("DOC-PIPELINE", f"the scope must {why}: {needle!r}"))

    pypi = sections.get("PYSH-SC-PYPI", "")
    if "Trusted Publishing" not in pypi or "publish.yml" not in pypi or "second PyPI publisher" not in pypi:
        out.append(Violation("DOC-PYPI", "the PyPI section must keep Trusted Publishing via publish.yml and forbid a second publisher"))
    eco = sections.get("PYSH-SC-ECOSYSTEM", "")
    if "default-deny" not in eco:
        out.append(Violation("DOC-ECOSYSTEM", "the ecosystem section must define default-deny installation"))
    root_text = sections.get("PYSH-SC-TRUST-ROOT", "").lower()
    for word in ("online", "offline", "rotation", "not a pysh signing key"):
        if word not in root_text:
            out.append(Violation("DOC-TRUST-ROOT", f"the trust-root policy must cover: {word}"))
    if "#35" not in sections.get("PYSH-SC-RELEASE-EVIDENCE", ""):
        out.append(Violation("DOC-RELEASE-EVIDENCE", "release evidence must be tied to the readiness audit #35"))
    return out


def check_packaging_agreement(root: Path) -> list[Violation]:
    """The supply-chain families and the packaging contract must name the same artifacts."""
    out: list[Violation] = []
    packaging = _read(root, PACKAGING_DOC)
    naming_owner = _read(root, ARTIFACT_CHECKER)
    doc = _read(root, DOC)
    if packaging is None:
        return [Violation("PKG-MISSING", f"{PACKAGING_DOC} is missing")]
    if naming_owner is None:
        out.append(Violation("PKG-MISSING", f"{ARTIFACT_CHECKER} is missing"))
    for family in FAMILIES:
        if family.naming_marker not in packaging:
            out.append(Violation("PKG-FAMILY", f"{PACKAGING_DOC} does not name the {family.family_id!r} family ({family.naming_marker})"))
        if naming_owner is not None and family.naming_marker not in naming_owner:
            out.append(Violation("PKG-FAMILY", f"{ARTIFACT_CHECKER} does not own the {family.family_id!r} family ({family.naming_marker})"))
    if doc is not None and "packaging.md" not in doc:
        out.append(Violation("PKG-FAMILY", f"{DOC} must defer file names to packaging.md"))
    return out


# --- workflows -------------------------------------------------------------------------------


def split_jobs(text: str) -> dict[str, str]:
    """Top-level job bodies of a workflow (stdlib text parsing, no YAML dependency)."""
    start = re.search(r"^jobs:\s*$", text, re.M)
    if start is None:
        return {}
    body = text[start.end():]
    matches = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", body, re.M))
    jobs: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        jobs[match.group(1)] = body[match.start():end]
    return jobs


def job_needs(job: str) -> set[str]:
    match = re.search(r"^    needs:[ \t]*(.*)$", job, re.M)
    if match is None:
        return set()
    inline = match.group(1).strip()
    if inline:
        return {n.strip() for n in inline.strip("[]").split(",") if n.strip()}
    names: set[str] = set()
    for line in job[match.end():].splitlines()[1:]:
        item = re.match(r"^      - (\S+)", line)
        if not item:
            break
        names.add(item.group(1))
    return names


def check_release_workflow(root: Path) -> list[Violation]:
    text = _read(root, RELEASE_WORKFLOW)
    if text is None:
        return [Violation("WF-MISSING", f"{RELEASE_WORKFLOW} is missing")]
    code = _code(text)
    jobs = split_jobs(code)
    out: list[Violation] = []
    for name in ("freebsd-pkg", "build-and-validate", "upload"):
        if name not in jobs:
            out.append(Violation("WF-RELEASE-GRAPH", f"{RELEASE_WORKFLOW}: job {name!r} is missing"))
    if out:
        return out
    if "freebsd-pkg" not in job_needs(jobs["build-and-validate"]):
        out.append(Violation("WF-RELEASE-GRAPH", "build-and-validate must depend on freebsd-pkg"))
    if "build-and-validate" not in job_needs(jobs["upload"]):
        out.append(Violation("WF-RELEASE-GRAPH", "upload must depend on build-and-validate"))
    gate = re.search(r"^    if:\s*(.+)$", jobs["upload"], re.M)
    if gate is None or "github.event_name == 'release'" not in gate.group(1):
        out.append(Violation("WF-UPLOAD-GATED", "the upload job must be gated on the release event"))

    validate = jobs["build-and-validate"]
    stage = validate.find("check_release_artifacts.sh")
    handoff = validate.find("name: release-assets")
    if stage < 0 or handoff < 0 or "dist/release-assets" not in validate:
        out.append(Violation("WF-STAGING", "build-and-validate must stage dist/release-assets and hand it over as the release-assets artifact"))
    elif stage > handoff:
        out.append(Violation("WF-STAGING", "canonical staging must precede the release-assets hand-off"))

    upload = jobs["upload"]
    download = re.search(r"download-artifact[\s\S]*?name:\s*release-assets", upload)
    release_cmd = re.search(RELEASE_UPLOAD_PATTERNS[0], upload)
    if download is None:
        out.append(Violation("WF-UPLOAD-ORDER", "the upload job must download the validated release-assets artifact"))
    elif release_cmd is not None and release_cmd.start() < download.start():
        out.append(Violation("WF-UPLOAD-ORDER", "the release upload must come after the validated artifact download"))
    return out


def check_release_upload_exclusivity(root: Path) -> list[Violation]:
    """Only the ``upload`` job of release-artifacts.yml may touch GitHub Release assets."""
    out: list[Violation] = []
    directory = root / WORKFLOWS
    files = sorted(directory.glob("*.y*ml")) if directory.is_dir() else []
    files += sorted((root / ".github" / "actions").rglob("*.y*ml")) if (root / ".github" / "actions").is_dir() else []
    for path in files:
        relative = path.relative_to(root)
        code = _code(path.read_text(encoding="utf-8"))
        if relative == RELEASE_WORKFLOW:
            jobs = split_jobs(code)
            owners = [n for n, body in jobs.items() if any(re.search(p, body) for p in RELEASE_UPLOAD_PATTERNS)]
            if sorted(set(owners) - {"upload"}):
                out.append(Violation("WF-UPLOAD-BYPASS", f"{relative}: release assets are touched outside the upload job: {sorted(set(owners) - {'upload'})}"))
            continue
        for pattern in RELEASE_UPLOAD_PATTERNS:
            if re.search(pattern, code):
                out.append(Violation("WF-UPLOAD-BYPASS", f"{relative}: an independent release-asset upload path ({pattern})"))
    return out


def check_publication_and_secrets(root: Path) -> list[Violation]:
    out: list[Violation] = []
    publish = _read(root, PUBLISH_WORKFLOW)
    if publish is None:
        out.append(Violation("WF-PYPI", f"{PUBLISH_WORKFLOW} is missing"))
    else:
        code = _code(publish)
        if not re.search(r"^\s*id-token:\s*write\s*$", code, re.M):
            out.append(Violation("WF-PYPI", "publish.yml must keep the id-token: write permission"))
        if "pypa/gh-action-pypi-publish@" not in code:
            out.append(Violation("WF-PYPI", "publish.yml must keep the PyPI Trusted Publishing action"))
    directory = root / WORKFLOWS
    for path in sorted(directory.glob("*.y*ml")) if directory.is_dir() else []:
        relative = path.relative_to(root)
        code = _code(path.read_text(encoding="utf-8"))
        if re.search(r"\btwine\s+upload\b", code):
            out.append(Violation("WF-PYPI", f"{relative}: an independent twine upload publication path"))
        if relative != PUBLISH_WORKFLOW and "gh-action-pypi-publish" in code:
            out.append(Violation("WF-PYPI", f"{relative}: a second PyPI publisher (publish.yml is the only one)"))
        if PYPI_TOKEN_RE.search(code):
            out.append(Violation("WF-PYPI", f"{relative}: token-based PyPI credentials (Trusted Publishing only)"))
        if SIGNING_SECRET_RE.search(code):
            out.append(Violation("WF-SECRETS", f"{relative}: a signing key/secret is referenced; keyless signing only"))
    return out


# --- future requirements (reported, never enforced) --------------------------------------------


def future_status(root: Path) -> list[str]:
    """Implemented items (informational): every slice of Issue #51 is implemented."""
    del root
    return [
        "implemented: SPDX 2.3 JSON SBOM generation (Slice 2)",
        "implemented: keyless provenance and SPDX SBOM attestations, verified before upload (Slice 3)",
        "implemented: per-artifact reproducibility measurement and evidence (Slice 4)",
        "implemented: final Tier-1 dry-run release evidence (Slice 5): docs/security/supply-chain-evidence.md",
    ]


#: Actions/tools that produce supply-chain material; any ``uses:`` of them must be SHA-pinned.
SUPPLY_CHAIN_ACTION_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s@]*(?:anchore|syft|sbom|cyclonedx|attest|cosign|sigstore)[^\s@]*)@(\S+)", re.I | re.M)
SBOM_DEPENDENCY_RE = re.compile(r"syft|anchore|spdx|cyclonedx|sbom", re.I)
STATUS_ROWS = (
    ("policy, anchors and structural contract check", "IMPLEMENTED (Slice 1)"),
    ("spdx 2.3 json sbom generation", "IMPLEMENTED (Slice 2)"),
    ("keyless provenance and spdx sbom attestations", "IMPLEMENTED (Slice 3)"),
    ("reproducibility measurement", "IMPLEMENTED (Slice 4)"),
    ("final tier-1 dry-run release evidence", "IMPLEMENTED (Slice 5)"),
)


def _stage_index(job: str, needle: str, start: int = 0) -> int:
    return job.find(needle, start)


def check_sbom_implementation(root: Path) -> list[Violation]:
    """Slice 2: real SBOM generation, its position in the release workflow and checksum policy."""
    out: list[Violation] = []
    generator = _read(root, SBOM_GENERATOR)
    if generator is None:
        return [Violation("SBOM-GENERATOR", f"{SBOM_GENERATOR} is missing")]
    version = re.search(r'^SYFT_VERSION = "(\d+\.\d+\.\d+)"', generator, re.M)
    digest = re.search(r'^SYFT_LINUX_AMD64_SHA256 = "([0-9a-f]{64})"', generator, re.M)
    if version is None or digest is None:
        out.append(Violation("SBOM-PIN", "the SBOM tool must be pinned by an exact version and an archive SHA-256"))
    if re.search(r"releases/latest|/latest/|install\.sh", generator):
        out.append(Violation("SBOM-PIN", "the SBOM tool must not be fetched through a mutable reference"))
    if not re.search(r'^SPDX_VERSION = "SPDX-2\.3"', generator, re.M):
        out.append(Violation("SBOM-FORMAT", "the generator must target SPDX-2.3"))
    if not re.search(r'^SBOM_SUFFIX = "\.spdx\.json"', generator, re.M) or not re.search(
        r"def sbom_name\(artifact_basename: str\) -> str:\s+(?:\"\"\"[^\n]*\"\"\"\s+)?return artifact_basename \+ SBOM_SUFFIX", generator
    ):
        out.append(Violation("SBOM-NAMING", "SBOM names must derive mechanically from the artifact basename plus .spdx.json"))
    if "shell=True" in _code(generator):
        out.append(Violation("SBOM-GENERATOR", "the generator must never use shell=True"))
    for pattern in RELEASE_UPLOAD_PATTERNS:
        if re.search(pattern, _code(generator)):
            out.append(Violation("WF-UPLOAD-BYPASS", f"{SBOM_GENERATOR}: the SBOM tooling must never upload release assets ({pattern})"))
    if re.search(r"""["']gh["']|\bgh\s+release\b""", _code(generator)):
        out.append(Violation("WF-UPLOAD-BYPASS", f"{SBOM_GENERATOR}: the SBOM tooling must not invoke the GitHub CLI"))
    modelled = {f.family_id for f in FAMILIES if f.requires_sbom}
    in_generator = set(re.findall(r'Family\("([a-z_]+)"', generator))
    if in_generator != modelled:
        out.append(Violation("SBOM-FAMILIES", f"generator families {sorted(in_generator)} differ from the SBOM-required families {sorted(modelled)}"))

    artifacts_script = _read(root, ARTIFACT_CHECKER) or ""
    if re.search(r'^SBOM_SUFFIX="\.spdx\.json"', artifacts_script, re.M) is None:
        out.append(Violation("SBOM-NAMING", f"{ARTIFACT_CHECKER} must use the same .spdx.json SBOM suffix"))
    if "--finalize-release-assets" not in artifacts_script or "grep -vx SHA256SUMS" not in artifacts_script:
        out.append(Violation("SBOM-CHECKSUMS", f"{ARTIFACT_CHECKER} must finalize SHA256SUMS over every published file except itself"))
    if "must not list itself" not in generator:
        out.append(Violation("SBOM-CHECKSUMS", "the bundle validator must reject a SHA256SUMS that lists itself"))
    doc = _read(root, DOC) or ""
    if "every published release file except `SHA256SUMS` itself" not in " ".join(doc.split()):
        out.append(Violation("SBOM-CHECKSUMS", "the documented checksum policy must cover every published file except SHA256SUMS itself"))
    status_lines = [line.lower() for line in doc.splitlines() if line.startswith("|")]
    for label, status in STATUS_ROWS:
        row = next((line for line in status_lines if line.startswith(f"| {label}")), "")
        if status.lower() not in row:
            out.append(Violation("DOC-STATUS", f"the slice status of {label!r} must read {status}"))

    workflow = _read(root, RELEASE_WORKFLOW)
    jobs = split_jobs(_code(workflow)) if workflow else {}
    build = jobs.get("build-and-validate", "")
    stage = _stage_index(build, "check_release_artifacts.sh\n")
    fetch = _stage_index(build, "generate_release_sboms.py fetch-syft")
    generate = _stage_index(build, "generate_release_sboms.py generate")
    validate = _stage_index(build, "generate_release_sboms.py validate --dir")
    finalize = _stage_index(build, "check_release_artifacts.sh --finalize-release-assets")
    bundle = _stage_index(build, "generate_release_sboms.py validate-bundle")
    handoff = _stage_index(build, "name: release-assets")
    order = [stage, fetch, generate, validate, finalize, bundle, handoff]
    if min(order) < 0:
        out.append(Violation("SBOM-WORKFLOW", "build-and-validate must stage, fetch the pinned tool, generate, validate, finalize checksums, validate the bundle and hand off"))
    elif order != sorted(order):
        out.append(Violation("SBOM-WORKFLOW", "SBOM steps are out of order: expected stage, fetch tool, generate, validate, finalize SHA256SUMS, validate bundle, hand-off"))
    elif "--input dist/release-assets" not in build[generate:validate]:
        out.append(Violation("SBOM-WORKFLOW", "SBOMs must be generated from the staged dist/release-assets only"))
    if "generate_release_sboms.py" in jobs.get("upload", "") or "fetch-syft" in jobs.get("upload", ""):
        out.append(Violation("SBOM-WORKFLOW", "the upload job must not run SBOM tooling"))

    directory = root / WORKFLOWS
    for path in sorted(directory.glob("*.y*ml")) if directory.is_dir() else []:
        text = _code(path.read_text(encoding="utf-8"))
        for action, ref in SUPPLY_CHAIN_ACTION_RE.findall(text):
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                out.append(Violation("SBOM-PIN", f"{path.relative_to(root)}: {action}@{ref} must be pinned to a full commit SHA"))
        if re.search(r"(?:curl|wget)\b[^\n]*(?:syft|anchore)", text, re.I):
            out.append(Violation("SBOM-PIN", f"{path.relative_to(root)}: the SBOM tool must not be piped or downloaded outside fetch-syft"))

    manifest = _read(root, Path("pyproject.toml"))
    if manifest is not None:
        data = tomllib.loads(manifest)
        names: list[str] = list(data.get("project", {}).get("dependencies", []))
        for group in data.get("project", {}).get("optional-dependencies", {}).values():
            names += list(group)
        for group in data.get("dependency-groups", {}).values():
            names += [item for item in group if isinstance(item, str)]
        for requirement in names:
            if SBOM_DEPENDENCY_RE.search(requirement):
                out.append(Violation("SBOM-DEPENDENCY", f"pyproject.toml declares an SBOM/supply-chain dependency: {requirement}"))
    lock = _read(root, Path("uv.lock")) or ""
    if re.search(r'^name = "(?:[^"]*(?:syft|anchore|spdx|cyclonedx)[^"]*)"', lock, re.M | re.I):
        out.append(Violation("SBOM-DEPENDENCY", "uv.lock must not lock an SBOM/supply-chain package"))
    source = root / "src"
    for path in sorted(source.rglob("*.py")) if source.is_dir() else []:
        if "generate_release_sboms" in path.read_text(encoding="utf-8"):
            out.append(Violation("SBOM-DEPENDENCY", f"{path.relative_to(root)}: runtime code must not use the SBOM tooling"))
    return out


def _permissions(text: str, indent: int) -> dict[str, str] | None:
    """The ``permissions:`` mapping at ``indent`` (``None`` when absent, ``{"*": v}`` when scalar)."""
    pad = " " * indent
    match = re.search(rf"^{pad}permissions:[ \t]*(.*)$", text, re.M)
    if match is None:
        return None
    inline = match.group(1).strip()
    if inline:
        return {"*": inline}
    found: dict[str, str] = {}
    for line in text[match.end():].splitlines()[1:]:
        child = re.match(rf"^{pad}  ([a-z-]+):\s*([a-z-]+)\s*$", line)
        if child is None:
            break
        found[child.group(1)] = child.group(2)
    return found


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _steps(job: str) -> list[tuple[int, str]]:
    """``(offset, text)`` of each step of a job body: a small indentation-aware YAML-subset parser.

    The ``steps:`` key is located at its real indentation, and the indentation of its sequence items
    is taken from the first item below it (YAML allows items at the key's own indentation or deeper).
    Only items at exactly that indentation are steps: deeper lines (``with:``/``env:`` content, nested
    lists, ``run: |`` block scalars) belong to the current step, and the sequence ends at the first
    dedent or sibling key. Offsets are relative to ``job`` and increase in source order.
    """
    lines = job.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    steps_line = -1
    steps_indent = 0
    for index, line in enumerate(lines):
        match = re.match(r"^( *)steps:\s*$", line)
        if match and (steps_line < 0 or len(match.group(1)) < steps_indent):
            steps_line, steps_indent = index, len(match.group(1))
    if steps_line < 0:
        return []
    first = -1
    item_indent = 0
    for index in range(steps_line + 1, len(lines)):
        text = lines[index].strip()
        if not text:
            continue
        if (text == "-" or text.startswith("- ")) and _indent(lines[index]) >= steps_indent:
            first, item_indent = index, _indent(lines[index])
        break
    if first < 0:
        return []
    starts: list[int] = []
    end = len(job)
    for index in range(first, len(lines)):
        text = lines[index].strip()
        if not text:
            continue
        indent = _indent(lines[index])
        if indent < item_indent or (indent == item_indent and not (text == "-" or text.startswith("- "))):
            end = offsets[index]  # dedent or a sibling key: the steps sequence is over
            break
        if indent == item_indent:
            starts.append(offsets[index])
    return [(start, job[start:(starts[n + 1] if n + 1 < len(starts) else end)]) for n, start in enumerate(starts)]


def _strip_comment(value: str) -> str:
    return re.sub(r"\s+#.*$", "", value).strip()


def _step_keys(step: str) -> dict[str, tuple[str, list[str]]]:
    """Step-level keys of one parsed step as ``{key: (inline value, nested lines)}``.

    Only keys at the step mapping's own indentation count; ``run:`` script lines, nested ``with:``
    content and anything deeper are nested lines of their key and never step-level keys.
    """
    lines = step.splitlines()
    head = re.match(r"^( *)-( +)(.*)$", lines[0]) if lines else None
    if head is None:
        return {}
    key_indent = len(head.group(1)) + 1 + len(head.group(2))
    lines[0] = " " * key_indent + head.group(3)
    keys: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    for line in lines:
        if not line.strip():
            if current is not None:
                keys[current][1].append(line)
            continue
        indent = _indent(line)
        if indent == key_indent:
            match = re.match(r"^ *([A-Za-z0-9_.-]+):[ \t]*(.*)$", line)
            current = match.group(1) if match else None
            if match and current not in keys:
                keys[current] = (_strip_comment(match.group(2)), [])
            elif match is None:
                current = None
        elif indent > key_indent and current is not None:
            keys[current][1].append(line)
    return keys


def _persists_credentials(step: str) -> bool:
    """``False`` only when this step's own ``with:`` mapping sets ``persist-credentials: false``."""
    inline, nested = _step_keys(step).get("with", ("", []))
    value = None
    if inline.startswith("{"):
        braces = re.search(r"persist-credentials:\s*([^,}\s]+)", inline)
        value = braces.group(1) if braces else None
    else:
        body = [line for line in nested if line.strip()]
        if body:
            indent = _indent(body[0])
            for line in body:
                match = re.match(r"^ *persist-credentials:[ \t]*(.*)$", line)
                if match and _indent(line) == indent:
                    value = _strip_comment(match.group(1))
                    break
    return value not in {"false", "'false'", '"false"'}


def _is_checkout_step(step: str) -> bool:
    return re.match(r"actions/checkout@", _step_keys(step).get("uses", ("", []))[0]) is not None


def _check_permissions(code: str, jobs: dict[str, str]) -> list[Violation]:
    out: list[Violation] = []
    top = _permissions(code.split("\njobs:", 1)[0], 0)
    if top is None or "write" in " ".join(top.values()) or "*" in top:
        out.append(Violation("ATT-PERMISSIONS", "the workflow-level permissions must be an explicit read-only mapping"))
    for name, expected in (("build-and-validate", BUILD_PERMISSIONS), ("upload", UPLOAD_PERMISSIONS)):
        actual = _permissions(jobs.get(name, ""), 4)
        if actual is None:
            out.append(Violation("ATT-PERMISSIONS", f"job {name!r} must declare its permissions explicitly"))
            continue
        for key, value in sorted(expected.items()):
            if actual.get(key) != value:
                out.append(Violation("ATT-PERMISSIONS", f"job {name!r} needs {key}: {value} (found {actual.get(key)!r})"))
        for key in sorted(set(actual) - set(expected)):
            out.append(Violation("ATT-PERMISSIONS", f"job {name!r} must not hold {key}: {actual[key]} (least privilege)"))
    for name, body in jobs.items():
        if name in {"build-and-validate", "upload"}:
            continue
        extra = _permissions(body, 4) or {}
        if "write" in " ".join(extra.values()):
            out.append(Violation("ATT-PERMISSIONS", f"job {name!r} must not hold a write permission"))
    return out


def check_attestation_implementation(root: Path) -> list[Violation]:
    """Slice 3: keyless provenance and SBOM attestations, verified before the hand-off."""
    out: list[Violation] = []
    raw = _read(root, RELEASE_WORKFLOW)
    if raw is None:
        return [Violation("ATT-WORKFLOW", f"{RELEASE_WORKFLOW} is missing")]
    code = _code(raw)
    jobs = split_jobs(code)
    build = jobs.get("build-and-validate", "")
    out += _check_permissions(code, jobs)

    directory = root / WORKFLOWS
    for path in sorted(directory.glob("*.y*ml")) if directory.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        body = _code(text)
        for action, ref in re.findall(r"^\s*-?\s*uses:\s*([^\s@]+)@(\S+)", body, re.M):
            if action == ATTEST_ACTION and ref != ATTEST_SHA:
                out.append(Violation("ATT-PIN", f"{path.relative_to(root)}: {ATTEST_ACTION}@{ref} must be exactly @{ATTEST_SHA} ({ATTEST_VERSION})"))
            if re.search(r"attest-build-provenance|attest-sbom", action):
                out.append(Violation("ATT-ALTERNATIVE", f"{path.relative_to(root)}: {action} is not allowed; use {ATTEST_ACTION}"))
        if ALTERNATIVE_SIGNING_RE.search(body):
            out.append(Violation("ATT-ALTERNATIVE", f"{path.relative_to(root)}: a second signing mechanism is not allowed (GitHub OIDC attestation only)"))
        for line in text.splitlines():
            if re.match(r"^\s*-?\s*uses:\s*actions/attest@", line) and not re.search(
                rf"@{ATTEST_SHA}\s+#\s*{re.escape(ATTEST_ACTION)} {re.escape(ATTEST_VERSION)}\s*$", line
            ):
                out.append(Violation("ATT-PIN", f"{path.relative_to(root)}: every {ATTEST_ACTION} reference must carry the comment '# {ATTEST_ACTION} {ATTEST_VERSION}'"))

    # The release workflow IS the signing trust boundary: every external action it runs must be an
    # immutable full commit SHA (not only the attestation actions), and a checkout must not persist
    # the job token in the checked-out repository.
    for action, ref in re.findall(r"^\s*-?\s*uses:\s*([^\s@]+)@(\S+)", code, re.M):
        if re.fullmatch(r"[0-9a-f]{40}", ref) is None:
            out.append(Violation("ATT-PIN", f"{RELEASE_WORKFLOW}: {action}@{ref} must be pinned to a full 40-hex commit SHA"))
    for job_name, job_body in jobs.items():
        if re.search(r"^ *steps:[ \t]*[^\s#]", job_body, re.M):
            out.append(Violation("ATT-CHECKOUT", f"{RELEASE_WORKFLOW}: job {job_name!r} must declare its steps as a block sequence"))
        for _, step_text in _steps(job_body):
            if _is_checkout_step(step_text) and _persists_credentials(step_text):
                out.append(Violation("ATT-CHECKOUT", f"{RELEASE_WORKFLOW}: the checkout step in job {job_name!r} must set its own with: persist-credentials: false"))

    steps = _steps(build)
    attest = [(at, text) for at, text in steps if re.search(r"uses:\s*actions/attest@", text)]
    prepare = _stage_index(build, "prepare_attestation_subjects.py")
    verify = _stage_index(build, "verify_release_attestations.py")
    finalize = _stage_index(build, "check_release_artifacts.sh --finalize-release-assets")
    bundle = _stage_index(build, "generate_release_sboms.py validate-bundle")
    handoff = _stage_index(build, "name: release-assets")
    generate = _stage_index(build, "generate_release_sboms.py generate")
    if not attest:
        out.append(Violation("ATT-WORKFLOW", "build-and-validate has no attestation step"))
    if prepare < 0 or "id: subjects" not in build:
        out.append(Violation("ATT-WORKFLOW", "build-and-validate must derive the subjects with scripts/prepare_attestation_subjects.py (id: subjects)"))
    if verify < 0:
        out.append(Violation("ATT-VERIFY", "build-and-validate must verify every attestation with scripts/verify_release_attestations.py"))
    if attest and min(finalize, bundle, generate) >= 0:
        first, last = attest[0][0], attest[-1][0]
        if first < max(finalize, bundle):
            out.append(Violation("ATT-ORDER", "attestations must come after the final SHA256SUMS and the validated bundle"))
        if first < generate:
            out.append(Violation("ATT-ORDER", "attestations must come after SBOM generation"))
        if prepare >= 0 and not max(finalize, bundle) < prepare < first:
            out.append(Violation("ATT-ORDER", "the subjects must be prepared after the validated bundle and before the first attestation"))
        if verify >= 0 and verify < last:
            out.append(Violation("ATT-ORDER", "verification must come after every attestation"))
        if handoff >= 0 and verify >= 0 and handoff < verify:
            out.append(Violation("ATT-ORDER", "the workflow-artifact hand-off must come after attestation verification"))
        if handoff < 0:
            out.append(Violation("ATT-ORDER", "the release-assets hand-off is missing"))

    provenance_a = [t for _, t in attest if "subject-checksums:" in t]
    sbom_steps = [t for _, t in attest if "sbom-path:" in t]
    self_steps = [t for _, t in attest if "subject-checksums:" not in t and "sbom-path:" not in t]
    if len(provenance_a) != 1 or not re.search(r"subject-checksums:\s*dist/release-assets/SHA256SUMS\s*$", provenance_a[0], re.M):
        out.append(Violation("ATT-SUBJECTS", "exactly one provenance attestation must take its subjects from dist/release-assets/SHA256SUMS"))
    if len(self_steps) != 1 or not (
        re.search(r"subject-name:\s*(?:SHA256SUMS|\$\{\{\s*steps\.subjects\.outputs\.checksums_name\s*\}\})\s*$", self_steps[0], re.M)
        and re.search(r"subject-digest:\s*sha256:\$\{\{\s*steps\.subjects\.outputs\.checksums_sha256\s*\}\}\s*$", self_steps[0], re.M)
    ):
        out.append(Violation("ATT-SUBJECTS", "SHA256SUMS itself needs exactly one separate provenance attestation (name and digest from the prepared subjects)"))
    families = [f.family_id for f in FAMILIES if f.requires_sbom]
    paired: list[str] = []
    for step in sbom_steps:
        refs = [
            re.search(rf"{key}:\s*{prefix}\$\{{\{{\s*steps\.subjects\.outputs\.([a-z_]+)_{suffix}\s*\}}\}}\s*$", step, re.M)
            for key, prefix, suffix in (
                ("subject-name", "", "name"), ("subject-digest", "sha256:", "sha256"), ("sbom-path", "", "sbom_path")
            )
        ]
        found = {m.group(1) for m in refs if m is not None}
        if None in refs or len(found) != 1 or not found <= set(families):
            out.append(Violation("ATT-SBOM-PAIR", "each SBOM attestation must pair one package's name, digest and SBOM path"))
        else:
            paired.append(next(iter(found)))
    if sorted(paired) != sorted(families) or len(sbom_steps) != len(families):
        out.append(Violation("ATT-SBOM-PAIR", f"exactly one SBOM attestation per package family is required: expected {sorted(families)}, found {sorted(paired)}"))
    for _, text in attest:
        if FORBIDDEN_ATTEST_INPUTS_RE.search(text):
            out.append(Violation("ATT-SUBJECTS", "attestation steps must use subject-checksums, subject-name/digest and sbom-path only"))
    for _, text in [*attest, *[(0, t) for _, t in steps if "verify_release_attestations.py" in t or "prepare_attestation_subjects.py" in t]]:
        if re.search(r"^\s+(?:continue-on-error:\s*true|if:)", text, re.M):
            out.append(Violation("ATT-VERIFY", "attestation, subject and verification steps must be unconditional and fail closed"))
    verify_steps = [t for _, t in steps if "verify_release_attestations.py" in t]
    if verify_steps:
        step = verify_steps[0]
        if "--assets-dir dist/release-assets" not in step:
            out.append(Violation("ATT-VERIFY", "the verifier must read dist/release-assets"))
        if not re.search(r"--repo\s+SSobol77/pysh(?:\s|\\|$)", step):
            out.append(Violation("ATT-VERIFY", f"the verifier must pin the repository {REPOSITORY_IDENTITY}"))
        if not re.search(rf"--signer-workflow\s+{re.escape(SIGNER_WORKFLOW)}(?:\s|\\|$)", step):
            out.append(Violation("ATT-VERIFY", f"the verifier must pin the signer workflow {SIGNER_WORKFLOW}"))
        if not re.search(r'--source-digest\s+"?(?:\$\{GITHUB_SHA\}|\$GITHUB_SHA|\$\{\{\s*github\.sha\s*\}\})"?', step):
            out.append(Violation("ATT-VERIFY", "the verifier must pin the exact source commit (GITHUB_SHA)"))

    out += _check_attestation_scripts(root)
    out += _check_attestation_documentation(root)
    return out


def _check_attestation_scripts(root: Path) -> list[Violation]:
    out: list[Violation] = []
    verifier = _read(root, ATTESTATION_VERIFIER)
    helper = _read(root, SUBJECT_HELPER)
    if verifier is None:
        out.append(Violation("ATT-VERIFY", f"{ATTESTATION_VERIFIER} is missing"))
    else:
        body = _code(verifier)
        for needle, why in (
            (f'PINNED_REPO = "{REPOSITORY_IDENTITY}"', "pin the repository identity"),
            (f'PINNED_SIGNER_WORKFLOW = "{SIGNER_WORKFLOW}"', "pin the signer workflow"),
            (f'SPDX_PREDICATE_TYPE = "{SPDX_PREDICATE_TYPE}"', "pin the SPDX 2.3 predicate type"),
            ('"--source-digest", source_digest', "pass the exact source digest to gh"),
            ('"--signer-workflow", signer_workflow', "pass the signer workflow to gh"),
            ('"--repo", repo', "pass the repository to gh"),
            ('"--predicate-type", predicate_type', "pass the predicate type to gh"),
            ('NOT_VISIBLE_PATTERN = r"\\bno attestations? found\\b"', "retry only the narrowly classified 'not visible yet' answer"),
            ("range(1, MAX_ATTEMPTS)", "bound the retry loop"),
        ):
            if needle not in body:
                out.append(Violation("ATT-VERIFY", f"{ATTESTATION_VERIFIER} must {why}"))
        attempts = re.search(r"^MAX_ATTEMPTS = (\d+)$", body, re.M)
        if attempts is None or not 1 <= int(attempts.group(1)) <= 10:
            out.append(Violation("ATT-RETRY", f"{ATTESTATION_VERIFIER}: MAX_ATTEMPTS must be a literal between 1 and 10"))
        if re.search(r"\bwhile\b", body):
            out.append(Violation("ATT-RETRY", f"{ATTESTATION_VERIFIER}: no unbounded loop is allowed"))
        if "shell=True" in body:
            out.append(Violation("ATT-VERIFY", f"{ATTESTATION_VERIFIER} must never use shell=True"))
        if ALTERNATIVE_SIGNING_RE.search(body) or re.search(r'"attestation",\s*"(?:create|sign)"', body):
            out.append(Violation("ATT-ALTERNATIVE", f"{ATTESTATION_VERIFIER} must contain no signing logic"))
        for pattern in RELEASE_UPLOAD_PATTERNS:
            if re.search(pattern, body):
                out.append(Violation("WF-UPLOAD-BYPASS", f"{ATTESTATION_VERIFIER}: must never upload release assets ({pattern})"))
    if helper is None:
        out.append(Violation("ATT-SUBJECTS", f"{SUBJECT_HELPER} is missing"))
    else:
        body = _code(helper)
        if "subprocess" in body or re.search(r"\b(?:urllib|socket|requests|http)\b", body):
            out.append(Violation("ATT-SUBJECTS", f"{SUBJECT_HELPER} must be offline and run no subprocess"))
        if "SUBJECT_COUNT = 12" not in body:
            out.append(Violation("ATT-SUBJECTS", f"{SUBJECT_HELPER} must derive exactly twelve release subjects"))
        if "EVIDENCE" not in body:
            out.append(Violation("ATT-SUBJECTS", f"{SUBJECT_HELPER} must include the published REPRODUCIBILITY.json as a subject"))
    return out


def _check_attestation_documentation(root: Path) -> list[Violation]:
    doc = " ".join((_read(root, DOC) or "").split())
    out: list[Violation] = []
    for needle, why in (
        (f"{ATTEST_ACTION} {ATTEST_VERSION}", "name the reviewed attestation action version"),
        (ATTEST_SHA, "record the immutable attestation action commit"),
        (f"--signer-workflow {SIGNER_WORKFLOW}", "document the pinned signer workflow"),
        ("--source-digest", "document source-commit pinning"),
        (f"--predicate-type {SPDX_PREDICATE_TYPE}", "document SPDX SBOM attestation verification"),
        ("gh attestation trusted-root", "document the offline trust root"),
        ("sha256sum -c SHA256SUMS", "keep checksum verification"),
    ):
        if needle not in doc:
            out.append(Violation("ATT-DOC", f"{DOC} must {why}: {needle!r}"))
    return out


#: Anything that rewrites build output after the fact to force equal hashes.
NORMALIZATION_RE = re.compile(
    r"strip-nondeterminism|add-determinism|\butime\b|touch\s+-[a-z]*[dtrm]\b|\brepack\b|\bzipnote\b"
    r"|normali[sz]e_(?:archive|artifact|timestamps?)",
    re.I,
)
#: Wall-clock time feeding the build epoch.
WALL_CLOCK_EPOCH_RE = re.compile(
    r"SOURCE_DATE_EPOCH[^\n]*(?:\$\(\s*date\b|`date\b|\bdate\s+\+%s|\btime\.time\(|datetime\.now|utcnow)"
)
REPRO_FAMILIES = ("wheel", "sdist", "deb", "rpm")
EVIDENCE_PUBLIC_NAME = "REPRODUCIBILITY.json"


def _step_text(steps: list[tuple[int, str]], needle: str, exclude: str | None = None) -> tuple[int, str] | None:
    for at, text in steps:
        if needle in text and (exclude is None or exclude not in text):
            return at, text
    return None


#: Anything that rewrites, repacks or fabricates a package after (or instead of) ``pkg create``.
FREEBSD_POST_BUILD_RE = re.compile(
    r"\btouch\b|\butime\b|strip-nondeterminism|\b(?:tar|xz|gzip|zstd|bzip2|ar|dd)\b|\bmv\b|\bcp\b|\bchmod\b"
    r"|>\s*\"?\$\{EXPECTED_PATH"
)
FREEBSD_WALL_CLOCK_RE = re.compile(r"\bdate\b|\bstat\b|EPOCHSECONDS|\btime\b\s")


def _check_freebsd_builder(root: Path) -> list[Violation]:
    """The native FreeBSD builder gives pkg create the commit epoch and never rewrites the result."""
    out: list[Violation] = []
    script = _read(root, Path("scripts/build_freebsd_pkg.sh"))
    if script is None:
        return [Violation("REPRO-FREEBSD", "scripts/build_freebsd_pkg.sh is missing")]
    code = _code(script)
    if not re.search(r'pkg create -t "\$\{SOURCE_DATE_EPOCH\}" ', code):
        out.append(Violation("REPRO-FREEBSD", 'scripts/build_freebsd_pkg.sh must call pkg create -t "${SOURCE_DATE_EPOCH}" when the epoch is set'))
    if "*[!0-9]*)" not in code or 'SOURCE_DATE_EPOCH must be decimal epoch seconds' not in code:
        out.append(Violation("REPRO-FREEBSD", "scripts/build_freebsd_pkg.sh must reject a SOURCE_DATE_EPOCH that is not decimal digits"))
    if len(re.findall(r"^\s*pkg create\b", code, re.M)) != 2:
        out.append(Violation("REPRO-FREEBSD", "scripts/build_freebsd_pkg.sh must have exactly the epoch and the ordinary pkg create invocations"))
    if FREEBSD_WALL_CLOCK_RE.search(code):
        out.append(Violation("REPRO-EPOCH", "scripts/build_freebsd_pkg.sh must not derive a wall-clock timestamp"))
    created = code.rsplit("pkg create", 1)
    if len(created) == 2 and FREEBSD_POST_BUILD_RE.search(created[1]):
        out.append(Violation("REPRO-NORMALIZE", "scripts/build_freebsd_pkg.sh must not rewrite the package after pkg create"))
    if '"$(uname -s)" != "FreeBSD"' not in code or "refusing to fake .pkg" not in code:
        out.append(Violation("REPRO-FREEBSD", "scripts/build_freebsd_pkg.sh must keep refusing to fake a .pkg on a non-FreeBSD host"))
    return out


def check_reproducibility_implementation(root: Path) -> list[Violation]:
    """Slice 4: per-artifact A/B measurement, validated evidence, published before the checksums."""
    out: list[Violation] = []
    harness = _read(root, REPRO_HARNESS)
    validator = _read(root, REPRO_VALIDATOR)
    if harness is None:
        out.append(Violation("REPRO-HARNESS", f"{REPRO_HARNESS} is missing"))
    else:
        body = _code(harness)
        for needle, why in (
            ("git", "extract the exact source commit with git archive"),
            ('"archive"', "extract the exact source commit with git archive"),
            ("SOURCE_DATE_EPOCH", "set SOURCE_DATE_EPOCH from the commit timestamp"),
            ("%ct", "derive the epoch from the commit timestamp"),
            ("start_new_session=True", "bound each build in its own process group"),
            ("shell=False", "execute argv lists, never a shell"),
            ("separate_source_roots", "record that the A/B source roots are independent"),
            ("separate_output_files", "record that the A/B outputs are separate files"),
            ("sha256_of", "compute the SHA-256 itself"),
            ("def bind_release", "bind the evidence to the staged public artifact"),
            ("release_matches_build_a", "record whether the release artifact equals build A"),
            ("release_matches_build_b", "record whether the release artifact equals build B"),
            ("matches neither measured build", "fail when the shipped artifact equals neither build"),
            ("--release-dir", "accept the staged release directory"),
            ("PIP_LOG", "capture the resolved build backend from the isolated build environment"),
            ("def resolved_backend", "record the resolved (not only declared) build backend version"),
            ("def wheel_generator", "corroborate the resolved backend with the built wheel"),
            ("umask=evidence.BUILD_UMASK", "run builds under the declared umask"),
        ):
            if needle not in body:
                out.append(Violation("REPRO-HARNESS", f"{REPRO_HARNESS} must {why}"))
        if "shell=True" in body or "os.system" in body:
            out.append(Violation("REPRO-HARNESS", f"{REPRO_HARNESS} must never use a shell"))
        if re.search(r"time\.time\(|datetime\.(?:now|utcnow)|date\s+\+%s", body):
            out.append(Violation("REPRO-EPOCH", f"{REPRO_HARNESS} must never use wall-clock time as the build epoch"))
        if NORMALIZATION_RE.search(body):
            out.append(Violation("REPRO-NORMALIZE", f"{REPRO_HARNESS} must not normalize or rewrite build output"))
        for pattern in RELEASE_UPLOAD_PATTERNS:
            if re.search(pattern, body):
                out.append(Violation("WF-UPLOAD-BYPASS", f"{REPRO_HARNESS}: must never upload release assets ({pattern})"))
    if validator is None:
        out.append(Violation("REPRO-VALIDATOR", f"{REPRO_VALIDATOR} is missing"))
    else:
        body = _code(validator)
        states = re.findall(r'^(REPRODUCIBLE|NON_REPRODUCIBLE|NOT_YET_MEASURED|PLATFORM_BLOCKED) = "\1"$', body, re.M)
        if sorted(states) != sorted(REPRODUCIBILITY_STATUSES):
            out.append(Violation("REPRO-VALIDATOR", f"{REPRO_VALIDATOR} must define exactly the four classifications {sorted(REPRODUCIBILITY_STATUSES)}"))
        for needle, why in (
            ("is not accepted in final evidence", "reject PLATFORM_BLOCKED and NOT_YET_MEASURED in final mode"),
            ('"final"', "support a final mode"),
            ('"local"', "support a local mode"),
            ('NATIVE_ONLY = {"freebsd_pkg": "FreeBSD"}', "require a native FreeBSD builder for the FreeBSD package"),
            ('"rpm": ("rpmbuild",)', "require real rpmbuild metadata for an RPM measurement"),
            ("source_date_epoch_origin", "reject a wall-clock build epoch"),
            ("separate_source_roots", "require independent A/B source roots"),
            ("separate_output_files", "reject output reuse between A and B"),
            ("release_sha256", "require the release-byte binding"),
            ("requires the release-byte binding", "require the release-byte binding in final mode"),
            ("matches neither measured build", "reject a release artifact that equals neither build"),
            ("EXACT_VERSION_RE", "require exact resolved tool versions"),
            ("declared_requirements", "keep the declared requirement apart from the resolved version"),
            ('"wheel": ("python", "build", "hatchling")', "require the resolved hatchling version for wheel"),
            ('"freebsd_pkg": ("pkg", "python")', "require the pkg and Python versions for the FreeBSD package"),
            ("NON_REPRODUCIBLE requires", "reject contradictory classifications"),
        ):
            if needle not in body:
                out.append(Violation("REPRO-VALIDATOR", f"{REPRO_VALIDATOR} must {why}"))
        for family, script in (("wheel", "build_pysh_package"), ("sdist", "build_pysh_package"), ("deb", "build_deb"),
                               ("rpm", "build_rpm"), ("freebsd_pkg", "build_freebsd_pkg")):
            if not re.search(rf'"{family}": "scripts/{script}\.sh"', body):
                out.append(Violation("REPRO-VALIDATOR", f"{REPRO_VALIDATOR} must map {family} to the repository builder scripts/{script}.sh"))
        if NORMALIZATION_RE.search(body):
            out.append(Violation("REPRO-NORMALIZE", f"{REPRO_VALIDATOR} must not normalize or rewrite build output"))

    raw = _read(root, RELEASE_WORKFLOW)
    if raw is None:
        return out + [Violation("REPRO-WORKFLOW", f"{RELEASE_WORKFLOW} is missing")]
    code = _code(raw)
    jobs = split_jobs(code)
    build = jobs.get("build-and-validate", "")
    freebsd = jobs.get("freebsd-pkg", "")
    steps = _steps(build)
    directory = root / WORKFLOWS
    for path in sorted(directory.glob("*.y*ml")) if directory.is_dir() else []:
        text = _code(path.read_text(encoding="utf-8"))
        if WALL_CLOCK_EPOCH_RE.search(text):
            out.append(Violation("REPRO-EPOCH", f"{path.relative_to(root)}: SOURCE_DATE_EPOCH must be the commit timestamp, never wall-clock time"))
        if NORMALIZATION_RE.search(text):
            out.append(Violation("REPRO-NORMALIZE", f"{path.relative_to(root)}: build output must not be normalized or rewritten after the build"))

    epoch = _step_text(steps, "SOURCE_DATE_EPOCH=")
    first_build = build.find("build_pysh_package.sh")
    if epoch is None or "git log -1 --format=%ct" not in epoch[1] or "GITHUB_ENV" not in epoch[1]:
        out.append(Violation("REPRO-EPOCH", "build-and-validate must export SOURCE_DATE_EPOCH from `git log -1 --format=%ct`"))
    elif first_build >= 0 and epoch[0] > first_build:
        out.append(Violation("REPRO-EPOCH", "SOURCE_DATE_EPOCH must be set before the first build"))
    if "git log -1 --format=%ct" not in freebsd or "SOURCE_DATE_EPOCH" not in freebsd:
        out.append(Violation("REPRO-EPOCH", "the freebsd-pkg job must derive SOURCE_DATE_EPOCH from the commit timestamp"))

    measure = _step_text(steps, "measure_release_reproducibility.py", exclude="measure_release_reproducibility.py merge")
    download = _step_text(steps, "name: freebsd-reproducibility-evidence")
    merge = _step_text(steps, "measure_release_reproducibility.py merge")
    final = _step_text(steps, "check_reproducibility_evidence.py")
    if measure is None:
        out.append(Violation("REPRO-WORKFLOW", "build-and-validate must measure Linux reproducibility (wheel, sdist, deb, rpm)"))
    else:
        for family in REPRO_FAMILIES:
            if f"--family {family}" not in measure[1]:
                out.append(Violation("REPRO-WORKFLOW", f"the Linux measurement must include --family {family}"))
        if "freebsd_pkg" in measure[1] or "--all" in measure[1]:
            out.append(Violation("REPRO-WORKFLOW", "the Linux job must not claim the FreeBSD measurement (native FreeBSD only)"))
        if "--source-commit" not in measure[1]:
            out.append(Violation("REPRO-WORKFLOW", "the Linux measurement must pin --source-commit to GITHUB_SHA"))
        if "--release-dir dist/release-assets" not in measure[1]:
            out.append(Violation("REPRO-RELEASE-BINDING", "the Linux measurement must bind to the staged public artifacts (--release-dir dist/release-assets)"))
    if download is None:
        out.append(Violation("REPRO-WORKFLOW", "build-and-validate must download the native FreeBSD reproducibility evidence"))
    if merge is None or "--input dist/reproducibility/linux.json" not in merge[1] or f"--output dist/release-assets/{EVIDENCE_PUBLIC_NAME}" not in merge[1]:
        out.append(Violation("REPRO-WORKFLOW", f"the platform evidence must be merged into dist/release-assets/{EVIDENCE_PUBLIC_NAME}"))
    elif "freebsd_pkg.json" not in merge[1] or "--source-commit" not in merge[1]:
        out.append(Violation("REPRO-WORKFLOW", "the merge must take the native FreeBSD evidence and pin --source-commit"))
    elif "--release-dir dist/release-assets" not in merge[1]:
        out.append(Violation("REPRO-RELEASE-BINDING", "the merge must bind every measured family to the staged public artifacts (--release-dir dist/release-assets)"))
    if final is None or "--mode final" not in final[1] or "--source-commit" not in final[1]:
        out.append(Violation("REPRO-WORKFLOW", "the published evidence must pass check_reproducibility_evidence.py --mode final --source-commit"))
    for found in (measure, download, merge, final):
        if found is not None and re.search(r"^\s+(?:continue-on-error:\s*true|if:)", found[1], re.M):
            out.append(Violation("REPRO-WORKFLOW", "measurement and evidence steps must be unconditional and fail closed"))

    validate_sbom = _stage_index(build, "generate_release_sboms.py validate --dir")
    finalize = _stage_index(build, "check_release_artifacts.sh --finalize-release-assets")
    prepare = _stage_index(build, "prepare_attestation_subjects.py")
    first_attest = _stage_index(build, "uses: actions/attest@")
    ordered = [validate_sbom, *(f[0] for f in (measure, download, merge, final) if f is not None), finalize]
    if min(validate_sbom, finalize) >= 0 and None not in (measure, download, merge, final):
        if ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
            out.append(Violation("REPRO-ORDER", "the reproducibility evidence must be measured, combined and validated after the SBOMs and before the final SHA256SUMS"))
    for found in (measure, merge, final):
        if found is not None and finalize >= 0 and found[0] > finalize:
            out.append(Violation("REPRO-ORDER", "reproducibility evidence must exist before the final SHA256SUMS"))
        if found is not None and first_attest >= 0 and found[0] > first_attest:
            out.append(Violation("REPRO-ORDER", "reproducibility evidence must exist before any attestation"))
    if prepare >= 0 and final is not None and final[0] > prepare:
        out.append(Violation("REPRO-ORDER", "the evidence must be validated before the attestation subjects are prepared"))
    if "REPRODUCIBILITY.json" in _code(raw) and "--source-commit" not in build[prepare:prepare + 400]:
        out.append(Violation("REPRO-WORKFLOW", "the attestation subjects must be prepared with --source-commit so that the evidence is bound to the release commit"))

    native = (
        "measure_release_reproducibility.py" in freebsd and "--family freebsd_pkg" in freebsd
        and "--source-archive" in freebsd and "--source-commit" in freebsd and "--source-date-epoch" in freebsd
        and "matrix.reference-pkg" in freebsd and "freebsd-reproducibility-evidence" in freebsd
    )
    if not native:
        out.append(Violation("REPRO-NATIVE", "the FreeBSD reference job must run the native A/B measurement and upload freebsd-reproducibility-evidence"))
    if "--family wheel" in freebsd or "--all" in freebsd:
        out.append(Violation("REPRO-NATIVE", "the FreeBSD job must measure only the freebsd_pkg family"))

    if "SUBJECT_COUNT" in (_read(root, SUBJECT_HELPER) or "") and EVIDENCE_PUBLIC_NAME not in (_read(root, SBOM_GENERATOR) or ""):
        out.append(Violation("REPRO-SUBJECTS", f"{SBOM_GENERATOR} must know the published {EVIDENCE_PUBLIC_NAME}"))
    out += _check_freebsd_builder(root)
    rpm_builder = _read(root, Path("scripts/build_rpm.sh")) or ""
    for macro in ("use_source_date_epoch_as_buildtime", "clamp_mtime_to_source_date_epoch"):
        if macro not in rpm_builder:
            out.append(Violation("REPRO-RPM", f"scripts/build_rpm.sh must enable the rpm macro {macro} when SOURCE_DATE_EPOCH is set (rpmbuild ignores the epoch otherwise)"))
    if NORMALIZATION_RE.search(_code(rpm_builder)):
        out.append(Violation("REPRO-NORMALIZE", "scripts/build_rpm.sh must not rewrite the built package"))
    artifacts_script = _read(root, ARTIFACT_CHECKER) or ""
    if EVIDENCE_PUBLIC_NAME not in artifacts_script:
        out.append(Violation("REPRO-CHECKSUMS", f"{ARTIFACT_CHECKER} must require {EVIDENCE_PUBLIC_NAME} among the files covered by the final SHA256SUMS"))

    doc = " ".join((_read(root, DOC) or "").split())
    for needle, why in (
        ("byte-for-byte", "define reproducibility as byte-for-byte identical artifacts"),
        ("SHA-256", "state that A/B equality is SHA-256 equality"),
        ("SOURCE_DATE_EPOCH", "document the SOURCE_DATE_EPOCH policy"),
        ("commit timestamp", "bind SOURCE_DATE_EPOCH to the commit timestamp"),
        (EVIDENCE_PUBLIC_NAME, "document the published evidence file"),
        ("native FreeBSD", "require a native FreeBSD measurement"),
        ("release_sha256", "document the release-byte binding"),
        ("resolved version", "document the resolved build toolchain"),
        ("umask", "document the declared build umask"),
        ("rpmbuild", "require rpmbuild for the RPM measurement"),
        ("check_reproducibility_evidence.py", "name the evidence validator"),
        ("independent controls", "state that reproducibility and provenance are independent controls"),
        ("NOT_YET_MEASURED", "define NOT_YET_MEASURED"),
    ):
        if needle not in doc:
            out.append(Violation("REPRO-DOC", f"{DOC} must {why}: {needle!r}"))
    return out


# --- Slice 5: the permanent Tier-1 evidence record ---------------------------------------------------------------

#: The recorded real run. The record is the repository-owned permanent baseline; pinning its key
#: facts here keeps an edit from silently changing them. Nothing is fetched from GitHub.
EVIDENCE_RUN = "37166005508"
EVIDENCE_SHA = "f642eaa5707456b2ecfa7696919bef2dfa5c4fa6"
EVIDENCE_FIELDS = {
    "Workflow run": EVIDENCE_RUN,
    "Tested source SHA": EVIDENCE_SHA,
    "Event": "workflow_dispatch",
    "Conclusion": "success",
    "Job: FreeBSD 14.4 reference": "success",
    "Job: FreeBSD 15 validation": "success",
    "Job: build-and-validate": "success",
    "Job: GitHub Release upload": "SKIPPED",
    "Release files": "12",
    "SHA256SUMS entries": "11",
    "Provenance subjects": "12",
    "SPDX SBOM attestations": "5",
    "Release upload job": "SKIPPED",
}
EVIDENCE_ATTESTATIONS = {
    "provenance, 11 SHA256SUMS subjects": "52499029",
    "provenance, SHA256SUMS": "52499033",
    "SPDX SBOM wheel": "52499037",
    "SPDX SBOM sdist": "52499040",
    "SPDX SBOM deb": "52499044",
    "SPDX SBOM rpm": "52499052",
    "SPDX SBOM freebsd_pkg": "52499055",
}
EVIDENCE_NEGATIVE_RUNS = {
    "37164782394": ("86be6f60e948df8a119598575619377839f5009b", "RPM"),
    "37165299323": ("12067296c6d184daaeaed1ca6e373d4acd312605", "FreeBSD"),
}
EVIDENCE_HEADINGS = (
    "Scope", "Tested Source Identity", "Workflow Evidence", "Platform Evidence", "Reproducibility Results",
    "Release Artifact Set", "SHA-256 Integrity", "SBOM Evidence", "Provenance Evidence",
    "Attestation Verification", "Trust Model", "Publication Boundary", "Historical Negative Evidence",
    "Residual Limitations", "Issue #51 Acceptance Mapping", "Issue #35 Handoff",
)
REQUIRED_ACCEPTANCE = (
    "SPDX SBOM generated for all five package families",
    "SBOM format SPDX 2.3 JSON",
    "Public SBOM filenames tied to canonical package basenames",
    "Final SHA256SUMS covers all public files except itself",
    "Exact source provenance",
    "Canonical subject names",
    "Canonical subject digests",
    "Repository identity pinned",
    "Signer workflow pinned",
    "Source digest pinned",
    "Verification before handoff",
    "Fail closed on missing or invalid attestation",
    "No release upload bypass",
    "No long-lived private signing key",
    "GitHub OIDC and Sigstore trust model",
    "PyPI Trusted Publishing preserved",
    "User verification documented",
    "Maintainer verification documented",
    "Trust-root rotation documented",
    "Future ecosystem verification is default-deny",
    "Reproducibility measured for all five package families",
    "Shipped-byte binding",
    "Exact resolved toolchain evidence",
    "RPM deterministic build",
    "Native FreeBSD deterministic build",
    "Real FreeBSD 14.4 evidence",
    "FreeBSD 15 validation",
    "Real GitHub attestation creation",
    "Real gh attestation verification",
    "Release upload skipped for workflow_dispatch",
    "Historical fail-closed negative controls",
    "Release Quality Gate integration",
    "Issue #35 evidence handoff",
)
#: Statements that must be present, and false claims that must not be.
EVIDENCE_REQUIRED_PHRASES = (
    "not itself attested",
    "is not the final v1.0.0 release attestation",
    "must rerun the same assurance pipeline on its final release SHA",
    "negative-control evidence",
    "Tested source SHA",
    "Evidence-record commit",
)
EVIDENCE_FALSE_CLAIMS = (
    re.compile(r"evidence-record commit[^.|]*\b(?:was|is|has been|were) (?:itself )?attested", re.I),
    re.compile(r"\bis the final v1\.0\.0 release attestation", re.I),
    re.compile(r"\bare (?:unresolved|open) release failures", re.I),
)


def _markdown_sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _rows(text: str, width: int) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|"):
            cells = _cells(line)
            if len(cells) == width and not set("".join(cells)) <= set("- "):
                rows.append(cells)
    return rows


def check_final_evidence(root: Path) -> list[Violation]:
    """Slice 5: the permanent Tier-1 evidence record, pinned offline."""
    out: list[Violation] = []
    raw = _read(root, EVIDENCE_DOC)
    if raw is None:
        return [Violation("EVID-MISSING", f"{EVIDENCE_DOC} is missing")]
    text = " ".join(raw.replace("**", "").split())
    sections = _markdown_sections(raw)
    for heading in EVIDENCE_HEADINGS:
        if heading not in sections:
            out.append(Violation("EVID-SECTION", f"{EVIDENCE_DOC} lacks the section '{heading}'"))

    pairs: dict[str, list[str]] = {}
    for label, value in _rows(raw, 2):
        pairs.setdefault(label, []).append(value)
    for label, expected in EVIDENCE_FIELDS.items():
        values = pairs.get(label)
        if not values:
            out.append(Violation("EVID-FACT", f"the evidence record must state '{label}'"))
        elif any(value != expected and not value.startswith(f"{expected} ") for value in values):
            out.append(Violation("EVID-FACT", f"'{label}' must be {expected!r}: found {values}"))

    results = {row[0]: row for row in _rows(sections.get("Reproducibility Results", ""), 3)}
    for family in (f.family_id for f in FAMILIES if f.requires_sbom):
        row = results.get(family)
        if row is None:
            out.append(Violation("EVID-REPRO", f"the reproducibility results must list the {family} family"))
        elif row[1] != "REPRODUCIBLE" or not re.fullmatch(r"[0-9a-f]{64}", row[2]):
            out.append(Violation("EVID-REPRO", f"{family} must be REPRODUCIBLE with a release/A/B SHA-256 (found {row[1]!r})"))

    attestations = {row[0]: row[1] for row in _rows(sections.get("Provenance Evidence", ""), 2)}
    for label, identifier in EVIDENCE_ATTESTATIONS.items():
        if attestations.get(label) != identifier:
            out.append(Violation("EVID-ATTEST", f"attestation '{label}' must be recorded with ID {identifier}"))

    history = {row[0]: row for row in _rows(sections.get("Historical Negative Evidence", ""), 4)}
    for run, (sha, family) in EVIDENCE_NEGATIVE_RUNS.items():
        row = history.get(run)
        if row is None or row[1] != sha or family not in row[3] or "release-byte binding" not in row[3]:
            out.append(Violation("EVID-NEGATIVE", f"the historical {family} fail-closed run {run} (source {sha[:12]}) must be recorded"))

    identity = " ".join(sections.get("Tested Source Identity", "").replace("**", "").split())
    if not all(needle in identity for needle in ("Tested source SHA", "Evidence-record commit", "not itself attested")):
        out.append(Violation("EVID-IDENTITY", "the evidence must distinguish the tested source SHA from the later evidence-record commit and say the latter is not itself attested"))
    for phrase in EVIDENCE_REQUIRED_PHRASES:
        if phrase not in text:
            out.append(Violation("EVID-CLAIM", f"the evidence record must state: {phrase!r}"))
    for pattern in EVIDENCE_FALSE_CLAIMS:
        if pattern.search(text):
            out.append(Violation("EVID-CLAIM", f"the evidence record makes a false claim ({pattern.pattern})"))
    if EVIDENCE_SHA not in sections.get("Tested Source Identity", "") or EVIDENCE_RUN not in sections.get("Workflow Evidence", ""):
        out.append(Violation("EVID-FACT", "the tested source SHA and the run ID must be recorded in their sections"))
    boundary = " ".join(sections.get("Publication Boundary", "").split())
    for needle in ("GitHub Release created | no", "Tag created | no", "PyPI publication | no"):
        if needle not in boundary:
            out.append(Violation("EVID-BOUNDARY", f"the publication boundary must record: {needle}"))

    mapping = {row[0]: row for row in _rows(sections.get("Issue #51 Acceptance Mapping", ""), 5)}
    for item in REQUIRED_ACCEPTANCE:
        row = mapping.get(item)
        if row is None:
            out.append(Violation("EVID-ACCEPTANCE", f"the acceptance mapping lacks the item '{item}'"))
        elif not all(row[1:4]) or row[4] != "PASS":
            out.append(Violation("EVID-ACCEPTANCE", f"'{item}' needs an implementation, a test and evidence, and must be PASS"))
        elif (root / "tests").is_dir():
            for path in re.findall(r"(?:scripts|tests)/[\w./-]+\.(?:py|sh)", " ".join(row[1:3])):
                if not (root / path).is_file():
                    out.append(Violation("EVID-ACCEPTANCE", f"'{item}' cites {path}, which does not exist"))
    extra = sorted(set(mapping) - set(REQUIRED_ACCEPTANCE) - {"Acceptance item"})
    if extra:
        out.append(Violation("EVID-ACCEPTANCE", f"unexpected acceptance items: {extra}"))

    doc = _read(root, DOC) or ""
    if "supply-chain-evidence.md" not in doc:
        out.append(Violation("EVID-LINK", f"{DOC} must link {EVIDENCE_DOC.name}"))
    repro_section = split_sections(doc).get("PYSH-SC-REPRODUCIBILITY", "")
    baseline = " ".join(repro_section.split())
    recorded = _table_rows(repro_section)
    for family in (f.family_id for f in FAMILIES if f.reproducibility_required):
        row = recorded.get(family)
        if row is None or row[-1] != "REPRODUCIBLE":
            out.append(Violation("EVID-BASELINE", f"the reproducibility status table must record {family} as REPRODUCIBLE (the measured Slice 5 baseline)"))
    for needle, why in (
        (EVIDENCE_SHA, "name the recorded baseline source SHA"),
        (EVIDENCE_RUN, "name the recorded baseline run"),
        ("do not transfer to v1.0.0", "say that the baseline statuses do not transfer to v1.0.0"),
        ("must rerun the full pipeline on its exact final release candidate SHA", "require the v1.0.0 rerun on its exact SHA"),
    ):
        if needle not in baseline:
            out.append(Violation("EVID-BASELINE", f"the reproducibility status table must {why}: {needle!r}"))
    release = " ".join((_read(root, RELEASE_DOC) or "").split())
    for needle, why in (
        ("supply-chain-evidence.md", "link the evidence record as the Issue #35 handoff"),
        ("Issue #35", "name the readiness audit"),
        ("gh attestation verify", "document maintainer verification"),
        ("must run again on the final release SHA", "require the pipeline to rerun for v1.0.0"),
    ):
        if needle not in release:
            out.append(Violation("EVID-HANDOFF", f"{RELEASE_DOC} must {why}: {needle!r}"))
    return out


CURRENT_CHECKS = (
    check_sbom_implementation,
    check_attestation_implementation,
    check_reproducibility_implementation,
    check_final_evidence,
    check_documentation,
    check_packaging_agreement,
    check_release_workflow,
    check_release_upload_exclusivity,
    check_publication_and_secrets,
)


def run_checks(root: Path = REPO_ROOT) -> list[Violation]:
    """All CURRENT structural invariants, sorted for deterministic output."""
    violations: list[Violation] = []
    for check in CURRENT_CHECKS:
        violations.extend(check(root))
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root to check")
    args = parser.parse_args(argv)
    violations = run_checks(args.root)
    for violation in violations:
        print(f"supply-chain contract: FAIL [{violation.code}] {violation.message}", file=sys.stderr)
    if violations:
        print(f"supply-chain contract: FAIL ({len(violations)} violation(s))", file=sys.stderr)
        return 1
    for line in future_status(args.root):
        print(line)
    print(f"supply-chain contract: PASS ({len(CURRENT_CHECKS)} current structural check groups)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
