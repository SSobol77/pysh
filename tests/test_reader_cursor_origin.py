# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_reader_cursor_origin.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""PTY regression: the command-line cursor origin must account for an ANSI-
colored prompt.

Root cause of the original bug: PyShell._prompt() returns the command symbol
wrapped in ANSI SGR color codes (e.g. "\x1b[97m>\x1b[0m "). The raw reader
measured prompt width with a plain display-width function that counts every
byte of the escape sequence as a visible column, so the cursor started ~11
columns too far right ("starts at position 11 instead of 1"). The reader must
measure the *visible* width of the prompt, ignoring CSI sequences.
"""
from __future__ import annotations

import os
import re
import select
import struct
import sys
import termios
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from pysh.editor.lineedit.autosuggest import AutoSuggester  # noqa: E402
from pysh.editor.lineedit.buffer import _display_width  # noqa: E402
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter  # noqa: E402
from pysh.editor.lineedit.reader import RawLineReader, _visible_width  # noqa: E402

pytestmark = pytest.mark.skipif(not hasattr(os, "openpty"), reason="pty unavailable")


class _Opts:
    def __init__(self, autosuggest: bool = False, syntax_highlight: bool = False) -> None:
        self.autosuggest = autosuggest
        self.syntax_highlight = syntax_highlight


class _Screen:
    """VT100-style grid with DEC pending-wrap to replay reader output faithfully."""

    def __init__(self, cols: int) -> None:
        self.cols = cols
        self.row = 0
        self.col = 0
        self._pending_wrap = False

    def _putc(self, ch: str) -> None:
        w = _display_width(ch)
        if self._pending_wrap:
            self.row += 1
            self.col = 0
            self._pending_wrap = False
        if self.col + w > self.cols:
            self.row += 1
            self.col = 0
        self.col += w
        if self.col >= self.cols:
            self.col = self.cols
            self._pending_wrap = True

    def feed(self, text: str) -> None:
        csi = re.compile(r"\x1b\[(\d*)([A-Za-z])")
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\r":
                self.col = 0
                self._pending_wrap = False
                i += 1
                continue
            if ch == "\n":
                self.row += 1
                self.col = 0
                self._pending_wrap = False
                i += 1
                continue
            if ch == "\x1b":
                m = csi.match(text, i)
                if m:
                    num = int(m.group(1)) if m.group(1) else 0
                    cmd = m.group(2)
                    self._pending_wrap = False
                    if cmd == "A":
                        self.row = max(0, self.row - max(1, num))
                    elif cmd == "B":
                        self.row += max(1, num)
                    elif cmd == "C":
                        self.col = min(self.cols, self.col + num)
                    elif cmd == "D":
                        self.col = max(0, self.col - num)
                    elif cmd == "H":
                        self.row = 0
                        self.col = 0
                    i = m.end()
                    continue
                i += 1
                continue
            self._putc(ch)
            i += 1


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    import fcntl

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _drain(fd: int, timeout: float = 0.5) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                break
            data = os.read(fd, 4096)
            if not data:
                break
        except OSError:
            break
        chunks.append(data)
        timeout = 0.05
    return b"".join(chunks)


def _run(cols: int, prompt: str, info_line: str, typed: bytes) -> bytes:
    """Print info line, run read_line with ``prompt``, type ``typed``; return
    the bytes emitted in response to the keystroke (the redraw to evaluate)."""
    master, slave = os.openpty()
    _set_winsize(slave, 24, cols)
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(master)
            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            if info_line:
                os.write(1, (info_line + "\n").encode("utf-8"))
            reader = RawLineReader(input_fd=0, output_fd=1)
            highlighter = LineHighlighter(builtins=frozenset({"echo", "cd"}))
            try:
                reader.read_line(
                    prompt,
                    history=[],
                    suggester=AutoSuggester(),
                    highlighter=highlighter,
                    scheme=DEFAULT_SCHEME,
                    options=_Opts(),
                )
            except (EOFError, KeyboardInterrupt):
                pass
        finally:
            os._exit(0)
    os.close(slave)
    _drain(master, 0.5)  # info + initial redraw
    os.write(master, typed)
    after = _drain(master, 0.5)
    try:
        os.write(master, b"\r")
    except OSError:
        pass
    _drain(master, 0.3)
    os.waitpid(pid, 0)
    try:
        os.close(master)
    except OSError:
        pass
    return after


# The exact prompt PyShell hands to the reader when prompt colors are on:
# a green/white ">" wrapped in SGR plus a trailing space. Visible width 2.
COLORED_PROMPT = "\x1b[97m>\x1b[0m "
PLAIN_PROMPT = "> "
EXPECTED_ORIGIN = 2  # display width of "> "


def test_visible_width_ignores_ansi() -> None:
    assert _visible_width(COLORED_PROMPT) == 2
    assert _visible_width(PLAIN_PROMPT) == 2
    assert _visible_width("\x1b[38;2;0;128;0m> \x1b[0m") == 2


def test_colored_prompt_cursor_origin_wide() -> None:
    # Wide terminal, nothing wraps: the typed char must land at column 3
    # (origin 2 for "> " plus 1 for the char), NOT column 12.
    out = _run(120, COLORED_PROMPT, "", b"x")
    screen = _Screen(120)
    screen.feed(out.decode("utf-8", errors="replace"))
    assert screen.col == EXPECTED_ORIGIN + 1, f"expected 3, got {screen.col}"


def test_colored_prompt_matches_plain_prompt() -> None:
    # The colored prompt must position the cursor identically to the plain one.
    out_color = _run(80, COLORED_PROMPT, "", b"x")
    out_plain = _run(80, PLAIN_PROMPT, "", b"x")
    sc_color = _Screen(80)
    sc_color.feed(out_color.decode("utf-8", errors="replace"))
    sc_plain = _Screen(80)
    sc_plain.feed(out_plain.decode("utf-8", errors="replace"))
    assert sc_color.col == sc_plain.col == EXPECTED_ORIGIN + 1


def test_colored_prompt_with_wrapping_info_line() -> None:
    # Long info line wraps at 40 cols; colored prompt still starts at column 3.
    info = (
        "(.venv) PySH ssobol@sun:~/Code/Project_PySH/pysh/pysh "
        "git:main py3.13 uv0.11.17 ruff0.15.15 [127]"
    )
    out = _run(40, COLORED_PROMPT, info, b"x")
    screen = _Screen(40)
    screen.feed(out.decode("utf-8", errors="replace"))
    assert screen.col == EXPECTED_ORIGIN + 1, f"expected 3, got {screen.col}"
