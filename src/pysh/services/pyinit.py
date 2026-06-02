# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/pyinit.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Parser for PyInit service metadata files.

A PyInit service file is a small, line-oriented descriptor:

    name: example
    command: python3.13 -m http.server 8080
    depends: [network]

Recognised fields:

  * ``name``     - identifier for the service (required)
  * ``command``  - shell command line to launch the service (required)
  * ``depends``  - list of dependency names, written either as a JSON-like
                   ``[a, b]`` form or as a comma-separated list (optional,
                   defaults to an empty list)

This module never starts services. It is a metadata-only layer that allows
PySH and PyInit to share a vocabulary; the actual control plane lives in
:mod:`pysh.services.service`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SERVICES_DIR = Path("~/.config/pyinit/services").expanduser()
_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


@dataclass(frozen=True)
class ServiceMetadata:
    """In-memory representation of a parsed service file."""

    name: str
    command: str
    depends: tuple[str, ...] = field(default_factory=tuple)


class ServiceMetadataError(ValueError):
    """Raised when service metadata is malformed."""


def _parse_depends(raw: str) -> tuple[str, ...]:
    """Parse the right-hand side of ``depends:``.

    Accepts ``[a, b, c]`` and ``a, b, c``. Each entry must be a bare token
    (no whitespace, no quotes) — anything else is rejected so callers get a
    deterministic error instead of silently dropping a typo.
    """
    text = raw.strip()
    if not text:
        return ()
    if text.startswith("["):
        if not text.endswith("]"):
            raise ServiceMetadataError(f"unterminated depends list: {raw!r}")
        text = text[1:-1].strip()
        if not text:
            return ()
    parts = [item.strip() for item in text.split(",")]
    out: list[str] = []
    for part in parts:
        if not part:
            raise ServiceMetadataError(f"empty dependency entry in {raw!r}")
        if not _VALID_NAME_RE.fullmatch(part):
            raise ServiceMetadataError(f"invalid dependency name: {part!r}")
        out.append(part)
    return tuple(out)


def parse_service_text(text: str) -> ServiceMetadata:
    """Parse the contents of a service file into :class:`ServiceMetadata`."""
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ServiceMetadataError(f"missing ':' in line: {raw!r}")
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in fields:
            raise ServiceMetadataError(f"duplicate field: {key!r}")
        fields[key] = value.strip()
    if "name" not in fields:
        raise ServiceMetadataError("missing required field: name")
    if "command" not in fields:
        raise ServiceMetadataError("missing required field: command")
    name = fields["name"]
    if not _VALID_NAME_RE.fullmatch(name):
        raise ServiceMetadataError(f"invalid service name: {name!r}")
    command = fields["command"]
    if not command:
        raise ServiceMetadataError("command must not be empty")
    depends = _parse_depends(fields.get("depends", ""))
    return ServiceMetadata(name=name, command=command, depends=depends)


def parse_service_file(path: Path) -> ServiceMetadata:
    """Read and parse a service file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ServiceMetadataError(f"cannot read {path}: {exc}") from exc
    return parse_service_text(text)


def discover_services(directory: Path = DEFAULT_SERVICES_DIR) -> list[Path]:
    """Return ``.service`` files in ``directory`` in lexicographic order."""
    if not directory.exists() or not directory.is_dir():
        return []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    services = [
        p for p in entries if p.is_file() and p.suffix == ".service"
    ]
    services.sort(key=lambda p: p.name)
    return services
