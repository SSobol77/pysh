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

* ``source_buffer``  — Python source text (list of lines).
* ``active_file``    — the :class:`~pathlib.Path` most recently opened or saved,
  or ``None`` when no file is associated.
* ``runtime``        — a :class:`~pysh.python_runtime.PythonRuntime` instance
  that holds the persistent ``__main__`` namespace for the session.

See docs/python-command-execution-layer.md for the full specification.
"""
from __future__ import annotations

import re
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
_DIRECTIVE_EXIT = object()       # signals the run-loop to exit Python mode
_DIRECTIVE_HANDLED = object()    # directive recognised and handled (non-exit)
_DIRECTIVE_NOT_FOUND = object()  # not a directive — treat as Python source

# ---------------------------------------------------------------------------
# Known directive token sets
# ---------------------------------------------------------------------------
# Exact directives take no arguments (extra trailing text is ignored).
# NOTE: #run is intentionally excluded — it has strict no-arg enforcement.
_EXACT_DIRECTIVES: frozenset[str] = frozenset({"#exit", "#help", "#clear", "#reset"})
# Optional-argument directives: bare form is valid; filename form is also valid.
_OPT_ARG_DIRECTIVES: frozenset[str] = frozenset({"#save", "#show"})
# Required-argument directives: must have a filename.
_REQ_ARG_DIRECTIVES: frozenset[str] = frozenset({"#open"})
# Explicitly forbidden shell-redirection patterns.
_FORBIDDEN_DIRECTIVES: frozenset[str] = frozenset({"#echo"})

# All known directive tokens (used to distinguish unknown directives from comments).
_ALL_KNOWN_DIRECTIVES: frozenset[str] = (
    _EXACT_DIRECTIVES | _OPT_ARG_DIRECTIVES | _REQ_ARG_DIRECTIVES
    | _FORBIDDEN_DIRECTIVES | frozenset({"#run"})
)

# Directives that accept a file path argument (for completion).
_FILE_ARG_DIRECTIVES: tuple[str, ...] = ("#open ", "#save ", "#show ")

# ---------------------------------------------------------------------------
# Missing-# detection: command words that look like directives typed without #
# ---------------------------------------------------------------------------
# Maps first-word → hint message (plain text after "pysh(py): ").
# Arg substitution is done at call time for open/save/show/run.
_MISSING_HASH_BARE: dict[str, str] = {
    "save":  "use #save to save the active Python edit buffer",
    "show":  "use #show to display the active Python edit buffer",
    "run":   "use #run to execute the active Python edit buffer",
    "reset": "use #reset to reset the Python command workspace",
    "clear": "use #clear to clear the active Python edit buffer",
    "exit":  "use #exit to return to the PySH prompt",
    "quit":  "use #exit to return to the PySH prompt",
    "help":  "use #help to show Python command mode commands",
}
# Words where the argument (if present) is incorporated into the hint.
_MISSING_HASH_ARG_WORDS: frozenset[str] = frozenset({"open", "save", "show", "run"})

# Pattern: a "path-like" argument starts with a path character, not an operator.
# This lets "show = 1" or "run()" fall through to Python execution.
_PATH_LIKE_START: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.~/]")


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

    Parameters
    ----------
    line:
        The current input buffer contents.
    cursor:
        The cursor position (index) inside *line*.
    cwd:
        The current PySH working directory used to anchor relative paths.

    Returns
    -------
    list[str]
        Candidate path strings that could replace the partial path portion of
        the input.  Empty when not in a file-directive context.
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

    # Determine which directory to scan and what stem to filter on.
    if partial == "" or partial.endswith("/"):
        # Complete directory contents.
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

    * ``(name, arg, None)``       — valid directive; *name* is the bare name
      (no leading ``#``), *arg* is the filename or ``None``.
    * ``(None, None, error_msg)`` — malformed or forbidden directive syntax.
    * ``None``                    — not a directive (normal Python source/comment).

    Directive argument rules
    ------------------------
    * ``#open`` requires a filename argument.
    * ``#save`` and ``#show`` accept an optional filename argument.
    * ``#exit``, ``#help``, ``#run``, ``#clear``, ``#reset`` take no arguments.
    * Shell redirection tokens ``>`` and ``<`` are forbidden inside arguments.
    * ``#echo`` is explicitly rejected with a readable error.
    * Any other ``#...`` token is treated as a Python comment (returns ``None``).
    """
    stripped = text.strip()
    if not stripped.startswith("#"):
        return None

    parts = stripped.split(None, 1)
    token: str = parts[0]
    rest: str = parts[1].strip() if len(parts) > 1 else ""

    # --- #run: strict no-argument directive ---
    if token == "#run":
        if rest:
            return (
                None,
                None,
                f"#run does not accept a file argument; "
                f"use #open {rest} then #run",
            )
        return ("run", None, None)

    # --- exact directives (no argument needed, extra trailing text ignored) ---
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
            return (None, None, f"usage: {token} <filename>")
        if ">" in rest or "<" in rest:
            return (
                None,
                None,
                f"{token}: shell redirection syntax is not supported; "
                f"use: {token} <filename>",
            )
        return (token[1:], rest.split()[0], None)

    # --- explicitly forbidden ---
    if token in _FORBIDDEN_DIRECTIVES:
        return (
            None,
            None,
            f"{token}: not a supported directive; "
            "use Python's built-in print() or open() instead",
        )

    # Unknown #word token (no space between # and word).
    # "# comment" has token == "#" (length 1) and is a Python comment → None.
    # "#unknown" has token length > 1 and is an unrecognised directive → error.
    if len(token) > 1:
        return (
            None,
            None,
            f"unknown Python mode directive: {token}\n"
            "type #help for available commands",
        )
    # Bare "#" followed by a space — ordinary Python comment.
    return None


