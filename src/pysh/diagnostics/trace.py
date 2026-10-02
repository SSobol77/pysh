# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/trace.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Opt-in observability and redaction primitives for PySH diagnostics.

This module is intentionally leaf-like: it imports no shell runtime modules,
performs no I/O at import time, and never executes subprocesses. Runtime
callers may attach a :class:`DiagnosticTrace` to write deterministic trace
events to stderr or another explicit stream.

The canonical redaction implementation lives in
:mod:`pysh.diagnostics.redaction`. The names below are re-exported here so
that existing imports (``from pysh.diagnostics.trace import RedactionPolicy``,
``DEFAULT_REDACTION_POLICY``, ``REDACTED_PLACEHOLDER``) continue to work
unchanged.
"""
from __future__ import annotations

import shlex
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import IO

from pysh.diagnostics.redaction import (
    DEFAULT_REDACTION_POLICY,
    REDACTED_PLACEHOLDER,
    SENSITIVE_NAME_TOKENS,
    RedactionPolicy,
    redact_env_mapping,
    redact_value,
)

__all__ = [
    "DEFAULT_REDACTION_POLICY",
    "REDACTED_PLACEHOLDER",
    "SENSITIVE_NAME_TOKENS",
    "RedactionPolicy",
    "redact_env_mapping",
    "redact_value",
    "DiagnosticLevel",
    "DiagnosticStage",
    "TraceOptions",
    "DiagnosticEvent",
    "DiagnosticSink",
    "DiagnosticTrace",
    "format_trace_event",
]


class DiagnosticLevel(StrEnum):
    """Severity level for diagnostic trace events."""

    DEBUG = "DEBUG"
    ERROR = "ERROR"


class DiagnosticStage(StrEnum):
    """Canonical diagnostic stages for parser-to-execution observability."""

    INPUT = "INPUT"
    LEX = "LEX"
    PARSE = "PARSE"
    HEREDOC = "HEREDOC"
    EXPAND = "EXPAND"
    PATH_EXPAND = "PATH_EXPAND"
    REDIRECT = "REDIRECT"
    RESOLVE = "RESOLVE"
    EXECUTE_PLAN = "EXECUTE_PLAN"
    JOB_CONTROL = "JOB_CONTROL"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TraceOptions:
    """Options for opt-in diagnostic tracing.

    ``enabled`` gates the pre-existing human-readable ``[PYSH_DEBUG]`` text
    trace. ``json_enabled`` independently gates the structured (schema v1)
    trace adapter (Issue #50 slice 2, see :mod:`pysh.diagnostics.jsonl`).
    Either, both, or neither may be set; a trace call becomes a no-op only
    when both are False.
    """

    enabled: bool = False
    json_enabled: bool = False
    prefix: str = "[PYSH_DEBUG]"
    redaction: RedactionPolicy = DEFAULT_REDACTION_POLICY


@dataclass(frozen=True)
class DiagnosticEvent:
    """One structured diagnostic trace event."""

    stage: DiagnosticStage
    message: str
    level: DiagnosticLevel = DiagnosticLevel.DEBUG
    fields: Mapping[str, object] = field(default_factory=dict)


class DiagnosticSink:
    """Explicit text sink for diagnostic trace output."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr

    def write_event(self, line: str) -> None:
        """Write one formatted event line."""
        print(line, file=self.stream)


#: Exception classes a structured_sink failure is expected to raise: schema
#: validation errors from a malformed event (TypeError/ValueError, see
#: pysh.diagnostics.schema), and serialization/stream I/O failures
#: (TypeError/ValueError from json.dumps, OSError from a closed or broken
#: stream). Diagnostics are observational (Issue #50): a failure in this set
#: must never alter command execution. Anything outside this set is treated
#: as a genuine programming error and is allowed to propagate.
_STRUCTURED_SINK_FAILURE_EXCEPTIONS: tuple[type[Exception], ...] = (
    TypeError,
    ValueError,
    OSError,
)


class DiagnosticTrace:
    """Runtime trace writer. Disabled traces are no-ops.

    ``structured_sink``, when supplied, is invoked with the raw
    :class:`DiagnosticEvent` whenever ``options.json_enabled`` is True. This
    class deliberately knows nothing about the structured (schema v1)
    event model: the adapter from :class:`DiagnosticEvent` to a
    ``StructuredDiagnosticEvent`` lives in :mod:`pysh.diagnostics.jsonl`,
    and callers (``pysh.cli``) wire the two together. This keeps the
    pre-existing text-trace path fully decoupled from the newer structured
    contract.

    Structured diagnostics are observational only (Issue #50): a failure
    raised by ``structured_sink`` (malformed event construction, JSON
    serialization, or sink I/O) is contained at this boundary and never
    propagates into the caller's command execution. It is not re-logged
    through this same trace (doing so could recurse or fail identically)
    and produces no secondary output. The pre-existing human-readable text
    sink is unaffected by this containment and keeps its original behavior.
    """

    def __init__(
        self,
        options: TraceOptions | None = None,
        sink: DiagnosticSink | None = None,
        structured_sink: Callable[[DiagnosticEvent], None] | None = None,
    ) -> None:
        self.options = options if options is not None else TraceOptions()
        self.sink = sink if sink is not None else DiagnosticSink()
        self.structured_sink = structured_sink

    @property
    def enabled(self) -> bool:
        """Return True when any trace emission (text or structured) is enabled."""
        return self.options.enabled or self.options.json_enabled

    def _dispatch(self, event: DiagnosticEvent) -> None:
        if self.options.enabled:
            self.sink.write_event(format_trace_event(event, self.options))
        if self.options.json_enabled and self.structured_sink is not None:
            try:
                self.structured_sink(event)
            except _STRUCTURED_SINK_FAILURE_EXCEPTIONS:
                # Observational only: never let a diagnostics-sink failure
                # affect command execution, and never re-attempt to log it.
                pass

    def emit(
        self,
        stage: DiagnosticStage,
        message: str,
        **fields: object,
    ) -> None:
        """Emit a debug event if tracing is enabled."""
        if not self.enabled:
            return
        event = DiagnosticEvent(stage=stage, message=message, fields=fields)
        self._dispatch(event)

    def error(self, message: str, **fields: object) -> None:
        """Emit an error event if tracing is enabled."""
        if not self.enabled:
            return
        event = DiagnosticEvent(
            stage=DiagnosticStage.ERROR,
            message=message,
            level=DiagnosticLevel.ERROR,
            fields=fields,
        )
        self._dispatch(event)


def format_trace_event(event: DiagnosticEvent, options: TraceOptions | None = None) -> str:
    """Format one trace event as a deterministic single line."""
    opts = options if options is not None else TraceOptions(enabled=True)
    fields: list[str] = [
        f"stage={event.stage.value}",
        f"level={event.level.value}",
        f"message={_quote(opts.redaction.redact_text(event.message))}",
    ]
    for name in sorted(event.fields):
        value = opts.redaction.redact_text(str(event.fields[name]))
        fields.append(f"{name}={_quote(value)}")
    return f"{opts.prefix} " + " ".join(fields)


def _quote(value: str) -> str:
    return shlex.quote(value)
