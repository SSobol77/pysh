# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structured diagnostics for declarative PySH configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pysh.diagnostics.redaction import DEFAULT_REDACTION_POLICY, SENSITIVE_NAME_TOKENS

# Re-exported for backward compatibility. The canonical sensitive-name list
# lives in pysh.diagnostics.redaction (Issue #50); this configuration module
# no longer owns a second, independently-maintained copy.
SECRET_KEY_MARKERS: tuple[str, ...] = SENSITIVE_NAME_TOKENS


@dataclass(frozen=True)
class ConfigDiagnostic:
    """One user-facing configuration diagnostic."""

    severity: str
    path: Path | None
    section: str | None
    key: str | None
    value: object | None
    reason: str
    valid_values: tuple[str, ...] = ()

    def format(self) -> str:
        """Return a plain-text diagnostic safe for dumb terminals."""
        location = "config"
        if self.path is not None:
            location = str(self.path)
        if self.section:
            location = f"{location}: [{self.section}]"
        if self.key:
            location = f"{location}.{self.key}"
        value_text = ""
        if self.value is not None:
            value_text = f": {safe_value_repr(self.key, self.value)}"
        valid_text = ""
        if self.valid_values:
            valid_text = f" (valid: {', '.join(self.valid_values)})"
        return f"pysh: config: {self.severity}: {location}{value_text}: {self.reason}{valid_text}"


def safe_value_repr(key: str | None, value: object) -> str:
    """Return a deterministic value representation with secret-like values redacted."""
    if is_secret_like(key):
        return "<redacted>"
    text = repr(value)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def is_secret_like(name: str | None) -> bool:
    """Return whether *name* looks sensitive enough to redact diagnostics.

    Delegates to the canonical :data:`pysh.diagnostics.redaction.DEFAULT_REDACTION_POLICY`
    so configuration diagnostics classify secrets identically to every other
    PySH diagnostic surface (Issue #50).
    """
    if not name:
        return False
    return DEFAULT_REDACTION_POLICY.is_sensitive_name(name)


def error(
    path: Path | None,
    section: str | None,
    key: str | None,
    value: object | None,
    reason: str,
    *,
    valid_values: tuple[str, ...] = (),
) -> ConfigDiagnostic:
    """Construct an error diagnostic."""
    return ConfigDiagnostic("error", path, section, key, value, reason, valid_values)


def warning(
    path: Path | None,
    section: str | None,
    key: str | None,
    value: object | None,
    reason: str,
    *,
    valid_values: tuple[str, ...] = (),
) -> ConfigDiagnostic:
    """Construct a warning diagnostic."""
    return ConfigDiagnostic("warning", path, section, key, value, reason, valid_values)
