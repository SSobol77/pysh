# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/repro.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical, deterministic failure formatting for generated and corpus inputs."""
from __future__ import annotations

import hashlib
import os
import platform
import traceback
from dataclasses import dataclass
from importlib import metadata


def encode_text(text: str) -> str:
    """Return lossless hex for any ``str``, including NUL and lone surrogates."""
    return text.encode("utf-8", "surrogatepass").hex()


def decode_text(encoded: str) -> str:
    """Invert :func:`encode_text`."""
    return bytes.fromhex(encoded).decode("utf-8", "surrogatepass")


@dataclass(frozen=True, slots=True)
class Reproduction:
    """Everything needed to rebuild one failing case locally."""

    target: str
    property_name: str
    text: str
    # "generated" | "generated:quoted" | "generated:argv" | "mutated:<case-id>" | "corpus:<case-id>"
    source: str
    seed: int | None = None
    iteration: int | None = None
    generator_version: str | None = None
    detail: str = ""
    engine: str = "stdlib"
    exception_type: str | None = None
    exception_message: str | None = None
    traceback_fingerprint: str | None = None
    replay_command: str | None = None


def input_sha256(text: str) -> str:
    """SHA-256 of the canonical (surrogatepass UTF-8) bytes of ``text``."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def traceback_fingerprint(error: BaseException) -> str:
    """Stable 16-hex fingerprint of an exception's type and call chain.

    Uses only file basenames and function names (never absolute paths, line
    text, or environment), so the same defect fingerprints identically across
    machines and checkouts.
    """
    frames = [
        f"{os.path.basename(frame.filename)}:{frame.name}"
        for frame in traceback.extract_tb(error.__traceback__)
    ]
    material = "\n".join([type(error).__name__, *frames])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _pysh_version() -> str:
    try:
        return metadata.version("pysh-shell")
    except metadata.PackageNotFoundError:
        return "unknown"


class PropertyFailure(AssertionError):
    """A property violation carrying its :class:`Reproduction`."""

    def __init__(self, reproduction: Reproduction) -> None:
        super().__init__(format_failure(reproduction))
        self.reproduction = reproduction


def format_failure(reproduction: Reproduction) -> str:
    """Render one stable, copy-pasteable failure report (no files are written)."""
    encoded = encode_text(reproduction.text)
    lines = [
        "FUZZ PROPERTY FAILURE",
        f"  target:     {reproduction.target}",
        f"  property:   {reproduction.property_name}",
        f"  source:     {reproduction.source}",
        f"  seed:       {reproduction.seed}",
        f"  iteration:  {reproduction.iteration}",
        f"  generator:  {reproduction.generator_version}",
        f"  engine:     {reproduction.engine}",
        f"  input:      {ascii(reproduction.text)}",
        f"  input_hex:  {encoded}",
        f"  input_sha256: {input_sha256(reproduction.text)}",
        f"  python:     {platform.python_version()}",
        f"  platform:   {platform.system()} {platform.machine()}",
        f"  pysh:       {_pysh_version()}",
        f"  exception:  {reproduction.exception_type}: {reproduction.exception_message}",
        f"  traceback:  {reproduction.traceback_fingerprint}",
        f"  detail:     {reproduction.detail}",
        "  decode:     tests.fuzz_support.repro.decode_text(input_hex)",
    ]
    if reproduction.replay_command is not None:
        lines.append(f"  replay:     {reproduction.replay_command}")
    replay = _REPLAY.get(reproduction.source)
    if reproduction.replay_command is None and replay is not None and reproduction.seed is not None:
        lines.append(
            f"  replay:     tests.fuzz_support.engines.{replay}"
            f"({reproduction.seed}, {reproduction.iteration})"
        )
    return "\n".join(lines)


_REPLAY = {
    "generated": "case_at",
    "generated:quoted": "quoted_operator_line_at",
    "generated:argv": "argv_case_at",
}
