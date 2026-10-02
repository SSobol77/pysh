# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/schema.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Versioned structured diagnostic event schema (Issue #50, schema v1).

This module defines the machine-oriented structured event contract that
later slices will persist, serialize, and route through opt-in sinks. It is
intentionally stdlib-only, deterministic, and free of I/O at import time:
constructing a :class:`StructuredDiagnosticEvent` never touches the clock,
the filesystem, or the environment.

Implementing an :class:`DiagnosticEventClass` member here reserves the
contract namespace for that subsystem; it does not mean the corresponding
feature (resource enforcement, package management, AI, remote execution)
is implemented. Those remain out of scope for PySH v1.0.0 unless a
dedicated issue says otherwise.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Union

DIAGNOSTIC_EVENT_SCHEMA_VERSION = 1

# A bounded, JSON-style recursive value type. Deliberately excludes arbitrary
# objects: callers must convert domain objects to one of these shapes before
# attaching them to a structured event, rather than relying on ``repr()``
# (which could silently leak unredacted data through an object's string
# form).
#
# The recursive member below needs string forward references, which the
# `X | Y` syntax cannot evaluate at runtime (unlike `typing.Union`), hence
# the explicit `Union` usage here instead of PEP 604 syntax.
StructuredScalar = None | bool | int | float | str
StructuredValue = Union[  # noqa: UP007
    StructuredScalar,
    "tuple[StructuredValue, ...]",
    "Mapping[str, StructuredValue]",
]


class DiagnosticEventClass(StrEnum):
    """Top-level namespace for a structured diagnostic event.

    Every member reserves a namespace prefix for ``event`` names of that
    class (for example ``runtime.command_failed``). Reserving a class here
    does not imply the corresponding subsystem is implemented.
    """

    STARTUP = "startup"
    PARSER = "parser"
    RUNTIME = "runtime"
    PLUGIN = "plugin"
    SECURITY = "security"
    RESOURCE = "resource"
    PACKAGE = "package"
    AI = "ai"
    REMOTE = "remote"


class DiagnosticSeverity(StrEnum):
    """Severity of a structured diagnostic event."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticResult(StrEnum):
    """Explicit outcome of the action a structured diagnostic event describes."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _validate_event_name(event: str, event_class: DiagnosticEventClass) -> None:
    if not isinstance(event, str) or not event:
        raise ValueError("event must be a non-empty string")
    if not _EVENT_NAME_PATTERN.fullmatch(event):
        raise ValueError(
            f"event {event!r} must be a dot-namespaced lowercase identifier, "
            "for example 'runtime.command_failed'"
        )
    prefix = event.split(".", 1)[0]
    if prefix != event_class.value:
        raise ValueError(
            f"event {event!r} must start with its event class {event_class.value!r}"
        )


def _require_str_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError(f"field keys must be strings, got {type(key)!r}")
    return key


def _normalize_structured_value(value: object) -> StructuredValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"non-finite float values are not JSON-representable: {value!r}"
            )
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_structured_value(item) for item in value)
    if isinstance(value, Mapping):
        return MappingProxyType(
            {_require_str_key(key): _normalize_structured_value(item) for key, item in value.items()}
        )
    raise TypeError(f"unsupported structured diagnostic field value type: {type(value)!r}")


def _normalize_fields(fields: object) -> Mapping[str, StructuredValue]:
    if not isinstance(fields, Mapping):
        raise TypeError(f"fields must be a mapping, got {type(fields)!r}")
    normalized = {_require_str_key(key): _normalize_structured_value(value) for key, value in fields.items()}
    return MappingProxyType(normalized)


def to_json_compatible(value: StructuredValue) -> object:
    """Convert a normalized structured value into plain ``dict``/``list`` form.

    :class:`StructuredDiagnosticEvent` stores nested mappings and sequences
    as immutable ``MappingProxyType``/``tuple`` instances so events cannot be
    mutated after construction. Serialization sinks (JSON encoders, test
    assertions) generally want plain ``dict``/``list`` instead; this helper
    performs that conversion without altering the represented data.
    """
    if isinstance(value, Mapping):
        return {key: to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_json_compatible(item) for item in value]
    return value


def _validate_optional_non_empty_str(value: str | None, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{field_name} must be a non-empty string when provided")


@dataclass(frozen=True, slots=True)
class StructuredDiagnosticEvent:
    """One schema v1 structured diagnostic event.

    ``event_class``, ``event``, and ``severity`` are mandatory. The
    contextual metadata fields (``actor``, ``action``, ``target``,
    ``result``, ``reason_code``) are optional: Issue #50 requires them only
    "where meaningful", so callers are never forced to invent a placeholder
    value. When one of the string-valued contextual fields is supplied, it
    must be non-empty; empty-string placeholders are rejected the same as a
    missing value would be meaningless either way.

    Construction validates the event eagerly: a malformed event raises
    before it can reach any sink. ``fields`` is normalized into immutable
    containers so a constructed event can never be mutated afterward.
    """

    schema_version: int
    event_class: DiagnosticEventClass
    event: str
    severity: DiagnosticSeverity
    actor: str | None = None
    action: str | None = None
    target: str | None = None
    result: DiagnosticResult | None = None
    reason_code: str | None = None
    fields: Mapping[str, StructuredValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != DIAGNOSTIC_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported diagnostic event schema version: {self.schema_version!r} "
                f"(expected {DIAGNOSTIC_EVENT_SCHEMA_VERSION})"
            )
        if not isinstance(self.event_class, DiagnosticEventClass):
            raise TypeError(f"event_class must be a DiagnosticEventClass, got {type(self.event_class)!r}")
        _validate_event_name(self.event, self.event_class)
        if not isinstance(self.severity, DiagnosticSeverity):
            raise TypeError(f"severity must be a DiagnosticSeverity, got {type(self.severity)!r}")
        if self.result is not None and not isinstance(self.result, DiagnosticResult):
            raise TypeError(f"result must be a DiagnosticResult when provided, got {type(self.result)!r}")
        _validate_optional_non_empty_str(self.actor, "actor")
        _validate_optional_non_empty_str(self.action, "action")
        _validate_optional_non_empty_str(self.target, "target")
        _validate_optional_non_empty_str(self.reason_code, "reason_code")
        object.__setattr__(self, "fields", _normalize_fields(self.fields))
