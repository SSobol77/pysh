# SPDX-License-Identifier: GPL-2.0-only
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
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, ColorScheme, LineHighlighter
from pysh.editor.lineedit.keys import Key, KeyDecoder, KeyEvent
from pysh.parsing.parser import split_paste_commands


class _Options(Protocol):
    autosuggest: bool
    syntax_highlight: bool


_saved_termios: dict[int, list[object]] = {}
_BRACKETED_PASTE_ENABLE = b"\x1b[?2004h"
_BRACKETED_PASTE_DISABLE = b"\x1b[?2004l"
_PASTE_DEBUG_ENV = "PYSH_PASTE_DEBUG"
_PASTE_DEBUG_PATH = Path("logs") / "pysh-paste-debug.log"


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

    def has_queued_commands(self) -> bool:
        """Return True when pasted commands are waiting to be replayed."""
        return bool(self._command_queue)

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

        # Bracketed paste state
        in_paste = False
        paste_buf: list[str] = []

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
    ) -> tuple[int | None, str] | str:
        del prompt, highlighter, scheme, enabled
        suggestion = self._suggest(buffer, history, suggester, options)
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
            self._reverse_search(buffer, history)
        elif event.key is Key.CTRL_L:
            self._write("\033[2J\033[H", self.output_fd)
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

    @staticmethod
    def _reverse_search(buffer: LineBuffer, history: Sequence[str]) -> None:
        needle = buffer.text
        if not needle:
            return
        for entry in reversed(history):
            if needle in entry:
                buffer.set(entry)
                return

    def _complete(self, buffer: LineBuffer, completer: Completer) -> None:
        result = completer.raw_completion(buffer.text, buffer.cursor)
        if len(result.candidates) == 1:
            text, cursor = completer.apply_raw_completion(buffer.text, result)
            buffer.set(text, cursor)
        elif result.candidates:
            self._write(
                "\r\n" + "  ".join(result.display_candidates) + "\r\n",
                self.output_fd,
            )
            self._start_rows = 0

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
