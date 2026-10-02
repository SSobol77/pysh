# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/cli.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Command-line entry point for the ``pysh`` console script."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pysh import __version__
from pysh.config.startup import StartupPolicy
from pysh.core.errors import ExitCode, exception_to_diagnostic
from pysh.core.shell import PyShell, _ExitShell
from pysh.diagnostics.audit import AuditLogError, AuditLogSink
from pysh.diagnostics.jsonl import JsonlDiagnosticSink, structured_event_from_trace
from pysh.diagnostics.redaction import DEFAULT_REDACTION_POLICY
from pysh.diagnostics.schema import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    DiagnosticEventClass,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
)
from pysh.diagnostics.trace import (
    DiagnosticEvent,
    DiagnosticTrace,
    StructuredSinkFanOut,
    TraceOptions,
)
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
    diagnostics_format_group = parser.add_mutually_exclusive_group()
    diagnostics_format_group.add_argument(
        "--debug",
        "--trace",
        dest="debug",
        action="store_true",
        help="emit deterministic PySH diagnostic trace lines to stderr",
    )
    diagnostics_format_group.add_argument(
        "--diagnostics-json",
        dest="diagnostics_json",
        action="store_true",
        help=(
            "emit structured (schema v1) diagnostic trace events as JSON "
            "Lines to stderr; mutually exclusive with --debug/--trace"
        ),
    )
    parser.add_argument(
        "--audit-log",
        dest="audit_log",
        metavar="PATH",
        default=None,
        help=(
            "append redacted structured (schema v1) audit events as JSON Lines "
            "to PATH (opt-in; orthogonal to --debug/--diagnostics-json)"
        ),
    )
    parser.add_argument(
        "--no-rc",
        action="store_true",
        help="start without reading or creating user configuration",
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


def _build_trace(
    *,
    debug: bool,
    diagnostics_json: bool,
    audit_sink: AuditLogSink | None = None,
) -> DiagnosticTrace:
    """Construct the runtime trace, wiring the requested structured sinks.

    ``pysh.diagnostics.trace`` stays decoupled from the schema v1 structured
    event model; this function is the single place that bridges the two.
    Each trace event is produced once and fanned out, in fixed order, to the
    stderr JSONL sink (``--diagnostics-json``) and then the audit file sink
    (``--audit-log``).
    """
    sinks: list[Callable[[DiagnosticEvent], None]] = []
    if diagnostics_json:
        json_sink = JsonlDiagnosticSink()

        def _write_json(event: DiagnosticEvent) -> None:
            json_sink.write_structured_event(structured_event_from_trace(event))

        sinks.append(_write_json)
    if audit_sink is not None:
        audit = audit_sink

        def _write_audit(event: DiagnosticEvent) -> None:
            audit.write_structured_event(structured_event_from_trace(event))

        sinks.append(_write_audit)
    return DiagnosticTrace(
        TraceOptions(enabled=debug, structured_enabled=bool(sinks)),
        structured_sink=StructuredSinkFanOut(*sinks) if sinks else None,
    )


def _invocation_mode(args: argparse.Namespace) -> str:
    if args.command is not None:
        return "command"
    if args.script is not None:
        return "script"
    return "batch" if not sys.stdin.isatty() else "interactive"


def _startup_event(args: argparse.Namespace) -> StructuredDiagnosticEvent:
    """Return the single bounded, non-secret startup audit event."""
    return StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=DiagnosticEventClass.STARTUP,
        event="startup.session_started",
        severity=DiagnosticSeverity.INFO,
        fields={"invocation_mode": _invocation_mode(args), "no_rc": bool(args.no_rc)},
    )


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
    audit_sink: AuditLogSink | None = None
    if args.audit_log is not None:
        # The user explicitly asked for an audit trail: never run without it.
        try:
            audit_sink = AuditLogSink.open(args.audit_log)
        except AuditLogError as exc:
            message = DEFAULT_REDACTION_POLICY.redact_text(str(exc))
            print(f"pysh: audit-log: {message}", file=sys.stderr)
            return int(ExitCode.GENERAL_ERROR)
    try:
        if audit_sink is not None:
            try:
                audit_sink.write_structured_event(_startup_event(args))
            except (TypeError, ValueError):
                pass  # observational; the sink contains OSError itself
        return _run(args, audit_sink)
    finally:
        if audit_sink is not None:
            audit_sink.close()


def _run(args: argparse.Namespace, audit_sink: AuditLogSink | None) -> int:
    startup_policy = StartupPolicy(load_user_configuration=not args.no_rc)
    shell = PyShell(
        trace=_build_trace(
            debug=bool(args.debug),
            diagnostics_json=bool(args.diagnostics_json),
            audit_sink=audit_sink,
        ),
        startup_policy=startup_policy,
    )
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
        if not sys.stdin.isatty():
            return shell.run_batch(sys.stdin)
        return shell.run()
    except _ExitShell as exc:
        return exc.code
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    except BaseException as exc:  # noqa: BLE001
        diag = exception_to_diagnostic(exc)
        print(diag.format_stderr(), file=sys.stderr)
        return diag.exit_code
