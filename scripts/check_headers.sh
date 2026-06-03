#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

set -u

PROJECT='Project: PySH - Python-first interactive shell for Debian and Unix-like systems'
REPOSITORY='Repository: https://github.com/SSobol77/pysh'
PYPI='PyPI: https://pypi.org/project/pysh-shell'
SPDX='SPDX-License-Identifier: GPL-2.0-only'
COPYRIGHT='Copyright (C) 2026 Siergej Sobolewski'

status=0

emit_missing() {
    path=$1
    field=$2
    printf 'header: %s: missing %s\n' "$path" "$field"
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
    has_line "$path" "$COPYRIGHT" || emit_missing "$path" Copyright
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
