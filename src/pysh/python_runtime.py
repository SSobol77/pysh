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
"""Persistent Python runtime used by the ``py`` builtin.

The runtime executes Python source in one shared globals namespace so that
variables and imports introduced by one ``py`` invocation are visible to the
next. Both the one-line form ``py <code>`` and the multiline block form

    py {
        ...
    }

share the same execution context.
"""
from __future__ import annotations

import sys
import textwrap
import traceback
from collections.abc import Iterable, Iterator
from types import CodeType

PY_BLOCK_OPENER = "py {"
PY_BLOCK_CLOSER = "}"


class UnterminatedBlockError(ValueError):
    """Raised when a multiline ``py { ... }`` block is never closed."""


class NestedBlockError(ValueError):
    """Raised when a nested ``py { ... }`` block opener is encountered."""


class PythonRuntime:
    """A persistent one-session Python execution context."""

    def __init__(self) -> None:
        self.globals: dict[str, object] = {
            "__builtins__": __builtins__,
            "__name__": "__pysh__",
        }

    def execute(self, code: str) -> int:
        """Execute Python ``code`` and return a shell-style status."""
        if not code.strip():
            return 0
        try:
            compiled = compile(code, "<pysh-py>", "exec")
        except SyntaxError as exc:
            _print_exception_only(exc)
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
        except Exception as exc:  # noqa: BLE001 - shell builtin must contain user exceptions
            _print_exception_only(exc)
            return 1
        return 0


def is_block_opener(line: str) -> bool:
    """Return True if ``line`` opens a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_OPENER


def is_block_closer(line: str) -> bool:
    """Return True if ``line`` closes a multiline ``py { ... }`` block."""
    return _strip_trailing_comment(line.strip()) == PY_BLOCK_CLOSER


def iter_logical_lines(lines: Iterable[str]) -> Iterator[str]:
    """Yield logical command strings from a stream of physical lines.

    Each yielded string is either a single physical line, or, when a
    ``py { ... }`` block is encountered, the joined contents of the block
    (opener ``py {``, the body lines, and the closing ``}``) preserved
    verbatim and separated by ``\\n``.

    Raises :class:`UnterminatedBlockError` if a block opener is never
    matched by a closer, and :class:`NestedBlockError` if a second opener
    appears inside an open block.
    """
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
            raise NestedBlockError(
                "nested py { ... } block is not supported"
            )
        state.append(line)
        if is_block_closer(line):
            yield "\n".join(state)
            state = None
    if state is not None:
        raise UnterminatedBlockError(
            "unterminated py { ... } block (missing '}')"
        )


def extract_block_body(text: str) -> str:
    """Return the inner body of a multi-line ``py { ... }`` block text.

    ``text`` must consist of a ``py {`` opener line, zero or more body
    lines, and a closing ``}`` line. The leading and trailing markers are
    stripped and the body is returned with original indentation preserved.
    """
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


def _print_exception_only(exc: BaseException) -> None:
    for line in traceback.format_exception_only(type(exc), exc):
        print(line, end="", file=sys.stderr)
