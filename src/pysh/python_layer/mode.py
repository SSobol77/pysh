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

Entered from the normal PySH prompt with::

    #py

Exited with::

    >>> #exit

The mode maintains an *active edit workspace* consisting of:

* ``_buffer``      — Python source text (list of lines).
* ``_active_file`` — the resolved :class:`~pathlib.Path` of the file most
  recently opened or saved, or ``None``.
* ``_edit_mode``   — ``True`` when a file has been opened and is active for
  editing; cleared by ``#reset``.
* ``_runtime``     — a :class:`~pysh.python_layer.runtime.PythonRuntime` instance
  that holds the persistent ``__main__`` namespace for the session.

After ``#open file.py``, PySH enters file-backed edit mode.  The prompt
changes to ``[file.py:edit] >>> `` to reflect the active file.

See docs/python-command-execution-layer.md for the full specification.
"""
from __future__ import annotations

import codeop
import os
import re
import sys
import termios
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import IO

from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.completion import CompletionResult, apply_single_completion
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.reader import RawLineReader
from pysh.python_layer.render import PythonSyntaxRenderer
from pysh.python_layer.runtime import PythonRuntime

# ---------------------------------------------------------------------------
# Prompt strings
# ---------------------------------------------------------------------------
_PROMPT_PRIMARY = ">>> "
_PROMPT_CONTINUATION = "... "

# ---------------------------------------------------------------------------
# Internal sentinels returned by _dispatch_directive()
# ---------------------------------------------------------------------------
_DIRECTIVE_EXIT = object()       # signals the run-loop to exit Python mode
_DIRECTIVE_HANDLED = object()    # directive recognised and handled (non-exit)
_DIRECTIVE_NOT_FOUND = object()  # not a directive — treat as Python source

# ---------------------------------------------------------------------------
# Known directive token sets
# ---------------------------------------------------------------------------
# Exact directives take no arguments (extra trailing text is ignored).
# NOTE: #run is intentionally excluded — it has strict no-arg enforcement.
_EXACT_DIRECTIVES: frozenset[str] = frozenset(
    {"#exit", "#help", "#clear", "#reset", "#append", "#edit"}
)
# Optional-argument directives: bare form is valid; filename form is also valid.
_OPT_ARG_DIRECTIVES: frozenset[str] = frozenset({"#save", "#show"})
# Required-argument directives: must have an argument.
_REQ_ARG_DIRECTIVES: frozenset[str] = frozenset(
    {"#open", "#insert", "#replace", "#delete"}
)
# Explicitly forbidden shell-redirection patterns.
_FORBIDDEN_DIRECTIVES: frozenset[str] = frozenset({"#echo"})

# All known directive tokens (used to distinguish unknown directives from
# Python comments in _parse_directive).
_ALL_KNOWN_DIRECTIVES: frozenset[str] = (
    _EXACT_DIRECTIVES | _OPT_ARG_DIRECTIVES | _REQ_ARG_DIRECTIVES
    | _FORBIDDEN_DIRECTIVES | frozenset({"#run"})
)

# Directives that accept a file path argument (for tab completion).
_FILE_ARG_DIRECTIVES: tuple[str, ...] = ("#open ", "#save ", "#show ")

# ---------------------------------------------------------------------------
# Missing-# detection: command words typed without the leading #
# ---------------------------------------------------------------------------
# Pattern: a "path-like" argument starts with a path character, not an
# operator, so "show = 1" or "reset()" fall through to Python execution.
_PATH_LIKE_START: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.~/]")


# ---------------------------------------------------------------------------
# Pending edit operation state
# ---------------------------------------------------------------------------

class _PendingEdit:
    """Accumulates Python source lines for an in-flight #insert or #replace."""

    __slots__ = ("op", "line_num", "lines")

    def __init__(self, op: str, line_num: int) -> None:
        self.op: str = op            # "insert" or "replace"
        self.line_num: int = line_num  # 1-based target line
        self.lines: list[str] = []


class _PythonModeCompleter:
    """Raw-line completion adapter for Python mode file directives."""

    def __init__(self, cwd_provider: Callable[[], Path]) -> None:
        self._cwd_provider = cwd_provider

    def raw_completion(self, line: str, cursor: int) -> CompletionResult:
        candidates = tuple(complete_python_mode_path(line, cursor, self._cwd_provider()))
        start = cursor
        partial = ""
        prefix_up_to_cursor = line[:cursor]
        for directive_prefix in _FILE_ARG_DIRECTIVES:
            if prefix_up_to_cursor.startswith(directive_prefix):
                partial = prefix_up_to_cursor[len(directive_prefix):]
                start = cursor - len(partial)
                break
        return CompletionResult(start, cursor, partial, candidates)

    def apply_raw_completion(self, line: str, result: CompletionResult) -> tuple[str, int]:
        return apply_single_completion(line, result)


