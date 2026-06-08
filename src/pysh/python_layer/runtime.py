# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/python_layer/runtime.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Persistent Python runtime used by the ``py`` builtin and Python command mode.

The runtime executes Python source in one shared globals namespace so that
variables and imports introduced by one ``py`` invocation are visible to the
next. Both the one-line form ``py <code>`` and the multiline block form

    py {
        ...
    }

share the same execution context (``self.globals``).

Python command mode (``#py``) uses a second, separate namespace
(``self._cmd_globals``) seeded with ``__name__ == "__main__"`` semantics.
The two namespaces are intentionally independent so that ``py`` builtin state
does not leak into the interactive Python command session and vice-versa.
"""
from __future__ import annotations

import builtins as _builtins_module
import codeop
import sys
import textwrap
import traceback
from collections.abc import Callable, Iterable, Iterator
from types import CodeType
from typing import IO

PY_BLOCK_OPENER = "py {"
PY_BLOCK_CLOSER = "}"


class UnterminatedBlockError(ValueError):
    """Raised when a multiline ``py { ... }`` block is never closed."""


class NestedBlockError(ValueError):
    """Raised when a nested ``py { ... }`` block opener is encountered."""

__all__ = [
    "NestedBlockError",
    "PY_BLOCK_CLOSER",
    "PY_BLOCK_OPENER",
    "PythonRuntime",
    "UnterminatedBlockError",
    "extract_block_body",
    "is_block_closer",
    "is_block_opener",
    "iter_logical_lines",
]


class PythonRuntime:
    """A persistent one-session Python execution context.

    ``self.globals`` is used by the ``py`` builtin (``execute`` /
    ``execute_block``).  ``self._cmd_globals`` is used exclusively by Python
    command mode (``push_interactive`` / ``run_buffer`` / ``reset``).

    Both namespaces survive across invocations and are independent of each
    other. ``reset()`` recreates ``_cmd_globals`` only.
    """

    def __init__(
        self,
        *,
        err_stream: IO[str] | None = None,
        error_renderer: Callable[[str], str] | None = None,
    ) -> None:
        # err_stream lets callers (e.g. PythonCommandMode) inject a test stream.
        # Defaults to sys.stderr so existing behaviour is unchanged.
        self._err: IO[str] = err_stream if err_stream is not None else sys.stderr
        self._error_renderer = error_renderer

        # Namespace for the ``py`` builtin — unchanged from the original.
        self.globals: dict[str, object] = {
            "__builtins__": __builtins__,
            "__name__": "__pysh__",
        }

        # Separate namespace for Python command mode.
        self._cmd_globals: dict[str, object] = {
            "__builtins__": _builtins_module,
            "__name__": "__main__",
        }

        # Accumulation buffer for incomplete interactive input units.
        self._interactive_buffer: list[str] = []

    # ------------------------------------------------------------------
    # Existing py-builtin execution paths — behaviour unchanged.
    # ------------------------------------------------------------------

    def execute(self, code: str) -> int:
        """Execute Python ``code`` and return a shell-style status."""
        if not code.strip():
            return 0
        try:
            compiled = compile(code, "<pysh-py>", "exec")
        except SyntaxError as exc:
            _print_exc_to(exc, self._err, self._error_renderer)
            return 1
        return self._execute_compiled(compiled)

    def execute_block(self, source: str) -> int:
        """Execute a multiline ``py { ... }`` block body.

        ``source`` is the raw text between the opening ``py {`` line and the
        closing ``}`` line. Leading common indentation is removed so that
        block bodies can be indented inside scripts and rc files.
        """
        if not source.strip():
            return 0
        dedented = textwrap.dedent(source)
        return self.execute(dedented)

    def _execute_compiled(self, compiled: CodeType) -> int:
        try:
            exec(compiled, self.globals, self.globals)
        except KeyboardInterrupt:
            # SIGINT (128 + 2 = 130) — no traceback for normal Ctrl+C.
            return 130
        except Exception as exc:  # noqa: BLE001 - shell builtin must contain user exceptions
            _print_exc_to(exc, self._err, self._error_renderer)
            return 1
        return 0

    # ------------------------------------------------------------------
    # Python command mode execution paths (push_interactive / run_buffer).
    # ------------------------------------------------------------------

    def push_interactive(self, line: str) -> tuple[bool, int]:
        """Feed one interactive input line into the Python runtime.

        Uses ``codeop.compile_command`` with ``symbol="single"`` so that
        top-level expression results are displayed through ``sys.displayhook``
        (matching normal interactive-Python behaviour).

        Returns:
            (more, status) where

            more:
                True  — current input unit is incomplete; caller must show the
                         continuation prompt and call ``push_interactive`` again.
                False — current unit is complete and has been compiled/executed.

            status:
                0 — success (or incomplete, when more=True)
                1 — uncaught runtime exception
                2 — syntax error
        """
        self._interactive_buffer.append(line)
        source = "\n".join(self._interactive_buffer)
        try:
            code = codeop.compile_command(source, filename="<pysh-python>", symbol="single")
        except SyntaxError as exc:
            self._interactive_buffer.clear()
            _print_exc_to(exc, self._err, self._error_renderer)
            return (False, 2)
        if code is None:
            # Incomplete input — more lines needed.
            return (True, 0)
        # Complete input — execute.
        self._interactive_buffer.clear()
        try:
            exec(code, self._cmd_globals)  # noqa: S102 - intentional user exec
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - user code exceptions are expected
            _print_exc_to(exc, self._err, self._error_renderer)
            return (False, 1)
        return (False, 0)

    def run_buffer(self, source: str) -> int:
        """Execute a complete source buffer with module-style exec semantics.

        Used by the ``#run`` directive. Expression results are *not* echoed
        (``"exec"`` mode, not ``"single"`` mode). ``__name__`` is ``"__main__"``
        so guard clauses work as expected.

        Returns:
            0 — success
            1 — uncaught runtime exception
            2 — syntax error
        """
        if not source.strip():
            return 0
        try:
            code = compile(source, "<pysh-buffer>", "exec")
        except SyntaxError as exc:
            _print_exc_to(exc, self._err, self._error_renderer)
            return 2
        try:
            exec(code, self._cmd_globals)  # noqa: S102 - intentional user exec
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - user code exceptions are expected
            _print_exc_to(exc, self._err)
            return 1
        return 0

    def reset(self) -> None:
        """Reset the Python command mode workspace.

        Recreates ``_cmd_globals`` with clean ``__main__`` semantics and clears
        the interactive input accumulation buffer. Does *not* touch
        ``self.globals`` (the ``py`` builtin namespace).
        """
        self._cmd_globals = {
            "__builtins__": _builtins_module,
            "__name__": "__main__",
        }
        self._interactive_buffer.clear()

    def clear_input_buffer(self) -> None:
        """Discard any partially accumulated interactive input without resetting globals."""
        self._interactive_buffer.clear()


def is_block_opener(line: str) -> bool:
    """Return True if ``line`` opens a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_OPENER


def is_block_closer(line: str) -> bool:
    """Return True if ``line`` closes a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_CLOSER


def iter_logical_lines(lines: Iterable[str]) -> Iterator[str]:
    """Yield logical command strings from a stream of physical lines."""
    state: list[str] | None = None
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        if state is None:
            if is_block_opener(line):
                state = [line]
            else:
                yield line
            continue
        if is_block_opener(line):
            raise NestedBlockError("nested py { ... } block is not supported")
        state.append(line)
        if is_block_closer(line):
            yield "\n".join(state)
            state = None
    if state is not None:
        raise UnterminatedBlockError("unterminated py { ... } block (missing '}')")


def extract_block_body(text: str) -> str:
    """Return the inner body of a multi-line ``py { ... }`` block text."""
    physical = text.split("\n")
    if len(physical) < 2 or not is_block_opener(physical[0]):
        raise ValueError("text does not start with a py { opener")
    if not is_block_closer(physical[-1]):
        raise ValueError("text does not end with a } closer")
    body = physical[1:-1]
    return "\n".join(body)


def _strip_trailing_comment(text: str) -> str:
    """Strip a trailing ``# ...`` comment outside of any string literal."""
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
        elif c == "#":
            return text[:i].rstrip()
        i += 1
    return text.rstrip()


def _print_exc_to(
    exc: BaseException,
    stream: IO[str],
    renderer: Callable[[str], str] | None = None,
) -> None:
    """Print the exception type and message to *stream* without a traceback."""
    text = "".join(traceback.format_exception_only(type(exc), exc))
    if renderer is not None:
        text = renderer(text)
    print(text, end="" if text.endswith("\n") else "\n", file=stream)


def _print_exception_only(exc: BaseException) -> None:
    """Backward-compatible wrapper that prints to ``sys.stderr``."""
    _print_exc_to(exc, sys.stderr)
