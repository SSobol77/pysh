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

SCRIPT_NAME="smoke_freebsd_package.sh"

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
usage: ${SCRIPT_NAME} <path-to-pysh-shell.pkg>

Installs the given FreeBSD package via real "pkg add <local-file>" package
management directly on the FreeBSD host this script runs on, then verifies
the installed console entrypoint (pysh --version, python3.13 -m pysh
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
        "see .github/workflows/release-artifacts.yml's FreeBSD 14.3 VM job or" \
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

echo "==> ${SCRIPT_NAME}: smoke-testing ${PKG_BASENAME} (expected version ${VERSION})"
echo "==> host: real FreeBSD $(uname -r) (native pkg(8) install, no container/emulation)"

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

echo "--- package isolation proof: python3.13 import location ---"
# The package installs source under /usr/local/lib/pysh-shell without a
# .pth file (by design: only the /usr/local/bin/pysh wrapper sets
# PYTHONPATH internally, mirroring the Debian .deb wrapper). This
# PYTHONPATH points at the installed system prefix, never at the
# repository checkout or a virtualenv.
MODULE_FILE="$(PYTHONPATH="${APP_PREFIX}" python3.13 -c 'import pysh; print(pysh.__file__)')"
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

echo "--- python3.13 -m pysh --version ---"
MODULE_VERSION_OUT="$(PYTHONPATH="${APP_PREFIX}" python3.13 -m pysh --version)"
echo "${MODULE_VERSION_OUT}"
case "${MODULE_VERSION_OUT}" in
    *"${VERSION}"*) ;;
    *) fail "python3.13 -m pysh --version did not report ${VERSION}: ${MODULE_VERSION_OUT}" ;;
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
python3.13 - <<'PYEOF'
import os
import pty
import subprocess
import sys
import time


def run_pty_command(argv, input_line, timeout=10.0):
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        argv, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True
    )
    os.close(slave_fd)
    os.write(master_fd, (input_line + "\n").encode())
    output = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if proc.poll() is not None:
            break
    os.close(master_fd)
    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = -1
    return rc, output.decode(errors="replace")


failed = False
for cmd in ("exit", "quit"):
    rc, out = run_pty_command(["/usr/local/bin/pysh"], cmd)
    print(f"PTY interactive {cmd!r}: rc={rc}")
    if rc != 0:
        print(
            f"SMOKE FAIL: PTY interactive {cmd!r} exited {rc}, output={out!r}",
            file=sys.stderr,
        )
        failed = True
    if "Traceback" in out:
        print(
            f"SMOKE FAIL: PTY interactive {cmd!r} produced a traceback: {out!r}",
            file=sys.stderr,
        )
        failed = True
if failed:
    sys.exit(1)
print("PTY interactive smoke PASSED")
PYEOF

echo "=== ALL FREEBSD INSTALL-AND-RUN SMOKE CHECKS PASSED ==="

echo "==> ${SCRIPT_NAME}: PASSED for ${PKG_BASENAME}"
