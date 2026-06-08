#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_release_quality.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

TMPDIR=""
PRESERVED_FREEBSD_PKG=""

cleanup() {
    if [ -n "${TMPDIR}" ] && [ -d "${TMPDIR}" ]; then
        rm -rf "${TMPDIR}"
    fi
    if [ -n "${PRESERVED_FREEBSD_PKG}" ] && [ -f "${PRESERVED_FREEBSD_PKG}" ]; then
        rm -f "${PRESERVED_FREEBSD_PKG}"
    fi
}
trap cleanup EXIT HUP INT TERM

log() {
    printf '==> %s\n' "$*"
}

fail() {
    printf 'check_release_quality.sh: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_file() {
    [ -f "$1" ] || fail "required file missing: $1"
}

require_command uv
require_command git
require_command dpkg-deb
require_command rpm
require_command rpmbuild
require_command sha256sum
require_command awk
require_command grep
require_command sed

normalize_package_listing() {
    sed 's#^\./#/#' "$1" | sed 's#//*#/#g' | sed 's#/$##'
}

require_listed_path() {
    local label="$1"
    local listing_file="$2"
    local required_path="$3"
    local normalized_required

    normalized_required="/${required_path#/}"
    normalized_required="${normalized_required%/}"
    if ! normalize_package_listing "${listing_file}" | grep -Fxq "${normalized_required}"; then
        fail "${label} missing required path: ${required_path}"
    fi
}

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    fail "failed to read version from pyproject.toml"
fi

EXPECTED_FREEBSD_PKG="pysh-shell-${VERSION}.pkg"
FREEBSD_PKG_PATH="${REPO_ROOT}/dist/os/freebsd/${EXPECTED_FREEBSD_PKG}"

preserve_freebsd_pkg() {
    if [ -f "${FREEBSD_PKG_PATH}" ]; then
        PRESERVED_FREEBSD_PKG="$(mktemp -t pysh-freebsd-pkg.XXXXXXXX)"
        cp "${FREEBSD_PKG_PATH}" "${PRESERVED_FREEBSD_PKG}"
        log "Preserved prebuilt FreeBSD .pkg: ${FREEBSD_PKG_PATH}"
    fi
}

restore_freebsd_pkg() {
    if [ -n "${PRESERVED_FREEBSD_PKG}" ] && [ -f "${PRESERVED_FREEBSD_PKG}" ]; then
        mkdir -p "${REPO_ROOT}/dist/os/freebsd"
        cp "${PRESERVED_FREEBSD_PKG}" "${FREEBSD_PKG_PATH}"
        log "Restored prebuilt FreeBSD .pkg: ${FREEBSD_PKG_PATH}"
    fi
}

preserve_freebsd_pkg

log "[1/12] ruff check src tests"
uv run ruff check src tests

log "[2/12] pytest -q"
uv run pytest -q

log "[3/12] check headers"
bash "${REPO_ROOT}/scripts/check_headers.sh"

log "[4/12] git diff --check"
git diff --check

log "[5/12] required release files"
require_file pyproject.toml
require_file uv.lock
require_file README.md
require_file CHANGELOG.md
require_file LICENSE
require_file docs/development/packaging.md
require_file docs/development/release.md
require_file docs/compatibility/system-shell-integration-policy.md
require_file .github/workflows/publish.yml
require_file scripts/build_release_artifacts.sh
require_file scripts/check_release_artifacts.sh
require_file scripts/build_pysh_package.sh
require_file scripts/build_deb.sh
require_file scripts/build_rpm.sh
require_file scripts/build_freebsd_pkg.sh

