# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/jsonl.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""JSON Lines structured diagnostic sink (Issue #50, schema v1 slice 2).

This module is the first concrete sink built on top of the validate-redact-
serialize pipeline in :mod:`pysh.diagnostics.emitter`. It adapts the
existing human-readable trace stream (:mod:`pysh.diagnostics.trace`) into
schema v1 :class:`~pysh.diagnostics.schema.StructuredDiagnosticEvent`
instances and writes one sanitized JSON object per line to an explicit
stream (stderr by default).

Enabling this sink never changes the existing ``--debug`` text trace
output: the human-readable and structured paths are independent and may be
used together or separately. This module performs no persistence; it only
writes to an explicitly supplied text stream.
"""
from __future__ import annotations

import json
import math
import sys
from collections.abc import Mapping
from typing import IO

from pysh.diagnostics.emitter import DiagnosticEmitter
from pysh.diagnostics.redaction import RedactionPolicy
from pysh.diagnostics.schema import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    DiagnosticEventClass,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
    StructuredValue,
)
from pysh.diagnostics.trace import DiagnosticEvent, DiagnosticLevel, DiagnosticStage

_STAGE_EVENT_CLASS: Mapping[DiagnosticStage, DiagnosticEventClass] = {
    DiagnosticStage.INPUT: DiagnosticEventClass.PARSER,
    DiagnosticStage.LEX: DiagnosticEventClass.PARSER,
    DiagnosticStage.PARSE: DiagnosticEventClass.PARSER,
    DiagnosticStage.HEREDOC: DiagnosticEventClass.PARSER,
    DiagnosticStage.EXPAND: DiagnosticEventClass.PARSER,
    DiagnosticStage.PATH_EXPAND: DiagnosticEventClass.PARSER,
    DiagnosticStage.REDIRECT: DiagnosticEventClass.PARSER,
    DiagnosticStage.RESOLVE: DiagnosticEventClass.RUNTIME,
    DiagnosticStage.EXECUTE_PLAN: DiagnosticEventClass.RUNTIME,
    DiagnosticStage.JOB_CONTROL: DiagnosticEventClass.RUNTIME,
    DiagnosticStage.COMPLETE: DiagnosticEventClass.RUNTIME,
    DiagnosticStage.ERROR: DiagnosticEventClass.RUNTIME,
}


def _coerce_trace_field(value: object) -> StructuredValue:
    """Coerce one arbitrary trace field value into a bounded structured value.

    Trace fields (the ``**fields`` passed to :meth:`DiagnosticTrace.emit`)
    are untyped by design, matching the pre-existing human-readable
    renderer (:func:`pysh.diagnostics.trace.format_trace_event`), which
    already stringifies every field via ``str()``. This adapter applies the
    same tolerant policy so a trace call site never needs to know about the
    structured schema's stricter type bounds: known JSON-safe types pass
    through unchanged, non-finite floats are stringified (schema v1 rejects
    them), and anything else is converted with ``str()`` rather than
    rejected, since these values already originate from trusted, internal
    trace call sites rather than external/attacker-controlled input.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return tuple(_coerce_trace_field(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _coerce_trace_field(item) for key, item in value.items()}
    return str(value)


def structured_event_from_trace(event: DiagnosticEvent) -> StructuredDiagnosticEvent:
    """Adapt one trace :class:`DiagnosticEvent` into a schema v1 structured event.

    The resulting event carries no ``actor``/``action``/``target``/``result``:
    a parser-to-execution trace line does not have meaningful values for
    those fields, and Issue #50 requires them only "where meaningful".
    """
    event_class = _STAGE_EVENT_CLASS[event.stage]
    severity = (
        DiagnosticSeverity.ERROR
        if event.level is DiagnosticLevel.ERROR
        else DiagnosticSeverity.DEBUG
    )
    fields: dict[str, StructuredValue] = {"message": event.message}
    for name, value in event.fields.items():
        fields[name] = _coerce_trace_field(value)
    return StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=event_class,
        event=f"{event_class.value}.{event.stage.value.lower()}",
        severity=severity,
        fields=fields,
    )


class JsonlDiagnosticSink:
    """Writes sanitized schema v1 structured events as one JSON object per line."""

    def __init__(
        self,
        stream: IO[str] | None = None,
        policy: RedactionPolicy | None = None,
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.emitter = DiagnosticEmitter(policy)

    def write_structured_event(
        self,
        event: StructuredDiagnosticEvent,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Validate, redact, and write *event* as one deterministic JSON line.

        ``sort_keys=True`` makes the key order deterministic across runs.
        ``allow_nan=False`` makes the encoder itself fail closed (raising
        ``ValueError``, contained by the caller) rather than ever emitting a
        non-standard ``NaN``/``Infinity`` token, even though schema v1
        construction already rejects non-finite floats before this point.
        """
        payload = self.emitter.sanitize_to_payload(event, env=env)
        line = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        print(line, file=self.stream)
