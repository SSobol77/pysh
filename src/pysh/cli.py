# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Command-line entry point for the ``pysh`` console script."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pysh import __version__
from pysh.core.errors import exception_to_diagnostic
from pysh.core.shell import PyShell
from pysh.diagnostics.trace import DiagnosticTrace, TraceOptions
from pysh.parsing.multiline import iter_logical_lines


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
    parser.add_argument(
        "--debug",
        "--trace",
        dest="debug",
        action="store_true",
        help="emit deterministic PySH diagnostic trace lines to stderr",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive PySH shell. Returns the final exit status.

    Uncaught exceptions are converted to a :class:`~pysh.core.errors.Diagnostic`
    via :func:`~pysh.core.errors.exception_to_diagnostic`, printed to stderr,
    and returned as a non-zero exit code.  This is the single boundary function
    for PySH top-level error handling (Issue #5).
    """
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    shell = PyShell(trace=DiagnosticTrace(TraceOptions(enabled=bool(args.debug))))
    try:
        if args.command is not None:
            if "\n" in args.command:
                status = 0
                for logical_line in iter_logical_lines(args.command.splitlines()):
                    status = shell.execute(logical_line)
                return status
            return shell.execute(args.command)
        return shell.run()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    except BaseException as exc:  # noqa: BLE001
        diag = exception_to_diagnostic(exc)
        print(diag.format_stderr(), file=sys.stderr)
        return diag.exit_code