log "[6/12] clean and build mandatory release artifacts"
preserve_freebsd_pkg
rm -rf dist build ./*.egg-info
restore_freebsd_pkg
TMPDIR="$(mktemp -d)"
PYTHON_WRAPPER="${TMPDIR}/python"
cat >"${PYTHON_WRAPPER}" <<'SH'
#!/usr/bin/env bash
exec uv run --with build --with twine python "$@"
SH
chmod +x "${PYTHON_WRAPPER}"
restore_freebsd_pkg
if [ "$(uname -s)" != "FreeBSD" ] && [ ! -s "${FREEBSD_PKG_PATH}" ]; then
    fail "prebuilt FreeBSD .pkg is required before build_release_artifacts.sh: ${FREEBSD_PKG_PATH}"
fi
PYTHON_BIN="${PYTHON_WRAPPER}" bash "${REPO_ROOT}/scripts/build_release_artifacts.sh"

log "[7/12] confirm mandatory artifact families"
shopt -s nullglob
wheels=(dist/*.whl)
sdists=(dist/*.tar.gz)
debs=(dist/os/deb/pysh-shell_*-1_all.deb)
rpms=(dist/os/rpm/pysh-shell-*-1.noarch.rpm)
pkgs=(dist/os/freebsd/pysh-shell-*.pkg)
shopt -u nullglob

if [ "${#wheels[@]}" -ne 1 ]; then
    fail "expected exactly one wheel in dist/, found ${#wheels[@]}"
fi
if [ "${#sdists[@]}" -ne 1 ]; then
    fail "expected exactly one sdist in dist/, found ${#sdists[@]}"
fi
if [ "${#debs[@]}" -ne 1 ]; then
    fail "expected exactly one Debian artifact matching dist/os/deb/pysh-shell_*-1_all.deb, found ${#debs[@]}"
fi
if [ "${#rpms[@]}" -ne 1 ]; then
    fail "expected exactly one RPM artifact matching dist/os/rpm/pysh-shell-*-1.noarch.rpm, found ${#rpms[@]}"
fi
if [ "${#pkgs[@]}" -ne 1 ]; then
    fail "expected exactly one FreeBSD artifact matching dist/os/freebsd/pysh-shell-*.pkg, found ${#pkgs[@]}; build it on FreeBSD 14+ with scripts/build_freebsd_pkg.sh before v0.8.0 release completion"
fi
require_file dist/SHA256SUMS
require_file dist/release-assets/SHA256SUMS

log "[8/12] twine metadata check"
uv run --with twine python -m twine check "${wheels[0]}" "${sdists[0]}"

log "[9/12] inspect package metadata, contents and docs"
uv run python - <<'PY'
from __future__ import annotations

import configparser
import email.parser
import hashlib
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

root = Path.cwd()
dist = root / "dist"


def fail(message: str) -> None:
    print(f"check_release_quality.sh: {message}", file=sys.stderr)
    raise SystemExit(1)


def one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        fail(f"expected exactly one {label}, found {len(paths)}")
    return paths[0]


pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
project = pyproject["project"]
expected_name = "pysh-shell"
expected_version = project["version"]
expected_license = "GPL-2.0-only"
expected_summary = project["description"]
expected_requires_python = project["requires-python"]

if project["name"] != expected_name:
    fail(f"project.name must be {expected_name!r}, got {project['name']!r}")
if project["license"] != expected_license:
    fail(f"project.license must be {expected_license!r}, got {project['license']!r}")
if project["scripts"].get("pysh") != "pysh.cli:main":
    fail("project.scripts.pysh must be pysh.cli:main")

wheel = one(sorted(dist.glob("*.whl")), "wheel")
sdist = one(sorted(dist.glob("*.tar.gz")), "sdist")
deb = one(sorted((dist / "os" / "deb").glob("pysh-shell_*-1_all.deb")), "Debian .deb")
rpm = one(sorted((dist / "os" / "rpm").glob("pysh-shell-*-1.noarch.rpm")), "RPM .rpm")
pkg = one(sorted((dist / "os" / "freebsd").glob("pysh-shell-*.pkg")), "FreeBSD .pkg")
checksums = dist / "SHA256SUMS"
release_assets = dist / "release-assets"
release_checksums = release_assets / "SHA256SUMS"

expected_wheel_name = f"pysh_shell-{expected_version}-py3-none-any.whl"
expected_sdist_names = {
    f"pysh_shell-{expected_version}.tar.gz",
    f"pysh-shell-{expected_version}.tar.gz",
}
expected_deb_name = f"pysh-shell_{expected_version}-1_all.deb"
expected_rpm_name = f"pysh-shell-{expected_version}-1.noarch.rpm"
expected_pkg_name = f"pysh-shell-{expected_version}.pkg"

if wheel.name != expected_wheel_name:
    fail(f"wheel filename must be {expected_wheel_name}, got {wheel.name}")
if sdist.name not in expected_sdist_names:
    fail(
        "sdist filename must be one of "
        + ", ".join(sorted(expected_sdist_names))
        + f", got {sdist.name}"
    )
if deb.name != expected_deb_name:
    fail(f"Debian filename must be {expected_deb_name}, got {deb.name}")
if rpm.name != expected_rpm_name:
    fail(f"RPM filename must be {expected_rpm_name}, got {rpm.name}")
if pkg.name != expected_pkg_name:
    fail(f"FreeBSD .pkg filename must be {expected_pkg_name}, got {pkg.name}")
if not checksums.is_file():
    fail("dist/SHA256SUMS is required")
if not release_checksums.is_file():
    fail("dist/release-assets/SHA256SUMS is required")

checksum_text = checksums.read_text(encoding="utf-8")
for artifact in (wheel, sdist, deb, rpm, pkg):
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    relative = artifact.relative_to(dist).as_posix()
    expected_line = f"{digest}  {relative}"
    if expected_line not in checksum_text:
        fail(f"dist/SHA256SUMS missing checksum line for {relative}")

expected_release_asset_names = {
    wheel.name,
    sdist.name,
    deb.name,
    rpm.name,
    pkg.name,
    "SHA256SUMS",
}
actual_release_asset_names = {path.name for path in release_assets.iterdir() if path.is_file()}
if actual_release_asset_names != expected_release_asset_names:
    fail(
        "dist/release-assets must contain exactly: "
        + ", ".join(sorted(expected_release_asset_names))
    )

release_checksum_text = release_checksums.read_text(encoding="utf-8")
for artifact in (wheel, sdist, deb, rpm, pkg):
    staged = release_assets / artifact.name
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    expected_line = f"{digest}  {artifact.name}"
    if expected_line not in release_checksum_text:
        fail(f"dist/release-assets/SHA256SUMS missing flat line for {artifact.name}")

for line in release_checksum_text.splitlines():
    parts = line.split()
    if len(parts) != 2:
        fail(f"dist/release-assets/SHA256SUMS has malformed line: {line!r}")
    filename = parts[1]
    if "/" in filename or filename.startswith("."):
        fail(f"dist/release-assets/SHA256SUMS must use flat filenames, got {filename!r}")

bad_parts = (
    ".git/",
    ".github/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "build/",
)

with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    for name in names:
        if any(part in name for part in bad_parts):
            fail(f"wheel contains unwanted path: {name}")
    required = {
        "pysh/__init__.py",
        "pysh/__main__.py",
        "pysh/cli.py",
        "pysh/core/shell.py",
    }
    missing = sorted(required.difference(names))
    if missing:
        fail("wheel missing package files: " + ", ".join(missing))

    dist_info_dirs = sorted({name.split("/", 1)[0] for name in names if ".dist-info/" in name})
    if len(dist_info_dirs) != 1:
        fail(f"expected one .dist-info directory, found {dist_info_dirs!r}")
    dist_info = dist_info_dirs[0]

    metadata_name = f"{dist_info}/METADATA"
    entry_points_name = f"{dist_info}/entry_points.txt"
    wheel_name = f"{dist_info}/WHEEL"
    record_name = f"{dist_info}/RECORD"
    for required_name in (metadata_name, entry_points_name, wheel_name, record_name):
        if required_name not in names:
            fail(f"wheel missing metadata file: {required_name}")

    metadata = email.parser.Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
    checks = {
        "Name": expected_name,
        "Version": expected_version,
        "License-Expression": expected_license,
        "Summary": expected_summary,
        "Requires-Python": expected_requires_python,
    }
    for field, expected in checks.items():
        actual = metadata.get(field)
        if actual != expected:
            fail(f"wheel METADATA {field} must be {expected!r}, got {actual!r}")

    entry_points = configparser.ConfigParser()
    entry_points.read_string(archive.read(entry_points_name).decode("utf-8"))
    if entry_points.get("console_scripts", "pysh", fallback="") != "pysh.cli:main":
        fail("wheel entry_points.txt must define pysh = pysh.cli:main")

with tarfile.open(sdist) as archive:
    names = archive.getnames()
    for name in names:
        normalized = name + ("/" if archive.getmember(name).isdir() else "")
        if any(part in normalized for part in bad_parts):
            fail(f"sdist contains unwanted path: {name}")
    required_suffixes = {
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "pyproject.toml",
        "src/pysh/cli.py",
        "src/pysh/__main__.py",
    }
    for suffix in sorted(required_suffixes):
        if not any(name.endswith("/" + suffix) or name == suffix for name in names):
            fail(f"sdist missing required file: {suffix}")

readme = (root / "README.md").read_text(encoding="utf-8")
github_doc_link = re.compile(
    r"https://github\.com/SSobol77/pysh/(?:blob|tree)/main/([^)#\s]+)"
)
missing_links: list[str] = []
for match in github_doc_link.finditer(readme):
    rel = match.group(1)
    if rel.startswith("docs/") and not (root / rel).exists():
        missing_links.append(rel)
if missing_links:
    fail("README references missing docs: " + ", ".join(sorted(set(missing_links))))

docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
local_doc_link = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")
missing_doc_links: list[str] = []
for match in local_doc_link.finditer(docs_index):
    target = match.group(1)
    if "://" in target or target.startswith("mailto:"):
        continue
    path = (root / "docs" / target).resolve()
    if not path.exists():
        missing_doc_links.append(target)
if missing_doc_links:
    fail("docs/README.md references missing docs: " + ", ".join(sorted(set(missing_doc_links))))

packaging_docs = [
    root / "docs" / "development" / "packaging.md",
    root / "docs" / "user" / "installation.md",
    root / "packaging" / "debian" / "README.md",
    root / "packaging" / "rpm" / "README.md",
]
for path in packaging_docs:
    text = path.read_text(encoding="utf-8")
    forbidden = (
        "PySH is a /bin/sh replacement",
        "PySH is POSIX-compatible",
        "PySH is bash-compatible",
        "PySH is zsh-compatible",
        "symlink /bin/sh to PySH",
    )
    for phrase in forbidden:
        if phrase in text:
            fail(f"{path.relative_to(root)} contains forbidden packaging claim: {phrase}")
PY

log "[10/12] inspect OS package contents"
DEB_LISTING="${TMPDIR}/deb-contents.txt"
RPM_LISTING="${TMPDIR}/rpm-contents.txt"
dpkg-deb --contents "${debs[0]}" | awk '{print $NF}' >"${DEB_LISTING}"
rpm -qpl --dbpath "${TMPDIR}/rpmdb" "${rpms[0]}" >"${RPM_LISTING}"
require_listed_path "Debian .deb" "${DEB_LISTING}" "/usr/bin/pysh"
require_listed_path "Debian .deb" "${DEB_LISTING}" "/opt/pysh-shell/lib/pysh"
require_listed_path "RPM .rpm" "${RPM_LISTING}" "/usr/bin/pysh"
require_listed_path "RPM .rpm" "${RPM_LISTING}" "/opt/pysh-shell/lib/pysh"

log "[11/12] clean virtualenv install smoke"
PYTHON_BIN="$(uv run python -c 'import sys; print(sys.executable)')"
"${PYTHON_BIN}" -m venv "${TMPDIR}/venv"
VENV_PY="${TMPDIR}/venv/bin/python"
VENV_PYSH="${TMPDIR}/venv/bin/pysh"
WHEEL_PATH="$(ls -1 dist/*.whl)"
"${VENV_PY}" -m pip install --no-deps "${WHEEL_PATH}"
"${VENV_PYSH}" --version
"${VENV_PY}" -m pysh --version
SMOKE_OUTPUT="$("${VENV_PYSH}" -c "echo release-smoke")"
if [ "${SMOKE_OUTPUT}" != "release-smoke" ]; then
    fail "pysh -c smoke output mismatch: ${SMOKE_OUTPUT}"
fi

log "[12/12] release quality gate complete"
printf 'Release quality gate passed. Artifacts are in dist/.\n'
