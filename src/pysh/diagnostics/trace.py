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
from collections.abc import Mapping
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
    """Options for opt-in diagnostic tracing."""

    enabled: bool = False
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


class DiagnosticTrace:
    """Runtime trace writer. Disabled traces are no-ops."""

    def __init__(
        self,
        options: TraceOptions | None = None,
        sink: DiagnosticSink | None = None,
    ) -> None:
        self.options = options if options is not None else TraceOptions()
        self.sink = sink if sink is not None else DiagnosticSink()

    @property
    def enabled(self) -> bool:
        """Return True when trace emission is enabled."""
        return self.options.enabled

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
        self.sink.write_event(format_trace_event(event, self.options))

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
        self.sink.write_event(format_trace_event(event, self.options))


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
