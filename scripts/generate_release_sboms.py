#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/generate_release_sboms.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Generate and validate SPDX 2.3 JSON SBOMs for the PySH release artifacts (Issue #51).

CI and release infrastructure only: PySH never imports or depends on this module or on
the SBOM tool. The tool is Anchore Syft, pinned below by version and by the SHA-256 of
its official release archive.

Subcommands
-----------
``fetch-syft --dest DIR``
    Download the pinned Syft release archive over HTTPS, verify its SHA-256 and unpack
    only the ``syft`` executable into ``DIR``. The only network access in this module.
``generate --input DIR --output DIR --syft PATH``
    Create exactly one ``<artifact-basename>.spdx.json`` for each of the five mandatory
    package artifacts found in ``DIR``. All documents are produced and validated in a
    private staging directory first; nothing is written to ``--output`` unless every
    one succeeded (no partial success). Artifact bytes are never modified.
``validate --dir DIR``
    Validate the five artifacts and their SBOMs (completeness, naming, SPDX 2.3
    structure, artifact binding, leaks, no unexpected siblings).
``validate-bundle --dir DIR``
    ``validate`` plus the published ``REPRODUCIBILITY.json`` and the final ``SHA256SUMS``
    policy: it covers every published release file except ``SHA256SUMS`` itself, and
    every digest is correct.

Nothing here uploads anything, uses a shell, or scans a path other than the explicit
input directory. The SBOM file name is the artifact basename plus ``.spdx.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- pinned SBOM tool (single source of truth; the workflow only calls ``fetch-syft``) ----------
SYFT_VERSION = "1.54.0"
#: Commit of the upstream ``v1.54.0`` tag, recorded for human review.
SYFT_TAG_COMMIT = "cc326e45a6213360266dda4b30cc68095946d676"
SYFT_LINUX_AMD64_SHA256 = "54a87372498168b2d033e876fd41fa4e8035b872699e525a57046e1f2f09c860"
SYFT_URL = (
    f"https://github.com/anchore/syft/releases/download/v{SYFT_VERSION}/"
    f"syft_{SYFT_VERSION}_linux_amd64.tar.gz"
)

SPDX_VERSION = "SPDX-2.3"
SBOM_SUFFIX = ".spdx.json"
CHECKSUMS = "SHA256SUMS"
#: The public reproducibility evidence (Issue #51 Slice 4): a published release asset that is
#: listed in SHA256SUMS and attested like the packages and SBOMs. It is created after the SBOMs.
EVIDENCE = "REPRODUCIBILITY.json"
SYFT_TIMEOUT_SECONDS = 300
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_MEMBERS = 20000
MAX_ERROR_CHARS = 2000


class SbomError(Exception):
    """A generation or validation failure; the message names the artifact concerned."""


@dataclass(frozen=True)
class Family:
    family_id: str
    #: Accepted canonical basenames, ``{v}`` is the version. Mirrors the packaging
    #: contract (``scripts/check_release_artifacts.sh``); a test keeps them equal.
    names: tuple[str, ...]
    #: ``zip``/``tar`` payloads are unpacked for scanning; ``archive`` is scanned as is
    #: (Syft catalogs ``.deb`` and ``.rpm`` archives natively).
    scan: str


FAMILIES: tuple[Family, ...] = (
    Family("wheel", ("pysh_shell-{v}-py3-none-any.whl",), "zip"),
    Family("sdist", ("pysh_shell-{v}.tar.gz", "pysh-shell-{v}.tar.gz"), "tar"),
    Family("deb", ("pysh-shell_{v}-1_all.deb",), "archive"),
    Family("rpm", ("pysh-shell-{v}-1.noarch.rpm",), "archive"),
    Family("freebsd_pkg", ("pysh-shell-{v}.pkg",), "tar"),
)


def project_version(root: Path = REPO_ROOT) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def sbom_name(artifact_basename: str) -> str:
    """The only SBOM naming rule: derived mechanically from the artifact basename."""
    return artifact_basename + SBOM_SUFFIX


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_artifacts(directory: Path, version: str) -> dict[str, Path]:
    """Exactly one canonical file per family; every other file is rejected."""
    if not directory.is_dir():
        raise SbomError(f"input directory does not exist: {directory.name}")
    present = {p.name: p for p in sorted(directory.iterdir())}
    found: dict[str, Path] = {}
    claimed: set[str] = set()
    for family in FAMILIES:
        matches = [n.format(v=version) for n in family.names if n.format(v=version) in present]
        if not matches:
            raise SbomError(f"missing mandatory {family.family_id} artifact: {family.names[0].format(v=version)}")
        if len(matches) > 1:
            raise SbomError(f"ambiguous {family.family_id} artifacts (aliases): {matches}")
        path = present[matches[0]]
        if not path.is_file() or path.is_symlink():
            raise SbomError(f"{matches[0]} is not a regular file")
        if path.stat().st_size == 0:
            raise SbomError(f"{matches[0]} is empty (0 bytes)")
        found[family.family_id] = path
        claimed.add(matches[0])
    return found


