# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/rc.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Loader for the ``~/.pyshrc`` startup file.

The rc file is a list of shell commands, one per line. Blank lines and lines
whose first non-whitespace character is ``#`` are skipped. Each remaining line
is executed through the normal shell execution path, so all features
(``alias``, ``export``, ``source``, pipelines, etc.) are available.

The loader never raises on a per-line error; failures are reported on stderr
and execution continues.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path

RC_PATH = Path("~/.pyshrc").expanduser()


def iter_rc_lines(lines: Iterable[str]) -> list[str]:
    """Return executable lines from ``lines`` (comments and blanks dropped)."""
    cleaned: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned.append(line)
    return cleaned


def read_rc_file(path: Path) -> list[str]:
    """Read and pre-filter an rc file. Missing files yield an empty list."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        print(f"pysh: cannot read {path}: {exc}", file=sys.stderr)
        return []
    return iter_rc_lines(text.splitlines())


def execute_rc(
    path: Path,
    executor: Callable[[str], int],
    *,
    quiet_missing: bool = True,
) -> int:
    """Execute commands from ``path`` via ``executor``.

    ``executor`` is a callable that runs a single shell line and returns the
    exit status. Returns the exit status of the last executed line, or 0 if
    no lines were run.
    """
    if not path.exists():
        if not quiet_missing:
            print(f"pysh: {path}: no such file", file=sys.stderr)
        return 0
    last_status = 0
    for line in read_rc_file(path):
        try:
            last_status = executor(line)
        except Exception as exc:  # noqa: BLE001 - rc lines must not crash the shell
            print(f"pysh: {path}: {exc}", file=sys.stderr)
            last_status = 1
    return last_status


def load_default_rc(executor: Callable[[str], int]) -> int:
    """Load the user's default rc file (``~/.pyshrc``) if present."""
    return execute_rc(RC_PATH, executor, quiet_missing=True)
