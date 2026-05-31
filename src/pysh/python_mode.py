# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/python_mode.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Interactive Python Command Execution Layer for PySH.

Entered from the normal PySH prompt with:

    #py

Exited with:

    >>> #exit

See docs/python-command-execution-layer.md for the full specification.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import IO

from pysh.python_runtime import PythonRuntime

# ---------------------------------------------------------------------------
# Prompt strings
# ---------------------------------------------------------------------------
_PROMPT_PRIMARY = ">>> "
_PROMPT_CONTINUATION = "... "

# ---------------------------------------------------------------------------
# Internal sentinels returned by _dispatch_directive()
# ---------------------------------------------------------------------------
_DIRECTIVE_EXIT = object()     # signals the run-loop to exit Python mode
_DIRECTIVE_HANDLED = object()  # directive was recognised and handled (non-exit)
_DIRECTIVE_NOT_FOUND = object()  # line is not a directive at all

# ---------------------------------------------------------------------------
# Known directive tokens
# ---------------------------------------------------------------------------
_EXACT_DIRECTIVES: frozenset[str] = frozenset(
    {"#exit", "#help", "#show", "#run", "#reset"}
)
_FILE_DIRECTIVES: frozenset[str] = frozenset({"#open", "#save"})
_FORBIDDEN_DIRECTIVES: frozenset[str] = frozenset({"#echo"})


# ---------------------------------------------------------------------------
# Pure helper: TAB expansion
# ---------------------------------------------------------------------------

def expand_tab(line: str, cursor: int) -> tuple[str, int]:
    """Insert four spaces at *cursor* and return the updated (line, cursor).

    This is a pure function with no terminal dependency so it can be
    unit-tested without a real TTY.

    Example::

        >>> expand_tab("def f():", 8)
        ('def f():    ', 12)
    """
    new_line = line[:cursor] + "    " + line[cursor:]
    return new_line, cursor + 4


# ---------------------------------------------------------------------------
# Directive parsing
# ---------------------------------------------------------------------------

