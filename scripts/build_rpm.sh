#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "build_rpm.sh: rpmbuild is required but was not found in PATH." >&2
    echo "build_rpm.sh: install the 'rpm' / 'rpm-build' packages and retry." >&2
    echo "build_rpm.sh: on Debian: 'sudo apt-get install -y rpm'." >&2
    exit 127
fi

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    echo "build_rpm.sh: failed to read version from pyproject.toml" >&2
    exit 1
fi

PKG_NAME="pysh-shell"
PKG_RELEASE="1"
PKG_ARCH="noarch"
EXPECTED_RPM="${PKG_NAME}-${VERSION}-${PKG_RELEASE}.${PKG_ARCH}.rpm"
OUT_DIR="${REPO_ROOT}/dist/os/rpm"
EXPECTED_PATH="${OUT_DIR}/${EXPECTED_RPM}"

echo "==> Building RPM package ${EXPECTED_RPM}"

BUILD_ROOT="$(mktemp -d -t pysh-rpm.XXXXXXXX)"
trap 'rm -rf "${BUILD_ROOT}"' EXIT

mkdir -p \
    "${BUILD_ROOT}/SOURCES" \
    "${BUILD_ROOT}/SPECS" \
    "${BUILD_ROOT}/BUILD" \
    "${BUILD_ROOT}/RPMS" \
    "${BUILD_ROOT}/SRPMS"

SRC_STAGE="$(mktemp -d -t pysh-rpm-src.XXXXXXXX)"
trap 'rm -rf "${BUILD_ROOT}" "${SRC_STAGE}"' EXIT

# Pack a source tarball laid out exactly as the spec expects:
# pysh-shell-X.Y.Z/
#   src/pysh/...
#   packaging/wrappers/pysh.sh
#   LICENSE README.md
TARBALL_TOP="${PKG_NAME}-${VERSION}"
mkdir -p "${SRC_STAGE}/${TARBALL_TOP}"
cp -a "${REPO_ROOT}/src" "${SRC_STAGE}/${TARBALL_TOP}/src"
cp -a "${REPO_ROOT}/packaging" "${SRC_STAGE}/${TARBALL_TOP}/packaging"
cp -a "${REPO_ROOT}/LICENSE" "${SRC_STAGE}/${TARBALL_TOP}/LICENSE"
cp -a "${REPO_ROOT}/README.md" "${SRC_STAGE}/${TARBALL_TOP}/README.md"
find "${SRC_STAGE}/${TARBALL_TOP}" -type d -name '__pycache__' \
    -prune -exec rm -rf {} +

tar -C "${SRC_STAGE}" -czf \
    "${BUILD_ROOT}/SOURCES/${TARBALL_TOP}.tar.gz" "${TARBALL_TOP}"

install -m 0644 "${REPO_ROOT}/packaging/rpm/${PKG_NAME}.spec" \
    "${BUILD_ROOT}/SPECS/${PKG_NAME}.spec"

mkdir -p "${OUT_DIR}"

rpmbuild \
    --define "_topdir ${BUILD_ROOT}" \
    --define "pysh_version ${VERSION}" \
    --define "dist %{nil}" \
    -bb "${BUILD_ROOT}/SPECS/${PKG_NAME}.spec"

PRODUCED="${BUILD_ROOT}/RPMS/${PKG_ARCH}/${EXPECTED_RPM}"
if [ ! -f "${PRODUCED}" ]; then
    echo "build_rpm.sh: expected ${PRODUCED} but it was not produced." >&2
    echo "build_rpm.sh: contents of ${BUILD_ROOT}/RPMS:" >&2
    find "${BUILD_ROOT}/RPMS" -type f >&2 || true
    exit 1
fi

cp -f "${PRODUCED}" "${EXPECTED_PATH}"

# Hard-fail on any unexpected sibling output to enforce the naming contract.
for f in "${OUT_DIR}"/*.rpm; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_RPM}" ]; then
        echo "build_rpm.sh: unexpected artifact filename: ${base}" >&2
        echo "build_rpm.sh: canonical name must be ${EXPECTED_RPM}" >&2
        exit 1
    fi
done

if command -v rpm >/dev/null 2>&1; then
    echo "==> Validating ${EXPECTED_PATH}"
    rpm -qip "${EXPECTED_PATH}"
    rpm -qlp "${EXPECTED_PATH}"
else
    echo "build_rpm.sh: rpm CLI not found; skipping rpm -qip/-qlp validation." >&2
fi

echo "==> RPM package built: ${EXPECTED_PATH}"
