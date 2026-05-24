#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# /usr/bin/pysh wrapper used by the pysh-shell .deb and .rpm packages.
# It runs PySH from the system's python3 against the bundled package
# tree under /opt/pysh-shell/lib.
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
