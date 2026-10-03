#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_fuzz_evidence.sh
#
# Copyright (C) 2026 Siergej Sobolewski
#
# Run the Issue #49 portable fuzz/property evidence on the current platform and
# print an identifying banner so Debian and FreeBSD runs are comparable.
#
# Portable /bin/sh; deterministic and finite. Needs no network, root, /proc,
# /dev/fd, Atheris, or user startup configuration (the fuzz targets run
# hermetically with a cleared environment and an empty temporary cwd).
#
# This script owns the portable evidence list. Coverage-guided Atheris fuzzing
# is Linux x86_64 only and is deliberately NOT part of it: see
# .github/workflows/fuzz-nightly.yml and docs/development/fuzzing.md.
set -eu

echo "PySH fuzz/property evidence (portable)"
echo "uname=$(uname -srm)"
echo "python=$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo unknown)"
echo "uid=$(id -u) user=$(id -un)"

PYTEST="${PYSH_PYTEST:-python3 -m pytest}"

# shellcheck disable=SC2086
if $PYTEST -q \
    tests/test_parser_properties.py \
    tests/test_fuzz_corpus.py \
    tests/test_fuzz_driver.py \
    tests/test_fuzz_regressions.py \
    tests/test_fd_robustness.py \
    tests/test_fuzz_contract.py
then
    echo "PASS: portable fuzz/property evidence"
else
    status=$?
    echo "FAIL: portable fuzz/property evidence (pytest exit ${status})" >&2
    exit "${status}"
fi