# ---------------------------------------------------------------------------
# Pure helper: TAB expansion
# ---------------------------------------------------------------------------

def expand_tab(line: str, cursor: int) -> tuple[str, int]:
    """Insert four spaces at *cursor* and return the updated ``(line, cursor)``.

    Pure function with no terminal dependency — unit-testable without a TTY.

    Inside normal Python code blocks, ``<TAB>`` calls this function rather
    than triggering shell-style path completion.

    Example::

        >>> expand_tab("def f():", 8)
        ('def f():    ', 12)
    """
    new_line = line[:cursor] + "    " + line[cursor:]
    return new_line, cursor + 4


# ---------------------------------------------------------------------------
# Path completion (pure, testable)
# ---------------------------------------------------------------------------

def complete_python_mode_path(
    line: str,
    cursor: int,
    cwd: Path,
) -> list[str]:
    """Return filesystem path completion candidates for file directives.

    Active only when ``line[:cursor]`` begins with one of::

        #open <partial>
        #save <partial>
        #show <partial>

    For any other input (including normal Python code lines), returns ``[]``
    so that ``<TAB>`` behaviour falls back to :func:`expand_tab`.

    Relative paths are resolved against *cwd*. Absolute paths are completed
    directly.  Directories in the result set are suffixed with ``/``.
    """
    prefix_up_to_cursor = line[:cursor]

    partial = ""
    for directive_prefix in _FILE_ARG_DIRECTIVES:
        if prefix_up_to_cursor.startswith(directive_prefix):
            partial = prefix_up_to_cursor[len(directive_prefix):]
            break
    else:
        return []

    is_absolute = partial.startswith("/")

    if partial == "" or partial.endswith("/"):
        if is_absolute:
            search_dir = Path(partial) if partial else Path("/")
        else:
            search_dir = (cwd / partial).resolve() if partial else cwd
        stem = ""
    else:
        partial_path = Path(partial)
        if is_absolute:
            search_dir = partial_path.parent
            stem = partial_path.name
        else:
            search_dir = (cwd / partial_path.parent).resolve()
            stem = partial_path.name

    try:
        raw_entries = sorted(search_dir.iterdir(), key=lambda e: (e.is_file(), e.name))
    except OSError:
        return []

    matching = [e for e in raw_entries if e.name.startswith(stem)]

    results: list[str] = []
    for entry in matching:
        suffix = "/" if entry.is_dir() else ""
        if is_absolute:
            results.append(str(entry) + suffix)
        else:
            try:
                rel = entry.relative_to(cwd)
                results.append(str(rel) + suffix)
            except ValueError:
                results.append(str(entry) + suffix)

    return results


# ---------------------------------------------------------------------------
# Directive parsing
# ---------------------------------------------------------------------------

def _parse_directive(
    text: str,
) -> tuple[str, str | None, str | None] | None:
    """Parse *text* as a potential Python-mode directive.

    Returns one of:

    * ``(name, arg, None)``       — valid directive.
    * ``(None, None, error_msg)`` — malformed or forbidden directive.
    * ``None``                    — not a directive (Python source/comment).

    Argument rules
    --------------
    * ``#open``, ``#insert``, ``#replace``, ``#delete`` require an argument.
    * ``#save``, ``#show`` accept an optional argument.
    * ``#exit``, ``#help``, ``#run``, ``#clear``, ``#reset``, ``#append``
      take no arguments (``#run`` is strict: a file argument is an error).
    * ``>`` / ``<`` inside arguments are forbidden.
    * ``#echo`` is explicitly rejected.
    * Unknown ``#word`` tokens (no space after ``#``) are errors.
    * ``# comment`` lines (space after ``#``) return ``None`` (Python source).
    """
    stripped = text.strip()
    if not stripped.startswith("#"):
        return None

    parts = stripped.split(None, 1)
    token: str = parts[0]
    rest: str = parts[1].strip() if len(parts) > 1 else ""

    # --- #run: strict no-argument ---
    if token == "#run":
        if rest:
            return (
                None,
                None,
                f"#run does not accept a file argument; "
                f"use #open {rest} then #run",
            )
        return ("run", None, None)

    # --- exact directives ---
    if token in _EXACT_DIRECTIVES:
        return (token[1:], None, None)

    # --- optional-argument directives ---
    if token in _OPT_ARG_DIRECTIVES:
        if rest and (">" in rest or "<" in rest):
            return (
                None,
                None,
                f"{token}: shell redirection syntax is not supported; "
                f"use: {token} [filename]",
            )
        filename: str | None = rest.split()[0] if rest else None
        return (token[1:], filename, None)

    # --- required-argument directives ---
    if token in _REQ_ARG_DIRECTIVES:
        if not rest:
            return (None, None, f"usage: {token} <argument>")
        if token in ("#open",) and (">" in rest or "<" in rest):
            return (
                None,
                None,
                f"{token}: shell redirection syntax is not supported; "
                f"use: {token} <filename>",
            )
        return (token[1:], rest.split()[0] if token == "#open" else rest, None)

    # --- explicitly forbidden ---
    if token in _FORBIDDEN_DIRECTIVES:
        return (
            None,
            None,
            f"{token}: not a supported directive; "
            "use Python's built-in print() or open() instead",
        )

    # Unknown #word token (len > 1 = no space between # and word).
    # "# comment" has token == "#" (length 1) and is a Python comment → None.
    if len(token) > 1:
        return (
            None,
            None,
            f"unknown Python mode directive: {token}\n"
            "type #help for available commands",
        )

    # Bare "#" followed by a space — Python comment.
    return None


