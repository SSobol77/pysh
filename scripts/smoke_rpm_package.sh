#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/smoke_rpm_package.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

SCRIPT_NAME="smoke_rpm_package.sh"
RPM_IMAGE="fedora:43"

# --- real RPM package install-and-run smoke (Issue #33 RPM follow-up) ----
#
# This installs the supplied .rpm through REAL RPM package management
# (`dnf install -y ./<pkg>.rpm`) inside a disposable "${RPM_IMAGE}"
# container, then exercises the INSTALLED console entrypoint. It never
# extracts the archive with `rpm2cpio`/`cpio` as a substitute for
# installation, and it never replaces the package under test with a
# PyPI/dnf-repository copy: PySH comes exclusively from the local .rpm
# mounted read-only into the container. The only network access this
# script performs is `dnf install python3` (before installing the local
# .rpm), needed because the package's own `Requires: python3 >= 3.13`
# must be satisfied from the base image's standard repositories, matching
# the way scripts/smoke_debian_package.sh bootstraps python3 via apt-get.
#
# This is complementary to, not a replacement for, the existing
# `rpm -qip`/`rpm -qlp` static content-listing checks in
# scripts/build_rpm.sh and scripts/check_release_quality.sh, which stay
# in place unchanged.

fail() {
    printf '%s: %s\n' "${SCRIPT_NAME}" "$*" >&2
    exit 1
}

usage() {
    cat <<USAGE >&2
usage: ${SCRIPT_NAME} <path-to-pysh-shell.rpm>

Installs the given RPM package into a disposable, network-isolated-
except-for-dnf ${RPM_IMAGE} container via real "dnf install ./<pkg>.rpm"
package management, then verifies the installed console entrypoint
(pysh --version, python3 -m pysh --version, pysh -c, and a real PTY-driven
interactive exit/quit). Requires Docker.
USAGE
}

if [ "$#" -ne 1 ]; then
    usage
    fail "expected exactly one argument (path to a .rpm file), got $#"
fi

RPM_PATH="$1"

case "${RPM_PATH}" in
    *.rpm) ;;
    *) fail "input does not have a .rpm extension: ${RPM_PATH}" ;;
esac

if [ ! -f "${RPM_PATH}" ]; then
    fail "artifact not found: ${RPM_PATH}"
fi

if [ ! -s "${RPM_PATH}" ]; then
    fail "artifact is empty (0 bytes); refusing to treat a placeholder as a real .rpm: ${RPM_PATH}"
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "docker is required to run an isolated ${RPM_IMAGE} install smoke, but was" \
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

RPM_ABS_PATH="$(cd "$(dirname "${RPM_PATH}")" && pwd)/$(basename "${RPM_PATH}")"
RPM_BASENAME="$(basename "${RPM_ABS_PATH}")"

echo "==> ${SCRIPT_NAME}: smoke-testing ${RPM_BASENAME} (expected version ${VERSION})"
echo "==> image: ${RPM_IMAGE} (disposable, --rm, unprivileged, artifact-only read-only mount)"

docker run --rm -i \
    -e "PYSH_RPM_PATH=/pkg/${RPM_BASENAME}" \
    -e "PYSH_EXPECTED_VERSION=${VERSION}" \
    -v "${RPM_ABS_PATH}:/pkg/${RPM_BASENAME}:ro" \
    -v "${REPO_ROOT}/scripts/pty_smoke.py:/pysh-pty-smoke.py:ro" \
    "${RPM_IMAGE}" \
    bash -s <<'CONTAINER_EOF'
set -eu

echo "--- container OS release (must be Fedora, real dnf) ---"
head -5 /etc/os-release
if ! grep -q '^ID=fedora$' /etc/os-release; then
    echo "SMOKE FAIL: container is not Fedora (ID != fedora)" >&2
    exit 1
fi

echo "--- dnf install python3 (base-image bootstrap only: this fetches" \
     "Fedora's own python3 dependency from the standard repositories;" \
     "PySH itself is installed exclusively from the locally mounted .rpm" \
     "below, never from dnf or PyPI) ---"
dnf -y install python3 >/tmp/pysh-python3-install.log 2>&1 || {
    cat /tmp/pysh-python3-install.log >&2
    echo "SMOKE FAIL: dnf install python3 failed" >&2
    exit 1
}
PYTHON3_VERSION="$(python3 --version)"
echo "${PYTHON3_VERSION}"
case "${PYTHON3_VERSION}" in
    "Python 3.13."*|"Python 3.1"[4-9]*|"Python 3.2"*) ;;
    *)
        echo "SMOKE FAIL: base image python3 does not satisfy Requires: python3 >= 3.13: ${PYTHON3_VERSION}" >&2
        exit 1
        ;;
