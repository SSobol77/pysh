#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/_freebsd_python.sh
#
# Copyright (C) 2026 Siergej Sobolewski

# Derive the FreeBSD package's explicit Python target from one input.
# Callers use `${PYSH_FREEBSD_PYTHON_VERSION-3.13}` semantics deliberately:
# an unset override selects the release-reference default, while an explicitly
# empty override is invalid and must not silently fall back.
pysh_freebsd_python_config() {
    pysh_python_component=$1
    pysh_python_version=${PYSH_FREEBSD_PYTHON_VERSION-3.13}

    case "${pysh_python_version}" in
        *.*.*|*[!0-9.]*|'')
            printf '%s: PYSH_FREEBSD_PYTHON_VERSION must be major.minor and >= 3.13; got %s\n' \
                "${pysh_python_component}" "'${pysh_python_version}'" >&2
            return 2
            ;;
        *.*)
            ;;
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
