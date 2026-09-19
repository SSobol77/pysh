#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/smoke_debian_package.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

SCRIPT_NAME="smoke_debian_package.sh"
DEBIAN_IMAGE="debian:13-slim"

# --- real Debian package install-and-run smoke (Issue #33 RQG-D) ---------
#
# This installs the supplied .deb through REAL Debian package management
# (`apt-get install ./<pkg>.deb`) inside a disposable `debian:13-slim`
# container, then exercises the INSTALLED console entrypoint. It never
# extracts the archive with `dpkg-deb --extract`/`ar`/`tar` as a substitute
# for installation, and it never replaces the package under test with a
# PyPI/apt-repository copy: PySH comes exclusively from the local .deb
# mounted read-only into the container. The only network access this
# script performs is `apt-get update`, needed to satisfy the package's own
# `python3 (>= 3.13)` dependency from Debian's standard archive on the
# `-slim` base image, which does not ship python3 by default.
#
# This is complementary to, not a replacement for, the existing
# `dpkg-deb --contents` static content-listing check in
# scripts/check_release_quality.sh, which stays in place unchanged.

fail() {
    printf '%s: %s\n' "${SCRIPT_NAME}" "$*" >&2
    exit 1
}

usage() {
    cat <<USAGE >&2
usage: ${SCRIPT_NAME} <path-to-pysh-shell.deb>

Installs the given Debian package into a disposable, network-isolated-
except-for-apt ${DEBIAN_IMAGE} container via real
"apt-get install ./<pkg>.deb" package management, then verifies the
installed console entrypoint (pysh --version, python3 -m pysh --version,
pysh -c, and a real PTY-driven interactive exit/quit). Requires Docker.
USAGE
}

if [ "$#" -ne 1 ]; then
    usage
    fail "expected exactly one argument (path to a .deb file), got $#"
fi

DEB_PATH="$1"

case "${DEB_PATH}" in
    *.deb) ;;
    *) fail "input does not have a .deb extension: ${DEB_PATH}" ;;
esac

if [ ! -f "${DEB_PATH}" ]; then
    fail "artifact not found: ${DEB_PATH}"
fi

if [ ! -s "${DEB_PATH}" ]; then
    fail "artifact is empty (0 bytes); refusing to treat a placeholder as a real .deb: ${DEB_PATH}"
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "docker is required to run an isolated Debian 13 install smoke, but was" \
        "not found in PATH. This check intentionally does not fall back to" \
        "installing the package on the host system -- install Docker and retry." \
        "See docs/development/release.md for the manual verification procedure."
fi

if ! docker info >/dev/null 2>&1; then
    fail "docker was found on PATH but the daemon is not reachable" \
        "(\`docker info\` failed). Start the Docker daemon and retry."
fi

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    fail "failed to read version from pyproject.toml"
fi

DEB_ABS_PATH="$(cd "$(dirname "${DEB_PATH}")" && pwd)/$(basename "${DEB_PATH}")"
DEB_BASENAME="$(basename "${DEB_ABS_PATH}")"

echo "==> ${SCRIPT_NAME}: smoke-testing ${DEB_BASENAME} (expected version ${VERSION})"
echo "==> image: ${DEBIAN_IMAGE} (disposable, --rm, unprivileged, artifact-only read-only mount)"

docker run --rm -i \
    -e "PYSH_DEB_PATH=/pkg/${DEB_BASENAME}" \
    -e "PYSH_EXPECTED_VERSION=${VERSION}" \
    -v "${DEB_ABS_PATH}:/pkg/${DEB_BASENAME}:ro" \
    -v "${REPO_ROOT}/scripts/pty_smoke.py:/pysh-pty-smoke.py:ro" \
    "${DEBIAN_IMAGE}" \
    bash -s <<'CONTAINER_EOF'
set -eu

echo "--- container OS release (must be Debian 13, not Ubuntu) ---"
head -3 /etc/os-release
if ! grep -q '^VERSION_ID="13"$' /etc/os-release; then
    echo "SMOKE FAIL: container is not Debian 13" >&2
    exit 1
fi
if ! grep -q '^ID=debian$' /etc/os-release; then
    echo "SMOKE FAIL: container is not Debian (ID != debian)" >&2
    exit 1
fi

echo "--- apt-get update (base-image bootstrap only: this fetches Debian's" \
     "own python3 dependency from the standard archive; PySH itself is" \
     "installed exclusively from the locally mounted .deb below, never" \
     "from apt or PyPI) ---"
