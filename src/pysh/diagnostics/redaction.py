# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/redaction.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical redaction policy for PySH diagnostics (Issue #50).

This module is the single core-owned implementation of name-based and
value-based redaction. It is intentionally leaf-like: it imports no shell
runtime modules, performs no I/O at import time, and never executes
subprocesses.

``pysh.diagnostics.trace`` re-exports the public names defined here so that
existing imports continue to work unchanged. New code, including the
structured diagnostics schema and emitter, must import from this module
directly instead of duplicating redaction logic.
"""
from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

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
    """Name-based and value-based redaction policy.

    Covers both the legacy human-readable text redaction used by
    :mod:`pysh.diagnostics.trace` and the structured recursive redaction
    used by the Issue #50 structured diagnostics contract.
    """

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
            redacted = _redact_value_at_word_boundaries(redacted, value, self.placeholder)
        return redacted

    def collect_secret_values(
        self,
        value: object,
        env: Mapping[str, str] | None = None,
    ) -> frozenset[str]:
        """Return concrete secret values exposed by sensitive names in *value* or *env*.

        *value* is walked recursively: any string found as the value of a
        sensitive mapping key, at any depth, is treated as an exposed secret
        and collected so it can later be redacted wherever else it appears
        (for example, embedded in an unrelated message string).
        """
        secrets: set[str] = set()
        source = env if env is not None else os.environ
        for name, env_value in source.items():
            if env_value and self.is_sensitive_name(name):
                secrets.add(env_value)
        self._collect_secret_values_from_structure(value, secrets)
        return frozenset(secrets)

    def _collect_secret_values_from_structure(self, value: object, secrets: set[str]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(key, str) and self.is_sensitive_name(key):
                    if isinstance(item, str) and item:
                        secrets.add(item)
                self._collect_secret_values_from_structure(item, secrets)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._collect_secret_values_from_structure(item, secrets)

    def redact_value_with_secrets(self, value: object, secrets: Iterable[str]) -> object:
        """Recursively redact *value*, replacing sensitive keys and exposed *secrets*.

        Supports ``None``, ``bool``, ``int``, ``float``, ``str``, mappings
        (including nested mappings), lists, and tuples. Any other object
        type is rejected with :class:`TypeError` rather than being
        stringified with ``repr()``, which could otherwise leak unredacted
        data through an unexpected object's string form.

        The original *value* is never mutated: new containers are built for
        every mapping, list, and tuple encountered.
        """
        return self._redact_value_with_secrets(value, tuple(secrets))

    def _redact_value_with_secrets(self, value: object, secrets: tuple[str, ...]) -> object:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            redacted = _redact_assignment_tokens(value, self)
            for secret in secrets:
                redacted = _redact_value_at_word_boundaries(redacted, secret, self.placeholder)
            return redacted
        if isinstance(value, Mapping):
            result: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(
                        f"structured redaction requires string keys, got {type(key)!r}"
                    )
                if self.is_sensitive_name(key):
                    result[key] = self.placeholder
                else:
                    result[key] = self._redact_value_with_secrets(item, secrets)
            return result
        if isinstance(value, tuple):
            return tuple(self._redact_value_with_secrets(item, secrets) for item in value)
        if isinstance(value, list):
            return [self._redact_value_with_secrets(item, secrets) for item in value]
        raise TypeError(f"unsupported structured diagnostic value type: {type(value)!r}")

    def redact_structured(self, value: object, env: Mapping[str, str] | None = None) -> object:
        """Return *value* with sensitive keys and exposed secret values redacted."""
        secrets = self.collect_secret_values(value, env)
        return self.redact_value_with_secrets(value, secrets)


DEFAULT_REDACTION_POLICY = RedactionPolicy()


def redact_value(name: str, value: object, policy: RedactionPolicy | None = None) -> str:
    """Return a display-safe value for *name* using *policy*."""
    return (policy or DEFAULT_REDACTION_POLICY).redact_value(name, value)


def redact_env_mapping(
    env: Mapping[str, str],
    policy: RedactionPolicy | None = None,
) -> dict[str, str]:
    """Return *env* with sensitive values redacted."""
    return (policy or DEFAULT_REDACTION_POLICY).redact_env_mapping(env)


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


def _redact_value_at_word_boundaries(text: str, value: str, placeholder: str) -> str:
    """Replace *value* with *placeholder* only where it forms a whole token.

    A naive ``text.replace(value, ...)`` corrupts unrelated diagnostic text
    (file paths, line numbers, counters) whenever a short sensitive value
    happens to be a substring of something else, e.g. value ``"1"`` inside
    path segment ``pytest-19``. Requiring a word boundary on both sides of
    the match keeps that unrelated text byte-for-byte unchanged while still
    redacting the value wherever it is genuinely exposed as its own token
    (e.g. surrounded by spaces, quotes, or the ends of the string).
    """
    pattern = rf"\b{re.escape(value)}\b"
    return re.sub(pattern, placeholder, text)
