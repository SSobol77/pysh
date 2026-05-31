# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_lineedit_highlight.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

from pysh.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter, Role


def _covered(line: str, spans) -> str:
    return "".join(line[span.start : span.end] for span in spans)


def test_command_valid_invalid_and_which_cache(monkeypatch) -> None:
    calls: list[str] = []

    def fake_which(token: str) -> str | None:
        calls.append(token)
        return "/bin/ls" if token == "ls" else None

    monkeypatch.setattr("pysh.lineedit.highlight.shutil.which", fake_which)
    highlighter = LineHighlighter({"cd"})
    line = "cd /tmp; ls -la | missing"
    spans = highlighter.tokenize(line)
    roles = [span.role for span in spans if line[span.start : span.end].strip()]
    assert Role.COMMAND_VALID in roles
    assert Role.COMMAND_INVALID in roles
    highlighter.tokenize("ls && ls")
    assert calls.count("ls") == 1


def test_roles_and_coverage(monkeypatch) -> None:
    monkeypatch.setattr("pysh.lineedit.highlight.shutil.which", lambda _token: None)
    line = "bad 'str' --flag $VAR ${HOME} | other > file"
    spans = LineHighlighter(set()).tokenize(line)
    assert _covered(line, spans) == line
    roles = {span.role for span in spans}
    assert {Role.STRING, Role.OPTION, Role.VARIABLE, Role.OPERATOR}.issubset(roles)


def test_partial_variable_does_not_drop_or_hang(monkeypatch) -> None:
    monkeypatch.setattr("pysh.lineedit.highlight.shutil.which", lambda _token: None)
    line = "echo $"
    spans = LineHighlighter({"echo"}).tokenize(line)
    assert _covered(line, spans) == line
    assert spans[-1].role is Role.VARIABLE


def test_pipeline_stages_recheck_command_and_render_disabled(monkeypatch) -> None:
    monkeypatch.setattr("pysh.lineedit.highlight.shutil.which", lambda token: f"/bin/{token}")
    highlighter = LineHighlighter(set())
    spans = highlighter.tokenize("one | two && three")
    command_spans = [span for span in spans if span.role is Role.COMMAND_VALID]
    assert len(command_spans) == 3
    assert highlighter.render("echo '$x'", DEFAULT_SCHEME, enabled=False) == "echo '$x'"