esac

echo "--- installing ${PYSH_RPM_PATH} via real RPM package management ---"
if ! dnf -y install "${PYSH_RPM_PATH}" >/tmp/pysh-install.log 2>&1; then
    cat /tmp/pysh-install.log >&2
    echo "SMOKE FAIL: dnf install failed" >&2
    exit 1
fi

echo "--- rpm -q: confirm the package manager recorded the install ---"
# Explicit queryformat avoids depending on rpm's default NVRA display
# format (which appends ".noarch"); this checks name-version-release
# exactly, independent of architecture tagging.
RPM_NVR="$(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}\n' pysh-shell)"
echo "${RPM_NVR}"
if [ "${RPM_NVR}" != "pysh-shell-${PYSH_EXPECTED_VERSION}-1" ]; then
    echo "SMOKE FAIL: rpm -q does not show pysh-shell-${PYSH_EXPECTED_VERSION}-1: ${RPM_NVR}" >&2
    exit 1
fi

mkdir -p /tmp/pysh-smoke
cd /tmp/pysh-smoke

echo "--- package isolation proof: command -v pysh ---"
# Fedora merges /usr/sbin into /usr/bin via a symlink (/usr/sbin -> bin),
# and root's PATH lists /usr/sbin before /usr/bin, so `command -v` may
# report the file through its /usr/sbin alias even though the RPM installs
# it at /usr/bin/pysh. Resolving the real path makes this check robust to
# that PATH-ordering quirk while still proving package isolation (i.e.
# not a repo checkout or a virtualenv).
PYSH_BIN="$(command -v pysh)"
PYSH_BIN_REAL="$(readlink -f "${PYSH_BIN}")"
echo "${PYSH_BIN} -> ${PYSH_BIN_REAL}"
if [ "${PYSH_BIN_REAL}" != "/usr/bin/pysh" ]; then
    echo "SMOKE FAIL: unexpected pysh location: ${PYSH_BIN} -> ${PYSH_BIN_REAL}" >&2
    exit 1
fi

echo "--- package isolation proof: python3 import location ---"
# The package installs source under /opt/pysh-shell/lib without a .pth
# file (by design: only the /usr/bin/pysh wrapper sets PYTHONPATH, the
# exact same packaging/wrappers/pysh.sh used by the Debian .deb). This
# PYTHONPATH points at the installed system prefix, never at a repository
# checkout or a virtualenv.
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

echo '--- pysh -c "echo rpm-smoke" ---'
ECHO_OUT="$(pysh -c "echo rpm-smoke")"
echo "${ECHO_OUT}"
if [ "${ECHO_OUT}" != "rpm-smoke" ]; then
    echo "SMOKE FAIL: expected exactly 'rpm-smoke', got: ${ECHO_OUT}" >&2
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
# Shared, strictly-bounded, readiness-gated PTY driver (Issue #33): every
# read is gated by select() on a single shrinking deadline, so a stuck or
# non-exiting child cannot hang this step -- it is killed and reported as
# a deterministic FAIL instead. Mounted read-only as a standalone harness
# file, not part of the PySH package under test.
#
# --ready-marker-hex is PySH's bracketed-paste-enable sequence
# (ESC [ ? 2 0 0 4 h), which the raw line editor only emits *after*
# tty.setraw() (whose default TCSAFLUSH action discards already-queued
# input) has already run. The helper withholds "exit"/"quit" until it
# observes this exact byte sequence on the PTY, so the command can never
# race that raw-mode transition and be silently discarded by it.
if ! python3 /pysh-pty-smoke.py --ready-marker-hex 1b5b3f3230303468 10 exit /usr/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive exit failed" >&2
    exit 1
fi
if ! python3 /pysh-pty-smoke.py --ready-marker-hex 1b5b3f3230303468 10 quit /usr/bin/pysh; then
    echo "SMOKE FAIL: PTY interactive quit failed" >&2
    exit 1
fi
echo "PTY interactive smoke PASSED"

echo "=== ALL RPM INSTALL-AND-RUN SMOKE CHECKS PASSED ==="
CONTAINER_EOF

echo "==> ${SCRIPT_NAME}: PASSED for ${RPM_BASENAME}"
