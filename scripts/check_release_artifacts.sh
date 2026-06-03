#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    echo "check_release_artifacts.sh: failed to read version" >&2
    exit 1
fi

PKG_NAME="pysh-shell"
PKG_RELEASE="1"

EXPECTED_WHEEL_NAME="pysh_shell-${VERSION}-py3-none-any.whl"
EXPECTED_SDIST_HYPHEN="pysh-shell-${VERSION}.tar.gz"
EXPECTED_SDIST_UNDER="pysh_shell-${VERSION}.tar.gz"
EXPECTED_DEB="${PKG_NAME}_${VERSION}-${PKG_RELEASE}_all.deb"
EXPECTED_RPM="${PKG_NAME}-${VERSION}-${PKG_RELEASE}.noarch.rpm"

WHEEL_PATH="${REPO_ROOT}/dist/${EXPECTED_WHEEL_NAME}"
DEB_PATH="${REPO_ROOT}/dist/os/deb/${EXPECTED_DEB}"
RPM_PATH="${REPO_ROOT}/dist/os/rpm/${EXPECTED_RPM}"

missing=0

check_present() {
    local path="$1"
    if [ ! -f "${path}" ]; then
        echo "check_release_artifacts.sh: missing artifact: ${path}" >&2
        missing=1
    fi
}

check_present "${WHEEL_PATH}"
check_present "${DEB_PATH}"
check_present "${RPM_PATH}"

# Accept either backend filename form for the sdist.
SDIST_PATH=""
if [ -f "${REPO_ROOT}/dist/${EXPECTED_SDIST_UNDER}" ]; then
    SDIST_PATH="${REPO_ROOT}/dist/${EXPECTED_SDIST_UNDER}"
elif [ -f "${REPO_ROOT}/dist/${EXPECTED_SDIST_HYPHEN}" ]; then
    SDIST_PATH="${REPO_ROOT}/dist/${EXPECTED_SDIST_HYPHEN}"
else
    echo "check_release_artifacts.sh: missing sdist (${EXPECTED_SDIST_UNDER} or ${EXPECTED_SDIST_HYPHEN})" >&2
    missing=1
fi

if [ "${missing}" -ne 0 ]; then
    echo "check_release_artifacts.sh: aborting due to missing artifacts." >&2
    exit 1
fi

# Hard-fail if any sibling .deb / .rpm violates naming.
for f in "${REPO_ROOT}/dist/os/deb"/*.deb; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_DEB}" ]; then
        echo "check_release_artifacts.sh: unexpected .deb filename: ${base}" >&2
        echo "check_release_artifacts.sh: canonical name must be ${EXPECTED_DEB}" >&2
        exit 1
    fi
done

for f in "${REPO_ROOT}/dist/os/rpm"/*.rpm; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_RPM}" ]; then
        echo "check_release_artifacts.sh: unexpected .rpm filename: ${base}" >&2
        echo "check_release_artifacts.sh: canonical name must be ${EXPECTED_RPM}" >&2
        exit 1
    fi
done

SUM_FILE="${REPO_ROOT}/dist/SHA256SUMS"
echo "==> Generating SHA256SUMS"
(
    cd "${REPO_ROOT}/dist"
    : >"${SUM_FILE}"
    # List the artifacts in a stable order using paths relative to dist/.
    sha256sum \
        "${EXPECTED_WHEEL_NAME}" \
        "$(basename "${SDIST_PATH}")" \
        "os/deb/${EXPECTED_DEB}" \
        "os/rpm/${EXPECTED_RPM}" \
        >"${SUM_FILE}"
)

echo "==> Verifying SHA256SUMS"
(
    cd "${REPO_ROOT}/dist"
    sha256sum -c SHA256SUMS
)

echo "==> Release artifacts:"
ls -1 "${REPO_ROOT}/dist"
echo "----"
ls -1 "${REPO_ROOT}/dist/os/deb"
ls -1 "${REPO_ROOT}/dist/os/rpm"
echo "----"
echo "SHA256SUMS:"
cat "${SUM_FILE}"
