#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: scripts/check_headers.sh
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
#
set -u

PROJECT='Project: PySH - Python-first interactive shell for Debian and Unix-like systems'
REPOSITORY='Repository: https://github.com/SSobol77/pysh'
PYPI='PyPI: https://pypi.org/project/pysh-shell'
SPDX='SPDX-License-Identifier: GPL-3.0-or-later'
COPYRIGHT='Copyright (c) 2026 Siergej Sobolewski'
LICENSE='Licensed under the GNU General Public License v3.0 or later.'
LICENSE_REF='See the LICENSE file in the project root for full license text.'

status=0

emit_missing() {
    path=$1
    field=$2
    printf 'header: %s: missing %s\n' "$path" "$field"
    status=1
}

emit_wrong_file() {
    path=$1
    printf 'header: %s: wrong File field\n' "$path"
    status=1
}

has_line() {
    path=$1
    text=$2
    grep -Fxq "$text" "$path" || grep -Fxq "# $text" "$path"
}

check_file() {
    path=$1

    has_line "$path" "$SPDX" || emit_missing "$path" SPDX
    has_line "$path" "$PROJECT" || emit_missing "$path" Project
    has_line "$path" "$REPOSITORY" || emit_missing "$path" Repository
    has_line "$path" "$PYPI" || emit_missing "$path" PyPI
    has_line "$path" "$COPYRIGHT" || emit_missing "$path" Copyright
    has_line "$path" "$LICENSE" || emit_missing "$path" License
    has_line "$path" "$LICENSE_REF" || emit_missing "$path" LICENSE-reference

    if grep -Eq '^(# )?File: ' "$path"; then
        grep -Fxq "File: $path" "$path" || grep -Fxq "# File: $path" "$path" || {
            emit_wrong_file "$path"
        }
    else
        emit_missing "$path" File
    fi
}

list_files() {
    git ls-files | grep -E '^(src|tests|docs)/.*\.(py|md|sh|toml|yaml|yml)$|^scripts/.*\.sh$|^[^/]+\.md$'
}

while IFS= read -r path; do
    case "$path" in
        .git/*|.venv/*|.ruff_cache/*|.pytest_cache/*|dist/*|build/*|*/__pycache__/*|*.pyc|uv.lock)
            continue
            ;;
    esac
    if [ ! -f "$path" ]; then
        continue
    fi
    check_file "$path"
done < <(list_files | sort -u)

exit "$status"
