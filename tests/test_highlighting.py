# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_highlighting.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the highlighting/color helper module."""
from __future__ import annotations

import io

from pysh.highlighting import (
    TokenKind,
    classify,
    colors_enabled,
    diagnostic,
    paint,
    render,
    tokenize,
)


def test_colors_disabled_when_not_tty() -> None:
    buf = io.StringIO()
    assert colors_enabled(buf, {"TERM": "xterm-256color"}) is False


def test_colors_disabled_when_no_color_set() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    assert colors_enabled(FakeTTY(), {"TERM": "xterm", "NO_COLOR": ""}) is False


def test_colors_disabled_when_term_dumb() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    assert colors_enabled(FakeTTY(), {"TERM": "dumb"}) is False


def test_colors_enabled_when_tty_and_term_ok() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    assert colors_enabled(FakeTTY(), {"TERM": "xterm-256color"}) is True


def test_pysh_color_zero_disables_colors() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    assert colors_enabled(FakeTTY(), {"TERM": "xterm", "PYSH_COLOR": "0"}) is False


def test_pysh_color_always_forces_colors_without_tty() -> None:
    assert colors_enabled(io.StringIO(), {"TERM": "dumb", "PYSH_COLOR": "always"}) is True


def test_no_color_overrides_pysh_color_always() -> None:
    assert (
        colors_enabled(
            io.StringIO(),
            {"TERM": "xterm", "PYSH_COLOR": "always", "NO_COLOR": "1"},
        )
        is False
    )


def test_paint_returns_plain_when_disabled() -> None:
    assert paint("hello", "builtin", enabled=False) == "hello"


def test_paint_wraps_with_ansi_when_enabled() -> None:
    painted = paint("hello", "builtin", enabled=True)
    assert painted.startswith("\033[")
    assert painted.endswith("\033[0m")
    assert "hello" in painted


def test_paint_unknown_kind_passes_through() -> None:
    assert paint("hi", "nonexistent", enabled=True) == "hi"


def test_tokenize_splits_words_and_operators() -> None:
    tokens = tokenize("ls -la | head -3")
    assert tokens == ["ls", "-la", "|", "head", "-3"]


def test_tokenize_preserves_quoted_strings() -> None:
    tokens = tokenize('echo "hello world" foo')
    assert tokens == ["echo", '"hello world"', "foo"]


def test_tokenize_keeps_pipe_inside_quotes() -> None:
    tokens = tokenize('echo "a | b"')
    assert tokens == ["echo", '"a | b"']


def test_tokenize_handles_redirections() -> None:
    tokens = tokenize("ls > out.txt")
    assert ">" in tokens
    assert "out.txt" in tokens


def test_tokenize_handles_comments() -> None:
    tokens = tokenize("ls -la  # show files")
    assert tokens[-1].startswith("#")


def test_classify_marks_builtin() -> None:
    classified = classify(
        tokenize("cd /tmp"),
        builtins=frozenset({"cd"}),
        aliases={},
    )
    assert classified[0].kind is TokenKind.BUILTIN
    assert classified[0].text == "cd"


def test_classify_marks_alias() -> None:
    classified = classify(
        tokenize("ll -h"),
        builtins=frozenset(),
        aliases={"ll": "ls -la"},
    )
    assert classified[0].kind is TokenKind.ALIAS


def test_classify_marks_external() -> None:
    classified = classify(
        tokenize("/usr/bin/grep foo"),
        builtins=frozenset(),
        aliases={},
    )
    assert classified[0].kind is TokenKind.EXTERNAL


def test_classify_marks_operators_and_redirections() -> None:
    classified = classify(
        tokenize("ls | grep foo > out.txt"),
        builtins=frozenset(),
        aliases={},
    )
    kinds = [t.kind for t in classified]
    assert TokenKind.OPERATOR in kinds
    assert TokenKind.REDIRECTION in kinds


def test_render_disabled_produces_no_ansi() -> None:
    classified = classify(
        tokenize("ls -la"),
        builtins=frozenset(),
        aliases={},
    )
    rendered = render(classified, enabled=False)
    assert "\033[" not in rendered
    assert "ls" in rendered


def test_render_enabled_emits_ansi() -> None:
    classified = classify(
        tokenize("ls -la"),
        builtins=frozenset(),
        aliases={},
    )
    rendered = render(classified, enabled=True)
    assert "\033[" in rendered


def test_diagnostic_disabled_returns_message_unchanged() -> None:
    assert diagnostic("oops", "error", enabled=False) == "oops"


def test_diagnostic_enabled_wraps_in_color() -> None:
    out = diagnostic("oops", "error", enabled=True)
    assert "oops" in out
    assert "\033[" in out
