#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -eu

PYSH_APP_PREFIX="${PYSH_APP_PREFIX:-/opt/pysh-shell}"
PYSH_PYTHONPATH="${PYSH_APP_PREFIX}/lib"

if [ -n "${PYTHONPATH:-}" ]; then
    PYTHONPATH="${PYSH_PYTHONPATH}:${PYTHONPATH}"
else
    PYTHONPATH="${PYSH_PYTHONPATH}"
fi
export PYTHONPATH

exec /usr/bin/python3 -m pysh "$@"
