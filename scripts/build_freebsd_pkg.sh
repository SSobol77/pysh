#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/build_freebsd_pkg.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"
# shellcheck source=scripts/_freebsd_python.sh
. "${REPO_ROOT}/scripts/_freebsd_python.sh"

fail() {
    echo "build_freebsd_pkg.sh: $*" >&2
    exit 1
}

pysh_freebsd_python_config "build_freebsd_pkg.sh"

if [ "$(uname -s)" != "FreeBSD" ]; then
    fail "FreeBSD .pkg must be built in a native FreeBSD-family pkg environment; refusing to fake .pkg on $(uname -s)."
fi

FREEBSD_MAJOR="$(uname -r | awk -F. '{print $1}')"
case "${FREEBSD_MAJOR}" in
    ''|*[!0-9]*)
        fail "failed to parse FreeBSD version from uname -r: $(uname -r)"
        ;;
esac
if ! command -v pkg >/dev/null 2>&1; then
    fail "required FreeBSD pkg tooling not found in PATH."
fi
pysh_freebsd_python_validate "build_freebsd_pkg.sh" || exit $?

HOST_ABI="$(pkg config ABI)" || fail "failed to read the native ABI from pkg config ABI."
HOST_ABI_SYSTEM="$(printf '%s\n' "${HOST_ABI}" | awk -F: '{print $1}')"
HOST_ABI_MAJOR="$(printf '%s\n' "${HOST_ABI}" | awk -F: '{print $2}')"
HOST_ABI_ARCH="$(printf '%s\n' "${HOST_ABI}" | awk -F: '{print $3}')"
if [ "${HOST_ABI}" != "${HOST_ABI_SYSTEM}:${HOST_ABI_MAJOR}:${HOST_ABI_ARCH}" ] || \
    [ "${HOST_ABI_SYSTEM}" != "FreeBSD" ] || \
    [ "${HOST_ABI_MAJOR}" != "${FREEBSD_MAJOR}" ]; then
    fail "pkg host ABI does not match uname -r: ${HOST_ABI} versus FreeBSD ${FREEBSD_MAJOR}."
fi
case "${HOST_ABI_ARCH}" in
    ''|*[!A-Za-z0-9_]*) fail "unsupported architecture token in pkg host ABI: ${HOST_ABI}" ;;
esac

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    fail "failed to read version from pyproject.toml"
fi

# Deterministic-build contract (Issue #51): SOURCE_DATE_EPOCH is the commit timestamp of the
# exact source commit, exported by the release workflow. When it is set, pkg create receives it
# through its native reproducible-package control (-t); the finished .pkg is never touched,
# repacked or normalized afterwards. An empty value is treated as unset and there is no
# wall-clock fallback: without SOURCE_DATE_EPOCH the ordinary manual build is unchanged.
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    case "${SOURCE_DATE_EPOCH}" in
        *[!0-9]*)
            fail "SOURCE_DATE_EPOCH must be decimal epoch seconds (the source commit timestamp); got '${SOURCE_DATE_EPOCH}'."
            ;;
    esac
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

echo "==> Building FreeBSD package ${EXPECTED_PKG} for native ABI ${HOST_ABI}"

STAGE_DIR="$(mktemp -d -t pysh-freebsd-pkg.XXXXXXXX)"
MANIFEST="$(mktemp -t pysh-freebsd-manifest.XXXXXXXX)"
LISTING="$(mktemp -t pysh-freebsd-listing.XXXXXXXX)"
PLIST="$(mktemp -t pysh-freebsd-plist.XXXXXXXX)"
trap 'rm -rf "${STAGE_DIR}" "${MANIFEST}" "${LISTING}" "${PLIST}"' EXIT

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
SH
printf '\nexec %s -m pysh "$@"\n' "${PYSH_FREEBSD_PYTHON_COMMAND}" \
    >>"${STAGE_DIR}${PREFIX}/bin/pysh"
chmod 0755 "${STAGE_DIR}${PREFIX}/bin/pysh"

install -m 0644 "${REPO_ROOT}/README.md" "${STAGE_DIR}${DOC_DIR}/README.md"
install -m 0644 "${REPO_ROOT}/LICENSE" "${STAGE_DIR}${DOC_DIR}/LICENSE"

# pkg create -M manifest does not auto-discover files from -r rootdir in pkg 2.x;
# an explicit plist of installed paths is required to populate the archive.
find "${STAGE_DIR}" \( -type f -o -type l \) \
    | LC_ALL=C sort \
    | sed "s|^${STAGE_DIR}||" > "${PLIST}"

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
  ${PYSH_FREEBSD_PYTHON_PACKAGE}: {
    origin: ${PYSH_FREEBSD_PYTHON_ORIGIN}
    version: ">=${PYSH_FREEBSD_PYTHON_VERSION}"
  }
}
EOF

rm -f "${EXPECTED_PATH}"
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    pkg create -t "${SOURCE_DATE_EPOCH}" -r "${STAGE_DIR}" -M "${MANIFEST}" -p "${PLIST}" -o "${OUT_DIR}"
else
    pkg create -r "${STAGE_DIR}" -M "${MANIFEST}" -p "${PLIST}" -o "${OUT_DIR}"
fi

if [ ! -f "${EXPECTED_PATH}" ]; then
    echo "build_freebsd_pkg.sh: expected ${EXPECTED_PATH} but it was not produced." >&2
    echo "build_freebsd_pkg.sh: contents of ${OUT_DIR}:" >&2
    ls -1 "${OUT_DIR}" >&2 || true
    exit 1
fi

PACKAGE_ABI="$(pkg query -F "${EXPECTED_PATH}" "%q")" || \
    fail "failed to read package ABI from ${EXPECTED_PATH}."
if [ "${PACKAGE_ABI}" != "${HOST_ABI}" ]; then
    fail "unexpected package ABI: expected native ${HOST_ABI}, got ${PACKAGE_ABI}"
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
VALIDATED_ABI="$(pkg query -F "${EXPECTED_PATH}" "%q")"
if [ "${VALIDATED_ABI}" != "${HOST_ABI}" ]; then
    fail "package ABI changed during validation: ${HOST_ABI} -> ${VALIDATED_ABI}"
fi
pkg query -F "${EXPECTED_PATH}" "%Fp" >"${LISTING}"

if ! grep -Fxq "${REQUIRED_BIN}" "${LISTING}"; then
    fail "FreeBSD .pkg missing required path: ${REQUIRED_BIN}"
fi
if ! grep -Eq "^${REQUIRED_LIB}(/|$)" "${LISTING}"; then
    fail "FreeBSD .pkg missing required path: ${REQUIRED_LIB}"
fi

echo "==> FreeBSD package built: ${EXPECTED_PATH}"
