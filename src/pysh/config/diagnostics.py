# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structured diagnostics for declarative PySH configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SECRET_KEY_MARKERS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASS",
    "KEY",
    "PRIVATE",
    "CREDENTIAL",
)


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
    """Return whether *name* looks sensitive enough to redact diagnostics."""
    if not name:
        return False
    upper = name.upper()
    return any(marker in upper for marker in SECRET_KEY_MARKERS)


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
