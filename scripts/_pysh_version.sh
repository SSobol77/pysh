#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/_pysh_version.sh
#
# Copyright (C) 2026 Siergej Sobolewski

pysh_read_version() {
    pyproject="$1"
    awk -F'"' '
        /^[[:space:]]*version[[:space:]]*=[[:space:]]*"/ {
            print $2
            exit
        }
    ' "${pyproject}"
}
