# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_lineedit_completion.py
#
# Copyright (C) 2026 Siergej Sobolewski

from __future__ import annotations

import os

from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.completion import (
    CompletionCandidate,
    CompletionKind,
    CompletionResult,
    apply_single_completion,
    complete_line,
)
from pysh.editor.lineedit.reader import RawLineReader, _visible_width

BUILTINS = (
    "cd",
    "pwd",
    "alias",
    "source",
    "source_zsh",
    "source_zsh_profile",
    "source_sh_aliases",
    "sys_info",
)


def test_prefix_s_filters_unrelated_builtins(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("s", 1, builtins=BUILTINS, aliases=(), path="")
    assert "source" in result.candidates
    assert "sys_info" in result.candidates
    assert "src/" in result.candidates
    assert "scripts/" in result.candidates
    assert "cd" not in result.candidates
    assert "pwd" not in result.candidates
    assert "alias" not in result.candidates
    assert ".venv/" not in result.candidates
    assert "README.md" not in result.candidates


def test_prefix_so_returns_source_family_only(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("so", 2, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == (
        "source",
        "source_sh_aliases",
        "source_zsh",
        "source_zsh_profile",
    )


def test_path_prefixes_match_directories(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv").mkdir()
    monkeypatch.chdir(tmp_path)
    assert "src/" in complete_line("src", 3, builtins=(), aliases=(), path="").candidates
    assert ".venv/" in complete_line(".v", 2, builtins=(), aliases=(), path="").candidates


def test_unknown_prefix_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert complete_line("zz", 2, builtins=BUILTINS, aliases=(), path="").candidates == ()


def test_single_match_inserts_suffix_and_directory_slash(tmp_path, monkeypatch) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.chdir(tmp_path)
    result = complete_line("scr", 3, builtins=(), aliases=(), path="")
    assert result.candidates == ("scripts/",)
    assert apply_single_completion("scr", result) == ("scripts/", 8)


def test_non_directory_single_match_appends_space(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("sys_", 4, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("sys_info",)
    assert apply_single_completion("sys_", result) == ("sys_info ", 9)


def test_multiple_matches_do_not_mutate_buffer(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("s", 1, builtins=BUILTINS, aliases=(), path="")
    assert len(result.candidates) > 1
    assert apply_single_completion("s", result) == ("s", 1)


class _StaticCompleter:
    def __init__(self, result: CompletionResult) -> None:
        self.result = result

    def raw_completion(self, _line: str, _cursor: int) -> CompletionResult:
        return self.result

    def apply_raw_completion(self, line: str, result: CompletionResult) -> tuple[str, int]:
        return apply_single_completion(line, result)


def test_repeated_tab_inserts_common_prefix_before_menu() -> None:
    read_fd, write_fd = os.pipe()
    try:
        result = CompletionResult(
            0,
            2,
            "so",
            ("source", "source_zsh"),
            (
                CompletionCandidate("source", CompletionKind.BUILTIN),
                CompletionCandidate("source_zsh", CompletionKind.BUILTIN),
            ),
        )
        reader = RawLineReader(output_fd=write_fd)
        buffer = LineBuffer("so", 2)
        reader._complete(buffer, _StaticCompleter(result))
        os.close(write_fd)
        write_fd = -1

        assert buffer.text == "source"
        assert os.read(read_fd, 4096) == b""
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)


def test_repeated_tab_candidate_display_preserves_buffer() -> None:
    read_fd, write_fd = os.pipe()
    try:
        result = CompletionResult(
            0,
            6,
            "source",
            ("source", "source_zsh"),
            (
                CompletionCandidate("source", CompletionKind.BUILTIN),
                CompletionCandidate("source_zsh", CompletionKind.BUILTIN),
            ),
        )
        reader = RawLineReader(output_fd=write_fd)
        buffer = LineBuffer("source", 6)
        completer = _StaticCompleter(result)
        reader._complete(buffer, completer)
        reader._complete(buffer, completer)
        os.close(write_fd)
        write_fd = -1
        output = os.read(read_fd, 4096).decode("utf-8")

        assert buffer.text == "source"
        assert "source [builtin]" in output
        assert "source_zsh [builtin]" in output
        assert output.count("source [builtin]") == 1
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)


def test_visible_width_strips_ansi_before_prompt_measurement() -> None:
    assert _visible_width("\033[32mPySH>\033[0m ") == len("PySH> ")
