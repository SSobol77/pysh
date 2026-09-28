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

FREEBSD_PKG_DIR="${REPO_ROOT}/dist/os/freebsd"
EXPECTED_FREEBSD_14_PKG="pysh-shell-${VERSION}-freebsd14-amd64.pkg"
EXPECTED_FREEBSD_15_PKG="pysh-shell-${VERSION}-freebsd15-amd64.pkg"
PRESERVED_FREEBSD_DIR=""

preserve_freebsd_pkgs() {
    local name path
    for name in "${EXPECTED_FREEBSD_14_PKG}" "${EXPECTED_FREEBSD_15_PKG}"; do
        path="${FREEBSD_PKG_DIR}/${name}"
        if [ -f "${path}" ]; then
            if [ -z "${PRESERVED_FREEBSD_DIR}" ]; then
                PRESERVED_FREEBSD_DIR="$(mktemp -d -t pysh-freebsd-pkgs.XXXXXXXX)"
            fi
            cp "${path}" "${PRESERVED_FREEBSD_DIR}/${name}"
            echo "==> Preserved prebuilt FreeBSD .pkg: ${path}"
        fi
    done
}

restore_missing_freebsd_pkgs() {
    local name preserved target
    if [ -z "${PRESERVED_FREEBSD_DIR}" ] || [ ! -d "${PRESERVED_FREEBSD_DIR}" ]; then
        return
    fi
    mkdir -p "${FREEBSD_PKG_DIR}"
    for name in "${EXPECTED_FREEBSD_14_PKG}" "${EXPECTED_FREEBSD_15_PKG}"; do
        preserved="${PRESERVED_FREEBSD_DIR}/${name}"
        target="${FREEBSD_PKG_DIR}/${name}"
        if [ -f "${preserved}" ] && [ ! -e "${target}" ]; then
            cp "${preserved}" "${target}"
            echo "==> Restored missing prebuilt FreeBSD .pkg: ${target}"
        fi
    done
}

require_freebsd_pkg() {
    local path="$1"
    [ -s "${path}" ] || {
        echo "build_release_artifacts.sh: required FreeBSD .pkg is missing or empty: ${path}" >&2
        exit 1
    }
}

cleanup() {
    if [ -n "${PRESERVED_FREEBSD_DIR}" ] && [ -d "${PRESERVED_FREEBSD_DIR}" ]; then
        rm -rf "${PRESERVED_FREEBSD_DIR}"
    fi
}

preserve_freebsd_pkgs
trap cleanup EXIT HUP INT TERM

echo "==> [1/7] pytest -q"
"${PYTHON_BIN}" -m pytest -q

echo "==> [2/7] ruff check src tests"
"${PYTHON_BIN}" -m ruff check src tests

echo "==> [3/7] PyPI artifacts"
bash "${REPO_ROOT}/scripts/build_pysh_package.sh"
restore_missing_freebsd_pkgs

echo "==> [4/7] Debian .deb"
bash "${REPO_ROOT}/scripts/build_deb.sh"
restore_missing_freebsd_pkgs

echo "==> [5/7] RPM .rpm"
bash "${REPO_ROOT}/scripts/build_rpm.sh"
restore_missing_freebsd_pkgs

echo "==> [6/7] FreeBSD .pkg"
if [ "$(uname -s)" = "FreeBSD" ]; then
    HOST_ABI="$(pkg config ABI)"
    case "${HOST_ABI}" in
        FreeBSD:14:amd64)
            require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_15_PKG}"
            ;;
        FreeBSD:15:amd64)
            require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_14_PKG}"
            ;;
        *)
            echo "build_release_artifacts.sh: release packages target FreeBSD 14/15 amd64; native host ABI is ${HOST_ABI}." >&2
            exit 1
            ;;
    esac
    bash "${REPO_ROOT}/scripts/build_freebsd_pkg.sh"
    # Preserve a freshly built native package. Only restore the other ABI if a
    # preceding build removed it; never overwrite new bytes with stale input.
    restore_missing_freebsd_pkgs
else
    require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_14_PKG}"
    require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_15_PKG}"
    echo "==> Using prebuilt FreeBSD 14/15 amd64 .pkg artifacts."
fi

echo "==> [7/7] check release artifacts + SHA256SUMS"
require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_14_PKG}"
require_freebsd_pkg "${FREEBSD_PKG_DIR}/${EXPECTED_FREEBSD_15_PKG}"
bash "${REPO_ROOT}/scripts/check_release_artifacts.sh"

echo "==> Done. Local artifacts are under dist/ and dist/os/."
echo "==> Flat GitHub Release assets are under dist/release-assets/."
