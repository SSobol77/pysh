#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/smoke_freebsd_package.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"
# shellcheck source=scripts/_freebsd_python.sh
. "${REPO_ROOT}/scripts/_freebsd_python.sh"

SCRIPT_NAME="smoke_freebsd_package.sh"
pysh_freebsd_python_config "${SCRIPT_NAME}"

# --- real FreeBSD package install-and-run smoke (Issue #33 RQG-E) --------
#
# This installs the supplied .pkg through REAL FreeBSD package management
# ("pkg add <local-file>", the pkg(8)-documented way to install a local
# package file without a configured repository) directly on the FreeBSD
# host this script runs on, then exercises the INSTALLED console
# entrypoint. It never extracts the archive as a substitute for
# installation, and it never runs anywhere but real FreeBSD: the .pkg
# format and pkg(8) tooling do not exist on Linux/macOS/Windows, so there
# is no container or emulation fallback that would prove anything real.
#
# This is complementary to, not a replacement for, the existing
# "pkg info -F" / "pkg query -F" static content-listing checks in
# scripts/build_freebsd_pkg.sh and .github/workflows/release-artifacts.yml,
# which stay in place unchanged.

fail() {
    printf '%s: %s\n' "${SCRIPT_NAME}" "$*" >&2
    exit 1
}

usage() {
    cat <<USAGE >&2
usage: ${SCRIPT_NAME} <path-to-abi-specific-pysh-shell.pkg>

Installs the given FreeBSD package via real "pkg add <local-file>" package
management directly on the FreeBSD host this script runs on, then verifies
the installed console entrypoint (pysh --version, selected-python -m pysh
--version, pysh -c, and a real PTY-driven interactive exit/quit). Must be
executed on real FreeBSD 14+; there is no Linux/Docker/emulation fallback.
USAGE
}

if [ "$#" -ne 1 ]; then
    usage
    fail "expected exactly one argument (path to a .pkg file), got $#"
fi

PKG_PATH="$1"

case "${PKG_PATH}" in
    *.pkg) ;;
    *) fail "input does not have a .pkg extension: ${PKG_PATH}" ;;
esac

if [ ! -f "${PKG_PATH}" ]; then
    fail "artifact not found: ${PKG_PATH}"
fi

if [ ! -s "${PKG_PATH}" ]; then
    fail "artifact is empty (0 bytes); refusing to treat a placeholder as a real .pkg: ${PKG_PATH}"
fi

if [ "$(uname -s)" != "FreeBSD" ]; then
    fail "this script installs and runs a native FreeBSD package via real" \
        "pkg(8) tooling and must be executed on FreeBSD 14+; found" \
        "$(uname -s) instead. There is no Linux/Docker/emulation fallback --" \
        "see .github/workflows/release-artifacts.yml's FreeBSD 14/15 VM matrix or" \
        "docs/development/release.md for the manual verification procedure."
fi

FREEBSD_MAJOR="$(uname -r | awk -F. '{print $1}')"
case "${FREEBSD_MAJOR}" in
    ''|*[!0-9]*)
        fail "failed to parse FreeBSD version from uname -r: $(uname -r)"
        ;;
esac
if [ "${FREEBSD_MAJOR}" -lt 14 ]; then
    fail "FreeBSD 14+ is required for this smoke; found $(uname -r)."
fi

if ! command -v pkg >/dev/null 2>&1; then
    fail "required FreeBSD pkg tooling not found in PATH."
fi
if [ ! -x "${PYSH_FREEBSD_PYTHON_COMMAND}" ]; then
    fail "selected package interpreter is unavailable: ${PYSH_FREEBSD_PYTHON_COMMAND}"
fi

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    fail "failed to read version from pyproject.toml"
fi

PKG_NAME="pysh-shell"
APP_PREFIX="/usr/local/lib/pysh-shell"
REQUIRED_BIN="/usr/local/bin/pysh"
REQUIRED_MODULE="${APP_PREFIX}/pysh/__init__.py"

PKG_ABS_PATH="$(cd "$(dirname "${PKG_PATH}")" && pwd)/$(basename "${PKG_PATH}")"
PKG_BASENAME="$(basename "${PKG_ABS_PATH}")"

