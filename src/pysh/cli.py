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

import argparse
import sys
from collections.abc import Sequence

from pysh import __version__
from pysh.shell import PyShell


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pysh",
        description="PySH - Python-first interactive shell.",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"pysh {__version__}",
    )
    parser.add_argument(
        "-c",
        dest="command",
        metavar="COMMAND",
        default=None,
        help="execute COMMAND and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive PySH shell. Returns the final exit status."""
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    shell = PyShell()
    if args.command is not None:
        return shell.execute(args.command)
    return shell.run()
