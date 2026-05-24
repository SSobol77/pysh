# SPDX-License-Identifier: Apache-2.0
#
# Project: PYSH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/shell.py
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any


class PyShell:
    """Python-first interactive shell with Unix command fallback."""

    def __init__(self) -> None:
        self.namespace: dict[str, Any] = {
            "Path": Path,
            "os": os,
            "shlex": shlex,
            "subprocess": subprocess,
        }

    def run(self) -> int:
        """Start the interactive shell loop."""
        while True:
            try:
                line = input(self._prompt()).strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print()
                continue

            if not line:
                continue

            if line in {"exit", "quit"}:
                return 0

            status = self.execute(line)
            if status != 0:
                self.namespace["_status"] = status

    def execute(self, line: str) -> int:
        """Execute one shell line."""
        if line.startswith(":"):
            return self._run_python(line[1:].strip())

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"pysh: parse error: {exc}")
            return 2

        if not parts:
            return 0

        if parts[0] == "cd":
            return self._cd(parts[1:])

        return self._run_external(line)

    def _prompt(self) -> str:
        """Build the interactive prompt."""
        cwd = Path.cwd()
        return f"pysh:{cwd}$ "

    def _cd(self, args: list[str]) -> int:
        """Change current working directory."""
        target = args[0] if args else str(Path.home())
        target = os.path.expanduser(target)

        try:
            os.chdir(target)
            return 0
        except OSError as exc:
            print(f"cd: {exc}")
            return 1

    def _run_python(self, code: str) -> int:
        """Run Python code inside a persistent namespace."""
        try:
            result = eval(code, self.namespace)
            if result is not None:
                print(repr(result))
            return 0
        except SyntaxError:
            try:
                exec(code, self.namespace)
                return 0
            except Exception as exc:
                print(f"pysh: {type(exc).__name__}: {exc}")
                return 1
        except Exception as exc:
            print(f"pysh: {type(exc).__name__}: {exc}")
            return 1

    def _run_external(self, command: str) -> int:
        """Run an external Unix command."""
        try:
            return subprocess.call(command, shell=True)
        except KeyboardInterrupt:
            print()
            return 130
