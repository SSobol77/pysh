#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: scripts/_pysh_version.sh
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
#
# Helper sourced by other build scripts. Defines pysh_read_version,
# which prints the canonical X.Y.Z version derived from pyproject.toml.

# shellcheck shell=bash

pysh_read_version() {
    local pyproject="$1"
    awk -F'"' '
        /^[[:space:]]*version[[:space:]]*=[[:space:]]*"/ {
            print $2
            exit
        }
    ' "${pyproject}"
}