# OS ABI and Python-minor compatibility are independent package contracts.
# pkg(8) owns the OS ABI; the selected Python target is derived above by
# _freebsd_python.sh. Never force-add an archive built for another OS ABI.
HOST_ABI="$(pkg config ABI)" || fail "failed to read the native ABI from pkg config ABI."
PACKAGE_ABI="$(pkg query -F "${PKG_ABS_PATH}" "%q")" || \
    fail "failed to read package ABI from ${PKG_ABS_PATH}."
if [ "${PACKAGE_ABI}" != "${HOST_ABI}" ]; then
    fail "package ABI ${PACKAGE_ABI} does not match native host ABI ${HOST_ABI}; refusing installation"
fi
PACKAGE_ABI_SYSTEM="$(printf '%s\n' "${PACKAGE_ABI}" | awk -F: '{print $1}')"
PACKAGE_FREEBSD_MAJOR="$(printf '%s\n' "${PACKAGE_ABI}" | awk -F: '{print $2}')"
PACKAGE_ARCH="$(printf '%s\n' "${PACKAGE_ABI}" | awk -F: '{print $3}')"
if [ "${PACKAGE_ABI}" != "${PACKAGE_ABI_SYSTEM}:${PACKAGE_FREEBSD_MAJOR}:${PACKAGE_ARCH}" ] || \
    [ "${PACKAGE_ABI_SYSTEM}" != "FreeBSD" ] || \
    [ "${PACKAGE_FREEBSD_MAJOR}" != "${FREEBSD_MAJOR}" ]; then
    fail "unexpected package ABI metadata: ${PACKAGE_ABI}"
fi
case "${PACKAGE_ARCH}" in
    ''|*[!A-Za-z0-9_]*) fail "unexpected package ABI metadata: ${PACKAGE_ABI}" ;;
esac
EXPECTED_PKG_BASENAME="${PKG_NAME}-${VERSION}-freebsd${PACKAGE_FREEBSD_MAJOR}-${PACKAGE_ARCH}.pkg"
if [ "${PKG_BASENAME}" != "${EXPECTED_PKG_BASENAME}" ]; then
    fail "package filename does not match embedded ABI metadata: expected ${EXPECTED_PKG_BASENAME}, got ${PKG_BASENAME}"
fi

echo "==> ${SCRIPT_NAME}: smoke-testing ${PKG_BASENAME} (expected version ${VERSION})"
echo "==> host: real FreeBSD $(uname -r), ABI ${HOST_ABI} (native pkg(8) install, no container/emulation)"

echo "--- installing ${PKG_BASENAME} via real FreeBSD package management ---"
if ! pkg add "${PKG_ABS_PATH}" >/tmp/pysh-freebsd-install.log 2>&1; then
    cat /tmp/pysh-freebsd-install.log >&2
    fail "pkg add failed"
fi

echo "--- pkg info: confirm the package manager recorded the install ---"
PKG_INFO_LINE="$(pkg info "${PKG_NAME}")"
echo "${PKG_INFO_LINE}"
case "${PKG_INFO_LINE}" in
    *"${PKG_NAME}-${VERSION}"*) ;;
    *)
        fail "pkg info does not show version ${VERSION}: ${PKG_INFO_LINE}"
        ;;
esac

SMOKE_DIR="$(mktemp -d -t pysh-freebsd-smoke.XXXXXXXX)"
trap 'rm -rf "${SMOKE_DIR}"' EXIT
cd "${SMOKE_DIR}"

echo "--- package isolation proof: command -v pysh ---"
# Neutral working directory, cleared PYTHONPATH, no venv sourcing: this
# must resolve to the installed package, never the repository checkout
# that is also present on this VM's workspace.
unset PYTHONPATH || true
PYSH_BIN="$(command -v pysh)"
echo "${PYSH_BIN}"
if [ "${PYSH_BIN}" != "${REQUIRED_BIN}" ]; then
    fail "unexpected pysh location: ${PYSH_BIN}"
fi
if ! grep -Fq "exec ${PYSH_FREEBSD_PYTHON_COMMAND} -m pysh \"\$@\"" "${REQUIRED_BIN}"; then
    fail "installed launcher does not use selected interpreter: ${PYSH_FREEBSD_PYTHON_COMMAND}"
fi

