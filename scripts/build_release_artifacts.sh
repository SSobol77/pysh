#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/build_release_artifacts.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    echo "build_release_artifacts.sh: failed to read version from pyproject.toml" >&2
    exit 1
fi

PRESERVED_FREEBSD_DIR=""

preserve_freebsd_pkgs() {
    local pkg
    shopt -s nullglob
    local pkgs=("${REPO_ROOT}"/dist/os/freebsd/pysh-shell-"${VERSION}"-freebsd*-amd64.pkg)
    shopt -u nullglob
    if [ "${#pkgs[@]}" -gt 0 ]; then
        PRESERVED_FREEBSD_DIR="$(mktemp -d -t pysh-freebsd-pkgs.XXXXXXXX)"
        for pkg in "${pkgs[@]}"; do
            cp "${pkg}" "${PRESERVED_FREEBSD_DIR}/"
            echo "==> Preserved prebuilt FreeBSD .pkg: ${pkg}"
        done
    fi
}

restore_freebsd_pkgs() {
    local pkg
    if [ -n "${PRESERVED_FREEBSD_DIR}" ] && [ -d "${PRESERVED_FREEBSD_DIR}" ]; then
        mkdir -p "${REPO_ROOT}/dist/os/freebsd"
        for pkg in "${PRESERVED_FREEBSD_DIR}"/*.pkg; do
            [ -e "${pkg}" ] || continue
            cp "${pkg}" "${REPO_ROOT}/dist/os/freebsd/"
            echo "==> Restored prebuilt FreeBSD .pkg: $(basename "${pkg}")"
        done
    fi
}

preserve_freebsd_pkgs
trap 'rm -rf "${PRESERVED_FREEBSD_DIR}"' EXIT HUP INT TERM

echo "==> [1/7] pytest -q"
"${PYTHON_BIN}" -m pytest -q

echo "==> [2/7] ruff check src tests"
"${PYTHON_BIN}" -m ruff check src tests

echo "==> [3/7] PyPI artifacts"
bash "${REPO_ROOT}/scripts/build_pysh_package.sh"
restore_freebsd_pkgs

echo "==> [4/7] Debian .deb"
bash "${REPO_ROOT}/scripts/build_deb.sh"
restore_freebsd_pkgs

echo "==> [5/7] RPM .rpm"
bash "${REPO_ROOT}/scripts/build_rpm.sh"
restore_freebsd_pkgs

echo "==> [6/7] FreeBSD .pkg"
if [ "$(uname -s)" = "FreeBSD" ]; then
    bash "${REPO_ROOT}/scripts/build_freebsd_pkg.sh"
else
    shopt -s nullglob
    FREEBSD_PKGS=("${REPO_ROOT}"/dist/os/freebsd/pysh-shell-"${VERSION}"-freebsd*-amd64.pkg)
    shopt -u nullglob
    if [ "${#FREEBSD_PKGS[@]}" -ne 2 ]; then
        echo "build_release_artifacts.sh: both FreeBSD 14 and 15 .pkg artifacts are mandatory; found ${#FREEBSD_PKGS[@]}." >&2
        echo "build_release_artifacts.sh: build them with the release workflow FreeBSD matrix, then rerun this gate." >&2
        exit 1
    fi
    echo "==> Using prebuilt FreeBSD 14/15 .pkg artifacts."
fi

echo "==> [7/7] check release artifacts + SHA256SUMS"
restore_freebsd_pkgs
bash "${REPO_ROOT}/scripts/check_release_artifacts.sh"

echo "==> Done. Local artifacts are under dist/ and dist/os/."
echo "==> Flat GitHub Release assets are under dist/release-assets/."
