#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_release_metadata.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

# --- release-only metadata consistency gate ------------------------------
#
# This script validates SOURCE-level release metadata: it never builds a
# wheel/sdist and never requires native packaging tools, so it is cheap
# enough to run on every ordinary push/PR. It is complementary to, and
# never a replacement for, scripts/check_release_quality.sh's authoritative
# BUILT-ARTIFACT verification (wheel METADATA, dpkg-deb/rpm content
# listing, clean-venv install smoke), which still owns that layer.
#
# Checks performed unconditionally:
#   - src/pysh/__init__.py __version__ agrees with pyproject.toml
#   - pyproject.toml project name/license/requires-python/entrypoint
#   - CHANGELOG.md heading contract (see below)
#
# Checks performed only when explicitly requested:
#   --release-mode      additionally require the target release's
#                        CHANGELOG section is no longer marked Unreleased
#   --tag TAG            additionally require TAG == v<target version>
#
# Ordinary CI must never pass --tag or --release-mode: this script's
# default invocation never requires a release tag to exist and never
# requires the current in-progress Unreleased section to be finalized.
#
# --changelog PATH and --target-version VERSION exist to make the
# CHANGELOG/tag contract independently testable against fixture files;
# omitting them targets the real CHANGELOG.md and the real pyproject.toml
# version, which is what every real caller (CI, release workflows) does.

usage() {
    cat <<'USAGE' >&2
usage: check_release_metadata.sh [--release-mode] [--tag TAG]
                                  [--changelog PATH] [--target-version VERSION]
USAGE
}

RELEASE_MODE=0
TAG=""
CHANGELOG_PATH="${REPO_ROOT}/CHANGELOG.md"
TARGET_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        --release-mode)
            RELEASE_MODE=1
            shift
            ;;
        --tag)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "check_release_metadata.sh: --tag requires a value" >&2
                exit 2
            fi
            TAG="$2"
            shift 2
            ;;
        --changelog)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "check_release_metadata.sh: --changelog requires a value" >&2
                exit 2
            fi
            CHANGELOG_PATH="$2"
            shift 2
            ;;
        --target-version)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "check_release_metadata.sh: --target-version requires a value" >&2
                exit 2
            fi
            TARGET_VERSION="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "check_release_metadata.sh: unknown argument: $1" >&2
            usage
            exit 2
            ;;
    esac
done

PYPROJECT_VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${PYPROJECT_VERSION}" ]; then
    echo "check_release_metadata.sh: failed to read version from pyproject.toml" >&2
    exit 1
fi
if [ -z "${TARGET_VERSION}" ]; then
    TARGET_VERSION="${PYPROJECT_VERSION}"
fi

echo "==> check_release_metadata.sh: pyproject.toml version ${PYPROJECT_VERSION}," \
    "target version ${TARGET_VERSION}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" - "${PYPROJECT_VERSION}" "${TARGET_VERSION}" "${RELEASE_MODE}" \
    "${TAG}" "${CHANGELOG_PATH}" <<'PY'
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

pyproject_version, target_version, release_mode_flag, tag, changelog_path = sys.argv[1:6]
release_mode = release_mode_flag == "1"

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


root = Path.cwd()

# --- 1. pyproject.toml <-> src/pysh/__init__.py version equality ---------
pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
project = pyproject["project"]

if project.get("version") != pyproject_version:
    fail(
        "internal error: pyproject.toml project.version "
        f"{project.get('version')!r} does not match the version "
        f"scripts/_pysh_version.sh derived ({pyproject_version!r})"
    )

init_py = root / "src" / "pysh" / "__init__.py"
init_text = init_py.read_text(encoding="utf-8")
match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
if match is None:
    fail("src/pysh/__init__.py: __version__ not found")
else:
    init_version = match.group(1)
    if init_version != pyproject_version:
        fail(
            "version drift: pyproject.toml declares "
            f"{pyproject_version!r} but src/pysh/__init__.py __version__ "
            f"is {init_version!r}"
        )

# --- 2. fast, pre-build pyproject.toml metadata sanity --------------------
# Complementary to, not a replacement for, check_release_quality.sh's
# post-build wheel METADATA verification.
if not re.match(r"^\d+\.\d+\.\d+$", pyproject_version):
    fail(f"pyproject.toml version must be X.Y.Z, got {pyproject_version!r}")
if project.get("name") != "pysh-shell":
    fail(f"pyproject.toml project.name must be 'pysh-shell', got {project.get('name')!r}")
if project.get("license") != "GPL-2.0-only":
    fail(
        "pyproject.toml project.license must be 'GPL-2.0-only', got "
        f"{project.get('license')!r}"
    )
if project.get("requires-python") != ">=3.13":
    fail(
        "pyproject.toml project.requires-python must be '>=3.13', got "
        f"{project.get('requires-python')!r}"
    )
if project.get("scripts", {}).get("pysh") != "pysh.cli:main":
    fail(
        "pyproject.toml project.scripts.pysh must be 'pysh.cli:main', got "
        f"{project.get('scripts', {}).get('pysh')!r}"
    )

# --- 3. CHANGELOG contract -------------------------------------------------
changelog_file = Path(changelog_path)
if not changelog_file.is_file():
    fail(f"changelog not found: {changelog_path}")
else:
    text = changelog_file.read_text(encoding="utf-8")
    heading_re = re.compile(r"^##\s+(\d+\.\d+\.\d+)(?:\s*-\s*(.+?))?\s*$", re.MULTILINE)
    headings = [
        (m.group(1), (m.group(2) or "").strip())
        for m in heading_re.finditer(text)
    ]

    if not headings:
        fail(f"{changelog_path}: no version headings found")
    else:
        counts: dict[str, int] = {}
        for version_str, _suffix in headings:
            counts[version_str] = counts.get(version_str, 0) + 1
        duplicates = sorted(v for v, count in counts.items() if count > 1)
        if duplicates:
            fail(f"{changelog_path}: duplicate version heading(s): {', '.join(duplicates)}")

        def version_tuple(value: str) -> tuple[int, ...]:
            return tuple(int(part) for part in value.split("."))

        previous: tuple[int, ...] | None = None
        for version_str, _suffix in headings:
            current = version_tuple(version_str)
            if previous is not None and current >= previous:
                fail(
                    f"{changelog_path}: version headings must be in strictly "
                    f"descending order; {version_str} does not precede the "
                    "prior heading correctly"
                )
            previous = current

        target_headings = [h for h in headings if h[0] == target_version]
        if not target_headings:
            fail(f"{changelog_path}: missing a heading for version {target_version}")
        else:
            _version, target_suffix = target_headings[0]
            target_is_unreleased = target_suffix.lower() == "unreleased"
            if release_mode and target_is_unreleased:
                fail(
                    f"{changelog_path}: release mode requires the "
                    f"{target_version} section to no longer be marked Unreleased"
                )
        # A newer Unreleased section above the target release's own section
        # is expected during active development and is never an error here;
        # only the target section's own Unreleased status is release-gated.

# --- 4. tag contract (only when --tag was explicitly given) ---------------
if tag:
    tag_match = re.match(r"^v(\d+\.\d+\.\d+)$", tag)
    if tag_match is None:
        fail(f"malformed tag {tag!r} (expected v<major>.<minor>.<patch>, e.g. v{target_version})")
    elif tag_match.group(1) != target_version:
        fail(f"tag {tag!r} does not match target version {target_version!r}")

if errors:
    for error in errors:
        print(f"check_release_metadata.sh: {error}", file=sys.stderr)
    sys.exit(1)

print("check_release_metadata.sh: all release metadata checks passed")
PY
