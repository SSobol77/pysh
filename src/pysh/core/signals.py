# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/core/signals.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Signal-handling architecture module for PySH (Issue #6).

Deterministic, testable signal helpers used across execution contexts:
  - Line editor / interactive prompt
  - External command execution
  - Python runtime evaluation
  - Secure PTY runner

Rules:
- Standard library only.  No pysh implementation imports.
- No I/O at import time.
- No signal registration at import time.
- No filesystem or git probing at import time.
- All functions are pure and deterministic.
"""
from __future__ import annotations

import signal
from enum import IntEnum

# ---------------------------------------------------------------------------
# Context labels (documentation / logging only)
# ---------------------------------------------------------------------------


class SignalContext(str):
    """Named execution context constants for signal-handling documentation."""

    LINE_EDITOR = "line_editor"
    EXTERNAL_COMMAND = "external_command"
    PYTHON_RUNTIME = "python_runtime"
    SECURE_RUNNER = "secure_runner"


# ---------------------------------------------------------------------------
# Canonical signal disposition
# ---------------------------------------------------------------------------


class SignalDisposition(IntEnum):
    """Canonical signal numbers relevant to PySH execution contexts."""

    SIGINT = signal.SIGINT    # 2  – Ctrl+C / keyboard interrupt
    SIGTERM = signal.SIGTERM  # 15 – termination request


# ---------------------------------------------------------------------------
# Signal status helpers
# ---------------------------------------------------------------------------


def is_signal_returncode(returncode: int) -> bool:
    """Return True when *returncode* indicates signal termination.

    Python :class:`subprocess.Popen` returns a negative value when the child
    process was killed by a signal:  ``returncode == -signum``.
    """
    return returncode < 0


def returncode_to_exit_status(returncode: int) -> int:
    """Convert a :class:`subprocess.Popen` return code to a POSIX exit status.

    Python reports signal-killed children as negative return codes::

        -signal.SIGINT   (-2)  →  130  (128 + 2)
        -signal.SIGTERM  (-15) →  143  (128 + 15)

    Non-negative return codes are passed through unchanged (including 0).
    """
    if returncode < 0:
        return 128 + (-returncode)
    return returncode


def keyboard_interrupt_status() -> int:
    """Return the canonical PySH exit status for a SIGINT / Ctrl+C event (130)."""
    return 128 + signal.SIGINT


def signal_name(signum: int) -> str:
    """Return the canonical signal name string for *signum*.

    Returns ``'SIGINT'`` for 2, ``'SIGTERM'`` for 15, etc.
    Falls back to ``'SIG<N>'`` for unknown signal numbers.
    """
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"SIG{signum}"
