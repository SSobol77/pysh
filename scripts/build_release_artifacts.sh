#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run the full local release pipeline:
#   1. pytest -q
#   2. ruff check src tests
#   3. scripts/build_pysh_package.sh   (PyPI artifacts)
#   4. scripts/build_deb.sh            (Debian .deb)
#   5. scripts/build_rpm.sh            (RPM .rpm)
#   6. scripts/check_release_artifacts.sh   (canonical naming + sha256)
#
# Does not publish anything. Does not call sudo. Local-only.
# Each step fails fast; if rpmbuild is missing, build_rpm.sh exits with
# a deterministic message and this orchestrator stops.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> [1/6] pytest -q"
"${PYTHON_BIN}" -m pytest -q

echo "==> [2/6] ruff check src tests"
"${PYTHON_BIN}" -m ruff check src tests

echo "==> [3/6] PyPI artifacts"
bash "${REPO_ROOT}/scripts/build_pysh_package.sh"

echo "==> [4/6] Debian .deb"
bash "${REPO_ROOT}/scripts/build_deb.sh"

echo "==> [5/6] RPM .rpm"
bash "${REPO_ROOT}/scripts/build_rpm.sh"

echo "==> [6/6] check release artifacts + SHA256SUMS"
bash "${REPO_ROOT}/scripts/check_release_artifacts.sh"

echo "==> Done. All release artifacts are under dist/ and dist/os/."
