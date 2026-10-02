# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Adapter from isolated-plugin events to structured diagnostics (Issue #50).

The dependency direction is ``pysh.plugins.isolated -> pysh.diagnostics``;
``pysh.diagnostics`` never imports isolated-plugin code. The adapter only
reads the bounded, payload-free :class:`IsolatedPluginEvent` metadata
(plugin name, capability labels, operation name, reason code). Child IPC
payloads, environment values, file contents, command output, and parent
objects are never part of that event and therefore can never be copied
into a structured event here. Canonical redaction still runs in the shared
sinks (:class:`~pysh.diagnostics.emitter.DiagnosticEmitter`).
"""
from __future__ import annotations

from collections.abc import Callable

from pysh.diagnostics.schema import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    DiagnosticEventClass,
    DiagnosticResult,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
    StructuredValue,
)
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind

__all__ = [
    "CAPABILITY_GRANT_ACTION",
    "make_structured_plugin_event_sink",
    "structured_event_from_isolated_plugin_event",
]

CAPABILITY_GRANT_ACTION = "capability_grant"

#: Failures of an observational structured sink: malformed event
#: construction/serialization (``TypeError``/``ValueError``) and sink I/O
#: (``OSError``). Anything else is a genuine programming error and propagates.
_SINK_FAILURE_EXCEPTIONS: tuple[type[Exception], ...] = (TypeError, ValueError, OSError)

_LIFECYCLE_EVENT_NAMES = {
    IsolatedPluginEventKind.SPAWN: "plugin.spawn",
    IsolatedPluginEventKind.HANDSHAKE: "plugin.handshake",
    IsolatedPluginEventKind.RUNNING: "plugin.running",
    IsolatedPluginEventKind.FAILURE: "plugin.failure",
    IsolatedPluginEventKind.STOPPED: "plugin.stopped",
}
_SUCCESS_KINDS = frozenset({
    IsolatedPluginEventKind.SPAWN,
    IsolatedPluginEventKind.HANDSHAKE,
    IsolatedPluginEventKind.RUNNING,
})
_ALWAYS_WITH_CAPABILITIES = frozenset({
    IsolatedPluginEventKind.SPAWN,
    IsolatedPluginEventKind.GRANTED,
})


def structured_event_from_isolated_plugin_event(
    event: IsolatedPluginEvent,
) -> StructuredDiagnosticEvent:
    """Map one isolated-plugin event to a schema v1 structured event."""
    kind = event.kind
    fields: dict[str, StructuredValue] = {}
    if kind in _ALWAYS_WITH_CAPABILITIES or event.requested_capabilities:
        fields["requested_capabilities"] = tuple(event.requested_capabilities)
    if kind in _ALWAYS_WITH_CAPABILITIES or event.granted_capabilities:
        fields["granted_capabilities"] = tuple(event.granted_capabilities)

    if kind is IsolatedPluginEventKind.RESOURCE_VIOLATION:
        # Bounded metadata only: never argv, environment, payload, or output.
        return StructuredDiagnosticEvent(
            schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            event_class=DiagnosticEventClass.RESOURCE,
            event="resource.limit_exceeded",
            severity=DiagnosticSeverity.ERROR,
            actor=event.plugin_name,
            action=event.operation,
            result=DiagnosticResult.FAILURE,
            reason_code=event.reason_code,
            fields={
                "plugin_name": event.plugin_name,
                "resource": event.resource,
                "configured_limit": event.configured_limit,
                "enforcement": event.enforcement,
            },
        )
    if kind is IsolatedPluginEventKind.DENIED:
        return StructuredDiagnosticEvent(
            schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            event_class=DiagnosticEventClass.SECURITY,
            event="security.capability_denied",
            severity=DiagnosticSeverity.WARNING,
            actor=event.plugin_name,
            action=event.operation,
            result=DiagnosticResult.DENIED,
            reason_code=event.reason_code or "capability_denied",
            fields=fields,
        )
    if kind is IsolatedPluginEventKind.GRANTED:
        return StructuredDiagnosticEvent(
            schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            event_class=DiagnosticEventClass.SECURITY,
            event="security.capability_granted",
            severity=DiagnosticSeverity.INFO,
            actor=event.plugin_name,
            action=CAPABILITY_GRANT_ACTION,
            result=DiagnosticResult.SUCCESS,
            reason_code=event.reason_code,
            fields=fields,
        )

    if kind is IsolatedPluginEventKind.FAILURE:
        severity = DiagnosticSeverity.ERROR
        result: DiagnosticResult | None = DiagnosticResult.FAILURE
    elif kind is IsolatedPluginEventKind.STOPPED:
        # A graceful stop carries no reason code; a forced stop does and its
        # outcome is not unambiguous, so no result is asserted for it.
        forced = event.reason_code is not None
        severity = DiagnosticSeverity.WARNING if forced else DiagnosticSeverity.INFO
        result = None if forced else DiagnosticResult.SUCCESS
    else:
        severity = DiagnosticSeverity.INFO
        result = DiagnosticResult.SUCCESS if kind in _SUCCESS_KINDS else None
    return StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=DiagnosticEventClass.PLUGIN,
        event=_LIFECYCLE_EVENT_NAMES[kind],
        severity=severity,
        actor=event.plugin_name,
        action=event.operation,
        result=result,
        reason_code=event.reason_code,
        fields=fields,
    )


def make_structured_plugin_event_sink(
    structured_sink: Callable[[StructuredDiagnosticEvent], None],
) -> Callable[[IsolatedPluginEvent], None]:
    """Return an ``event_sink`` that feeds *structured_sink* (JSONL/audit).

    Mapping, redaction, and serialization failures plus sink I/O failures
    (``TypeError``/``ValueError``/``OSError``) are contained: diagnostics are
    observational and must never replace the isolated runtime's own result.
    Failures are not re-reported, so no recursion occurs. Other exceptions
    are programming errors and propagate.
    """

    def _sink(event: IsolatedPluginEvent) -> None:
        try:
            structured_sink(structured_event_from_isolated_plugin_event(event))
        except _SINK_FAILURE_EXCEPTIONS:
            return

    return _sink
