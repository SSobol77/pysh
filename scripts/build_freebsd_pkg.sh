#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

fail() {
    echo "build_freebsd_pkg.sh: $*" >&2
    exit 1
}

if [ "$(uname -s)" != "FreeBSD" ]; then
    fail "FreeBSD .pkg must be built on FreeBSD 14+ with native pkg tooling; refusing to fake .pkg on $(uname -s)."
fi

FREEBSD_MAJOR="$(uname -r | awk -F. '{print $1}')"
case "${FREEBSD_MAJOR}" in
    ''|*[!0-9]*)
        fail "failed to parse FreeBSD version from uname -r: $(uname -r)"
        ;;
esac
if [ "${FREEBSD_MAJOR}" -lt 14 ]; then
    fail "FreeBSD 14+ is required to build PySH .pkg artifacts; found $(uname -r)."
fi

if ! command -v pkg >/dev/null 2>&1; then
    fail "required FreeBSD pkg tooling not found in PATH."
fi

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    fail "failed to read version from pyproject.toml"
fi

PKG_NAME="pysh-shell"
# Canonical FreeBSD package filename format: pysh-shell-${VERSION}.pkg
EXPECTED_PKG="${PKG_NAME}-${VERSION}.pkg"
OUT_DIR="${REPO_ROOT}/dist/os/freebsd"
EXPECTED_PATH="${OUT_DIR}/${EXPECTED_PKG}"
PREFIX="/usr/local"
LIB_DIR="${PREFIX}/lib/${PKG_NAME}/pysh"
DOC_DIR="${PREFIX}/share/doc/${PKG_NAME}"
REQUIRED_BIN="/usr/local/bin/pysh"
REQUIRED_LIB="/usr/local/lib/pysh-shell/pysh"

echo "==> Building FreeBSD package ${EXPECTED_PKG}"

STAGE_DIR="$(mktemp -d -t pysh-freebsd-pkg.XXXXXXXX)"
MANIFEST="$(mktemp -t pysh-freebsd-manifest.XXXXXXXX)"
LISTING="$(mktemp -t pysh-freebsd-listing.XXXXXXXX)"
trap 'rm -rf "${STAGE_DIR}" "${MANIFEST}" "${LISTING}"' EXIT

mkdir -p \
    "${STAGE_DIR}${LIB_DIR}" \
    "${STAGE_DIR}${PREFIX}/bin" \
    "${STAGE_DIR}${DOC_DIR}" \
    "${OUT_DIR}"

cp -a "${REPO_ROOT}/src/pysh/." "${STAGE_DIR}${LIB_DIR}/"
find "${STAGE_DIR}${LIB_DIR}" -type d -name '__pycache__' -prune -exec rm -rf {} +

cat >"${STAGE_DIR}${PREFIX}/bin/pysh" <<'SH'
#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -eu

PYSH_APP_PREFIX="${PYSH_APP_PREFIX:-/usr/local/lib/pysh-shell}"

if [ -n "${PYTHONPATH:-}" ]; then
    PYTHONPATH="${PYSH_APP_PREFIX}:${PYTHONPATH}"
else
    PYTHONPATH="${PYSH_APP_PREFIX}"
fi
export PYTHONPATH

exec /usr/local/bin/python3.13 -m pysh "$@"
SH
chmod 0755 "${STAGE_DIR}${PREFIX}/bin/pysh"

install -m 0644 "${REPO_ROOT}/README.md" "${STAGE_DIR}${DOC_DIR}/README.md"
install -m 0644 "${REPO_ROOT}/LICENSE" "${STAGE_DIR}${DOC_DIR}/LICENSE"

cat >"${MANIFEST}" <<EOF
name: ${PKG_NAME}
version: "${VERSION}"
origin: shells/${PKG_NAME}
comment: Fast, Python-first universal interactive shell
desc: <<EOD
PySH is a Python-first interactive shell and command execution environment.
It installs the explicit pysh command only and must not replace /bin/sh or
claim POSIX sh compatibility.
EOD
maintainer: Siergej Sobolewski <ssobo77@gmail.com>
www: https://github.com/SSobol77/pysh
prefix: ${PREFIX}
licenselogic: single
licenses: [GPLv2]
categories: [shells, python]
deps: {
  python313: {
    origin: lang/python313
    version: ">=3.13"
  }
}
EOF

rm -f "${EXPECTED_PATH}"
pkg create -r "${STAGE_DIR}" -M "${MANIFEST}" -o "${OUT_DIR}"

if [ ! -f "${EXPECTED_PATH}" ]; then
    echo "build_freebsd_pkg.sh: expected ${EXPECTED_PATH} but it was not produced." >&2
    echo "build_freebsd_pkg.sh: contents of ${OUT_DIR}:" >&2
    ls -1 "${OUT_DIR}" >&2 || true
    exit 1
fi

for f in "${OUT_DIR}"/*.pkg; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_PKG}" ]; then
        echo "build_freebsd_pkg.sh: unexpected artifact filename: ${base}" >&2
        echo "build_freebsd_pkg.sh: canonical name must be ${EXPECTED_PKG}" >&2
        exit 1
    fi
done

echo "==> Validating ${EXPECTED_PATH}"
pkg info -F "${EXPECTED_PATH}"
pkg query -F "${EXPECTED_PATH}" "%Fp" >"${LISTING}"

if ! grep -Fxq "${REQUIRED_BIN}" "${LISTING}"; then
    fail "FreeBSD .pkg missing required path: ${REQUIRED_BIN}"
fi
if ! grep -Eq "^${REQUIRED_LIB}(/|$)" "${LISTING}"; then
    fail "FreeBSD .pkg missing required path: ${REQUIRED_LIB}"
fi

echo "==> FreeBSD package built: ${EXPECTED_PATH}"
