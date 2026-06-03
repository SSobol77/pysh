#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "build_deb.sh: dpkg-deb is required but was not found in PATH." >&2
    echo "build_deb.sh: install the 'dpkg' package and retry." >&2
    exit 127
fi

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    echo "build_deb.sh: failed to read version from pyproject.toml" >&2
    exit 1
fi

PKG_NAME="pysh-shell"
PKG_RELEASE="1"
PKG_ARCH="all"
EXPECTED_DEB="${PKG_NAME}_${VERSION}-${PKG_RELEASE}_${PKG_ARCH}.deb"
OUT_DIR="${REPO_ROOT}/dist/os/deb"
EXPECTED_PATH="${OUT_DIR}/${EXPECTED_DEB}"

echo "==> Building Debian package ${EXPECTED_DEB}"

STAGE_DIR="$(mktemp -d -t pysh-deb.XXXXXXXX)"
trap 'rm -rf "${STAGE_DIR}"' EXIT

mkdir -p \
    "${STAGE_DIR}/DEBIAN" \
    "${STAGE_DIR}/opt/pysh-shell/lib/pysh" \
    "${STAGE_DIR}/usr/bin" \
    "${STAGE_DIR}/usr/share/doc/${PKG_NAME}"

# Substitute @VERSION@ in the control file.
sed "s/@VERSION@/${VERSION}/g" \
    "${REPO_ROOT}/packaging/debian/control" \
    >"${STAGE_DIR}/DEBIAN/control"

install -m 0755 "${REPO_ROOT}/packaging/debian/postinst" \
    "${STAGE_DIR}/DEBIAN/postinst"
install -m 0755 "${REPO_ROOT}/packaging/debian/prerm" \
    "${STAGE_DIR}/DEBIAN/prerm"
install -m 0644 "${REPO_ROOT}/packaging/debian/copyright" \
    "${STAGE_DIR}/usr/share/doc/${PKG_NAME}/copyright"

# Copy the Python source tree, stripping caches.
cp -a "${REPO_ROOT}/src/pysh/." "${STAGE_DIR}/opt/pysh-shell/lib/pysh/"
find "${STAGE_DIR}/opt/pysh-shell/lib/pysh" -type d -name '__pycache__' \
    -prune -exec rm -rf {} +

# Install the wrapper command.
install -m 0755 "${REPO_ROOT}/packaging/wrappers/pysh.sh" \
    "${STAGE_DIR}/usr/bin/pysh"

mkdir -p "${OUT_DIR}"

DPKG_BUILD_OPTS=()
if command -v fakeroot >/dev/null 2>&1; then
    DPKG_BUILD_CMD=(fakeroot dpkg-deb --build "${DPKG_BUILD_OPTS[@]}" \
        "${STAGE_DIR}" "${OUT_DIR}")
else
    echo "build_deb.sh: fakeroot not found; building without it." >&2
    DPKG_BUILD_CMD=(dpkg-deb --build "${DPKG_BUILD_OPTS[@]}" \
        "${STAGE_DIR}" "${OUT_DIR}")
fi
"${DPKG_BUILD_CMD[@]}"

if [ ! -f "${EXPECTED_PATH}" ]; then
    echo "build_deb.sh: expected ${EXPECTED_PATH} but it was not produced." >&2
    echo "build_deb.sh: contents of ${OUT_DIR}:" >&2
    ls -1 "${OUT_DIR}" >&2 || true
    exit 1
fi

# Hard-fail on any unexpected sibling output to enforce the naming contract.
for f in "${OUT_DIR}"/*.deb; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_DEB}" ]; then
        echo "build_deb.sh: unexpected artifact filename: ${base}" >&2
        echo "build_deb.sh: canonical name must be ${EXPECTED_DEB}" >&2
        exit 1
    fi
done

echo "==> Validating ${EXPECTED_PATH}"
dpkg-deb --info "${EXPECTED_PATH}"
dpkg-deb --contents "${EXPECTED_PATH}"

echo "==> Debian package built: ${EXPECTED_PATH}"
