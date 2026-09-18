# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_lineedit_highlight.py
#
# Copyright (C) 2026 Siergej Sobolewski

from __future__ import annotations

import re

from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.highlight import (
    DEFAULT_SCHEME,
    LineHighlighter,
    Role,
)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _covered(line: str, spans) -> str:
    return "".join(line[span.start : span.end] for span in spans)


def _role_text(line: str, spans, role: Role) -> list[str]:
    return [line[span.start : span.end] for span in spans if span.role is role]


def test_command_valid_invalid_and_which_cache(monkeypatch) -> None:
    calls: list[str] = []

    def fake_which(token: str) -> str | None:
        calls.append(token)
        return "/bin/ls" if token == "ls" else None

    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", fake_which)
    highlighter = LineHighlighter({"cd"})
    line = "cd /tmp; ls -la | missing"
    spans = highlighter.tokenize(line)
    roles = [span.role for span in spans if line[span.start : span.end].strip()]
    assert Role.BUILTIN in roles
    assert Role.COMMAND_VALID in roles
    assert Role.COMMAND_INVALID in roles
    highlighter.tokenize("ls && ls")
    assert calls.count("ls") == 1


def test_roles_and_coverage(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    line = "bad 'str' --flag $VAR ${HOME} | other > file"
    spans = LineHighlighter(set()).tokenize(line)
    assert _covered(line, spans) == line
    roles = {span.role for span in spans}
    assert {Role.STRING, Role.OPTION, Role.VARIABLE, Role.OPERATOR}.issubset(roles)


def test_partial_variable_does_not_drop_or_hang(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    line = "echo $"
    spans = LineHighlighter({"echo"}).tokenize(line)
    assert _covered(line, spans) == line
    assert spans[-1].role is Role.VARIABLE


def test_pipeline_stages_recheck_command_and_render_disabled(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda token: f"/bin/{token}")
    highlighter = LineHighlighter(set())
    spans = highlighter.tokenize("one | two && three")
    command_spans = [span for span in spans if span.role is Role.COMMAND_VALID]
    assert len(command_spans) == 3
    assert highlighter.render("echo '$x'", DEFAULT_SCHEME, enabled=False) == "echo '$x'"


def test_builtin_wins_over_alias_and_alias_wins_over_external(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda token: f"/bin/{token}")
    highlighter = LineHighlighter({"cd", "echo"}, aliases=lambda: {"cd", "gs"})
    line = "cd /tmp; gs && echo ok"
    spans = highlighter.tokenize(line)
    assert _role_text(line, spans, Role.BUILTIN) == ["cd", "echo"]
    assert _role_text(line, spans, Role.ALIAS) == ["gs"]


def test_comment_starts_only_at_token_boundary_outside_quotes(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    line = "echo '#not comment' value#literal # real comment"
    spans = LineHighlighter({"echo"}).tokenize(line)
    assert _covered(line, spans) == line
    assert _role_text(line, spans, Role.COMMENT) == ["# real comment"]
    assert "#not comment" in _role_text(line, spans, Role.STRING)[0]


def test_heredoc_operator_and_delimiter_are_highlighted(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    line = "cat <<-'EOF'"
    spans = LineHighlighter({"cat"}).tokenize(line)
    assert _covered(line, spans) == line
    assert _role_text(line, spans, Role.OPERATOR) == ["<<-"]
    assert _role_text(line, spans, Role.HEREDOC) == ["'EOF'"]


def test_render_does_not_mutate_buffer_and_strips_to_input(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    buffer = LineBuffer("echo $HOME # comment")
    original = buffer.text
    rendered = LineHighlighter({"echo"}).render(buffer.text, DEFAULT_SCHEME, enabled=True)
    assert buffer.text == original
    assert ANSI_RE.sub("", rendered) == original


def test_wide_and_combining_text_remain_buffer_stable(monkeypatch) -> None:
    monkeypatch.setattr("pysh.editor.lineedit.highlight.shutil.which", lambda _token: None)
    line = "echo cafe\u0301 漢字"
    buffer = LineBuffer(line)
    rendered = LineHighlighter({"echo"}).render(buffer.text, DEFAULT_SCHEME, enabled=True)
    assert buffer.text == line
    assert ANSI_RE.sub("", rendered) == line
    assert buffer.cursor_width() == 0
    buffer.move_end()
    assert buffer.cursor_width() == 14
