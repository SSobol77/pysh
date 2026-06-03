# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/script_runner.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Script transition runner for legacy shell scripts and native PySH scripts."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pysh.parsing.multiline import is_block_opener, iter_logical_lines
from pysh.parsing.parser import ChainOp, split_chain

SUPPORTED_INTERPRETERS = frozenset({"zsh", "bash", "sh"})


@dataclass(frozen=True)
class ScriptType:
    """Detected script execution mode."""

    interpreter: str | None
    shebang: str

    @property
    def is_native(self) -> bool:
        """Return whether the script has no supported shell shebang."""
        return self.interpreter is None


class ScriptRunner:
    """Run scripts through explicit interpreters or PySH's native line engine."""

    def __init__(
        self,
        execute_line: Callable[[str], int],
        *,
        interpreter_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._execute_line = execute_line
        self._resolve_interpreter = (
            interpreter_resolver if interpreter_resolver is not None else shutil.which
        )

    def run(self, path: Path, args: list[str]) -> int:
        """Run ``path`` as a transition script and return its exit status."""
        try:
            script_type = detect_script_type(path)
        except FileNotFoundError:
            print(f"run_script: {path}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"run_script: {path}: {exc}", file=sys.stderr)
            return 1

        if script_type.interpreter is not None:
            return self._run_interpreter_script(script_type.interpreter, path, args)
        return self._run_native_script(path)

    def _run_interpreter_script(self, interpreter: str, path: Path, args: list[str]) -> int:
        executable = self._resolve_interpreter(interpreter)
        if executable is None:
            print(f"pysh: run_script: {interpreter}: command not found", file=sys.stderr)
            return 127
        argv = [executable, str(path), *args]
        try:
            proc = subprocess.Popen(argv)  # noqa: S603 - explicit transition interpreter
        except FileNotFoundError:
            print(f"pysh: run_script: {interpreter}: command not found", file=sys.stderr)
            return 127
        except PermissionError as exc:
            print(f"pysh: run_script: {interpreter}: {exc}", file=sys.stderr)
            return 126
        except OSError as exc:
            print(f"pysh: run_script: {interpreter}: {exc}", file=sys.stderr)
            return 1
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            return 130

    def _run_native_script(self, path: Path) -> int:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            print(f"run_script: {path}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"run_script: {path}: {exc}", file=sys.stderr)
            return 1

        try:
            logical_lines = list(iter_logical_lines(lines))
        except ValueError as exc:
            print(f"run_script: {path}: {exc}", file=sys.stderr)
            return 1

        for raw_line in logical_lines:
            status = self._dispatch_logical_line(raw_line)
            if status is not None:
                return status
        return 0

    def _dispatch_logical_line(self, raw_line: str) -> int | None:
        """Execute one logical line. Return non-None to abort the script."""
        if "\n" in raw_line and is_block_opener(raw_line.split("\n", 1)[0]):
            status = self._execute_line(raw_line)
            return status if status != 0 else None
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return None
        status = self._execute_line(line)
        if status != 0 and not _line_has_error_operator(line):
            return status
        return None


def detect_script_type(path: Path) -> ScriptType:
    """Detect whether ``path`` declares zsh, bash, sh, or native PySH mode."""
    with path.open("rb") as script:
        first_line = script.readline(4096).decode("utf-8", errors="replace").rstrip("\r\n")
    if not first_line.startswith("#!"):
        return ScriptType(None, "")

    shebang = first_line[2:].strip()
    try:
        parts = shlex.split(shebang, posix=True)
    except ValueError:
        return ScriptType(None, shebang)
    if not parts:
        return ScriptType(None, shebang)

    command = Path(parts[0]).name
    if command == "env":
        interpreter = _interpreter_from_env_shebang(parts[1:])
    else:
        interpreter = command
    if interpreter in SUPPORTED_INTERPRETERS:
        return ScriptType(interpreter, shebang)
    return ScriptType(None, shebang)


def _interpreter_from_env_shebang(parts: list[str]) -> str | None:
    for part in parts:
        if part.startswith("-"):
            continue
        name = Path(part).name
        if name in SUPPORTED_INTERPRETERS:
            return name
        return None
    return None


def _line_has_error_operator(line: str) -> bool:
    try:
        chain = split_chain(line)
    except ValueError:
        return False
    return any(element.operator in {ChainOp.AND, ChainOp.OR} for element in chain)