# ---------------------------------------------------------------------------
# Missing-# hint detection (pure, testable)
# ---------------------------------------------------------------------------

def _check_missing_hash(line: str) -> str | None:
    """Return a hint message when *line* looks like a missing-``#`` directive.

    Intercepts command words (``show``, ``reset``, ``run``, ``save``,
    ``open``, ``clear``, ``exit``, ``quit``, ``help``) typed without ``#``
    at the primary Python prompt.

    Returns ``None`` for normal Python source (``show = 1``, ``reset()``,
    etc.) so those lines fall through to the runtime unchanged.
    """
    stripped = line.strip()
    parts = stripped.split(None, 1)
    if not parts:
        return None

    word = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    # Only intercept when rest is path-like or absent (not an operator).
    if rest and not _PATH_LIKE_START.match(rest):
        return None

    if word == "open":
        if rest:
            return f"use #open {rest} to open a file into the Python edit buffer"
        return "use #open <file> to open a file into the Python edit buffer"
    if word == "save":
        if rest:
            return f"use #save {rest} to save the Python edit buffer to that file"
        return "use #save to save the active Python edit buffer"
    if word == "show":
        if rest:
            return f"use #show {rest} to print a file without opening it"
        return "use #show to display the active Python edit buffer"
    if word == "run":
        if rest:
            return f"use #open {rest} then #run"
        return "use #run to execute the active Python edit buffer"
    if not rest:
        if word == "reset":
            return "use #reset to reset the Python command workspace"
        if word == "clear":
            return "use #clear to clear the active Python edit buffer"
        if word in ("exit", "quit"):
            return "use #exit to return to the PySH prompt"
        if word == "help":
            return "use #help to show Python command mode commands"
    return None


# ---------------------------------------------------------------------------
# Auto-indentation helper (pure, testable)
# ---------------------------------------------------------------------------

