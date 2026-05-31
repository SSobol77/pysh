#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the PyPI artifacts for pysh-shell (sdist + wheel).
#
# Output:
#   dist/pysh_shell-X.Y.Z.tar.gz
#   dist/pysh_shell-X.Y.Z-py3-none-any.whl
#
# Does not publish anything. Does not call sudo. Local-only.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> Cleaning old Python build artifacts"
rm -rf dist build ./*.egg-info

echo "==> Building sdist and wheel"
"${PYTHON_BIN}" -m build

echo "==> Validating package metadata with twine"
"${PYTHON_BIN}" -m twine check dist/*

echo "==> PyPI artifacts ready under dist/"
ls -1 dist/
