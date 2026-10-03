#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_supply_chain_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structural supply-chain contract check for Issue #51 (Slice 1).

Read-only, deterministic and offline: it validates the repository-owned policy
(``docs/security/supply-chain.md``), its agreement with the packaging contract, and
the structure of the release and publication workflows. It performs no
cryptographic verification, calls no external tool and touches neither the network
nor the repository.

Two classes of requirements are kept apart:

* CURRENT structural invariants must hold now; a violation fails the check.
* FUTURE implementation requirements (real SBOM generation, attestations, ...) are
  only *reported* as deferred or present, never enforced, so Slice 1 passes honestly
  without them.

Exit codes: 0 contract holds, 1 contract violation, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import re
import sys
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
    if "later slices" not in " ".join(sections.get("PYSH-SC-SCOPE", "").lower().split()):
        out.append(Violation("DOC-PIPELINE", "the scope must state that real SBOM/provenance generation is implemented in later slices"))

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
    """Deferred implementation items and whether each is already present (informational)."""
    directory = root / WORKFLOWS
    corpus = "\n".join(
        _code(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.y*ml"))
    ) if directory.is_dir() else ""
    items = (
        ("SPDX SBOM generation (Slice 2)", r"spdx|sbom"),
        ("keyless artifact attestation (Slice 3)", r"actions/attest|attest-build-provenance"),
        ("attestation verification before upload (Slice 3)", r"gh\s+attestation\s+verify"),
        ("reproducibility measurement (Slice 4)", r"reproducib"),
    )
    return [
        f"deferred: {name}: " + ("present" if re.search(pattern, corpus, re.I) else "not yet implemented")
        for name, pattern in items
    ]


CURRENT_CHECKS = (
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
