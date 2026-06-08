# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/trace.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Opt-in observability and redaction primitives for PySH diagnostics.

This module is intentionally leaf-like: it imports no shell runtime modules,
performs no I/O at import time, and never executes subprocesses. Runtime
callers may attach a :class:`DiagnosticTrace` to write deterministic trace
events to stderr or another explicit stream.
"""
from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import IO


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


SENSITIVE_NAME_TOKENS: tuple[str, ...] = (
    "PASSWORD",
    "PASSWD",
    "PASS",
    "TOKEN",
    "SECRET",
    "KEY",
    "PRIVATE",
    "CREDENTIAL",
    "AUTH",
    "COOKIE",
    "SESSION",
    "API_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
)

REDACTED_PLACEHOLDER = "<redacted>"


@dataclass(frozen=True)
class RedactionPolicy:
    """Name-based environment and diagnostic redaction policy."""

    sensitive_tokens: tuple[str, ...] = SENSITIVE_NAME_TOKENS
    placeholder: str = REDACTED_PLACEHOLDER
    redact_sensitive_env_values_in_text: bool = True

    def is_sensitive_name(self, name: str) -> bool:
        """Return True when *name* is classified as sensitive."""
        upper = name.upper()
        return any(token in upper for token in self.sensitive_tokens)

    def redact_value(self, name: str, value: object) -> str:
        """Return a display-safe value for *name*."""
        if self.is_sensitive_name(name):
            return self.placeholder
        return str(value)

    def redact_env_mapping(self, env: Mapping[str, str]) -> dict[str, str]:
        """Return a copy of *env* with sensitive values replaced."""
        return {name: self.redact_value(name, value) for name, value in env.items()}

    def redact_text(self, text: str, env: Mapping[str, str] | None = None) -> str:
        """Redact sensitive assignments and known sensitive env values in *text*."""
        redacted = _redact_assignment_tokens(text, self)
        if not self.redact_sensitive_env_values_in_text:
            return redacted
        source = env if env is not None else os.environ
        for name, value in source.items():
            if not value or not self.is_sensitive_name(name):
                continue
            redacted = redacted.replace(value, self.placeholder)
        return redacted


DEFAULT_REDACTION_POLICY = RedactionPolicy()


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


def redact_value(name: str, value: object, policy: RedactionPolicy | None = None) -> str:
    """Return a display-safe value for *name* using *policy*."""
    return (policy or DEFAULT_REDACTION_POLICY).redact_value(name, value)


def redact_env_mapping(
    env: Mapping[str, str],
    policy: RedactionPolicy | None = None,
) -> dict[str, str]:
    """Return *env* with sensitive values redacted."""
    return (policy or DEFAULT_REDACTION_POLICY).redact_env_mapping(env)


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


def _redact_assignment_tokens(text: str, policy: RedactionPolicy) -> str:
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        return text
    redacted = text
    for token in tokens:
        name, sep, _value = token.partition("=")
        if not sep or not name or not policy.is_sensitive_name(name):
            continue
        redacted = redacted.replace(token, f"{name}={policy.placeholder}")
    return redacted
