# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/mc_compat.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Midnight Commander compatibility helpers.

Midnight Commander (mc) sets several environment variables in its subshell
environment.  PySH detects these to enable mc-safe mode, which disables
the raw-mode line editor's cursor-repositioning redraws.  This prevents
the cursor-placement corruption that occurs when mc manages the terminal
and PySH tries to rewrite the prompt line with ANSI cursor-up sequences.
"""
from __future__ import annotations

import os

_MC_ENV_VARS: tuple[str, ...] = (
    "MC_TMPDIR",
    "MC_SID",
    "MC_CONTROL_FILE",
    "MC_CONTROL_FILE_NAME",
)


def is_mc_environment() -> bool:
    """Return True when PySH is running as a subshell inside Midnight Commander.

    Midnight Commander exports at least one of the variables in
    ``_MC_ENV_VARS`` before starting its subshell.  Any non-empty value is
    sufficient for detection.
    """
    return any(os.environ.get(var) for var in _MC_ENV_VARS)