def _parse_directive(
    text: str,
) -> tuple[str, str | None, str | None] | None:
    """Parse *text* as a potential Python-mode directive.

    Returns one of:

    * ``(name, arg, None)``  — valid directive; *name* is the bare name
      (without ``#``), *arg* is the filename argument or ``None``.
    * ``(None, None, error_msg)`` — malformed or forbidden directive syntax.
    * ``None`` — *text* is not a directive at all (treat as Python source).

    Only exact supported patterns are recognised as directives. Everything
    else that starts with ``#`` remains normal Python source/comment.
    """
    stripped = text.strip()
    if not stripped.startswith("#"):
        return None

    parts = stripped.split(None, 1)
    token: str = parts[0]           # e.g. "#exit", "#open", "#save"
    rest: str = parts[1].strip() if len(parts) > 1 else ""

    if token in _EXACT_DIRECTIVES:
        # These directives take no arguments; extra trailing content is ignored
        # for user convenience (except that we still distinguish them from
        # Python comments by the exact token match).
        return (token[1:], None, None)

    if token in _FILE_DIRECTIVES:
        if not rest:
            return (None, None, f"usage: {token} <filename>")
        if ">" in rest or "<" in rest:
            return (
                None,
                None,
                f"{token}: shell redirection syntax is not supported; "
                f"use: {token} <filename>",
            )
        # Use only the first whitespace-delimited word as the filename.
        filename = rest.split()[0]
        return (token[1:], filename, None)

    if token in _FORBIDDEN_DIRECTIVES:
        return (
            None,
            None,
            f"{token}: not a supported directive; "
            "use Python's built-in print() or open() instead",
        )

    # Unknown hash-prefixed token — ordinary Python comment or code.
    return None


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PythonCommandMode:
    """Interactive Python Command Execution Layer for PySH.

    All I/O dependencies are injectable so the mode can be unit-tested
    without a real terminal or PTY.

    Parameters
    ----------
    runtime:
        The :class:`~pysh.python_runtime.PythonRuntime` instance to use.
        When *None* a fresh instance is created per session; its state is
        independent from the ``py`` builtin's runtime.
    input_source:
        An iterable of pre-supplied input lines used instead of ``input()``.
        Each element is one logical line (no trailing newline required).
        When exhausted, EOF / ``#exit`` semantics apply.
    out_stream:
        Destination for mode-level output (banners, help, ``#show``,
        ``opened:`` / ``saved:`` messages).  Defaults to ``sys.stdout``.
    err_stream:
        Destination for mode-level errors (directive errors, file errors).
        Defaults to ``sys.stderr``.  Python runtime exceptions are sent to
        the same stream when *runtime* is created internally.
    cwd_provider:
        Zero-argument callable returning the current :class:`~pathlib.Path`.
        Defaults to :func:`pathlib.Path.cwd`.
    """

    def __init__(
        self,
        *,
        runtime: PythonRuntime | None = None,
        input_source: Iterable[str] | None = None,
        out_stream: IO[str] | None = None,
        err_stream: IO[str] | None = None,
        cwd_provider: Callable[[], Path] | None = None,
    ) -> None:
        self._out: IO[str] = out_stream if out_stream is not None else sys.stdout
        self._err: IO[str] = err_stream if err_stream is not None else sys.stderr
        # Pass the same err_stream to the runtime so all error output is
        # captured by the same stream in tests.
        self._runtime: PythonRuntime = (
            runtime
            if runtime is not None
            else PythonRuntime(err_stream=self._err)
        )
        self._input_iter: Iterator[str] | None = (
            iter(input_source) if input_source is not None else None
        )
        self._cwd_provider: Callable[[], Path] = (
            cwd_provider if cwd_provider is not None else Path.cwd
        )
        # Source buffer — stores Python source lines only (no prompts,
        # no tracebacks, no directive lines).
        self._buffer: list[str] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the interactive Python command loop.

        Reads lines until the user types ``#exit`` or sends EOF at the
        primary prompt.  Returns 0.
        """
        self._print_banner()

        at_primary = True
        # Lines being accumulated for the current (possibly multi-line) block.
        pending: list[str] = []

        while True:
            try:
                line = self._read_line(at_primary)
            except EOFError:
                if at_primary:
                    # Ctrl+D at primary prompt → exit Python mode.
                    print("", file=self._out)
                    break
                # Ctrl+D during continuation → cancel incomplete block.
                print("", file=self._out)
                self._runtime.clear_input_buffer()
                pending.clear()
                at_primary = True
                continue
            except KeyboardInterrupt:
                print("", file=self._out)
                self._runtime.clear_input_buffer()
                pending.clear()
                at_primary = True
                continue

            # Directives are recognised only at the primary prompt.
            if at_primary:
                action = self._dispatch_directive(line)
                if action is _DIRECTIVE_EXIT:
                    break
                if action is _DIRECTIVE_HANDLED:
                    continue
                # _DIRECTIVE_NOT_FOUND → fall through to runtime execution.

            # Feed the line to the runtime.
            pending.append(line)
            try:
                more, status = self._runtime.push_interactive(line)
            except SystemExit:
                # sys.exit() from user code exits Python mode, not PySH.
                break
            except KeyboardInterrupt:
                print("", file=self._out)
                self._runtime.clear_input_buffer()
                pending.clear()
                at_primary = True
                continue

            if more:
                at_primary = False
            else:
                at_primary = True
                # Append real source lines to the buffer (skip blank-only blocks
                # and syntax-error lines).
                if status != 2 and any(ln.strip() for ln in pending):
                    self._buffer.extend(pending)
                pending.clear()

        return 0

    # ------------------------------------------------------------------
    # Directive dispatch
    # ------------------------------------------------------------------

    def _dispatch_directive(self, line: str) -> object:
        """Try to handle *line* as a Python-mode directive.

        Returns one of the three module-level sentinels:
        ``_DIRECTIVE_EXIT``, ``_DIRECTIVE_HANDLED``, ``_DIRECTIVE_NOT_FOUND``.
        """
        parsed = _parse_directive(line)
        if parsed is None:
            return _DIRECTIVE_NOT_FOUND

        name, arg, error = parsed

        if error is not None:
            print(f"pysh(py): {error}", file=self._err)
            return _DIRECTIVE_HANDLED

        if name == "exit":
            return _DIRECTIVE_EXIT
        if name == "help":
            self._print_help()
        elif name == "open":
            self._handle_open(arg)  # type: ignore[arg-type]
        elif name == "save":
            self._handle_save(arg)  # type: ignore[arg-type]
        elif name == "show":
            self._handle_show()
        elif name == "run":
            self._handle_run()
        elif name == "reset":
            self._handle_reset()

        return _DIRECTIVE_HANDLED

    # ------------------------------------------------------------------
    # Directive handlers
    # ------------------------------------------------------------------

    def _handle_open(self, filename: str) -> int:
        """Load *filename* into the source buffer without executing it."""
        path = self._cwd_provider() / filename
        if path.is_dir():
            print(f"pysh(py): #open: {filename}: is a directory", file=self._err)
            return 1
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"pysh(py): #open: {filename}: no such file", file=self._err)
            return 1
        except OSError as exc:
            print(f"pysh(py): #open: {filename}: {exc}", file=self._err)
            return 1
        self._buffer = content.splitlines()
        print(f"opened: {filename}", file=self._out)
        return 0

    def _handle_save(self, filename: str) -> int:
        """Write the source buffer to *filename* (UTF-8, trailing newline)."""
        path = self._cwd_provider() / filename
        if path.is_dir():
            print(f"pysh(py): #save: {filename}: is a directory", file=self._err)
            return 1
        source = "\n".join(self._buffer)
        # Always end with a newline even for an empty buffer.
        if not source.endswith("\n"):
            source += "\n"
        try:
            path.write_text(source, encoding="utf-8")
        except OSError as exc:
            print(f"pysh(py): #save: {filename}: {exc}", file=self._err)
            return 1
        print(f"saved: {filename}", file=self._out)
        return 0

    def _handle_show(self) -> None:
        """Print the source buffer with line numbers."""
        if not self._buffer:
            print("buffer empty", file=self._out)
            return
        for i, ln in enumerate(self._buffer, 1):
            print(f"{i} | {ln}", file=self._out)

    def _handle_run(self) -> int:
        """Execute the source buffer in the active runtime."""
        if not self._buffer:
            return 0
        source = "\n".join(self._buffer)
        try:
            return self._runtime.run_buffer(source)
        except SystemExit:
            return 0
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt", file=self._err)
            return 130

    def _handle_reset(self) -> None:
        """Clear the source buffer and recreate the runtime namespace."""
        self._buffer.clear()
        self._runtime.reset()

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _read_line(self, at_primary: bool) -> str:
        """Read one input line.

        When an ``input_source`` was injected (test mode), pulls from the
        iterator and raises ``EOFError`` on exhaustion.  Otherwise calls
        ``input()`` with the appropriate prompt.
        """
        prompt = _PROMPT_PRIMARY if at_primary else _PROMPT_CONTINUATION
        if self._input_iter is not None:
            try:
                return next(self._input_iter)
            except StopIteration:
                raise EOFError from None
        return input(prompt)

    def _print_banner(self) -> None:
        vi = sys.version_info
        print("PySH Python Command Execution Layer", file=self._out)
        print(f"Python {vi.major}.{vi.minor}.{vi.micro}", file=self._out)
        print("Type #help for commands.\n", file=self._out)

    def _print_help(self) -> None:
        help_text = (
            "Python Command Execution Layer — directives:\n"
            "\n"
            "  #exit           Exit Python command mode.\n"
            "  #help           Show this help.\n"
            "  #open <file>    Load a Python source file into the buffer.\n"
            "  #save <file>    Save the source buffer to a file.\n"
            "  #show           Display the source buffer with line numbers.\n"
            "  #run            Execute the source buffer.\n"
            "  #reset          Clear the buffer and reset the runtime.\n"
            "\n"
            "  TAB             Insert four spaces.\n"
            "  Ctrl+D          Exit (same as #exit).\n"
            "  Ctrl+C          Cancel current input.\n"
            "\n"
            "Normal Python code is executed interactively.\n"
            "Lines starting with # that are not exact directives are\n"
            "treated as Python comments.\n"
            "\n"
            "Clean file execution workflow:\n"
            "  #reset          (clear previous state)\n"
            "  #open main.py   (load source into buffer)\n"
            "  #run            (execute the buffer)\n"
        )
        print(help_text, file=self._out)
