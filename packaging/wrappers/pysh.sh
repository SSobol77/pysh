#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: packaging/wrappers/pysh.sh
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

pysh_python_compatible() {
    [ -x "$1" ] && "$1" -c '
import sys
raise SystemExit(
    0
    if sys.implementation.name == "cpython" and sys.version_info >= (3, 13)
    else 1
)
' >/dev/null 2>&1
}

# Prefer the distribution's generic command when it satisfies the runtime
# contract. If it is older, search versioned commands on PATH. Executable
# names are only candidates: every interpreter is validated by running it.
PYSH_PYTHON=""
if command -v python3 >/dev/null 2>&1; then
    PYSH_PYTHON_CANDIDATE="$(command -v python3)"
    if pysh_python_compatible "${PYSH_PYTHON_CANDIDATE}"; then
        PYSH_PYTHON="${PYSH_PYTHON_CANDIDATE}"
    fi
fi

if [ -z "${PYSH_PYTHON}" ]; then
    pysh_old_ifs=${IFS}
    IFS=:
    for pysh_path_dir in ${PATH:-/usr/local/bin:/usr/bin:/bin}; do
        [ -n "${pysh_path_dir}" ] || pysh_path_dir=.
        for PYSH_PYTHON_CANDIDATE in "${pysh_path_dir}"/python3.*; do
            [ -e "${PYSH_PYTHON_CANDIDATE}" ] || continue
            pysh_candidate_name=${PYSH_PYTHON_CANDIDATE##*/}
            pysh_candidate_suffix=${pysh_candidate_name#python3.}
            case "${pysh_candidate_suffix}" in
                ''|*[!0-9]*) continue ;;
            esac
            if pysh_python_compatible "${PYSH_PYTHON_CANDIDATE}"; then
                PYSH_PYTHON="${PYSH_PYTHON_CANDIDATE}"
                break 2
            fi
        done
    done
    IFS=${pysh_old_ifs}
fi

if [ -z "${PYSH_PYTHON}" ]; then
    echo "pysh: launcher: PySH requires CPython >= 3.13" >&2
    exit 1
fi

exec "${PYSH_PYTHON}" -m pysh "$@"
