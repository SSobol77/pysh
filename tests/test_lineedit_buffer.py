# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_lineedit_buffer.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

from pysh.editor.lineedit.buffer import LineBuffer, _display_width


def test_edit_operations_and_bounds() -> None:
    buf = LineBuffer()
    buf.insert("abc")
    buf.move_left()
    buf.backspace()
    assert (buf.text, buf.cursor) == ("ac", 1)
    buf.delete()
    assert (buf.text, buf.cursor) == ("a", 1)
    buf.move_right()
    assert buf.cursor == 1
    buf.move_home()
    buf.insert("x")
    buf.move_end()
    buf.insert("yz")
    assert (buf.text, buf.cursor) == ("xayz", 4)


def test_kill_operations() -> None:
    buf = LineBuffer("alpha beta  gamma", 17)
    buf.kill_word_back()
    assert (buf.text, buf.cursor) == ("alpha beta  ", 12)
    buf.kill_to_start()
    assert (buf.text, buf.cursor) == ("", 0)
    buf.set("abc", 1)
    buf.kill_to_end()
    assert (buf.text, buf.cursor) == ("a", 1)


def test_display_width() -> None:
    assert _display_width("abc") == 3
    assert _display_width("界") == 2
    assert _display_width("e\u0301") == 1

