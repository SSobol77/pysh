#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
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
