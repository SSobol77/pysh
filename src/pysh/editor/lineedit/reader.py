# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/lineedit/reader.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Raw-mode line reader for capable Unix TTYs.

The reader redraws the command line in place and handles multi-row prompts
conservatively: it returns to the logical start row, clears from cursor to end
of screen, reprints the prompt and buffer, then repositions the cursor by
terminal column math. This avoids stale prompt fragments and scrollback
corruption even when a terminal resizes while editing.

Multiline paste support
-----------------------
When a terminal does not provide bracketed paste markers, it may deliver a
block of pasted command bytes in a single ``read()`` call.  The reader decodes
those bytes into ``KeyEvent`` objects and, upon the first ``ENTER`` event,
returns the first complete command while queuing subsequent complete lines in
``_command_queue``.  The next call to :meth:`read_line` drains the queue without
touching the TTY, preserving compatibility with existing plain-paste behavior.

Bracketed paste mode
--------------------
Terminals that support bracketed paste mode wrap pasted text with the CSI
sequences ``ESC [ 200 ~`` (paste-start) and ``ESC [ 201 ~`` (paste-end).
When these markers are detected the reader collects the paste payload as
editable input.  Paste-end never returns a completed command and never queues
pasted lines for execution; the command can execute only after a later explicit
``ENTER`` key event outside the paste markers.  Because the current line buffer
is single-line, true multiline bracketed paste is handed to the shell through an
explicit callback and left pending for ``paste_show``, ``paste_run``, or
``paste_cancel``; a single trailing paste newline is accepted and dropped. Paste
markers and terminal control sequences never appear in the command buffer or in
the returned command string.
"""
from __future__ import annotations

import atexit
import os
import re
import select
import signal
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pysh.editor.completion import Completer
from pysh.editor.highlight import colors_enabled
from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.buffer import LineBuffer, _display_width
from pysh.editor.lineedit.completion import CompletionResult, common_completion_prefix
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, ColorScheme, LineHighlighter
from pysh.editor.lineedit.keys import Key, KeyDecoder, KeyEvent
from pysh.editor.lineedit.state import EditorMode, EditorState
from pysh.parsing.parser import split_paste_commands


class _Options(Protocol):
    autosuggest: bool
    syntax_highlight: bool


_saved_termios: dict[int, list[object]] = {}
_BRACKETED_PASTE_ENABLE = b"\x1b[?2004h"
_BRACKETED_PASTE_DISABLE = b"\x1b[?2004l"
_PASTE_DEBUG_ENV = "PYSH_PASTE_DEBUG"
_PASTE_DEBUG_PATH = Path("logs") / "pysh-paste-debug.log"

# BUG-022: hard cap on candidate ROWS the completion menu will print, so a
# broad prefix (e.g. "p<TAB>") cannot flood the terminal. Candidate discovery
# and ranking are unaffected; only how many of the already-ranked candidates
# are rendered is bounded here. A summary line reporting the exact hidden
# count is appended beyond this row budget, not counted within it.
_MAX_COMPLETION_MENU_ROWS = 10
_COMPLETION_MENU_COLUMN_SPACING = 2

# ANSI SGR constants for reverse-search display.  Applied only when
# colors_enabled() returns True so dumb/no-color terminals stay readable.
# \033[2;37m (dim+white) is intentionally absent — it renders as black on
# dark-background terminals.  \033[90m (bright-black / gray) is used instead.
_SGR_SEARCH_LABEL = "\033[35m"   # magenta — (reverse-i-search) label
_SGR_SEARCH_QUERY = "\033[36m"   # cyan    — typed query text
_SGR_LABEL       = "\033[90m"    # gray    — field labels (match:, query:)
_SGR_RESET = "\033[0m"


@dataclass(frozen=True)
class QueuedCommand:
    """One pasted command waiting to be replayed by the shell loop."""

    text: str
    echo: bool = True
    interrupt: bool = False
    eof: bool = False

# Matches ANSI CSI sequences (e.g. SGR color codes like "\x1b[32m"). The prompt
# string handed to the reader may already contain color escapes; those bytes
# occupy zero display columns and must be excluded from cursor/width math.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _visible_width(text: str) -> int:
    """Return the on-screen display width of ``text``, ignoring ANSI CSI codes.

    The reader's cursor positioning is computed in terminal columns. Color
    escape sequences in the prompt (e.g. ``\\x1b[32m> \\x1b[0m``) are not
    visible columns, so they are stripped before measuring. The raw command
    buffer never contains escapes and is measured directly elsewhere.
    """
    return _display_width(_ANSI_CSI_RE.sub("", text))


def _restore_saved_termios() -> None:
    for fd, state in list(_saved_termios.items()):
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, state)
        except termios.error:
            pass
        _saved_termios.pop(fd, None)


atexit.register(_restore_saved_termios)


class RawLineReader:
    """Read one editable line from a raw-mode TTY.

    The reader keeps a ``_command_queue`` for commands that arrive as part of a
    pasted block but were not the first complete command.  Each call to
    :meth:`read_line` returns exactly one command string.  When the queue is
    non-empty the command is dequeued immediately without touching the terminal.
    """

    def __init__(self, *, input_fd: int | None = None, output_fd: int | None = None) -> None:
        self.input_fd = input_fd
        self.output_fd = output_fd
        self._start_rows = 0
        self._command_queue: list[QueuedCommand] = []
        self._last_completion_buffer: str | None = None
        self._last_completion_result: CompletionResult | None = None
        self._completion_displayed = False
        # Outer, cross-call collection mode (NORMAL/MULTILINE/HEREDOC/
        # PASTE_STAGED). Owned by this reader but driven only by the caller
        # (pysh.core.shell) through enter_multiline_mode()/enter_heredoc_mode()/
        # enter_paste_mode()/clear_editor_state(): a single read_line() call
        # never mutates it, so it survives unchanged across the repeated
        # read_line() calls a multiline/heredoc continuation collector makes.
        self._state = EditorState()
        # Transient, per-call sub-interactions. These are tracked separately
        # from ``_state`` (rather than through EditorState.enter()) because
        # they may legitimately nest inside an outer collection mode set by
        # the caller (e.g. TAB completion while a paste is staged, or Ctrl+R
        # while collecting a heredoc body) and must resume that outer mode
        # afterward rather than forcing NORMAL.
        self._in_reverse_search = False

    @property
    def editor_mode(self) -> EditorMode:
        """Return the editor mode currently in effect.

        Transient sub-interactions (reverse search, an on-screen completion
        menu) take precedence over the outer collection mode a caller may
        have set, since they are what the user is actually looking at.
        """
        if self._in_reverse_search:
            return EditorMode.REVERSE_SEARCH
        if self._completion_displayed:
            return EditorMode.COMPLETION
        return self._state.mode

    def enter_multiline_mode(self, *, opener: str | None = None) -> None:
        """Mark the outer collection mode as MULTILINE for a `py { ... }` block."""
        self._state.enter_multiline(opener=opener)

    def enter_heredoc_mode(
        self, *, opener: str | None = None, delimiters: list[str] | None = None
    ) -> None:
        """Mark the outer collection mode as HEREDOC for pending *delimiters*."""
        self._state.enter_heredoc(opener=opener, delimiters=delimiters)

    def enter_paste_mode(self, payload: str) -> None:
        """Mark the outer collection mode as PASTE_STAGED with *payload*."""
        self._state.enter_paste(payload)

    def clear_editor_state(self) -> None:
        """Return the outer collection mode to NORMAL, clearing its payload."""
        self._state.exit_to_normal()

    def _on_winch(self, signum: int, frame: object) -> None:
        """SIGWINCH handler: signal-safe minimal work only.

        Records that a resize happened; the redraw itself happens later, on
        the next safe iteration of the ``read_line`` event loop.
        """
        del signum, frame
        self._resize_pending = True

    def has_queued_commands(self) -> bool:
        """Return True when pasted commands are waiting to be replayed."""
        return bool(self._command_queue)

    def clear_command_queue(self) -> None:
        """Clear queued commands produced by paste handling."""
        self._command_queue.clear()

    def read_line(
        self,
        prompt: str,
        *,
        history: Sequence[str],
        suggester: AutoSuggester,
        highlighter: LineHighlighter,
        scheme: ColorScheme = DEFAULT_SCHEME,
        options: _Options,
        completer: Completer | None = None,
        line_renderer: Callable[[str], str] | None = None,
        tab_handler: Callable[[LineBuffer], bool] | None = None,
        on_multiline_paste: Callable[[str], Sequence[str] | None] | None = None,
        initial_text: str = "",
        echo_queued: bool = True,
        paste_pending: bool = False,
    ) -> str:
        """Read a command line, raising EOF/KeyboardInterrupt for Ctrl-D/C.

        When *initial_text* is provided the line buffer is pre-filled with that
        text and the cursor is positioned at its end before the first redraw.
        This enables auto-indentation in Python continuation prompts.

        If the internal ``_command_queue`` is non-empty the first queued command
        is returned without any TTY interaction.  This drains paste-queued
        commands efficiently.
        """
        if self._command_queue:
            queued = self._command_queue.pop(0)
            if queued.interrupt:
                raise KeyboardInterrupt
            if queued.eof:
                raise EOFError
            if queued.echo and echo_queued:
                out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
                self._write((prompt + queued.text + "\n"), out_fd)
            return queued.text

        self._start_rows = 0
        in_fd = self.input_fd if self.input_fd is not None else sys.stdin.fileno()
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        old_state = termios.tcgetattr(in_fd)
        _saved_termios[in_fd] = old_state
        tty.setraw(in_fd)
        buffer = LineBuffer()
        if initial_text:
            buffer.set(initial_text)
        decoder = KeyDecoder()
        nav_index: int | None = None
        enabled = bool(options.syntax_highlight) and colors_enabled()
        history_list = list(history)
        suggestion = ""

        # Bracketed paste state.
        # _local_paste_pending is seeded from the caller's paste_pending flag
        # and is updated to True when on_multiline_paste captures a paste
        # mid-session.  This ensures Ctrl+R blocking works even when paste
        # arrives after read_line has started.
        in_paste = False
        paste_buf: list[str] = []
        _local_paste_pending = paste_pending

        # SIGWINCH: the handler only sets a flag (signal-safe minimal work);
        # the actual redraw happens on the next safe editor-loop iteration,
        # below. Registration only succeeds on the main thread of the main
        # interpreter, so background-thread callers (as used throughout the
        # test suite) simply run without live resize handling instead of
        # raising.
        self._resize_pending = False
        old_winch_handler: object | None = None
        winch_installed = False
        if hasattr(signal, "SIGWINCH"):
            try:
                old_winch_handler = signal.signal(signal.SIGWINCH, self._on_winch)
                winch_installed = True
            except ValueError:
                pass

        try:
            self._enable_bracketed_paste(out_fd)
            self._redraw(
                prompt,
                buffer,
                suggestion,
                highlighter,
                scheme,
                enabled,
                line_renderer,
            )
            while True:
                data = os.read(in_fd, 512)
                if not data:
                    raise EOFError
                if self._resize_pending:
                    self._resize_pending = False
                    # The prior row count was computed for the old terminal
                    # width and is invalid at the new one; _redraw() below
                    # recomputes it from the current width. The input buffer
                    # and active editor mode are untouched.
                    self._start_rows = 0
                    self._redraw(
                        prompt,
                        buffer,
                        suggestion,
                        highlighter,
                        scheme,
                        enabled,
                        line_renderer,
                    )
                events = decoder.feed(data)
                if data == b"\x1b":
                    ready, _, _ = select.select([in_fd], [], [], 0.005)
                    if not ready:
                        events.extend(decoder.flush_pending())

                plain_paste = self._plain_paste_text(events)
                if plain_paste is not None:
                    combined = buffer.text + plain_paste
                    cmds = split_paste_commands(combined)
                    if cmds:
                        self._queue_commands(cmds[1:], echo=True)
                        returned_line = cmds[0]
                        self._debug_read_chunk(data, events, buffer, returned=returned_line)
                        self._write("\r" + prompt + returned_line + "\r\n", out_fd)
                        return returned_line
                    self._debug_read_chunk(data, events, buffer, returned=None)
                    continue

                returned_line: str | None = None
                idx = 0
                while idx < len(events):
                    event = events[idx]
                    idx += 1

                    # --- bracketed paste collection ---
                    if in_paste:
                        if event.key is Key.PASTE_END:
                            in_paste = False
                            paste_text, is_multiline = self._classify_bracketed_paste(
                                "".join(paste_buf)
                            )
                            paste_buf = []
                            if is_multiline:
                                diagnostics: Sequence[str] | None = None
                                if on_multiline_paste is not None:
                                    diagnostics = on_multiline_paste(paste_text)
                                _local_paste_pending = True
                                buffer.set("")
                                suggestion = ""
                                if diagnostics:
                                    self._write("\r\n" + "\r\n".join(diagnostics) + "\r\n", out_fd)
                                self._start_rows = 0
                                self._redraw(
                                    prompt,
                                    buffer,
                                    suggestion,
                                    highlighter,
                                    scheme,
                                    enabled,
                                    line_renderer,
                                )
                            elif paste_text:
                                buffer.insert(paste_text)
                                suggestion = self._suggest(
                                    buffer,
                                    history_list,
                                    suggester,
                                    options,
                                )
                                self._redraw(
                                    prompt,
                                    buffer,
                                    suggestion,
                                    highlighter,
                                    scheme,
                                    enabled,
                                    line_renderer,
                                )
                            # Empty paste: continue editing.  A following ENTER
                            # event in the same read batch is explicit user input
                            # outside the bracketed paste payload and may submit.
                        elif event.key is Key.ENTER:
                            paste_buf.append("\n")
                        elif event.key is Key.PRINTABLE and event.text:
                            paste_buf.append(event.text)
                        # Ignore all other keys (control, navigation) inside paste.
                        continue

                    if event.key is Key.PASTE_START:
                        in_paste = True
                        continue

                    # --- normal interactive key processing ---
                    search_initial_events: list[KeyEvent] = []
                    if event.key is Key.CTRL_R:
                        search_initial_events = events[idx:]
                        idx = len(events)
                    result = self._handle_event(
                        event,
                        prompt,
                        buffer,
                        history_list,
                        suggester,
                        highlighter,
                        scheme,
                        enabled,
                        options,
                        nav_index,
                        completer,
                        tab_handler,
                        search_input_fd=in_fd,
                        search_decoder=decoder,
                        search_initial_events=search_initial_events,
                        paste_pending=_local_paste_pending,
                    )
                    if isinstance(result, str):
                        # First complete command: queue any remaining events.
                        self._enqueue_from_events(events[idx:])
                        returned_line = result
                        self._debug_read_chunk(data, events, buffer, returned=returned_line)
                        self._write("\r\n", out_fd)
                        return returned_line
                    nav_index, suggestion = result
                    self._redraw(
                        prompt,
                        buffer,
                        suggestion,
                        highlighter,
                        scheme,
                        enabled,
                        line_renderer,
                    )
                if returned_line is None:
                    self._debug_read_chunk(data, events, buffer, returned=None)
        finally:
            if winch_installed:
                signal.signal(signal.SIGWINCH, old_winch_handler)
            self._resize_pending = False
            self._disable_bracketed_paste(out_fd)
            termios.tcsetattr(in_fd, termios.TCSADRAIN, old_state)
            _saved_termios.pop(in_fd, None)

    def _enqueue_from_events(self, events: list[KeyEvent]) -> None:
        """Collect remaining key events into complete command lines and queue them.

        Reconstructs the text stream from printable characters and ENTER events.
        Uses :func:`pysh.parsing.parser.split_paste_commands` so that quoted newlines
        are not treated as command boundaries.
        """
        parts: list[str] = []
        for event in events:
            if event.key is Key.ENTER:
                parts.append("\n")
            elif event.key in {Key.PASTE_START, Key.PASTE_END}:
                pass  # drop paste markers
            elif event.key is Key.CTRL_C:
                self._queue_commands(split_paste_commands("".join(parts)), echo=True)
                parts = []
                self._command_queue.append(QueuedCommand("", echo=False, interrupt=True))
            elif event.key is Key.CTRL_D:
                self._queue_commands(split_paste_commands("".join(parts)), echo=True)
                parts = []
                self._command_queue.append(QueuedCommand("", echo=False, eof=True))
            elif event.key is Key.PRINTABLE and event.text:
                parts.append(event.text)
            # Navigation, backspace, etc. are meaningless outside a live buffer.
        raw = "".join(parts)
        if raw:
            self._queue_commands(split_paste_commands(raw), echo=True)

    def _queue_commands(self, commands: list[str], *, echo: bool) -> None:
        """Append commands to the replay queue with explicit echo policy."""
        self._command_queue.extend(QueuedCommand(cmd, echo=echo) for cmd in commands if cmd)

    @staticmethod
    def _plain_paste_text(events: list[KeyEvent]) -> str | None:
        """Return plain pasted text for simple multi-line printable chunks.

        VTE may deliver paste bytes without bracketed-paste markers.  When a
        single read contains newline-delimited printable text, handle it
        atomically instead of redrawing character-by-character with suggestions.
        """
        if any(event.key in {Key.PASTE_START, Key.PASTE_END} for event in events):
            return None
        if not any(event.key is Key.ENTER for event in events):
            return None
        if not any(event.key is Key.PRINTABLE and event.text for event in events):
            return None
        parts: list[str] = []
        for event in events:
            if event.key is Key.ENTER:
                parts.append("\n")
            elif event.key is Key.PRINTABLE and event.text:
                parts.append(event.text)
            else:
                return None
        text = "".join(parts)
        return text if "\n" in text else None

    @staticmethod
    def _sanitize_raw_paste_payload(text: str) -> str:
        """Strip terminal-affecting bytes from raw bracketed paste payload."""
        text = _ANSI_CSI_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return "".join(ch for ch in text if ch == "\n" or ord(ch) >= 0x20)

    @classmethod
    def _classify_bracketed_paste(cls, text: str) -> tuple[str, bool]:
        """Return ``(single_line_payload, is_multiline)`` for bracketed paste.

        Bracketed paste is editable input, not an already submitted command
        stream.  The current editor does not support multi-line buffer display,
        so true multiline payloads are captured instead of transformed into
        executable text.  A single final newline from copying one command line
        is accepted and removed.
        """
        sanitized = cls._sanitize_raw_paste_payload(text)
        newline_count = sanitized.count("\n")
        if newline_count == 0:
            return sanitized, False
        if newline_count == 1 and sanitized.endswith("\n"):
            return sanitized[:-1], False
        return sanitized, True

    def _enable_bracketed_paste(self, out_fd: int) -> None:
        """Ask capable terminals to wrap pasted text in bracketed-paste markers."""
        try:
            os.write(out_fd, _BRACKETED_PASTE_ENABLE)
        except OSError:
            pass

    def _disable_bracketed_paste(self, out_fd: int) -> None:
        """Disable bracketed paste mode before leaving raw editor control."""
        try:
            os.write(out_fd, _BRACKETED_PASTE_DISABLE)
        except OSError:
            pass

    def _debug_read_chunk(
        self,
        data: bytes,
        events: list[KeyEvent],
        buffer: LineBuffer,
        *,
        returned: str | None,
    ) -> None:
        """Append raw paste diagnostics when PYSH_PASTE_DEBUG=1 is set."""
        if os.environ.get(_PASTE_DEBUG_ENV) != "1":
            return
        try:
            _PASTE_DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
            event_repr = [
                (event.key.value, len(event.text) if event.text else 0)
                for event in events
            ]
            seen_start = any(event.key is Key.PASTE_START for event in events)
            seen_end = any(event.key is Key.PASTE_END for event in events)
            with _PASTE_DEBUG_PATH.open("a", encoding="utf-8") as stream:
                stream.write("read_chunk\n")
                stream.write(f"raw_len={len(data)}\n")
                stream.write(f"event_keys_and_text_lengths={event_repr!r}\n")
                stream.write(f"paste_start={seen_start} paste_end={seen_end}\n")
                stream.write(f"buffer_before_enter_len={len(buffer.text)}\n")
                stream.write(f"returned_len={len(returned) if returned is not None else None}\n")
                stream.write(f"queued_count={len(self._command_queue)}\n\n")
        except OSError:
            pass

    def _handle_event(
        self,
        event: KeyEvent,
        prompt: str,
        buffer: LineBuffer,
        history: Sequence[str],
        suggester: AutoSuggester,
        highlighter: LineHighlighter,
        scheme: ColorScheme,
        enabled: bool,
        options: _Options,
        nav_index: int | None,
        completer: Completer | None,
        tab_handler: Callable[[LineBuffer], bool] | None,
        *,
        search_input_fd: int | None = None,
        search_decoder: KeyDecoder | None = None,
        search_initial_events: Sequence[KeyEvent] = (),
        paste_pending: bool = False,
    ) -> tuple[int | None, str] | str:
        del highlighter, scheme, enabled
        suggestion = self._suggest(buffer, history, suggester, options)
        if event.key is not Key.TAB:
            self._reset_completion_state()
        if event.key is Key.ENTER:
            return buffer.text
        if event.key is Key.CTRL_C:
            raise KeyboardInterrupt
        if event.key is Key.CTRL_D and not buffer.text:
            raise EOFError
        if event.key is Key.PRINTABLE and event.text:
            buffer.insert(event.text)
            return None, self._suggest(buffer, history, suggester, options)
        if event.key is Key.BACKSPACE:
            buffer.backspace()
        elif event.key is Key.DELETE:
            buffer.delete()
        elif event.key in {Key.LEFT, Key.CTRL_B}:
            buffer.move_left()
        elif event.key in {Key.RIGHT, Key.CTRL_F}:
            if buffer.cursor == len(buffer.text) and suggestion:
                buffer.insert(suggestion)
            else:
                buffer.move_right()
        elif event.key in {Key.HOME, Key.CTRL_A}:
            buffer.move_home()
        elif event.key in {Key.END, Key.CTRL_E}:
            buffer.move_end()
        elif event.key is Key.CTRL_K:
            buffer.kill_to_end()
        elif event.key is Key.CTRL_U:
            buffer.kill_to_start()
        elif event.key is Key.CTRL_W:
            buffer.kill_word_back()
        elif event.key is Key.UP:
            nav_index = self._history_up(buffer, history, nav_index)
        elif event.key is Key.DOWN:
            nav_index = self._history_down(buffer, history, nav_index)
        elif event.key is Key.CTRL_R:
            if paste_pending:
                if colors_enabled():
                    msg = (
                        "\r\n\033[1;33mpysh: pending multiline paste; "
                        "use paste_run or paste_cancel\033[0m\r\n"
                    )
                else:
                    msg = (
                        "\r\npysh: pending multiline paste; "
                        "use paste_run or paste_cancel\r\n"
                    )
                self._write(msg, self.output_fd)
                self._start_rows = 0
            else:
                result = self._reverse_search(
                    buffer,
                    history,
                    prompt,
                    input_fd=search_input_fd,
                    decoder=search_decoder,
                    initial_events=search_initial_events,
                )
                if isinstance(result, str):
                    return result
        elif event.key is Key.CTRL_L:
            self._write("\033[2J\033[H", self.output_fd)
            # Screen is now blank and cursor is at the home position; the
            # previous row count is invalid and would move the cursor up
            # from the wrong origin on the next redraw.
            self._start_rows = 0
        elif event.key is Key.TAB and tab_handler is not None and tab_handler(buffer):
            pass
        elif event.key is Key.TAB and completer is not None:
            self._complete(buffer, completer)
        return nav_index, self._suggest(buffer, history, suggester, options)

    @staticmethod
    def _suggest(
        buffer: LineBuffer,
        history: Sequence[str],
        suggester: AutoSuggester,
        options: _Options,
    ) -> str:
        if not options.autosuggest or buffer.cursor != len(buffer.text):
            return ""
        return suggester.suggest(buffer.text, history) or ""

    @staticmethod
    def _history_up(buffer: LineBuffer, history: Sequence[str], index: int | None) -> int | None:
        if not history:
            return None
        index = len(history) - 1 if index is None else max(0, index - 1)
        buffer.set(history[index])
        return index

    @staticmethod
    def _history_down(buffer: LineBuffer, history: Sequence[str], index: int | None) -> int | None:
        if index is None:
            return None
        if index >= len(history) - 1:
            buffer.set("")
            return None
        index += 1
        buffer.set(history[index])
        return index

    def _reverse_search(
        self,
        buffer: LineBuffer,
        history: Sequence[str],
        prompt: str,
        *,
        input_fd: int | None,
        decoder: KeyDecoder | None,
        initial_events: Sequence[KeyEvent] = (),
    ) -> str | None:
        """Run reverse incremental history search.

        Enter submits the selected match immediately.  Escape or Ctrl+G cancels
        back to the original buffer.  Ctrl+C follows normal prompt interrupt
        semantics by raising ``KeyboardInterrupt``.
        """
        original = buffer.text
        query = ""
        cycle_offset = 0
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        self._in_reverse_search = True

        def current_match() -> str | None:
            matches = self._reverse_search_matches(history, query)
            if not matches:
                return None
            return matches[min(cycle_offset, len(matches) - 1)]

        match = current_match()
        self._render_reverse_search(query, match, out_fd)

        def process_event(event: KeyEvent) -> str | None:
            nonlocal query, cycle_offset, match
            if event.key is Key.PRINTABLE and event.text:
                query += event.text
                cycle_offset = 0
            elif event.key is Key.BACKSPACE:
                query = query[:-1]
                cycle_offset = 0
            elif event.key is Key.CTRL_R:
                matches = self._reverse_search_matches(history, query)
                if matches:
                    cycle_offset = (cycle_offset + 1) % len(matches)
            elif event.key is Key.ENTER:
                match = current_match()
                if match is None:
                    buffer.set(original)
                    self._write("\r\n", out_fd)
                    return ""
                buffer.set(match)
                self._write("\r\n", out_fd)
                return match
            elif event.key is Key.CTRL_C:
                buffer.set(original)
                raise KeyboardInterrupt
            elif event.key in {Key.ESC, Key.CTRL_G}:
                buffer.set(original)
                self._write("\r\n", out_fd)
                return ""
            else:
                return None
            match = current_match()
            self._render_reverse_search(query, match, out_fd)
            return None

        try:
            for event in initial_events:
                outcome = process_event(event)
                if outcome is not None:
                    return outcome or None

            if input_fd is None or decoder is None:
                return None

            while True:
                data = os.read(input_fd, 512)
                if not data:
                    raise EOFError
                events = decoder.feed(data)
                if data == b"\x1b":
                    ready, _, _ = select.select([input_fd], [], [], 0.005)
                    if not ready:
                        events.extend(decoder.flush_pending())

                for event in events:
                    outcome = process_event(event)
                    if outcome is not None:
                        return outcome or None
        finally:
            self._in_reverse_search = False

    @staticmethod
    def _reverse_search_matches(history: Sequence[str], query: str) -> list[str]:
        """Return newest-first history entries matching ``query``."""
        entries = [entry for entry in reversed(history) if entry]
        if not query:
            return entries
        return [entry for entry in entries if query in entry]

    def _render_reverse_search(self, query: str, match: str | None, out_fd: int) -> None:
        """Render reverse-search state on the current terminal line.

        Layout — query is placed LAST so the cursor lands after the query
        text, making it visually clear that typing changes the query, not the
        matched command.

        Color format:
          (reverse-i-search) match: <match>  |  query: <query>_
        Plain format:
          (reverse-i-search) match: <match> | query: <query>

        The substring ``reverse-i-search`` is preserved in both modes so
        existing test assertions that check for that literal remain valid.
        """
        shown_query = self._search_display_text(query)
        shown_match = self._search_display_text(match) if match is not None else "<no match>"
        if colors_enabled():
            lbl   = f"{_SGR_SEARCH_LABEL}(reverse-i-search){_SGR_RESET}"
            m_lbl = f"{_SGR_LABEL}match:{_SGR_RESET}"
            sep   = f"  {_SGR_LABEL}|{_SGR_RESET}  "
            q_lbl = f"{_SGR_LABEL}query:{_SGR_RESET}"
            q_txt = f"{_SGR_SEARCH_QUERY}{shown_query}{_SGR_RESET}"
            line  = f"\r\033[J{lbl} {m_lbl} {shown_match}{sep}{q_lbl} {q_txt}\033[K"
        else:
            line = (
                f"\r\033[J(reverse-i-search) match: {shown_match}"
                f" | query: {shown_query}\033[K"
            )
        self._write(line, out_fd)

    @staticmethod
    def _search_display_text(text: str | None) -> str:
        """Return text safe for one-line terminal search display."""
        if text is None:
            return ""
        visible: list[str] = []
        for char in text:
            code = ord(char)
            if char == "\n":
                visible.append("\\n")
            elif char == "\r":
                visible.append("\\r")
            elif char == "\t":
                visible.append("\\t")
            elif code < 0x20 or code == 0x7F:
                visible.append("?")
            else:
                visible.append(char)
        return "".join(visible)

    def _complete(self, buffer: LineBuffer, completer: Completer) -> None:
        result = completer.raw_completion(buffer.text, buffer.cursor)
        if len(result.candidates) == 1:
            text, cursor = completer.apply_raw_completion(buffer.text, result)
            buffer.set(text, cursor)
            self._reset_completion_state()
        elif result.candidates:
            common = common_completion_prefix(result)
            if common and common != result.prefix:
                text = buffer.text[: result.token_start] + common + buffer.text[result.token_end :]
                buffer.set(text, result.token_start + len(common))
                self._last_completion_buffer = buffer.text
                self._last_completion_result = result
                self._completion_displayed = False
                return
            repeated_same_buffer = self._last_completion_buffer == buffer.text
            repeated_same_result = self._last_completion_result == result
            if not self._completion_displayed or not (repeated_same_buffer and repeated_same_result):
                out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
                terminal_width = self._terminal_width(out_fd)
                self._write(
                    "\r\n"
                    + self._format_completion_menu(
                        result.display_candidates, terminal_width=terminal_width
                    )
                    + "\r\n",
                    self.output_fd,
                )
                self._start_rows = 0
            self._last_completion_buffer = buffer.text
            self._last_completion_result = result
            self._completion_displayed = True

    def _reset_completion_state(self) -> None:
        """Forget repeated-TAB state after non-TAB input."""
        self._last_completion_buffer = None
        self._last_completion_result = None
        self._completion_displayed = False

    @staticmethod
    def _format_completion_menu(
        candidates: Sequence[str],
        *,
        terminal_width: int = 80,
        max_rows: int = _MAX_COMPLETION_MENU_ROWS,
    ) -> str:
        """Return a compact, deterministic, viewport-bounded candidate menu.

        Candidate order, ranking and deduplication are the caller's concern
        (this only decides how many of the already-ranked candidates fit in
        ``max_rows`` rows at the current ``terminal_width``). When some
        candidates do not fit, an exact hidden-count summary line is
        appended beyond the row budget so nothing is silently dropped.
        """
        if not candidates:
            return ""
        column_width = (
            max(_display_width(candidate) for candidate in candidates)
            + _COMPLETION_MENU_COLUMN_SPACING
        )
        columns = max(1, terminal_width // column_width)
        max_visible = max_rows * columns
        visible = candidates[:max_visible]
        hidden = len(candidates) - len(visible)
        lines: list[str] = []
        for idx in range(0, len(visible), columns):
            row = visible[idx : idx + columns]
            padded = "".join(
                candidate + " " * max(0, column_width - _display_width(candidate))
                for candidate in row
            )
            lines.append(padded.rstrip())
        if hidden > 0:
            lines.append(f"… {hidden} more candidates — type more characters to narrow")
        return "\r\n".join(lines)

    def _redraw(
        self,
        prompt: str,
        buffer: LineBuffer,
        suggestion: str,
        highlighter: LineHighlighter,
        scheme: ColorScheme,
        enabled: bool,
        line_renderer: Callable[[str], str] | None,
    ) -> None:
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        width = self._terminal_width(out_fd)
        prompt_width = _visible_width(prompt)
        if line_renderer is not None:
            rendered = line_renderer(buffer.text)
        else:
            rendered = highlighter.render(buffer.text, scheme, enabled=enabled)
        suggestion_text = ""
        if suggestion:
            suggestion_text = f"{scheme.suggestion}{suggestion}{scheme.reset}" if enabled else suggestion
        total_width = prompt_width + _display_width(buffer.text + suggestion)
        cursor_width = prompt_width + buffer.cursor_width()
        rows = max(0, total_width // max(1, width))
        cursor_rows = cursor_width // max(1, width)
        cursor_col = cursor_width % max(1, width)
        prefix = "\r"
        if self._start_rows:
            prefix += f"\033[{self._start_rows}A"
        line = f"{prefix}\033[J{prompt}{rendered}{suggestion_text}\033[K"
        if rows > cursor_rows:
            line += f"\033[{rows - cursor_rows}A"
        line += f"\r\033[{cursor_col}C"
        self._write(line, out_fd)
        self._start_rows = rows

    @staticmethod
    def _terminal_width(fd: int) -> int:
        try:
            return max(20, os.get_terminal_size(fd).columns)
        except OSError:
            return 80

    @staticmethod
    def _write(text: str, fd: int | None) -> None:
        out_fd = fd if fd is not None else sys.stdout.fileno()
        os.write(out_fd, text.encode("utf-8", errors="replace"))
