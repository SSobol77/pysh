# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/cli.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Command-line entry point for the ``pysh`` console script."""
from __future__ import annotations

from pysh.shell import PyShell


def main() -> int:
    """Run the interactive PySH shell. Returns the final exit status."""
    shell = PyShell()
    return shell.run()
