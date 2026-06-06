#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
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

EXPECTED_FREEBSD_PKG="pysh-shell-${VERSION}.pkg"
FREEBSD_PKG_PATH="${REPO_ROOT}/dist/os/freebsd/${EXPECTED_FREEBSD_PKG}"
PRESERVED_FREEBSD_PKG=""

if [ -f "${FREEBSD_PKG_PATH}" ]; then
    PRESERVED_FREEBSD_PKG="$(mktemp -t pysh-freebsd-pkg.XXXXXXXX)"
    cp "${FREEBSD_PKG_PATH}" "${PRESERVED_FREEBSD_PKG}"
    echo "==> Preserved prebuilt FreeBSD .pkg: ${FREEBSD_PKG_PATH}"
fi

restore_freebsd_pkg() {
    if [ -n "${PRESERVED_FREEBSD_PKG}" ] && [ -f "${PRESERVED_FREEBSD_PKG}" ]; then
        mkdir -p "${REPO_ROOT}/dist/os/freebsd"
        cp "${PRESERVED_FREEBSD_PKG}" "${FREEBSD_PKG_PATH}"
        echo "==> Restored prebuilt FreeBSD .pkg: ${FREEBSD_PKG_PATH}"
    fi
}
trap 'rm -f "${PRESERVED_FREEBSD_PKG}"' EXIT HUP INT TERM

echo "==> [1/7] pytest -q"
"${PYTHON_BIN}" -m pytest -q

echo "==> [2/7] ruff check src tests"
"${PYTHON_BIN}" -m ruff check src tests

echo "==> [3/7] PyPI artifacts"
bash "${REPO_ROOT}/scripts/build_pysh_package.sh"
restore_freebsd_pkg

echo "==> [4/7] Debian .deb"
bash "${REPO_ROOT}/scripts/build_deb.sh"
restore_freebsd_pkg

echo "==> [5/7] RPM .rpm"
bash "${REPO_ROOT}/scripts/build_rpm.sh"
restore_freebsd_pkg

echo "==> [6/7] FreeBSD .pkg"
if [ "$(uname -s)" = "FreeBSD" ]; then
    bash "${REPO_ROOT}/scripts/build_freebsd_pkg.sh"
elif [ -f "${FREEBSD_PKG_PATH}" ]; then
    echo "==> Using prebuilt FreeBSD .pkg: ${FREEBSD_PKG_PATH}"
else
    echo "build_release_artifacts.sh: FreeBSD .pkg is mandatory but ${FREEBSD_PKG_PATH} is missing." >&2
    echo "build_release_artifacts.sh: build it on FreeBSD 14+ with scripts/build_freebsd_pkg.sh, then rerun this gate." >&2
    exit 1
fi

echo "==> [7/7] check release artifacts + SHA256SUMS"
restore_freebsd_pkg
bash "${REPO_ROOT}/scripts/check_release_artifacts.sh"

echo "==> Done. Local artifacts are under dist/ and dist/os/."
echo "==> Flat GitHub Release assets are under dist/release-assets/."
