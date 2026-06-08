# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/cli.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Command-line entry point for the ``pysh`` console script."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pysh import __version__
from pysh.core.errors import exception_to_diagnostic
from pysh.core.shell import PyShell, _ExitShell
from pysh.diagnostics.trace import DiagnosticTrace, TraceOptions
from pysh.parsing.multiline import iter_logical_lines

_UNSUPPORTED_SYSTEM_SHELL_NAMES: frozenset[str] = frozenset(
    {
        "sh",
        "dash",
        "ash",
    }
)


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
    parser.add_argument(
        "script",
        nargs="?",
        help="execute a PySH script file and exit",
    )
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="arguments passed to the script",
    )
    return parser


def is_unsupported_system_shell_invocation(
    argv0: str,
    argv: Sequence[str] | None = None,
) -> bool:
    """Return True when argv asks PySH to masquerade as a system sh."""
    name = Path(argv0).name
    if name in _UNSUPPORTED_SYSTEM_SHELL_NAMES:
        return True
    if name == "busybox":
        args = list(argv or ())
        return bool(args and args[0] == "sh")
    return False


def _print_unsupported_system_shell_invocation(argv0: str) -> None:
    name = Path(argv0).name
    print(f"pysh: unsupported invocation mode: {name}", file=sys.stderr)
    print(
        "hint: PySH is not a POSIX /bin/sh provider. Run PySH explicitly as `pysh`.",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive PySH shell. Returns the final exit status.

    Uncaught exceptions are converted to a :class:`~pysh.core.errors.Diagnostic`
    via :func:`~pysh.core.errors.exception_to_diagnostic`, printed to stderr,
    and returned as a non-zero exit code.  This is the single boundary function
    for PySH top-level error handling (Issue #5).
    """
    if argv is None and is_unsupported_system_shell_invocation(sys.argv[0], sys.argv[1:]):
        _print_unsupported_system_shell_invocation(sys.argv[0])
        return 2

    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    shell = PyShell(trace=DiagnosticTrace(TraceOptions(enabled=bool(args.debug))))
    try:
        if args.command is not None:
            if args.script is not None:
                print("pysh: -c does not accept a script path", file=sys.stderr)
                return 2
            if "\n" in args.command:
                status = 0
                for logical_line in iter_logical_lines(args.command.splitlines()):
                    status = shell.execute(logical_line)
                return status
            return shell.execute(args.command)
        if args.script is not None:
            return shell.run_script_file(
                Path(args.script),
                list(args.script_args),
                native_only=True,
            )
        return shell.run()
    except _ExitShell as exc:
        return exc.code
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    except BaseException as exc:  # noqa: BLE001
        diag = exception_to_diagnostic(exc)
        print(diag.format_stderr(), file=sys.stderr)
        return diag.exit_code