# ---------------------------------------------------------------------------
# Missing-# hint detection (pure, testable)
# ---------------------------------------------------------------------------

def _check_missing_hash(line: str) -> str | None:
    """Return a hint message when *line* looks like a missing-``#`` directive.

    Intercepts command words (``show``, ``reset``, ``run``, ``save``,
    ``open``, ``exit``, ``quit``, ``help``, ``clear``) typed at the primary
    Python prompt without a leading ``#``.

    Returns ``None`` when the line is not a bare command attempt, so that
    normal Python source (``show = 1``, ``reset()``, etc.) falls through to
    the runtime unchanged.

    Only intercepts when the first word exactly matches a command word AND
    the rest of the line is empty or looks like a path argument (not an
    operator such as ``=``, ``(``, ``[``).
    """
    stripped = line.strip()
    parts = stripped.split(None, 1)
    if not parts:
        return None

    word = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    # If rest is present, only intercept when it looks path-like.
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

    # Bare-word-only commands (no argument makes sense for these).
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
# Main class
# ---------------------------------------------------------------------------

class PythonCommandMode:
    """Interactive Python Command Execution Layer for PySH.

    The mode maintains an *active edit workspace*:

    * ``_buffer``      — Python source lines (the editable buffer).
    * ``_active_file`` — resolved :class:`~pathlib.Path` of the currently
      open/saved file, or ``None``.
    * ``_runtime``     — persistent :class:`~pysh.python_runtime.PythonRuntime`.

    Workspace state rules
    ---------------------
    * ``#open file``  sets ``_active_file``.
    * ``#save file``  sets ``_active_file``.
    * ``#save``       requires ``_active_file`` (errors if unset).
    * ``#clear``      clears ``_buffer``; keeps ``_active_file`` and runtime.
    * ``#reset``      clears ``_buffer``, clears ``_active_file``, resets runtime.
    * ``#show file``  reads a file for display only; never touches ``_buffer``
      or ``_active_file``.

    All I/O dependencies are injectable for deterministic unit tests.

    Parameters
    ----------
    runtime:
        :class:`~pysh.python_runtime.PythonRuntime` instance.  When *None*
        a fresh session-local instance is created (independent of the ``py``
        builtin runtime).
    input_source:
        Iterable of pre-supplied lines used instead of ``input()``.
        Exhaustion triggers EOF / ``#exit`` semantics.  When provided,
        visual padding is automatically disabled.
    out_stream:
        Destination for mode-level output.  Defaults to ``sys.stdout``.
    err_stream:
        Destination for mode-level errors.  Defaults to ``sys.stderr``.
    cwd_provider:
        Zero-argument callable returning the current working directory.
        Defaults to :func:`pathlib.Path.cwd`.
    visual_padding_lines:
        Number of blank lines printed below the prompt in interactive mode.
        Automatically set to 0 when *input_source* is provided (test mode).
    """

    def __init__(
        self,
        *,
        runtime: PythonRuntime | None = None,
        input_source: Iterable[str] | None = None,
        out_stream: IO[str] | None = None,
        err_stream: IO[str] | None = None,
        cwd_provider: Callable[[], Path] | None = None,
        visual_padding_lines: int = 2,
    ) -> None:
        self._out: IO[str] = out_stream if out_stream is not None else sys.stdout
        self._err: IO[str] = err_stream if err_stream is not None else sys.stderr
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
        # Active edit workspace state.
        self._buffer: list[str] = []
        self._active_file: Path | None = None
        # Disable visual padding in test/scripted mode (input_source provided).
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
        pending: list[str] = []

        while True:
            self._print_visual_padding()
            try:
                line = self._read_line(at_primary)
            except EOFError:
                if at_primary:
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

                # Intercept bare command words typed without a leading #
                # BEFORE they reach the Python runtime.  These must not be
                # executed as Python and must not be appended to the buffer.
                hint = _check_missing_hash(line)
                if hint is not None:
                    print(f"pysh(py): {hint}", file=self._err)
                    continue

            # Feed the line to the Python runtime.
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
                if status != 2 and any(ln.strip() for ln in pending):
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
            print(f"pysh(py): {error}", file=self._err)
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
        elif name == "clear":
            self._handle_clear()
        elif name == "reset":
            self._handle_reset()

        return _DIRECTIVE_HANDLED

    # ------------------------------------------------------------------
    # Directive handlers
    # ------------------------------------------------------------------

    def _handle_open(self, filename: str) -> int:
        """Load *filename* into the source buffer and set ``active_file``."""
        path = self._resolve_path(filename)
        if path.is_dir():
            print(f"pysh(py): #open: {filename}: is a directory", file=self._err)
            return 1
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"pysh(py): #open: {filename}: no such file", file=self._err)
            return 1
        except PermissionError:
            print(f"pysh(py): #open: {filename}: permission denied", file=self._err)
            return 1
        except UnicodeDecodeError as exc:
            print(f"pysh(py): #open: {filename}: decode error: {exc}", file=self._err)
            return 1
        except OSError as exc:
            print(f"pysh(py): #open: {filename}: {exc}", file=self._err)
            return 1
        self._buffer = content.splitlines()
        self._active_file = path
        print(f"opened: {filename}", file=self._out)
        return 0

    def _handle_save(self, filename: str | None) -> int:
        """Write the source buffer to *filename* or to ``active_file``.

        * ``#save``         — writes to ``active_file``; errors if unset.
        * ``#save file.py`` — writes to *file.py* and sets ``active_file``.
        """
        if filename is None:
            if self._active_file is None:
                print(
                    "pysh(py): no active file; use #save file.py",
                    file=self._err,
                )
                return 1
            target = self._active_file
            display = str(self._active_file.name)
        else:
            target = self._resolve_path(filename)
            display = filename

        if target.is_dir():
            print(f"pysh(py): #save: {display}: is a directory", file=self._err)
            return 1

        source = "\n".join(self._buffer)
        if not source.endswith("\n"):
            source += "\n"
        try:
            target.write_text(source, encoding="utf-8")
        except OSError as exc:
            print(f"pysh(py): #save: {display}: {exc}", file=self._err)
            return 1

        if filename is not None:
            self._active_file = target
        print(f"saved: {display}", file=self._out)
        return 0

    def _handle_show(self, filename: str | None) -> None:
        """Show the active buffer (``#show``) or a file's contents (``#show file``).

        ``#show`` without argument prints the source buffer with line numbers.
        ``#show file.py`` prints the file content verbatim (like ``cat``).
        Neither form modifies ``_buffer`` or ``_active_file``.
        """
        if filename is None:
            # Show the active edit buffer.
            if not self._buffer:
                print("buffer empty", file=self._out)
                return
            for i, ln in enumerate(self._buffer, 1):
                print(f"{i} | {ln}", file=self._out)
            return

        # Show a file (read-only, no buffer/active_file modification).
        path = self._resolve_path(filename)
        if path.is_dir():
            print(f"pysh(py): #show: {filename}: is a directory", file=self._err)
            return
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"pysh(py): #show: {filename}: no such file", file=self._err)
            return
        except PermissionError:
            print(f"pysh(py): #show: {filename}: permission denied", file=self._err)
            return
        except OSError as exc:
            print(f"pysh(py): #show: {filename}: {exc}", file=self._err)
            return
        # Print plain file content (no line numbers for cat-style display).
        print(content, end="" if content.endswith("\n") else "\n", file=self._out)

    def _handle_run(self) -> int:
        """Execute the source buffer with exec semantics."""
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

    def _handle_clear(self) -> None:
        """Clear the source buffer and any incomplete input unit.

        Keeps ``active_file`` and runtime globals intact.
        """
        self._buffer.clear()
        self._runtime.clear_input_buffer()
        print("buffer cleared", file=self._out)

    def _handle_reset(self) -> None:
        """Full workspace reset: clears buffer, active_file, and runtime globals."""
        self._buffer.clear()
        self._active_file = None
        self._runtime.reset()
        print("workspace reset", file=self._out)

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_path(self, arg: str) -> Path:
        """Resolve *arg* to an absolute :class:`~pathlib.Path`.

        Absolute paths (starting with ``/``) are used as-is (after resolving
        symlinks).  Relative paths are anchored to the current PySH working
        directory.
        """
        p = Path(arg)
        if p.is_absolute():
            return p.resolve()
        return (self._cwd_provider() / p).resolve()

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _read_line(self, at_primary: bool) -> str:
        """Read one input line from the injected source or ``input()``."""
        prompt = _PROMPT_PRIMARY if at_primary else _PROMPT_CONTINUATION
        if self._input_iter is not None:
            try:
                return next(self._input_iter)
            except StopIteration:
                raise EOFError from None
        return input(prompt)

    def _print_visual_padding(self) -> None:
        """Print blank lines below the prompt in interactive mode.

        Only active in real interactive mode (``_input_iter is None``).
        The number of lines is controlled by ``_visual_padding_lines``.
        Automatically suppressed in test/scripted mode.
        """
        if self._visual_padding_lines > 0 and self._input_iter is None:
            for _ in range(self._visual_padding_lines):
                print(file=self._out)

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
            "  #open <file>    Open a Python file into the editable buffer.\n"
            "  #save [file]    Save the buffer to the active file or to a selected file.\n"
            "  #show [file]    Show the active buffer or print a file like cat.\n"
            "  #run            Execute the active Python edit buffer.\n"
            "  #clear          Clear the active Python edit buffer.\n"
            "  #reset          Clear buffer, active file, and reset runtime state.\n"
            "\n"
            "  TAB             Insert four spaces (inside Python code).\n"
            "  Ctrl+D          Exit (same as #exit).\n"
            "  Ctrl+C          Cancel current input.\n"
            "\n"
            "Path completion is available for #open, #save, and #show.\n"
            "TAB inside Python code inserts four spaces.\n"
            "Use #exit, not exit, to return to PySH.\n"
            "\n"
            "Normal Python code is executed interactively.\n"
            "Lines starting with '# ' are Python comments.\n"
            "Unknown directives (#edit, #delete, etc.) produce an error.\n"
            "\n"
            "Active file workflow:\n"
            "  #open main.py   (load file into buffer, sets active file)\n"
            "  # ... edit interactively ...\n"
            "  #save           (save back to the same active file)\n"
            "\n"
            "Clean file execution workflow:\n"
            "  #reset          (clear all state)\n"
            "  #open main.py   (load source into buffer)\n"
            "  #run            (execute the buffer)\n"
        )
        print(help_text, file=self._out)
