# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/parsing/ast.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
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