apt-get update -qq

echo "--- installing ${PYSH_DEB_PATH} via real Debian package management ---"
if ! apt-get install -y --no-install-recommends "${PYSH_DEB_PATH}" >/tmp/pysh-install.log 2>&1; then
    cat /tmp/pysh-install.log >&2
    echo "SMOKE FAIL: apt-get install failed" >&2
    exit 1
fi

echo "--- dpkg-query: confirm the package manager recorded the install ---"
DPKG_LINE="$(dpkg-query -W pysh-shell)"
echo "${DPKG_LINE}"
case "${DPKG_LINE}" in
    pysh-shell*"${PYSH_EXPECTED_VERSION}"*) ;;
    *)
        echo "SMOKE FAIL: dpkg-query does not show version ${PYSH_EXPECTED_VERSION}: ${DPKG_LINE}" >&2
        exit 1
        ;;
esac

mkdir -p /tmp/pysh-smoke
cd /tmp/pysh-smoke

echo "--- package isolation proof: command -v pysh ---"
PYSH_BIN="$(command -v pysh)"
echo "${PYSH_BIN}"
if [ "${PYSH_BIN}" != "/usr/bin/pysh" ]; then
    echo "SMOKE FAIL: unexpected pysh location: ${PYSH_BIN}" >&2
    exit 1
fi

echo "--- package isolation proof: python3 import location ---"
# The package installs source under /opt/pysh-shell/lib without a .pth
# file (by design: only the /usr/bin/pysh wrapper sets PYTHONPATH). This
# PYTHONPATH points at the installed system prefix, never at a repository
# checkout or a virtualenv -- it is the same value the installed wrapper
# itself sets internally (see packaging/wrappers/pysh.sh).
MODULE_FILE="$(PYTHONPATH=/opt/pysh-shell/lib python3 -c 'import pysh; print(pysh.__file__)')"
echo "${MODULE_FILE}"
if [ "${MODULE_FILE}" != "/opt/pysh-shell/lib/pysh/__init__.py" ]; then
    echo "SMOKE FAIL: pysh module resolved outside the installed package prefix: ${MODULE_FILE}" >&2
    exit 1
fi

echo "--- pysh --version ---"
VERSION_OUT="$(pysh --version)"
echo "${VERSION_OUT}"
case "${VERSION_OUT}" in
    *"${PYSH_EXPECTED_VERSION}"*) ;;
    *)
        echo "SMOKE FAIL: pysh --version did not report ${PYSH_EXPECTED_VERSION}: ${VERSION_OUT}" >&2
        exit 1
        ;;
esac

echo "--- python3 -m pysh --version ---"
MODULE_VERSION_OUT="$(PYTHONPATH=/opt/pysh-shell/lib python3 -m pysh --version)"
echo "${MODULE_VERSION_OUT}"
case "${MODULE_VERSION_OUT}" in
    *"${PYSH_EXPECTED_VERSION}"*) ;;
    *)
        echo "SMOKE FAIL: python3 -m pysh --version did not report ${PYSH_EXPECTED_VERSION}: ${MODULE_VERSION_OUT}" >&2
        exit 1
        ;;
esac

echo '--- pysh -c "echo deb-smoke" ---'
ECHO_OUT="$(pysh -c "echo deb-smoke")"
echo "${ECHO_OUT}"
if [ "${ECHO_OUT}" != "deb-smoke" ]; then
    echo "SMOKE FAIL: expected exactly 'deb-smoke', got: ${ECHO_OUT}" >&2
    exit 1
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
# Shared, strictly-bounded PTY driver (Issue #33): every read is gated by
# select() on a shrinking deadline, so a stuck/non-exiting child cannot
# hang this step -- it is killed and reported as a deterministic FAIL
# instead. Mounted read-only as a standalone harness file, not part of
# the PySH package under test.
if ! python3 /pysh-pty-smoke.py 10 exit /usr/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive exit failed" >&2
    exit 1
fi
if ! python3 /pysh-pty-smoke.py 10 quit /usr/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive quit failed" >&2
    exit 1
fi
echo "PTY interactive smoke PASSED"

echo "=== ALL DEBIAN INSTALL-AND-RUN SMOKE CHECKS PASSED ==="
CONTAINER_EOF

echo "==> ${SCRIPT_NAME}: PASSED for ${DEB_BASENAME}"