# --- payload preparation (safe extraction) ---------------------------------------------------------


def _safe_member(name: str) -> bool:
    parts = Path(name).parts
    return bool(name) and not name.startswith("/") and ".." not in parts and "\\" not in name


def _extract_zip(archive: Path, target: Path) -> None:
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_EXTRACTED_MEMBERS:
            raise SbomError(f"{archive.name}: too many members")
        for info in infos:
            if not _safe_member(info.filename):
                raise SbomError(f"{archive.name}: unsafe member path {info.filename!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SbomError(f"{archive.name}: symbolic link member {info.filename!r}")
            total += info.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise SbomError(f"{archive.name}: extracted size exceeds the bound")
        bundle.extractall(target)


def _extract_tar(archive: Path, target: Path) -> None:
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_EXTRACTED_MEMBERS:
                raise SbomError(f"{archive.name}: too many members")
            if sum(m.size for m in members) > MAX_EXTRACTED_BYTES:
                raise SbomError(f"{archive.name}: extracted size exceeds the bound")
            bundle.extractall(target, filter="data")  # rejects absolute/escaping/special members
        return
    except (tarfile.ReadError, tarfile.CompressionError):
        pass
    # Compression the stdlib cannot read (for example zstd in a FreeBSD pkg): the platform tar.
    tar = shutil.which("tar")
    if tar is None:
        raise SbomError(f"{archive.name}: unreadable by the standard library and no tar is available")
    done = subprocess.run(  # noqa: S603 - explicit argv, no shell
        [tar, "-xf", str(archive), "-C", str(target), "--no-same-owner", "--no-same-permissions"],
        capture_output=True, text=True, timeout=SYFT_TIMEOUT_SECONDS, check=False, stdin=subprocess.DEVNULL,
    )
    if done.returncode != 0:
        raise SbomError(f"{archive.name}: tar failed: {done.stderr.strip()[:MAX_ERROR_CHARS]}")
    for path in target.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(target.resolve()):
            raise SbomError(f"{archive.name}: a link escapes the extraction root")


def prepare_scan_directory(family: Family, artifact: Path, scratch: Path) -> Path:
    """A private directory for Syft to scan for this artifact."""
    scan_dir = scratch / f"scan-{family.family_id}"
    scan_dir.mkdir()
    if family.scan == "zip":
        _extract_zip(artifact, scan_dir)
    elif family.scan == "tar":
        _extract_tar(artifact, scan_dir)
    else:
        shutil.copyfile(artifact, scan_dir / artifact.name)
    return scan_dir


# --- running the tool ---------------------------------------------------------------------------------


def tool_environment(home: Path) -> dict[str, str]:
    """A minimal environment: no host variables, no secrets, no update check, no network use."""
    return {
        "HOME": str(home),
        "TMPDIR": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_CONFIG_HOME": str(home / "config"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "SYFT_CHECK_FOR_APP_UPDATE": "false",
    }


def check_tool_version(syft: Path, home: Path) -> None:
    done = subprocess.run(  # noqa: S603 - explicit executable, no shell
        [str(syft), "version"], env=tool_environment(home), capture_output=True, text=True,
        timeout=60, check=False, stdin=subprocess.DEVNULL,
    )
    match = re.search(r"^Version:\s*(\S+)", done.stdout, re.M)
    if done.returncode != 0 or match is None or match.group(1) != SYFT_VERSION:
        found = match.group(1) if match else "unreadable"
        raise SbomError(f"SBOM tool version mismatch: expected {SYFT_VERSION}, found {found}")


def run_tool(syft: Path, scan_dir: Path, artifact: Path, output: Path, home: Path) -> None:
    command = [
        str(syft), "scan", f"dir:{scan_dir}",
        "--source-name", artifact.name,
        "--source-version", f"sha256:{sha256_of(artifact)}",
        "-o", f"spdx-json={output}", "-q",
    ]
    try:
        done = subprocess.run(  # noqa: S603 - explicit argv, no shell
            command, env=tool_environment(home), capture_output=True, text=True,
            timeout=SYFT_TIMEOUT_SECONDS, check=False, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as error:
        raise SbomError(f"{artifact.name}: the SBOM tool timed out") from error
    if done.returncode != 0:
        raise SbomError(
            f"{artifact.name}: the SBOM tool failed with exit {done.returncode}: "
            f"{(done.stderr or done.stdout).strip()[:MAX_ERROR_CHARS]}"
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise SbomError(f"{artifact.name}: the SBOM tool produced no document")


# --- validation ----------------------------------------------------------------------------------------

LEAK_PATTERNS = (
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/(?:tmp|var/folders|private/var)/"),
    re.compile(r"/runner(?:admin)?/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
SENSITIVE_ENV_RE = re.compile(r"TOKEN|SECRET|PASSWORD|PASSPHRASE|PRIVATE|CREDENTIAL|API_?KEY", re.I)


def find_leaks(text: str, forbidden: tuple[str, ...] = (), environ: Mapping[str, str] | None = None) -> list[str]:
    """Host paths, secrets and sensitive environment values embedded in SBOM text."""
    leaks = [p.pattern for p in LEAK_PATTERNS if p.search(text)]
    leaks += [f"path {value!r}" for value in forbidden if value and value in text]
    for name, value in (os.environ if environ is None else environ).items():
        if SENSITIVE_ENV_RE.search(name) and len(value) >= 12 and value in text:
            leaks.append(f"value of environment variable {name}")
    return leaks


def validate_document(
    sbom: Path, artifact: Path, forbidden: tuple[str, ...] = (), environ: Mapping[str, str] | None = None
) -> None:
    """Validate one SBOM against the artifact it must describe."""
    name = sbom.name
    if name != sbom_name(artifact.name):
        raise SbomError(f"{name}: file name does not map to artifact {artifact.name}")
    if not sbom.is_file() or sbom.stat().st_size == 0:
        raise SbomError(f"{name}: empty or missing")
    text = sbom.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SbomError(f"{name}: malformed JSON: {error}") from error
    if not isinstance(document, dict):
        raise SbomError(f"{name}: the document root must be an object")
    if document.get("spdxVersion") != SPDX_VERSION:
        raise SbomError(f"{name}: spdxVersion must be {SPDX_VERSION}, found {document.get('spdxVersion')!r}")
    if document.get("dataLicense") != "CC0-1.0":
        raise SbomError(f"{name}: dataLicense must be CC0-1.0")
    namespace = document.get("documentNamespace")
    if not isinstance(namespace, str) or not namespace.strip():
        raise SbomError(f"{name}: documentNamespace is missing")
    info = document.get("creationInfo")
    if not isinstance(info, dict) or not info.get("creators") or not info.get("created"):
        raise SbomError(f"{name}: creationInfo (creators, created) is missing")
    if document.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise SbomError(f"{name}: the document SPDXID must be SPDXRef-DOCUMENT")
    packages = document.get("packages")
    relationships = document.get("relationships")
    if not isinstance(packages, list) or not packages or not isinstance(relationships, list):
        raise SbomError(f"{name}: packages and relationships are required")
    described = {
        r.get("relatedSpdxElement")
        for r in relationships
        if isinstance(r, dict) and r.get("relationshipType") == "DESCRIBES"
        and r.get("spdxElementId") == "SPDXRef-DOCUMENT"
    }
    roots = [p for p in packages if isinstance(p, dict) and p.get("SPDXID") in described]
    digest = sha256_of(artifact)
    if len(roots) != 1 or roots[0].get("name") != artifact.name or roots[0].get("versionInfo") != f"sha256:{digest}":
        raise SbomError(
            f"{name}: the described root package must be {artifact.name} at sha256:{digest[:12]}... "
            "(the SBOM is not bound to this artifact)"
        )
    leaks = find_leaks(text, forbidden, environ)
    if leaks:
        raise SbomError(f"{name}: embeds host or secret data: {leaks}")


def validate_set(directory: Path, version: str, forbidden: tuple[str, ...] = (),
                 environ: Mapping[str, str] | None = None) -> dict[str, Path]:
    """The five artifacts and exactly their five SBOMs; nothing else except SHA256SUMS and REPRODUCIBILITY.json."""
    artifacts = locate_artifacts(directory, version)
    expected_sboms = {sbom_name(p.name): p for p in artifacts.values()}
    present = {p.name for p in directory.iterdir()}
    allowed = {p.name for p in artifacts.values()} | set(expected_sboms) | {CHECKSUMS, EVIDENCE}
    for family_id, artifact in artifacts.items():
        if sbom_name(artifact.name) not in present:
            raise SbomError(f"missing SBOM for the {family_id} artifact: {sbom_name(artifact.name)}")
    unexpected = sorted(present - allowed)
    if unexpected:
        raise SbomError(f"unexpected files in the release set: {unexpected}")
    roots: set[str] = set()
    for sbom_filename, artifact in sorted(expected_sboms.items()):
        validate_document(directory / sbom_filename, artifact, forbidden, environ)
        if artifact.name in roots:
            raise SbomError(f"duplicate SBOM for {artifact.name}")
        roots.add(artifact.name)
    return artifacts


def validate_bundle(directory: Path, version: str, forbidden: tuple[str, ...] = ()) -> None:
    """The complete public set: packages, SBOMs, the reproducibility evidence and a final SHA256SUMS."""
    validate_set(directory, version, forbidden)
    evidence_path = directory / EVIDENCE
    if not evidence_path.is_file() or evidence_path.is_symlink() or evidence_path.stat().st_size == 0:
        raise SbomError(f"{EVIDENCE} is missing or empty: the reproducibility evidence is a published release asset")
    validate_checksums(directory)


def validate_checksums(directory: Path) -> None:
    """The final manifest covers every published file except itself, with correct digests."""
    manifest = directory / CHECKSUMS
    if not manifest.is_file() or manifest.stat().st_size == 0:
        raise SbomError(f"{CHECKSUMS} is missing or empty")
    listed: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](\S.*)", line)
        if match is None:
            raise SbomError(f"{CHECKSUMS}: malformed line {line!r}")
        if match.group(2) in listed:
            raise SbomError(f"{CHECKSUMS}: duplicate entry {match.group(2)}")
        listed[match.group(2)] = match.group(1)
    if CHECKSUMS in listed:
        raise SbomError(f"{CHECKSUMS} must not list itself")
    published = {p.name for p in directory.iterdir() if p.name != CHECKSUMS}
    if set(listed) != published:
        missing, extra = sorted(published - set(listed)), sorted(set(listed) - published)
        raise SbomError(f"{CHECKSUMS} must cover every published file except itself: missing={missing} extra={extra}")
    for filename, digest in sorted(listed.items()):
        if sha256_of(directory / filename) != digest:
            raise SbomError(f"{CHECKSUMS}: digest mismatch for {filename}")


# --- commands -----------------------------------------------------------------------------------------------


def generate(input_dir: Path, output_dir: Path, syft: Path, version: str) -> list[Path]:
    """Create the five SBOMs atomically: nothing is written unless all five are valid."""
    artifacts = locate_artifacts(input_dir, version)
    if not syft.is_absolute() or not syft.is_file() or not os.access(syft, os.X_OK):
        raise SbomError("--syft must be an absolute path to an executable")
    output_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts.values():
        if (output_dir / sbom_name(artifact.name)).exists():
            raise SbomError(f"refusing to overwrite {sbom_name(artifact.name)}")
    produced: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="pysh-sbom-") as scratch_name:
        scratch = Path(scratch_name)
        home = scratch / "home"
        home.mkdir()
        staging = scratch / "staging"
        staging.mkdir()
        check_tool_version(syft, home)
        for family in FAMILIES:  # deterministic order
            artifact = artifacts[family.family_id]
            scan_dir = prepare_scan_directory(family, artifact, scratch)
            document = staging / sbom_name(artifact.name)
            run_tool(syft, scan_dir, artifact, document, home)
            validate_document(document, artifact, forbidden=(str(scratch), str(input_dir.resolve())))
            produced.append(document)
        for document in produced:
            shutil.copyfile(document, output_dir / document.name)
    return [output_dir / d.name for d in produced]


def fetch_syft(dest: Path) -> Path:
    """Download the pinned Syft archive, verify its digest and unpack only ``syft``."""
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SbomError("the pinned Syft archive is for Linux x86_64 only")
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SYFT_URL, timeout=120) as response:  # noqa: S310 - fixed https URL
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != SYFT_LINUX_AMD64_SHA256:
        raise SbomError("the downloaded Syft archive does not match its pinned SHA-256")
    archive = dest / "syft.tar.gz"
    archive.write_bytes(payload)
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("syft")
        if not member.isfile():
            raise SbomError("the Syft archive has no regular 'syft' file")
        source = bundle.extractfile(member)
        assert source is not None
        executable = dest / "syft"
        executable.write_bytes(source.read())
    executable.chmod(0o755)
    archive.unlink()
    return executable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch-syft")
    fetch.add_argument("--dest", type=Path, required=True)
    gen = commands.add_parser("generate")
    gen.add_argument("--input", type=Path, required=True)
    gen.add_argument("--output", type=Path, required=True)
    gen.add_argument("--syft", type=Path, required=True)
    gen.add_argument("--version")
    for name in ("validate", "validate-bundle"):
        sub = commands.add_parser(name)
        sub.add_argument("--dir", type=Path, required=True)
        sub.add_argument("--version")
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch-syft":
            print(fetch_syft(args.dest))
            return 0
        version = args.version or project_version()
        if args.command == "generate":
            for path in generate(args.input, args.output, args.syft, version):
                print(f"sbom: {path.name}")
            return 0
        forbidden = (str(args.dir.resolve()), str(REPO_ROOT))
        if args.command == "validate-bundle":
            validate_bundle(args.dir, version, forbidden)
        else:
            validate_set(args.dir, version, forbidden)
        print(f"sbom: {args.command} OK")
        return 0
    except SbomError as error:
        print(f"generate_release_sboms: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"generate_release_sboms: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