echo "--- package isolation proof: selected Python import location ---"
# The package installs source under /usr/local/lib/pysh-shell without a
# .pth file (by design: only the /usr/local/bin/pysh wrapper sets
# PYTHONPATH internally, mirroring the Debian .deb wrapper). This
# PYTHONPATH points at the installed system prefix, never at the
# repository checkout or a virtualenv.
MODULE_FILE="$(PYTHONPATH="${APP_PREFIX}" "${PYSH_FREEBSD_PYTHON_COMMAND}" -c 'import pysh; print(pysh.__file__)')"
echo "${MODULE_FILE}"
if [ "${MODULE_FILE}" != "${REQUIRED_MODULE}" ]; then
    fail "pysh module resolved outside the installed package prefix: ${MODULE_FILE}"
fi

echo "--- pysh --version ---"
VERSION_OUT="$(pysh --version)"
echo "${VERSION_OUT}"
case "${VERSION_OUT}" in
    *"${VERSION}"*) ;;
    *) fail "pysh --version did not report ${VERSION}: ${VERSION_OUT}" ;;
esac

echo "--- selected Python -m pysh --version ---"
MODULE_VERSION_OUT="$(PYTHONPATH="${APP_PREFIX}" "${PYSH_FREEBSD_PYTHON_COMMAND}" -m pysh --version)"
echo "${MODULE_VERSION_OUT}"
case "${MODULE_VERSION_OUT}" in
    *"${VERSION}"*) ;;
    *) fail "selected Python -m pysh --version did not report ${VERSION}: ${MODULE_VERSION_OUT}" ;;
esac

echo '--- pysh -c "echo freebsd-smoke" ---'
ECHO_OUT="$(pysh -c "echo freebsd-smoke")"
echo "${ECHO_OUT}"
if [ "${ECHO_OUT}" != "freebsd-smoke" ]; then
    fail "expected exactly 'freebsd-smoke', got: ${ECHO_OUT}"
fi

echo '--- pysh -c "exit" ---'
pysh -c "exit"
echo "exit status: $?"

echo '--- pysh -c "quit" ---'
pysh -c "quit"
echo "quit status: $?"

echo "--- non-TTY batch-mode smoke ---"
echo "    (NOT a PTY test: PySH intentionally treats piped/non-TTY stdin as"
echo "    batch command input, not an interactive session; the real PTY"
echo "    check below is the interactive smoke.)"
printf 'exit\n' | pysh
echo "batch-mode exit status: $?"
printf 'quit\n' | pysh
echo "batch-mode quit status: $?"

echo "--- real interactive PTY smoke (genuine pseudo-terminal) ---"
# Shared, strictly-bounded, readiness-gated PTY driver (Issue #33): every
# read is gated by select() on a single shrinking deadline, so a stuck or
# non-exiting child cannot hang this step -- it is killed and reported as
# a deterministic FAIL instead, rather than hanging the whole VM job as
# the old bare blocking-os.read() loop did. Referenced directly from the
# repository checkout (unlike the Debian/RPM containers, this VM already
# has the full workspace synced) -- never copied or duplicated.
#
# --ready-marker-hex is PySH's bracketed-paste-enable sequence
# (ESC [ ? 2 0 0 4 h), which the raw line editor only emits *after*
# tty.setraw() (whose default TCSAFLUSH action discards already-queued
# input) has already run. The helper withholds "exit"/"quit" until it
# observes this exact byte sequence on the PTY, so the command can never
# race that raw-mode transition and be silently discarded by it -- this
# is the same readiness contract used by the Debian and RPM smokes, no
# FreeBSD-specific handling.
if ! "${PYSH_FREEBSD_PYTHON_COMMAND}" "${REPO_ROOT}/scripts/pty_smoke.py" --ready-marker-hex 1b5b3f3230303468 \
    10 exit /usr/local/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive exit failed" >&2
    exit 1
fi
if ! "${PYSH_FREEBSD_PYTHON_COMMAND}" "${REPO_ROOT}/scripts/pty_smoke.py" --ready-marker-hex 1b5b3f3230303468 \
    10 quit /usr/local/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive quit failed" >&2
    exit 1
fi
echo "PTY interactive smoke PASSED"

echo "=== ALL FREEBSD INSTALL-AND-RUN SMOKE CHECKS PASSED ==="

echo "==> ${SCRIPT_NAME}: PASSED for ${PKG_BASENAME}"
