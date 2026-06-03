# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Small parser data structures shared by PySH parsing modules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChainOp(StrEnum):
    """Operator joining a command to the next one in a command chain."""

    SEMI = ";"
    AND = "&&"
    OR = "||"


@dataclass(frozen=True)
class ChainElement:
    """Single command in a chain with the operator that follows it."""

    command: str
    operator: ChainOp | None
