#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/prepare_attestation_subjects.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Derive the exact attestation subjects from the final release bundle (Issue #51, Slice 3).

Read-only, deterministic, stdlib-only and offline. The authority is the final
``SHA256SUMS`` of the validated release-assets directory: it lists the five package
artifacts and their five ``.spdx.json`` SBOM files with exact names and digests, and
intentionally does not list itself. This helper classifies those entries with the
canonical family rules of ``scripts/generate_release_sboms.py`` (no second filename
list), computes the digest of ``SHA256SUMS`` itself and emits GitHub step outputs, so
the workflow never hardcodes a version-specific file name or digest.

It never signs, attests or uploads anything.

Exit codes: 0 subjects prepared, 1 invalid bundle, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import generate_release_sboms as sboms  # noqa: E402

#: ``sha256sum`` text-mode line: lowercase digest, exactly two spaces, a flat basename.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")
MANIFEST_LINE_RE = re.compile(r"([0-9a-f]{64})  (" + NAME_RE.pattern + ")")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
#: Number of public release files: five packages, five SBOMs and SHA256SUMS.
SUBJECT_COUNT = 11


class SubjectError(Exception):
    """The release bundle does not yield a valid, complete subject set."""


@dataclass(frozen=True)
class Subject:
    """One release file and its digest."""

    name: str
    sha256: str


@dataclass(frozen=True)
class PackageSubject:
    """A package artifact, its digest and the SBOM file that describes it."""

    family_id: str
    package: Subject
    sbom: Subject


@dataclass(frozen=True)
class SubjectSet:
    """Every release subject of one final bundle."""

    packages: tuple[PackageSubject, ...]
    checksums: Subject

    def manifest_subjects(self) -> tuple[Subject, ...]:
        """The ten subjects listed in ``SHA256SUMS`` (packages and SBOMs), sorted by name."""
        listed = [s for entry in self.packages for s in (entry.package, entry.sbom)]
        return tuple(sorted(listed, key=lambda s: s.name))

    def all_subjects(self) -> tuple[Subject, ...]:
        """All eleven public release files, manifest subjects first."""
        return (*self.manifest_subjects(), self.checksums)


def check_basename(name: str) -> str:
    """A subject name is a flat basename: no directory, no traversal, no odd characters."""
    if NAME_RE.fullmatch(name) is None:
        raise SubjectError(f"subject name must be a plain basename: {name!r}")
    return name


def parse_manifest(text: str) -> dict[str, str]:
    """``{name: sha256}`` of a ``SHA256SUMS`` text; rejects malformed, duplicate or path entries."""
    listed: dict[str, str] = {}
    for line in text.splitlines():
        match = MANIFEST_LINE_RE.fullmatch(line)
        if match is None:
            raise SubjectError(f"{sboms.CHECKSUMS}: malformed line {line!r}")
        digest, name = match.groups()
        check_basename(name)
        if name in listed:
            raise SubjectError(f"{sboms.CHECKSUMS}: duplicate subject {name}")
        listed[name] = digest
    if not listed:
        raise SubjectError(f"{sboms.CHECKSUMS} is empty")
    return listed


def prepare(directory: Path, version: str) -> SubjectSet:
    """Classify the final bundle; every family exactly once, nothing unknown."""
    try:
        sboms.validate_checksums(directory)
        artifacts = sboms.locate_artifacts(directory, version)
    except sboms.SbomError as error:
        raise SubjectError(str(error)) from error
    listed = parse_manifest((directory / sboms.CHECKSUMS).read_text(encoding="utf-8"))
    entries: list[PackageSubject] = []
    claimed: set[str] = set()
    for family in sboms.FAMILIES:
        artifact = artifacts[family.family_id]
        sbom_file = sboms.sbom_name(artifact.name)
        for name in (artifact.name, sbom_file):
            if name not in listed:
                raise SubjectError(f"{sboms.CHECKSUMS} does not list the {family.family_id} subject {name}")
            claimed.add(name)
        entries.append(PackageSubject(
            family.family_id,
            Subject(artifact.name, listed[artifact.name]),
            Subject(sbom_file, listed[sbom_file]),
        ))
    unknown = sorted(set(listed) - claimed)
    if unknown:
        raise SubjectError(f"{sboms.CHECKSUMS} lists unknown release subjects: {unknown}")
    checksums = Subject(sboms.CHECKSUMS, sboms.sha256_of(directory / sboms.CHECKSUMS))
    result = SubjectSet(tuple(entries), checksums)
    names = [s.name for s in result.all_subjects()]
    if len(names) != SUBJECT_COUNT or len(set(names)) != SUBJECT_COUNT:
        raise SubjectError(f"expected {SUBJECT_COUNT} distinct release subjects, found {len(set(names))}")
    for subject in result.all_subjects():
        if SHA256_RE.fullmatch(subject.sha256) is None:
            raise SubjectError(f"{subject.name}: not a lowercase hexadecimal SHA-256")
    return result


def outputs(subjects: SubjectSet, assets_dir: Path) -> dict[str, str]:
    """Deterministic ``key -> value`` step outputs for the workflow."""
    values: dict[str, str] = {}
    for entry in subjects.packages:
        values[f"{entry.family_id}_name"] = entry.package.name
        values[f"{entry.family_id}_sha256"] = entry.package.sha256
        values[f"{entry.family_id}_sbom_path"] = (assets_dir / entry.sbom.name).as_posix()
    values["checksums_name"] = subjects.checksums.name
    values["checksums_sha256"] = subjects.checksums.sha256
    values["subject_count"] = str(SUBJECT_COUNT)
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9._+~/-]+", value):
            raise SubjectError(f"output {key} has an unsafe value: {value!r}")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--assets-dir", type=Path, required=True, help="the final dist/release-assets directory")
    parser.add_argument("--version", help="release version (default: pyproject.toml)")
    parser.add_argument("--github-output", type=Path, help="append the outputs to this GITHUB_OUTPUT file")
    args = parser.parse_args(argv)
    try:
        version = args.version or sboms.project_version()
        values = outputs(prepare(args.assets_dir, version), args.assets_dir)
    except (SubjectError, OSError, KeyError) as error:
        print(f"prepare_attestation_subjects: {error}", file=sys.stderr)
        return 1
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)
    print(f"prepare_attestation_subjects: {SUBJECT_COUNT} release subjects prepared", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
