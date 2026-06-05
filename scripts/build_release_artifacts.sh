#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

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

echo "==> Done. Local artifacts are under dist/ and dist/os/."
echo "==> Flat GitHub Release assets are under dist/release-assets/."