def next_python_indent(lines: list[str], tab_width: int = 4) -> str:
    """Return the indentation prefix for the next Python continuation line.

    Scans *lines* in reverse, skipping blank lines, and examines the last
    meaningful (non-blank, non-comment) line.  If that line's stripped form
    ends with ``:``, the current block indent is increased by *tab_width*
    spaces.  Otherwise the current block indent is preserved unchanged.

    Examples::

        next_python_indent(["def f():"])             == "    "
        next_python_indent(["def f():", "    if x:"]) == "        "
        next_python_indent(["def f():", "    pass"]) == "    "
        next_python_indent([])                       == ""
    """
    for line in reversed(lines):
        if not line.strip():
            continue
        indent = line[: len(line) - len(line.lstrip())]
        stripped = line.strip()
        if not stripped.startswith("#") and stripped.endswith(":"):
            indent += " " * tab_width
        return indent
    return ""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PythonCommandMode:
    """Interactive Python Command Execution Layer with file-backed edit mode.

    After ``#open file.py`` the mode enters file-backed edit mode.  The
    prompt changes to ``[file.py:edit] >>> `` and normal Python source
    entered at the prompt is appended to the source buffer by default.

    Edit workspace state
    --------------------
    * ``_buffer``      — Python source lines.
    * ``_active_file`` — resolved path of the open file, or ``None``.
    * ``_edit_mode``   — ``True`` when a file is open for editing.
    * ``_pending_edit``— ``_PendingEdit`` instance when collecting content
      for ``#insert`` or ``#replace``, else ``None``.

    Workspace rules
    ~~~~~~~~~~~~~~~
    * ``#open f``   → sets ``_active_file``, ``_edit_mode = True``.
    * ``#save f``   → writes buffer, sets ``_active_file``, keeps ``_edit_mode``.
    * ``#save``     → writes to ``_active_file``; errors if unset.
    * ``#clear``    → clears ``_buffer``; keeps ``_active_file`` and ``_edit_mode``.
    * ``#reset``    → clears everything; ``_edit_mode = False``.
    * ``#show f``   → cat-style; never modifies ``_buffer`` or ``_active_file``.

    Edit operation content (``#insert``, ``#replace``) is applied to the
    buffer only and is **not** executed automatically.  Use ``#run`` to
    execute the modified buffer.

    All I/O dependencies are injectable for deterministic unit tests.

    Parameters
    ----------
    runtime:
        :class:`~pysh.python_layer.runtime.PythonRuntime` instance.  When *None*
        a fresh session-local instance is created.
    input_source:
        Iterable of pre-supplied lines used instead of ``input()``.  When
        provided, visual padding is automatically disabled.
    out_stream:
        Destination for mode-level output.  Defaults to ``sys.stdout``.
        err_stream:
            Destination for mode-level errors.  Defaults to ``sys.stderr``.
    renderer:
        Optional terminal renderer. Tests may inject ``force_color=True``.
    cwd_provider:
        Zero-argument callable returning the current working directory.
        Defaults to :func:`pathlib.Path.cwd`.
    visual_padding_lines:
        Blank lines printed above each prompt in interactive mode.
        Defaults to 0 (compact REPL layout); raising it pollutes scrollback.
        Auto-set to 0 when *input_source* is provided.
    """

    def __init__(
        self,
        *,
        runtime: PythonRuntime | None = None,
        input_source: Iterable[str] | None = None,
        out_stream: IO[str] | None = None,
        err_stream: IO[str] | None = None,
        renderer: PythonSyntaxRenderer | None = None,
        cwd_provider: Callable[[], Path] | None = None,
        visual_padding_lines: int = 0,
    ) -> None:
        self._out: IO[str] = out_stream if out_stream is not None else sys.stdout
        self._err: IO[str] = err_stream if err_stream is not None else sys.stderr
        self._renderer = renderer if renderer is not None else PythonSyntaxRenderer(stream=self._out)
        self._runtime: PythonRuntime = (
            runtime
            if runtime is not None
            else PythonRuntime(
                err_stream=self._err,
                error_renderer=self._renderer.render_traceback,
            )
        )
        self._input_iter: Iterator[str] | None = (
            iter(input_source) if input_source is not None else None
        )
        self._cwd_provider: Callable[[], Path] = (
            cwd_provider if cwd_provider is not None else Path.cwd
        )
        # Active edit workspace state.
        self._buffer: list[str] = []
        self._active_file: Path | None = None
        self._edit_mode: bool = False
        self._pending_edit: _PendingEdit | None = None
        self._raw_reader = RawLineReader()
        self._raw_suggester = AutoSuggester()
        self._raw_highlighter = LineHighlighter(frozenset())
        self._raw_completer = _PythonModeCompleter(self._cwd_provider)
        self._last_read_live_rendered = False
        # Visual padding: auto-disabled in test/scripted mode.
        self._visual_padding_lines: int = (
            0 if input_source is not None else max(0, visual_padding_lines)
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the interactive Python command loop until ``#exit`` or EOF."""
        self._print_banner()

        at_primary = True
        pending: list[str] = []  # normal Python block accumulation

        while True:
            # Show primary prompt only when neither a pending edit op nor a
            # multi-line Python block is in progress.
            show_primary = at_primary and self._pending_edit is None

            self._print_visual_padding()
            indent_prefix = (
                next_python_indent(pending)
                if not at_primary and self._pending_edit is None
                else ""
            )
            try:
                line = self._read_line(show_primary, indent_prefix=indent_prefix)
            except EOFError:
                if show_primary:
                    print("", file=self._out)
                    break
                # Cancel any in-progress state.
                print("", file=self._out)
                self._runtime.clear_input_buffer()
                pending.clear()
                self._pending_edit = None
                at_primary = True
                continue
            except KeyboardInterrupt:
                print("", file=self._out)
                self._runtime.clear_input_buffer()
                pending.clear()
                self._pending_edit = None
                at_primary = True
                continue

            self._echo_post_entry_highlight(line)

            # Normalize auto-indent prefix to a true blank line: when the raw
            # reader pre-fills the buffer with indent spaces and the user presses
            # Enter without typing anything extra, the returned line equals
            # indent_prefix exactly.  codeop requires an empty string (not
            # whitespace) to close a compound statement, matching CPython REPL.
            if not at_primary and indent_prefix and line == indent_prefix:
                line = ""

            # ----------------------------------------------------------
            # PRIORITY 1: pending edit operation (#insert / #replace)
            # ----------------------------------------------------------
            if self._pending_edit is not None:
                done, err_msg = self._collect_edit_line(line)
                if done:
                    if err_msg:
                        self._print_error(f"pysh(py): {err_msg}")
                    self._pending_edit = None
                    at_primary = True
                continue

            # ----------------------------------------------------------
            # PRIORITY 2: directive dispatch (primary prompt only)
            # ----------------------------------------------------------
            if at_primary:
                action = self._dispatch_directive(line)
                if action is _DIRECTIVE_EXIT:
                    break
                if action is _DIRECTIVE_HANDLED:
                    continue

                # Intercept bare command words typed without '#'.
                hint = _check_missing_hash(line)
                if hint is not None:
                    self._print_error(f"pysh(py): {hint}")
                    continue

            # ----------------------------------------------------------
            # PRIORITY 3: normal Python execution
            # ----------------------------------------------------------
            pending.append(line)
            try:
                more, status = self._runtime.push_interactive(line)
            except SystemExit:
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
                if status == 0 and any(ln.strip() for ln in pending):
                    self._buffer.extend(pending)
                pending.clear()

        return 0

    # ------------------------------------------------------------------
    # Directive dispatch
    # ------------------------------------------------------------------

    def _dispatch_directive(self, line: str) -> object:
        """Try to handle *line* as a directive.

        Returns one of ``_DIRECTIVE_EXIT``, ``_DIRECTIVE_HANDLED``, or
        ``_DIRECTIVE_NOT_FOUND``.
        """
        parsed = _parse_directive(line)
        if parsed is None:
            return _DIRECTIVE_NOT_FOUND

        name, arg, error = parsed

        if error is not None:
            self._print_error(f"pysh(py): {error}")
            return _DIRECTIVE_HANDLED

        if name == "exit":
            return _DIRECTIVE_EXIT
        if name == "help":
            self._print_help()
        elif name == "open":
            self._handle_open(arg)  # type: ignore[arg-type]
        elif name == "save":
            self._handle_save(arg)
        elif name == "show":
            self._handle_show(arg)
        elif name == "run":
            self._handle_run()
        elif name == "edit":
            self._handle_edit()
        elif name == "append":
            self._handle_append()
        elif name == "insert":
            self._handle_insert(arg)  # type: ignore[arg-type]
        elif name == "replace":
            self._handle_replace(arg)  # type: ignore[arg-type]
        elif name == "delete":
            self._handle_delete(arg)  # type: ignore[arg-type]
        elif name == "clear":
            self._handle_clear()
        elif name == "reset":
            self._handle_reset()

        return _DIRECTIVE_HANDLED

    # ------------------------------------------------------------------
    # Directive handlers
    # ------------------------------------------------------------------

    def _handle_open(self, filename: str) -> int:
        """Load *filename* into the edit buffer and enter file-backed edit mode."""
        path = self._resolve_path(filename)
        if path.is_dir():
            self._print_error(f"pysh(py): #open: {filename}: is a directory")
            return 1
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._print_error(f"pysh(py): #open: {filename}: no such file")
            return 1
        except PermissionError:
            self._print_error(f"pysh(py): #open: {filename}: permission denied")
            return 1
        except UnicodeDecodeError as exc:
            self._print_error(f"pysh(py): #open: {filename}: decode error: {exc}")
            return 1
        except OSError as exc:
            self._print_error(f"pysh(py): #open: {filename}: {exc}")
            return 1
        self._buffer = content.splitlines()
        self._active_file = path
        self._edit_mode = True
        self._print_status(f"opened: {filename}")
        self._print_status(f"editing: {filename}")
        return 0

    def _handle_save(self, filename: str | None) -> int:
        """Write the source buffer to *filename* or to ``_active_file``.

        * ``#save``         — writes to ``_active_file``; errors if unset.
        * ``#save file.py`` — writes to *file.py*, sets ``_active_file``.
        """
        if filename is None:
            if self._active_file is None:
                self._print_error("pysh(py): no active file; use #save file.py")
                return 1
            target = self._active_file
            display = str(self._active_file.name)
        else:
            target = self._resolve_path(filename)
            display = filename

        if target.is_dir():
            self._print_error(f"pysh(py): #save: {display}: is a directory")
            return 1

        source = "\n".join(self._buffer)
        if not source.endswith("\n"):
            source += "\n"
        try:
            target.write_text(source, encoding="utf-8")
        except OSError as exc:
            self._print_error(f"pysh(py): #save: {display}: {exc}")
            return 1

        if filename is not None:
            self._active_file = target
            self._edit_mode = True
        self._print_status(f"saved: {display}")
        return 0

    def _handle_show(self, filename: str | None) -> None:
        """Show the active buffer (``#show``) or a file's contents (``#show f``).

        ``#show`` is read-only: it never modifies ``_buffer`` or ``_active_file``.
        Source buffer lines are rendered with syntax highlighting when available.
        ANSI escape sequences are only in the terminal output — the buffer stays clean.
        """
        if filename is None:
            if not self._buffer:
                self._print_status("buffer empty")
                return
            for i, ln in enumerate(self._buffer, 1):
                hl = self._renderer.render_line(ln)
                print(f"{i} | {hl}", file=self._out)
            return

        # File display (cat-style, read-only).
        path = self._resolve_path(filename)
        if path.is_dir():
            self._print_error(f"pysh(py): #show: {filename}: is a directory")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._print_error(f"pysh(py): #show: {filename}: no such file")
            return
        except PermissionError:
            self._print_error(f"pysh(py): #show: {filename}: permission denied")
            return
        except OSError as exc:
            self._print_error(f"pysh(py): #show: {filename}: {exc}")
            return
        # Render the file content with syntax highlighting.
        # rstrip the trailing newline before rendering so Pygments does not
        # double-up; print() adds the final newline.
        rendered = self._renderer.render_code(content.rstrip("\n"))
        print(rendered, file=self._out)

    def _handle_edit(self) -> None:
        """Render the active buffer with full Python syntax highlighting.

        ``#edit`` is a read-only view command that displays the source buffer
        with syntax highlighting applied.  It never modifies ``_buffer``,
        ``_active_file``, or any file.  The ANSI escape sequences are only in
        the terminal output — the buffer and saved files remain clean.

        This is distinct from ``#show``:
        * ``#show`` displays the buffer with line numbers.
        * ``#edit`` displays the buffer as highlighted source (no line numbers).
        """
        if not self._buffer:
            self._print_status("buffer empty")
            return
        source = "\n".join(self._buffer)
        rendered = self._renderer.render_code(source)
        print(rendered, file=self._out)

    def _handle_run(self) -> int:
        """Execute the source buffer with exec semantics (no expression echoing)."""
        if not self._buffer:
            return 0
        source = "\n".join(self._buffer)
        try:
            return self._runtime.run_buffer(source)
        except SystemExit:
            return 0
        except KeyboardInterrupt:
            self._print_error("\nKeyboardInterrupt")
            return 130

    def _handle_append(self) -> None:
        """Confirm append mode (default after #open).

        Normal Python code entered at the prompt is already appended to the
        source buffer when edit mode is active, so this directive is a
        no-op that simply prints a confirmation.
        """
        self._print_status(
            "append mode — Python source entered at the prompt is appended to the edit buffer"
        )

    def _handle_insert(self, arg: str) -> int:
        """Prepare to insert Python source before line *arg* (1-based)."""
        try:
            line_num = int(arg.strip())
        except ValueError:
            self._print_error(f"pysh(py): #insert: invalid line number: {arg!r}")
            return 1
        n = len(self._buffer)
        if line_num < 1 or line_num > n + 1:
            self._print_error(
                f"pysh(py): #insert: line {line_num} out of range "
                f"(valid: 1-{n + 1})"
            )
            return 1
        self._pending_edit = _PendingEdit("insert", line_num)
        self._print_status(f"insert before line {line_num} — enter Python source:")
        return 0

    def _handle_replace(self, arg: str) -> int:
        """Prepare to replace line *arg* (1-based) with new Python source."""
        try:
            line_num = int(arg.strip())
        except ValueError:
            self._print_error(f"pysh(py): #replace: invalid line number: {arg!r}")
            return 1
        n = len(self._buffer)
        if n == 0:
            self._print_error("pysh(py): #replace: buffer is empty")
            return 1
        if line_num < 1 or line_num > n:
            self._print_error(
                f"pysh(py): #replace: line {line_num} out of range "
                f"(valid: 1-{n})"
            )
            return 1
        self._pending_edit = _PendingEdit("replace", line_num)
        self._print_status(f"replace line {line_num} — enter replacement Python source:")
        return 0

    def _handle_delete(self, arg: str) -> int:
        """Delete one line or an inclusive range from the source buffer."""
        n = len(self._buffer)
        if n == 0:
            self._print_error("pysh(py): #delete: buffer is empty")
            return 1

        if ":" in arg:
            parts = arg.split(":", 1)
            try:
                start = int(parts[0].strip())
                end = int(parts[1].strip())
            except ValueError:
                self._print_error(f"pysh(py): #delete: invalid range: {arg!r}")
                return 1
            if start < 1 or end > n or start > end:
                self._print_error(
                    f"pysh(py): #delete: range {start}:{end} out of range "
                    f"(valid: 1:{n})"
                )
                return 1
            count = end - start + 1
            del self._buffer[start - 1 : end]
            self._print_status(f"deleted lines {start}-{end} ({count} line(s))")
        else:
            try:
                line_num = int(arg.strip())
            except ValueError:
                self._print_error(f"pysh(py): #delete: invalid line number: {arg!r}")
                return 1
            if line_num < 1 or line_num > n:
                self._print_error(
                    f"pysh(py): #delete: line {line_num} out of range "
                    f"(valid: 1-{n})"
                )
                return 1
            del self._buffer[line_num - 1]
            self._print_status(f"deleted line {line_num}")
        return 0

    def _collect_edit_line(self, line: str) -> tuple[bool, str | None]:
        """Feed one line into the pending ``#insert`` or ``#replace`` operation.

        Uses ``codeop.compile_command`` to detect completeness — the same
        mechanism used for interactive Python code.  Edit content is applied
        to the source buffer only and is NOT executed.

        Returns
        -------
        (done, error_msg)
            ``done=True``  — operation complete (applied or failed).
            ``done=False`` — incomplete; more input needed.
            ``error_msg``  — non-``None`` on syntax error.
        """
        op = self._pending_edit
        assert op is not None
        op.lines.append(line)
        source = "\n".join(op.lines)

        try:
            result = codeop.compile_command(source, symbol="single")
        except SyntaxError as exc:
            return (True, f"syntax error in {op.op} content: {exc}")

        if result is None:
            # Incomplete input unit — need more lines.
            return (False, None)

        # Complete — apply the edit.
        new_lines = source.splitlines()
        if op.op == "insert":
            idx = op.line_num - 1
            self._buffer[idx:idx] = new_lines
            self._print_status(f"inserted {len(new_lines)} line(s) at position {op.line_num}")
        elif op.op == "replace":
            idx = op.line_num - 1
            self._buffer[idx : idx + 1] = new_lines
            self._print_status(f"line {op.line_num} replaced")

        return (True, None)

    def _handle_clear(self) -> None:
        """Clear the source buffer; keep ``_active_file`` and ``_edit_mode``."""
        self._buffer.clear()
        self._runtime.clear_input_buffer()
        self._print_status("buffer cleared")

    def _handle_reset(self) -> None:
        """Full workspace reset: clears buffer, active file, edit mode, runtime."""
        self._buffer.clear()
        self._active_file = None
        self._edit_mode = False
        self._pending_edit = None
        self._runtime.reset()
        self._print_status("workspace reset")

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_path(self, arg: str) -> Path:
        """Resolve *arg* to an absolute :class:`~pathlib.Path`.

        ``~`` and ``~user`` prefixes are expanded before resolution.
        Absolute paths are resolved as-is; relative paths are anchored to
        the current PySH working directory.
        """
        p = Path(arg).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (self._cwd_provider() / p).resolve()

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _get_primary_prompt(self) -> str:
        """Return the primary prompt, including file context when in edit mode."""
        if self._edit_mode and self._active_file is not None:
            return f"[{self._active_file.name}:edit] >>> "
        return _PROMPT_PRIMARY

    def _read_line(self, at_primary: bool, indent_prefix: str = "") -> str:
        """Read one input line from the injected source or ``input()``.

        *indent_prefix* pre-fills the raw-reader buffer so the terminal shows
        the auto-indented continuation text before the user types.  It has no
        effect in test/scripted mode (``input_source``) — those supply complete
        lines directly.
        """
        prompt = self._get_primary_prompt() if at_primary else _PROMPT_CONTINUATION
        rendered_prompt = self._renderer.render_prompt(prompt)
        self._last_read_live_rendered = False
        if self._input_iter is not None:
            try:
                return next(self._input_iter)
            except StopIteration:
                raise EOFError from None
        if self._should_use_raw_reader():
            try:
                self._last_read_live_rendered = True
                return self._raw_reader.read_line(
                    rendered_prompt,
                    history=[],
                    suggester=self._raw_suggester,
                    highlighter=self._raw_highlighter,
                    scheme=DEFAULT_SCHEME,
                    options=SimpleNamespace(autosuggest=False, syntax_highlight=False),
                    completer=self._raw_completer,
                    line_renderer=self._renderer.render_line,
                    tab_handler=self._handle_raw_tab,
                    initial_text=indent_prefix,
                )
            except (OSError, termios.error):
                self._last_read_live_rendered = False
        return input(rendered_prompt)

    @staticmethod
    def _should_use_raw_reader() -> bool:
        try:
            return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        except (AttributeError, ValueError):
            return False

    def _echo_post_entry_highlight(self, line: str) -> None:
        """Echo highlighted source only when live raw redraw was not used."""
        if self._last_read_live_rendered:
            return
        if not self._renderer._active():
            return
        if not line or line.lstrip().startswith("#"):
            return
        print(self._renderer.render_line(line), file=self._out)

    def _handle_raw_tab(self, buffer: LineBuffer) -> bool:
        """Insert four spaces for Python code; let file directives complete."""
        prefix = buffer.text[: buffer.cursor]
        if any(prefix.startswith(directive) for directive in _FILE_ARG_DIRECTIVES):
            return False
        text, cursor = expand_tab(buffer.text, buffer.cursor)
        buffer.set(text, cursor)
        return True

    def _print_visual_padding(self) -> None:
        """Print blank lines below the prompt in interactive mode only."""
        if self._visual_padding_lines > 0 and self._input_iter is None:
            for _ in range(self._visual_padding_lines):
                print(file=self._out)

    def _print_status(self, text: str = "") -> None:
        """Print Python-mode status text through the terminal renderer."""
        print(self._renderer.render_status(text), file=self._out)

    def _print_error(self, text: str) -> None:
        """Print Python-mode diagnostics through the terminal renderer."""
        print(self._renderer.render_error(text), file=self._err)

    def _print_banner(self) -> None:
        from pysh import LICENSE_NAME  # noqa: PLC0415
        vi = sys.version_info
        self._print_status(f"PySH Python Command Execution Layer | {LICENSE_NAME}")
        self._print_status(f"Python {vi.major}.{vi.minor}.{vi.micro}")
        self._print_status("Type #help for commands. Ctrl+D or #exit to return to PySH.")
        print(file=self._out)

    def _print_help(self) -> None:
        help_text = (
            "Python Command Execution Layer — file-backed edit mode directives:\n"
            "\n"
            "  #exit              Return to the PySH prompt.\n"
            "  Ctrl+D             Exit Python mode and return to PySH.\n"
            "  #help              Show this help.\n"
            "  #open <file>       Open a Python file into edit mode.\n"
            "  #save [file]       Save the active edit buffer.\n"
            "  #show [file]       Show active buffer (numbered) or print file like cat.\n"
            "  #edit              Show active buffer with full syntax highlighting.\n"
            "  #run               Execute the active edit buffer.\n"
            "  #clear             Clear the active edit buffer.\n"
            "  #reset             Reset buffer, active file, and runtime state.\n"
            "\n"
            "  #append            Append following Python input to the edit buffer.\n"
            "  #insert <line>     Insert following Python input before line.\n"
            "  #replace <line>    Replace line with following Python input.\n"
            "  #delete <line>     Delete one line.\n"
            "  #delete <a>:<b>    Delete inclusive line range.\n"
            "\n"
            "  TAB                Insert four spaces (inside Python code).\n"
            "  Ctrl+C             Cancel current input.\n"
            "\n"
            "Syntax highlighting:\n"
            "  Python source shown in #py mode is syntax-highlighted when\n"
            "  terminal color is enabled. Pygments is installed by default.\n"
            "  Highlighting applies to interactive input, continuation input,\n"
            "  prompts, diagnostics, #show, #show file.py, and #edit.\n"
            "  Highlighting is visual only and is never saved to files.\n"
            "\n"
            "Path completion is available for #open, #save, and #show.\n"
            "TAB inside Python code inserts four spaces.\n"
            "Use #exit, not exit, to return to PySH.\n"
            "\n"
            "After #open, PySH enters file-backed edit mode.\n"
            "Use #show to inspect the buffer and #save to write it back.\n"
            "\n"
            "Edit operation behavior:\n"
            "  #insert and #replace collect the next Python input unit.\n"
            "  Edit content updates the buffer only (not auto-executed).\n"
            "  Use #run to execute the edited buffer.\n"
            "\n"
            "Active file workflow:\n"
            "  #open main.py      (load file into edit mode)\n"
            "  #replace 5         (enter replacement for line 5)\n"
            "  #save              (write back to the active file)\n"
            "  #run               (execute the edited buffer)\n"
            "\n"
            "Clean execution workflow:\n"
            "  #reset             (clear all state)\n"
            "  #open main.py      (load source into edit mode)\n"
            "  #run               (execute the buffer)\n"
        )
        print(self._renderer.render_status(help_text), file=self._out)
