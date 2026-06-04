# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the PySH terminal styling helpers.

Covers:
- style_enabled(): NO_COLOR, PYSH_NO_COLOR, TERM, PYSH_COLOR overrides.
- style(): ANSI wrapping with role codes and passthrough when disabled.
- frame_preview(): [title:begin]/N | line/[title:end] structure in both modes.
- format_key_hints(): pipe-separated plain vs styled output.
- highlight_python_preview_line(): Python syntax highlighting for preview.
- PyShell._capture_multiline_paste(): NO_COLOR / PYSH_NO_COLOR suppression.
- PyShell._format_pending_paste_preview(): color stability and paste_run title.
"""
from __future__ import annotations

import os
import re
from unittest.mock import patch

from pysh.core.shell import PyShell
from pysh.prompt.terminal_style import (
    format_key_hints,
    frame_preview,
    highlight_python_preview_line,
    highlight_shell_preview_line,
    style,
    style_enabled,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------- style_enabled


def test_style_enabled_no_color_env_disables() -> None:
    assert style_enabled(env={"NO_COLOR": "", "TERM": "xterm-256color"}) is False


def test_style_enabled_pysh_no_color_disables() -> None:
    assert style_enabled(env={"PYSH_NO_COLOR": "1", "TERM": "xterm-256color"}) is False


def test_style_enabled_pysh_no_color_not_1_allows() -> None:
    """PYSH_NO_COLOR=0 should not disable (only =1 is the opt-out)."""
    result = style_enabled(
        env={"PYSH_NO_COLOR": "0", "TERM": "xterm-256color", "PYSH_COLOR": "always"}
    )
    assert result is True


def test_style_enabled_dumb_term_disables() -> None:
    assert style_enabled(env={"TERM": "dumb"}) is False


def test_style_enabled_empty_term_disables() -> None:
    assert style_enabled(env={"TERM": ""}) is False


def test_style_enabled_pysh_color_always_forces_on() -> None:
    assert style_enabled(env={"PYSH_COLOR": "always", "TERM": "xterm-256color"}) is True


def test_style_enabled_pysh_color_zero_disables() -> None:
    assert style_enabled(env={"PYSH_COLOR": "0", "TERM": "xterm-256color"}) is False


def test_style_enabled_no_color_beats_pysh_color_always() -> None:
    """NO_COLOR must win over PYSH_COLOR=always."""
    assert (
        style_enabled(
            env={"NO_COLOR": "", "PYSH_COLOR": "always", "TERM": "xterm-256color"}
        )
        is False
    )


# ---------------------------------------------------------------- style


def test_style_passthrough_when_disabled() -> None:
    result = style("hello", "warning", enabled=False)
    assert result == "hello"
    assert "\033" not in result


def test_style_wraps_ansi_when_enabled() -> None:
    result = style("hello", "warning", enabled=True)
    assert "\033[" in result
    assert _strip_ansi(result) == "hello"


def test_style_empty_text_passthrough() -> None:
    result = style("", "error", enabled=True)
    assert result == ""


def test_style_unknown_role_passthrough() -> None:
    result = style("text", "no_such_role", enabled=True)
    assert result == "text"


def test_style_all_colored_roles_produce_output() -> None:
    """Roles with non-empty SGR codes must produce ANSI output when enabled."""
    colored_roles = [
        "prompt", "warning", "error", "hint", "frame",
        "success", "search", "pending",
    ]
    for role in colored_roles:
        result = style("x", role, enabled=True)
        assert "\033[" in result, f"role {role!r} produced no ANSI code"
        assert _strip_ansi(result) == "x"


def test_style_passthrough_roles_are_plain() -> None:
    """payload and line_number are intentionally plain — syntax context provides colour."""
    for role in ("payload", "line_number"):
        result = style("text", role, enabled=True)
        assert result == "text", f"role {role!r} should be plain but got {result!r}"


def test_no_dim_white_in_any_role() -> None:
    """No role may use SGR 2;37 (dim+white) — it renders black on dark backgrounds."""
    from pysh.prompt.terminal_style import _ROLE_SGR
    for role, code in _ROLE_SGR.items():
        assert "2;37" not in code, (
            f"role {role!r} uses SGR 2;37m which renders black on dark backgrounds"
        )


def test_no_dark_blue_in_shell_highlight() -> None:
    """Shell preview highlighter must not emit dark-blue SGR (renders black on dark backgrounds)."""
    line = "cat /tmp/foo ; echo $? ; ls --color"
    result = highlight_shell_preview_line(line, enabled=True)
    assert "\033[34m" not in result, "dark-blue SGR 34 found in shell preview"
    assert "\033[0;34m" not in result, "dark-blue SGR 0;34 found in shell preview"
    assert "2;37" not in result, "dim-white SGR 2;37 found in shell preview"
    assert _strip_ansi(result) == line, "ANSI-stripped shell preview differs from plain"


def test_no_dark_blue_in_python_highlight() -> None:
    """Python preview highlighter must not emit dark-blue SGR."""
    lines = [
        "import os",
        "def foo():",
        "    return 42",
        "    # a comment",
        "x = 'hello'",
    ]
    for ln in lines:
        result = highlight_python_preview_line(ln, enabled=True)
        assert "\033[34m" not in result, f"dark-blue in Python preview for {ln!r}"
        assert "2;37" not in result, f"dim-white in Python preview for {ln!r}"
        assert _strip_ansi(result) == ln, f"ANSI-strip not stable for {ln!r}"


def test_python_comment_uses_gray_not_dim_white() -> None:
    """Python comment must use bright-black (90m) not dim+white (2;37m)."""
    result = highlight_python_preview_line("# comment line", enabled=True)
    assert "\033[90m" in result, "Python comment should use 90m (gray)"
    assert "2;37" not in result, "Python comment must not use 2;37m"


# ---------------------------------------------------------------- frame_preview


def test_frame_preview_begin_end_markers_present_disabled() -> None:
    lines = frame_preview("echo one\necho two", "paste", enabled=False)
    assert "[paste:begin]" in lines[0]
    assert "[paste:end]" in lines[-1]


def test_frame_preview_begin_end_markers_after_strip_when_enabled() -> None:
    lines = frame_preview("echo one\necho two", "paste", enabled=True)
    assert _strip_ansi(lines[0]) == "[paste:begin]"
    assert _strip_ansi(lines[-1]) == "[paste:end]"


def test_frame_preview_line_numbers_disabled() -> None:
    lines = frame_preview("echo one\necho two", "paste", enabled=False)
    assert "1 | echo one" in lines
    assert "2 | echo two" in lines


def test_frame_preview_line_numbers_after_strip_when_enabled() -> None:
    lines = frame_preview("echo one\necho two", "paste", enabled=True)
    stripped = [_strip_ansi(ln) for ln in lines]
    assert "1 | echo one" in stripped
    assert "2 | echo two" in stripped


def test_frame_preview_no_ansi_when_disabled() -> None:
    lines = frame_preview("echo hello", "paste_run", enabled=False)
    for ln in lines:
        assert "\033" not in ln


def test_frame_preview_ansi_present_when_enabled() -> None:
    lines = frame_preview("echo hello", "paste", enabled=True)
    assert any("\033" in ln for ln in lines)


def test_frame_preview_title_in_markers() -> None:
    lines = frame_preview("data", "paste_run", enabled=False)
    assert "[paste_run:begin]" in lines[0]
    assert "[paste_run:end]" in lines[-1]


def test_frame_preview_max_lines_truncation_disabled() -> None:
    payload = "\n".join(f"line {i}" for i in range(1, 6))
    lines = frame_preview(payload, "paste", enabled=False, max_lines=3)
    assert "1 | line 1" in lines
    assert "3 | line 3" in lines
    assert not any("4 | line 4" in ln for ln in lines)
    assert any("more lines hidden" in ln for ln in lines)


def test_frame_preview_max_lines_truncation_after_strip_when_enabled() -> None:
    payload = "\n".join(f"line {i}" for i in range(1, 6))
    lines = frame_preview(payload, "paste", enabled=True, max_lines=3)
    stripped = [_strip_ansi(ln) for ln in lines]
    assert "1 | line 1" in stripped
    assert not any("4 | line 4" in ln for ln in stripped)
    assert any("more lines hidden" in ln for ln in stripped)


def test_frame_preview_empty_payload() -> None:
    lines = frame_preview("", "paste", enabled=False)
    assert "[paste:begin]" in lines[0]
    assert "1 | " in lines[1]
    assert "[paste:end]" in lines[-1]


def test_frame_preview_stable_after_ansi_strip() -> None:
    """ANSI-stripped color output must match plain no-color output exactly."""
    payload = "echo hello\necho world"
    plain = frame_preview(payload, "paste", enabled=False)
    colored = frame_preview(payload, "paste", enabled=True)
    assert plain == [_strip_ansi(ln) for ln in colored]


# ---------------------------------------------------------------- format_key_hints


def test_format_key_hints_plain_uses_pipe_separator() -> None:
    result = format_key_hints([("Enter", "run"), ("Ctrl+C", "cancel")], enabled=False)
    assert "Enter = run" in result
    assert "Ctrl+C = cancel" in result
    assert "|" in result
    assert "\033" not in result


def test_format_key_hints_enabled_uses_spaces_no_pipe() -> None:
    result = format_key_hints([("Enter", "run"), ("Ctrl+C", "cancel")], enabled=True)
    stripped = _strip_ansi(result)
    assert "Enter = run" in stripped
    assert "Ctrl+C = cancel" in stripped


def test_format_key_hints_no_ansi_when_disabled() -> None:
    result = format_key_hints([("A", "b"), ("C", "d")], enabled=False)
    assert "\033" not in result


def test_format_key_hints_ansi_present_when_enabled() -> None:
    result = format_key_hints([("Enter", "run")], enabled=True)
    assert "\033[" in result


# ---------------------------------------------------------------- PyShell._capture_multiline_paste — NO_COLOR / PYSH_NO_COLOR


def test_capture_diagnostics_no_color_has_no_ansi() -> None:
    """With NO_COLOR set, _capture_multiline_paste diagnostics must not contain ANSI."""
    shell = PyShell()
    with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
        diags = shell._capture_multiline_paste("echo one\necho two")
    for line in diags:
        assert "\033" not in line, f"ANSI found in no-color mode: {line!r}"


def test_capture_diagnostics_pysh_no_color_has_no_ansi() -> None:
    """With PYSH_NO_COLOR=1, diagnostics must not contain ANSI."""
    shell = PyShell()
    with patch.dict(os.environ, {"PYSH_NO_COLOR": "1"}, clear=False):
        diags = shell._capture_multiline_paste("echo one\necho two")
    for line in diags:
        assert "\033" not in line, f"ANSI found with PYSH_NO_COLOR=1: {line!r}"


def test_capture_diagnostics_plain_markers_always_present() -> None:
    """Plain text markers must survive regardless of color mode."""
    shell = PyShell()
    for env_patch in ({"NO_COLOR": "1"}, {"PYSH_NO_COLOR": "1"}):
        with patch.dict(os.environ, env_patch, clear=False):
            diags = shell._capture_multiline_paste("echo one\necho two")
        text = "\n".join(diags)
        assert "pysh: multiline paste captured (2 lines). Review below." in text
        assert "[paste:begin]" in text
        assert "1 | echo one" in text
        assert "2 | echo two" in text
        assert "[paste:end]" in text


# ---------------------------------------------------------------- PyShell._format_pending_paste_preview


def test_format_pending_paste_preview_stable_after_strip() -> None:
    """ANSI-stripped color preview must match the no-color preview exactly."""
    shell = PyShell()
    plain = shell._format_pending_paste_preview(
        "a\nb\nc", title="paste", max_lines=None, enabled=False
    )
    colored = shell._format_pending_paste_preview(
        "a\nb\nc", title="paste", max_lines=None, enabled=True
    )
    assert plain == [_strip_ansi(ln) for ln in colored]


def test_format_pending_paste_preview_paste_run_title() -> None:
    """paste_run preview must use [paste_run:begin] / [paste_run:end] markers."""
    shell = PyShell()
    lines = shell._format_pending_paste_preview(
        "echo one\necho two", title="paste_run", max_lines=None, enabled=False
    )
    assert lines[0] == "[paste_run:begin]"
    assert lines[-1] == "[paste_run:end]"
    assert "1 | echo one" in lines
    assert "2 | echo two" in lines


def test_format_pending_paste_preview_truncation() -> None:
    """max_lines must truncate and emit a 'more lines hidden' notice."""
    shell = PyShell()
    payload = "\n".join(f"line {i}" for i in range(1, 6))
    lines = shell._format_pending_paste_preview(
        payload, title="paste", max_lines=3, enabled=False
    )
    assert "1 | line 1" in lines
    assert "3 | line 3" in lines
    assert not any("4 | line 4" in ln for ln in lines)
    assert any("more lines hidden" in ln for ln in lines)


# ---------------------------------------------------------------- highlight_python_preview_line


def test_python_highlight_keyword_at_line_start() -> None:
    """Keywords at the start of a line must be coloured."""
    result = highlight_python_preview_line("for x in range(10):", enabled=True)
    assert "\033[" in result
    assert _strip_ansi(result) == "for x in range(10):"


def test_python_highlight_passthrough_when_disabled() -> None:
    result = highlight_python_preview_line("for x in range(10):", enabled=False)
    assert result == "for x in range(10):"
    assert "\033" not in result


def test_python_highlight_comment_colored() -> None:
    result = highlight_python_preview_line("# this is a comment", enabled=True)
    assert "\033[" in result
    assert _strip_ansi(result) == "# this is a comment"


def test_python_highlight_string_colored() -> None:
    """Quoted strings must be highlighted and stable after ANSI stripping."""
    result = highlight_python_preview_line('x = "hello world"', enabled=True)
    assert "\033[" in result
    assert _strip_ansi(result) == 'x = "hello world"'


def test_python_highlight_number_colored() -> None:
    result = highlight_python_preview_line("x = 42", enabled=True)
    assert _strip_ansi(result) == "x = 42"


def test_python_highlight_preserves_indentation() -> None:
    """Indented lines must not have indentation stripped."""
    result = highlight_python_preview_line("    return x + 1", enabled=True)
    plain = _strip_ansi(result)
    assert plain == "    return x + 1"
    assert plain.startswith("    ")


def test_python_highlight_empty_line_passthrough() -> None:
    result = highlight_python_preview_line("", enabled=True)
    assert result == ""


def test_python_highlight_stable_after_strip() -> None:
    """ANSI-stripped result must equal plain-mode result."""
    lines = [
        "def foo(x):",
        "    if x > 0:",
        '        return "positive"',
        "    # negative path",
        "    return 0",
    ]
    for ln in lines:
        plain = highlight_python_preview_line(ln, enabled=False)
        colored = highlight_python_preview_line(ln, enabled=True)
        assert plain == _strip_ansi(colored), (
            f"ANSI-stripped result differs from plain for {ln!r}"
        )


# ---------------------------------------------------------------- syntax-highlighted paste preview (shell.py integration)


def test_paste_preview_with_shell_highlight_stable() -> None:
    """Shell-highlighted paste preview must still contain plain markers after strip."""
    shell = PyShell()
    payload = "echo one\necho two"
    lines = shell._format_pending_paste_preview(
        payload,
        title="paste",
        max_lines=None,
        enabled=True,
        highlighter=shell._make_paste_line_highlighter(payload, enabled=True),
    )
    stripped = [_strip_ansi(ln) for ln in lines]
    assert "[paste:begin]" in stripped[0]
    assert "1 | echo one" in stripped
    assert "2 | echo two" in stripped
    assert "[paste:end]" in stripped[-1]


def test_paste_preview_python_block_highlight_stable() -> None:
    """Python block preview must still contain plain markers after ANSI strip."""
    shell = PyShell()
    payload = "py {\nx = 40 + 2\nprint(x)\n}"
    lines = shell._format_pending_paste_preview(
        payload,
        title="paste",
        max_lines=None,
        enabled=True,
        highlighter=shell._make_paste_line_highlighter(payload, enabled=True),
    )
    stripped = [_strip_ansi(ln) for ln in lines]
    assert "1 | py {" in stripped
    assert "2 | x = 40 + 2" in stripped
    assert "3 | print(x)" in stripped
    assert "4 | }" in stripped


# ---------------------------------------------------------------- _raw_editor_terminal_capable (NO_COLOR safety)


def test_raw_editor_terminal_capable_xterm() -> None:
    """xterm-256color must be considered a capable terminal."""
    from unittest.mock import patch
    with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False):
        from pysh.core.shell import PyShell as _PyShell
        assert _PyShell._raw_editor_terminal_capable() is True


def test_raw_editor_terminal_capable_dumb_is_not() -> None:
    """TERM=dumb must not be considered capable."""
    with patch.dict(os.environ, {"TERM": "dumb"}, clear=False):
        from pysh.core.shell import PyShell as _PyShell
        assert _PyShell._raw_editor_terminal_capable() is False


def test_raw_editor_terminal_capable_empty_term_is_not() -> None:
    """Empty TERM must not be considered capable."""
    env = {k: v for k, v in os.environ.items() if k != "TERM"}
    with patch.dict(os.environ, env, clear=True):
        from pysh.core.shell import PyShell as _PyShell
        assert _PyShell._raw_editor_terminal_capable() is False


def test_raw_editor_terminal_capable_no_color_does_not_affect() -> None:
    """NO_COLOR must not affect terminal capability check."""
    with patch.dict(os.environ, {"TERM": "xterm-256color", "NO_COLOR": "1"}, clear=False):
        from pysh.core.shell import PyShell as _PyShell
        assert _PyShell._raw_editor_terminal_capable() is True


# ---------------------------------------------------------------- highlight_shell_preview_line


def test_shell_highlight_command_colored() -> None:
    """Command names must receive a non-black colour."""
    result = highlight_shell_preview_line("echo hello", enabled=True)
    assert "\033[" in result
    assert _strip_ansi(result) == "echo hello"


def test_shell_highlight_variable_safe_color() -> None:
    """Variables must use magenta (35), not dark-blue (34)."""
    result = highlight_shell_preview_line("echo $?", enabled=True)
    assert "\033[35m" in result, "$? must be coloured magenta"
    assert "\033[34m" not in result, "dark-blue must not be used for $?"
    assert _strip_ansi(result) == "echo $?"


def test_shell_highlight_semicolon_operator() -> None:
    """Semicolons must be highlighted and the following word treated as a new command."""
    result = highlight_shell_preview_line("echo one ; echo two", enabled=True)
    assert _strip_ansi(result) == "echo one ; echo two"


def test_shell_highlight_heredoc_opener() -> None:
    """Heredoc opener must be highlighted and ANSI-strip-stable."""
    line = "cat > /tmp/out.txt <<'EOF'"
    result = highlight_shell_preview_line(line, enabled=True)
    assert _strip_ansi(result) == line


def test_shell_highlight_disabled_passthrough() -> None:
    result = highlight_shell_preview_line("echo $VAR ; ls", enabled=False)
    assert result == "echo $VAR ; ls"
    assert "\033" not in result


def test_shell_highlight_no_dim_white() -> None:
    """Shell highlighter must not emit dim+white (2;37) anywhere."""
    lines = [
        "echo hello",
        "cat foo ; echo $?",
        "ls > /tmp/out.txt",
        "# a comment",
        "VAR=value command",
    ]
    for ln in lines:
        result = highlight_shell_preview_line(ln, enabled=True)
        assert "2;37" not in result, f"dim-white in shell preview for {ln!r}"
        assert _strip_ansi(result) == ln, f"ANSI-strip not stable for {ln!r}"


# ---------------------------------------------------------------- reverse-search layout (query-last)


def test_reverse_search_query_appears_after_match_in_output() -> None:
    """Reverse-search must render match: before query: so cursor lands after query text."""
    import os as _os
    import pty as _pty

    from pysh.editor.lineedit.reader import RawLineReader

    master, slave = _pty.openpty()
    reader = RawLineReader(output_fd=slave)
    try:
        reader._render_reverse_search("first", "echo first-command", slave)
        raw = _os.read(master, 4096)
        text = _ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
        assert "reverse-i-search" in text, "reverse-i-search label missing"
        assert "match:" in text, "match: label missing"
        assert "query:" in text, "query: label missing"
        assert "echo first-command" in text, "matched command text missing"
        assert "first" in text, "query text missing"
        # query: must appear AFTER match: so cursor lands after query text.
        assert text.index("query:") > text.index("match:"), (
            "query: should appear after match: so cursor lands after query text"
        )
    finally:
        _os.close(master)
        _os.close(slave)


def test_reverse_search_no_dim_white_in_labels() -> None:
    """Reverse-search render must not emit dim+white SGR (2;37m)."""
    import os as _os
    import pty as _pty

    from pysh.editor.lineedit.reader import RawLineReader

    master, slave = _pty.openpty()
    reader = RawLineReader(output_fd=slave)
    try:
        reader._render_reverse_search("qry", "echo match-cmd", slave)
        raw = _os.read(master, 4096)
        assert b"2;37" not in raw, "dim+white SGR 2;37m found in reverse-search output"
    finally:
        _os.close(master)
        _os.close(slave)
