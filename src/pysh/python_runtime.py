# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/python_runtime.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Persistent Python runtime used by the ``py`` builtin."""
from __future__ import annotations

import sys
import traceback
from types import CodeType


class PythonRuntime:
    """A persistent one-session Python execution context."""

    def __init__(self) -> None:
        self.globals: dict[str, object] = {
            "__builtins__": __builtins__,
            "__name__": "__pysh__",
        }

    def execute(self, code: str) -> int:
        """Execute one line of Python code and return a shell-style status."""
        try:
            compiled = compile(code, "<pysh-py>", "exec")
        except SyntaxError as exc:
            _print_exception_only(exc)
            return 1
        return self._execute_compiled(compiled)

    def _execute_compiled(self, compiled: CodeType) -> int:
        try:
            exec(compiled, self.globals, self.globals)
        except Exception as exc:  # noqa: BLE001 - shell builtin must contain user exceptions
            _print_exception_only(exc)
            return 1
        return 0


def _print_exception_only(exc: BaseException) -> None:
    for line in traceback.format_exception_only(type(exc), exc):
        print(line, end="", file=sys.stderr)
