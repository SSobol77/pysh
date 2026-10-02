# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/repro.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical, deterministic failure formatting for generated and corpus inputs."""
from __future__ import annotations

from dataclasses import dataclass


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
        f"  input:      {ascii(reproduction.text)}",
        f"  input_hex:  {encoded}",
        f"  detail:     {reproduction.detail}",
        "  decode:     tests.fuzz_support.repro.decode_text(input_hex)",
    ]
    replay = _REPLAY.get(reproduction.source)
    if replay is not None and reproduction.seed is not None:
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
