# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/plugins.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Plugin loader for ``~/.pyshrc.d/*.pysh`` startup snippets.

Each file in ``~/.pyshrc.d/`` whose name ends with ``.pysh`` is executed
through the same rc mini-interpreter as ``~/.pyshrc``. Files are loaded in
deterministic lexicographic order; non-files and files with the wrong
extension are skipped.

Failures in one plugin do not affect later plugins: the error is reported
on stderr (or via the supplied reporter) and loading continues.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from pysh.rc import execute_rc

PLUGIN_DIR = Path("~/.pyshrc.d").expanduser()
PLUGIN_SUFFIX = ".pysh"


def discover_plugins(directory: Path) -> list[Path]:
    """Return plugin files in ``directory`` sorted lexicographically.

    Only regular files ending in ``.pysh`` are returned. A missing directory
    yields an empty list.
    """
    if not directory.exists() or not directory.is_dir():
        return []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    plugins = [p for p in entries if p.is_file() and p.name.endswith(PLUGIN_SUFFIX)]
    plugins.sort(key=lambda p: p.name)
    return plugins


def load_plugins(
    executor: Callable[[str], int],
    *,
    directory: Path = PLUGIN_DIR,
    reporter: Callable[[str], None] | None = None,
) -> list[Path]:
    """Execute every plugin file in ``directory`` through ``executor``.

    Returns the list of plugin paths that were attempted. The order matches
    the deterministic lexicographic order of plugin filenames.
    """
    report = reporter if reporter is not None else (lambda msg: print(msg, file=sys.stderr))
    attempted: list[Path] = []
    for plugin in discover_plugins(directory):
        attempted.append(plugin)
        try:
            execute_rc(plugin, executor, quiet_missing=True)
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not abort the loop
            report(f"pysh: plugin {plugin}: {exc}")
            continue
    return attempted
