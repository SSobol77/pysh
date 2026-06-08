# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/core/errors.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical error and exit-code module for PySH (Issue #5).

Rules:
- Standard library only.  No pysh implementation imports.
- No I/O at import time.
- No printing from this module.
- All values are deterministic and testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

# ---------------------------------------------------------------------------
# Canonical exit codes
# ---------------------------------------------------------------------------


class ExitCode(IntEnum):
    """Canonical PySH exit-code enumeration.

    These values map to the POSIX shell convention used by PySH:

    - 0    success
    - 1    general runtime error
    - 2    builtin/command usage error (wrong arguments, unknown option)
    - 126  command found but cannot be executed (permission denied)
    - 127  command not found in PATH
    - 128  base for signal-termination codes (``128 + signum``)
    - 130  interrupted by SIGINT (``128 + 2``)
    """

    SUCCESS = 0
    GENERAL_ERROR = 1
    BUILTIN_MISUSE = 2
    CANNOT_EXECUTE = 126
    COMMAND_NOT_FOUND = 127
    SIGNAL_BASE = 128
    SIGINT = 130


def signal_exit_code(signum: int) -> int:
    """Return the conventional exit code for termination by *signum*.

    Maps to ``128 + signum`` per POSIX convention.
    ``signal_exit_code(2)`` returns 130 (SIGINT).
    """
    return ExitCode.SIGNAL_BASE + signum


# ---------------------------------------------------------------------------
# Structured exception taxonomy
# ---------------------------------------------------------------------------


class PyShError(Exception):
    """Base class for all PySH-raised errors.

    Carries an *exit_code* so callers can convert to an integer status
    without pattern-matching on exception type.
    """

    def __init__(self, message: str, exit_code: int = ExitCode.GENERAL_ERROR) -> None:
        super().__init__(message)
        self.exit_code: int = exit_code


class CommandNotFoundError(PyShError):
    """Raised when a command cannot be located in PATH (exit code 127)."""

    def __init__(self, command: str) -> None:
        super().__init__(f"{command}: command not found", ExitCode.COMMAND_NOT_FOUND)
        self.command: str = command


class CommandNotExecutableError(PyShError):
    """Raised when a command exists but cannot be executed (exit code 126)."""

    def __init__(self, command: str, detail: str = "") -> None:
        msg = f"{command}: {detail}" if detail else f"{command}: permission denied"
        super().__init__(msg, ExitCode.CANNOT_EXECUTE)
        self.command: str = command


class BuiltinUsageError(PyShError):
    """Raised when a builtin is called with invalid arguments (exit code 2)."""

    def __init__(self, builtin: str, detail: str = "") -> None:
        msg = f"{builtin}: {detail}" if detail else f"{builtin}: usage error"
        super().__init__(msg, ExitCode.BUILTIN_MISUSE)
        self.builtin: str = builtin


class PyShParseError(PyShError):
    """Raised on a shell syntax or parse error (exit code 2).

    Distinct from Python ``SyntaxError``.  Maps to BUILTIN_MISUSE (2)
    because parse errors in an interactive shell are equivalent to command
    misuse from the exit-code perspective.
    """

    def __init__(self, detail: str = "") -> None:
        msg = f"parse error: {detail}" if detail else "parse error"
        super().__init__(msg, ExitCode.BUILTIN_MISUSE)


class ExecutionError(PyShError):
    """Generic execution-level error with a caller-supplied exit code."""

    def __init__(self, message: str, exit_code: int = ExitCode.GENERAL_ERROR) -> None:
        super().__init__(message, exit_code)


class PyShInterruptedError(PyShError):
    """Raised when a command is interrupted by SIGINT (exit code 130)."""

    def __init__(self, message: str = "interrupted") -> None:
        super().__init__(message, ExitCode.SIGINT)


# ---------------------------------------------------------------------------
# Diagnostic: stderr-formatted error record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Diagnostic:
    """Immutable record pairing a human-readable message with an exit code.

    Produced by :func:`exception_to_diagnostic` and consumed by the CLI
    boundary to write to stderr and determine the process exit status.
    """

    message: str
    exit_code: int
    prefix: str = field(default="pysh")

    def format_stderr(self) -> str:
        """Return the canonical ``pysh: <message>`` stderr line."""
        return f"{self.prefix}: {self.message}"


# ---------------------------------------------------------------------------
# Boundary functions
# ---------------------------------------------------------------------------


def exception_to_diagnostic(exc: BaseException) -> Diagnostic:
    """Convert any exception to a :class:`Diagnostic` without leaking tracebacks.

    Mapping rules (first match wins):

    - :class:`PyShError` subclasses: use ``exc.exit_code`` and ``str(exc)``.
    - :class:`KeyboardInterrupt`: exit code 130 (SIGINT).
    - :class:`FileNotFoundError`: exit code 127 (command not found).
    - :class:`PermissionError`: exit code 126 (cannot execute).
    - Any other exception: exit code 1 (general error); message is
      ``str(exc)`` or ``"internal error"`` if empty.

    This function never re-raises and never performs I/O.
    """
    if isinstance(exc, PyShError):
        return Diagnostic(message=str(exc), exit_code=exc.exit_code)
    if isinstance(exc, KeyboardInterrupt):
        return Diagnostic(message="interrupted", exit_code=ExitCode.SIGINT)
    if isinstance(exc, FileNotFoundError):
        cmd = exc.filename or str(exc)
        return Diagnostic(
            message=f"{cmd}: command not found",
            exit_code=ExitCode.COMMAND_NOT_FOUND,
        )
    if isinstance(exc, PermissionError):
        cmd = exc.filename or str(exc)
        return Diagnostic(
            message=f"{cmd}: permission denied",
            exit_code=ExitCode.CANNOT_EXECUTE,
        )
    msg = str(exc).strip() or "internal error"
    return Diagnostic(message=msg, exit_code=ExitCode.GENERAL_ERROR)


def diagnostic_to_exit_code(diagnostic: Diagnostic) -> int:
    """Extract the integer exit code from a :class:`Diagnostic`."""
    return diagnostic.exit_code
