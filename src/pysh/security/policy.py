# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/security/policy.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Security and trust model constants for PySH (Issue #7).

Defines the canonical trust categories, execution modes, and security
boundaries that govern PySH's runtime behavior.

Rules:
- Standard library only.  No pysh implementation imports.
- No terminal I/O at import time.
- No subprocess calls.
- No filesystem probing at import time.
- No config loading at import time.
- All values are deterministic and testable.
"""
from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Trust levels
# ---------------------------------------------------------------------------


class TrustLevel(StrEnum):
    """Canonical trust categories for PySH execution surfaces.

    TRUSTED_LOCAL      Local user-owned PySH configuration and code that runs
                       in-process and is not sandboxed.  This includes
                       ~/.pyshrc, ~/.pyshrc.py, and ~/.pyshrc.d/*.pysh.

    TRUSTED_DELEGATED  Explicit user delegation to an external interpreter.
                       The delegation command is user-issued.  Examples:
                       ``zsh <command>``, ``run_script``, ``zsh_fallback on``.

    STATIC_IMPORT      Read-only text parse of a foreign profile file.  No
                       shell code is executed.  Examples: source_zsh,
                       source_zsh_profile, source_sh_aliases, compat_check.

    UNTRUSTED          Not a supported execution mode in current PySH.
                       Automatic execution of foreign profiles or untrusted
                       code is not supported and not documented as supported.
    """

    TRUSTED_LOCAL = "trusted_local"
    TRUSTED_DELEGATED = "trusted_delegated"
    STATIC_IMPORT = "static_import"
    UNTRUSTED = "untrusted"


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


class ExecutionMode(StrEnum):
    """Execution modes for PySH command surfaces."""

    IN_PROCESS = "in_process"      # Python code runs inside PySH process
    SUBPROCESS = "subprocess"      # child inherits terminal via Popen
    PTY_BRIDGE = "pty_bridge"      # explicit PTY (secure <cmd> only)
    STATIC_READ = "static_read"    # text parse only — no subprocess
    NONE = "none"                  # advisory only — nothing runs


# ---------------------------------------------------------------------------
# Security boundaries
# ---------------------------------------------------------------------------


class SecurityBoundary(StrEnum):
    """Security boundary for each PySH execution path."""

    TERMINAL_INHERITED = "terminal_inherited"  # normal external command
    PTY_BRIDGED = "pty_bridged"               # secure <cmd> explicit PTY
    IN_PROCESS_EXEC = "in_process_exec"       # py / ~/.pyshrc.py
    STATIC_PARSE = "static_parse"             # source_zsh / compat_check
    NONE = "none"                             # plan / env_audit (advisory)


# ---------------------------------------------------------------------------
# Trust policy predicates
# ---------------------------------------------------------------------------


def is_foreign_profile_execution_forbidden_by_default() -> bool:
    """Return True: automatic execution of foreign shell profiles is forbidden.

    PySH's static importers (source_zsh, source_zsh_profile,
    source_sh_aliases) parse foreign profile files as plain text and extract
    only safe static constructs (aliases, exports, simple assignments).  They
    never execute the file as shell code.

    Any future feature that executes .zshrc, .bashrc, .profile, or equivalent
    must require explicit opt-in and must be documented as delegated/untrusted
    execution.  This predicate is the machine-checkable contract for that rule.
    """
    return True


def is_pty_bridge_opt_in() -> bool:
    """Return True: PTY bridge execution (secure <cmd>) requires explicit user invocation.

    Normal external commands inherit the terminal without a PTY bridge.
    The PTY bridge is only created when the user explicitly invokes
    ``secure <cmd>``.  This predicate is the contract for that rule.
    """
    return True


def is_python_runtime_sandboxed() -> bool:
    """Return False: the Python runtime (py, py { ... }, #py) is not sandboxed.

    Python code executed via PySH builtins runs in-process with full access
    to the Python interpreter, stdlib, and the OS.  PySH does not apply any
    sandboxing, import filtering, capability restriction, or privilege
    separation.  Callers must not rely on PySH to contain arbitrary Python.
    """
    return False
