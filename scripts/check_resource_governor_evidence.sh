#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_resource_governor_evidence.sh
#
# Copyright (C) 2026 Siergej Sobolewski
#
# Run the Issue #53 resource-governor evidence suite on the current platform
# and print an identifying banner so Debian and FreeBSD runs are comparable.
# Portable /bin/sh; needs no root, /proc, cgroups, or systemd.
set -eu

echo "PySH resource-governor evidence"
echo "uname=$(uname -srm)"
echo "python=$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo unknown)"
echo "uid=$(id -u) user=$(id -un)"

# Platforms whose privilege can relax rlimits must run this suite unprivileged:
# the launcher fails closed for a privileged account by design.
if [ "${PYSH_EVIDENCE_REQUIRE_UNPRIVILEGED:-0}" = "1" ] && [ "$(id -u)" = "0" ]; then
    echo "error: resource governor evidence must not run as uid 0" >&2
    exit 1
fi

PYTEST="${PYSH_PYTEST:-python3 -m pytest}"
# shellcheck disable=SC2086
$PYTEST -q \
    tests/test_resource_governor.py \
    tests/test_resource_enforcement.py \
    tests/test_resource_supervisor.py \
    tests/test_resource_abuse.py \
    tests/test_resource_governor_contract.py \
    tests/test_isolated_plugin_runtime.py \
    tests/test_isolated_plugin_diagnostics.py
