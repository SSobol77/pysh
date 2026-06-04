# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Script runner for explicit interpreter delegation and native PySH scripts."""
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
BUILTIN_MISUSE_STATUS = 2


@dataclass(frozen=True)
class ScriptType:
    """Detected script execution mode."""

    interpreter: str | None
    shebang: str

    @property
    def is_native(self) -> bool:
        """Return whether the script has no supported shell shebang."""
        return self.interpreter is None


class ScriptExit(Exception):
    """Raised by the shell adapter when ``exit N`` terminates a script."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class ScriptRunner:
    """Run scripts through explicit interpreters or PySH's native line engine."""

    def __init__(
        self,
        execute_line: Callable[[str], int],
        *,
        interpreter_resolver: Callable[[str], str | None] | None = None,
        before_execute: Callable[[Path, int, str], None] | None = None,
    ) -> None:
        self._execute_line = execute_line
        self._before_execute = before_execute
        self._resolve_interpreter = (
            interpreter_resolver if interpreter_resolver is not None else shutil.which
        )

    def run(self, path: Path, args: list[str], *, native_only: bool = False) -> int:
        """Run ``path`` as a script and return its exit status.

        ``native_only`` is used by direct CLI script mode. It ignores any
        shebang as a PySH script header instead of delegating to that target.
        The ``run_script`` builtin leaves ``native_only`` false so its explicit
        transition-runner behavior for bash/sh/zsh shebangs is preserved.
        """
        try:
            script_type = detect_script_type(path)
        except FileNotFoundError:
            print(f"run_script: {path}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"run_script: {path}: {exc}", file=sys.stderr)
            return 1

        if script_type.interpreter is not None and not native_only:
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

        if lines and lines[0].startswith("#!"):
            lines = ["", *lines[1:]]

        try:
            logical_lines = list(iter_logical_lines(lines))
        except ValueError as exc:
            print(f"run_script: {path}: {exc}", file=sys.stderr)
            return BUILTIN_MISUSE_STATUS

        status = 0
        for line_number, raw_line in enumerate(logical_lines, start=1):
            result = self._dispatch_logical_line(raw_line, path=path, line_number=line_number)
            if result.stop:
                return result.status
            if result.executed:
                status = result.status
        return status

    def run_native_text(self, text: str, *, name: str = "<input>") -> int:
        """Run in-memory PySH text through the native logical-line engine."""
        lines = text.splitlines()
        try:
            logical_lines = list(iter_logical_lines(lines))
        except ValueError as exc:
            print(f"run_script: {name}: {exc}", file=sys.stderr)
            return BUILTIN_MISUSE_STATUS

        status = 0
        path = Path(name)
        for line_number, raw_line in enumerate(logical_lines, start=1):
            result = self._dispatch_logical_line(raw_line, path=path, line_number=line_number)
            if result.stop:
                return result.status
            if result.executed:
                status = result.status
        return status

    def _dispatch_logical_line(self, raw_line: str, *, path: Path, line_number: int) -> _LineResult:
        """Execute one logical line and report whether the script must stop."""
        if "\n" in raw_line and is_block_opener(raw_line.split("\n", 1)[0]):
            return self._execute_script_line(raw_line, path=path, line_number=line_number)
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return _LineResult(0, stop=False, executed=False)
        return self._execute_script_line(line, path=path, line_number=line_number)

    def _execute_script_line(self, line: str, *, path: Path, line_number: int) -> _LineResult:
        if self._before_execute is not None:
            self._before_execute(path, line_number, line)
        try:
            status = self._execute_line(line)
        except ScriptExit as exc:
            return _LineResult(exc.code, stop=True, executed=True)
        stop = status == BUILTIN_MISUSE_STATUS and not _line_has_error_operator(line)
        if stop:
            print(f"pysh: {path}:{line_number}: stopping script on status {status}", file=sys.stderr)
        return _LineResult(status, stop=stop, executed=True)


@dataclass(frozen=True)
class _LineResult:
    status: int
    stop: bool
    executed: bool


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
