# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/lineedit/reader.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Raw-mode line reader for capable Unix TTYs.

The reader redraws the command line in place and handles multi-row prompts
conservatively: it returns to the logical start row, clears from cursor to end
of screen, reprints the prompt and buffer, then repositions the cursor by
terminal column math. This avoids stale prompt fragments and scrollback
corruption even when a terminal resizes while editing.
"""
from __future__ import annotations

import atexit
import os
import select
import sys
import termios
import tty
from collections.abc import Sequence
from typing import Protocol

from pysh.completion import Completer
from pysh.highlighting import colors_enabled
from pysh.lineedit.autosuggest import AutoSuggester
from pysh.lineedit.buffer import LineBuffer, _display_width
from pysh.lineedit.highlight import DEFAULT_SCHEME, ColorScheme, LineHighlighter
from pysh.lineedit.keys import Key, KeyDecoder, KeyEvent


class _Options(Protocol):
    autosuggest: bool
    syntax_highlight: bool


_saved_termios: dict[int, list[object]] = {}


def _restore_saved_termios() -> None:
    for fd, state in list(_saved_termios.items()):
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, state)
        except termios.error:
            pass
        _saved_termios.pop(fd, None)


atexit.register(_restore_saved_termios)


class RawLineReader:
    """Read one editable line from a raw-mode TTY."""

    def __init__(self, *, input_fd: int | None = None, output_fd: int | None = None) -> None:
        self.input_fd = input_fd
        self.output_fd = output_fd
        self._start_rows = 0

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
    ) -> str:
        """Read a command line, raising EOF/KeyboardInterrupt for Ctrl-D/C."""
        in_fd = self.input_fd if self.input_fd is not None else sys.stdin.fileno()
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        old_state = termios.tcgetattr(in_fd)
        _saved_termios[in_fd] = old_state
        tty.setraw(in_fd)
        buffer = LineBuffer()
        decoder = KeyDecoder()
        nav_index: int | None = None
        enabled = bool(options.syntax_highlight) and colors_enabled()
        history_list = list(history)
        suggestion = ""
        try:
            self._redraw(prompt, buffer, suggestion, highlighter, scheme, enabled)
            while True:
                data = os.read(in_fd, 32)
                if not data:
                    raise EOFError
                events = decoder.feed(data)
                if data == b"\x1b":
                    ready, _, _ = select.select([in_fd], [], [], 0.005)
                    if not ready:
                        events.extend(decoder.flush_pending())
                for event in events:
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
                    )
                    if isinstance(result, str):
                        self._write("\r\n", out_fd)
                        return result
                    nav_index, suggestion = result
                    self._redraw(prompt, buffer, suggestion, highlighter, scheme, enabled)
        finally:
            termios.tcsetattr(in_fd, termios.TCSADRAIN, old_state)
            _saved_termios.pop(in_fd, None)

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
        start = buffer.text.rfind(" ", 0, buffer.cursor) + 1
        prefix = buffer.text[start : buffer.cursor]
        matches: list[str] = []
        if hasattr(completer, "complete_line"):
            matches = completer.complete_line(buffer.text, buffer.cursor)
        else:
            state = 0
            while True:
                match = completer.complete(prefix, state)
                if match is None:
                    break
                matches.append(match)
                state += 1
        if len(matches) == 1:
            buffer.set(buffer.text[:start] + matches[0] + buffer.text[buffer.cursor :])
            buffer.cursor = start + len(matches[0])
        elif matches:
            self._write("\r\n" + "  ".join(matches) + "\r\n", self.output_fd)

    def _redraw(
        self,
        prompt: str,
        buffer: LineBuffer,
        suggestion: str,
        highlighter: LineHighlighter,
        scheme: ColorScheme,
        enabled: bool,
    ) -> None:
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        width = self._terminal_width(out_fd)
        prompt_width = _display_width(prompt)
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
