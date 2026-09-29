#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/_freebsd_python.sh
#
# Copyright (C) 2026 Siergej Sobolewski

# Derive the FreeBSD package's explicit Python target from one input.
# An unset override selects the v0.9.1 reference default. An explicitly empty
# override is invalid and must not silently fall back.
pysh_freebsd_python_config() {
    pysh_python_component=$1
    pysh_python_version=${PYSH_FREEBSD_PYTHON_VERSION-3.13}

    case "${pysh_python_version}" in
        *.*.*|*[!0-9.]*|''|.*|*.)
            printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be major.minor and >= 3.13; got %s\n' \
                "${pysh_python_component}" "'${pysh_python_version}'" >&2
            return 2
            ;;
        *.*) ;;
        *)
            printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be major.minor and >= 3.13; got %s\n' \
                "${pysh_python_component}" "'${pysh_python_version}'" >&2
            return 2
            ;;
    esac

    pysh_python_major=${pysh_python_version%%.*}
    pysh_python_minor=${pysh_python_version#*.}
    case "${pysh_python_major}" in
        0|[1-9]|[1-9][0-9]) ;;
        *)
            printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be major.minor and >= 3.13; got %s\n' \
                "${pysh_python_component}" "'${pysh_python_version}'" >&2
            return 2
            ;;
    esac
    case "${pysh_python_minor}" in
        0|[1-9]|[1-9][0-9]) ;;
        *)
            printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be major.minor and >= 3.13; got %s\n' \
                "${pysh_python_component}" "'${pysh_python_version}'" >&2
            return 2
            ;;
    esac

    if [ "${pysh_python_major}" -lt 3 ] || \
        { [ "${pysh_python_major}" -eq 3 ] && [ "${pysh_python_minor}" -lt 13 ]; }; then
        printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be >= 3.13; got %s\n' \
            "${pysh_python_component}" "'${pysh_python_version}'" >&2
        return 2
    fi

    PYSH_FREEBSD_PYTHON_VERSION=${pysh_python_version}
    PYSH_FREEBSD_PYTHON_COMMAND="/usr/local/bin/python${pysh_python_version}"
    PYSH_FREEBSD_PYTHON_PACKAGE="python${pysh_python_major}${pysh_python_minor}"
    PYSH_FREEBSD_PYTHON_ORIGIN="lang/${PYSH_FREEBSD_PYTHON_PACKAGE}"
}

pysh_freebsd_python_validate() {
    pysh_python_component=$1
    if [ ! -x "${PYSH_FREEBSD_PYTHON_COMMAND}" ]; then
        printf '%s: selected package interpreter is unavailable: %s\n' \
            "${pysh_python_component}" "${PYSH_FREEBSD_PYTHON_COMMAND}" >&2
        return 2
    fi
    if ! "${PYSH_FREEBSD_PYTHON_COMMAND}" -c '
import sys

selected = tuple(int(part) for part in sys.argv[1].split("."))
valid = (
    sys.implementation.name == "cpython"
    and sys.version_info >= (3, 13)
    and sys.version_info[:2] == selected
)
raise SystemExit(0 if valid else 1)
' "${PYSH_FREEBSD_PYTHON_VERSION}"; then
        printf '%s: %s is not the selected compatible CPython %s interpreter\n' \
            "${pysh_python_component}" "${PYSH_FREEBSD_PYTHON_COMMAND}" \
            "${PYSH_FREEBSD_PYTHON_VERSION}" >&2
        return 2
    fi
}
