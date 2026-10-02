# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/emitter.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Core-owned structured diagnostic emission boundary (Issue #50).

The conceptual pipeline implemented here is::

    event -> validate -> redact -> serialize/forward

:class:`StructuredDiagnosticEvent` construction already validates (see
:mod:`pysh.diagnostics.schema`). :class:`DiagnosticEmitter` adds the
redaction and serialization steps so that no sink, present or future, can
accidentally receive raw, unredacted event content.

This module does not persist events, write to stderr/files, open sockets,
or add CLI flags. It is a pure transformation boundary; wiring it to an
actual sink is deferred to a later Issue #50 slice.
"""
from __future__ import annotations

from collections.abc import Mapping

from pysh.diagnostics.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy
from pysh.diagnostics.schema import StructuredDiagnosticEvent, to_json_compatible


class DiagnosticEmitter:
    """Validate-redact-serialize boundary for structured diagnostic events."""

    def __init__(self, policy: RedactionPolicy | None = None) -> None:
        self._policy = policy if policy is not None else DEFAULT_REDACTION_POLICY

    @property
    def policy(self) -> RedactionPolicy:
        """Return the redaction policy this emitter applies."""
        return self._policy

    def sanitize_event(
        self,
        event: StructuredDiagnosticEvent,
        env: Mapping[str, str] | None = None,
    ) -> StructuredDiagnosticEvent:
        """Return a new, fully redacted copy of *event*.

        Secret values are collected from ``event.fields`` and, when
        exposed through *env* (or ``os.environ`` by default), from known
        sensitive environment variables. Those secrets are then redacted
        everywhere they appear: in sensitive-named fields, in nested
        fields, and embedded inside unrelated ``actor``/``action``/
        ``target`` text. ``actor``/``action``/``target``/``result`` are
        optional on the event; a ``None`` value passes through unchanged.
        """
        fields_plain = to_json_compatible(event.fields)
        secrets = self._policy.collect_secret_values(fields_plain, env)
        sanitized_fields = self._policy.redact_value_with_secrets(fields_plain, secrets)
        sanitized_actor = (
            self._policy.redact_value_with_secrets(event.actor, secrets)
            if event.actor is not None
            else None
        )
        sanitized_action = (
            self._policy.redact_value_with_secrets(event.action, secrets)
            if event.action is not None
            else None
        )
        sanitized_target = (
            self._policy.redact_value_with_secrets(event.target, secrets)
            if event.target is not None
            else None
        )
        return StructuredDiagnosticEvent(
            schema_version=event.schema_version,
            event_class=event.event_class,
            event=event.event,
            severity=event.severity,
            actor=sanitized_actor,
            action=sanitized_action,
            target=sanitized_target,
            result=event.result,
            reason_code=event.reason_code,
            fields=sanitized_fields,
        )

    def to_payload(self, event: StructuredDiagnosticEvent) -> dict[str, object]:
        """Return a plain JSON-compatible payload for *event*.

        This does not redact; callers that need a sanitized payload should
        pass the result of :meth:`sanitize_event` here, or call
        :meth:`sanitize_to_payload`.
        """
        return {
            "schema_version": event.schema_version,
            "event_class": event.event_class.value,
            "event": event.event,
            "severity": event.severity.value,
            "actor": event.actor,
            "action": event.action,
            "target": event.target,
            "result": event.result.value if event.result is not None else None,
            "reason_code": event.reason_code,
            "fields": to_json_compatible(event.fields),
        }

    def sanitize_to_payload(
        self,
        event: StructuredDiagnosticEvent,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        """Return a fully redacted, JSON-compatible payload for *event*."""
        return self.to_payload(self.sanitize_event(event, env=env))
