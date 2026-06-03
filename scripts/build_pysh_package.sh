#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

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
