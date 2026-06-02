# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_lineedit_completion.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

from pysh.editor.lineedit.completion import apply_single_completion, complete_line

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
    result = complete_line("s", 1, builtins=BUILTINS, aliases=())
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
    result = complete_line("so", 2, builtins=BUILTINS, aliases=())
    assert result.candidates == (
        "source",
        "source_zsh",
        "source_zsh_profile",
        "source_sh_aliases",
    )


def test_path_prefixes_match_directories(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv").mkdir()
    monkeypatch.chdir(tmp_path)
    assert "src/" in complete_line("src", 3, builtins=(), aliases=()).candidates
    assert ".venv/" in complete_line(".v", 2, builtins=(), aliases=()).candidates


def test_unknown_prefix_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert complete_line("zz", 2, builtins=BUILTINS, aliases=()).candidates == ()


def test_single_match_inserts_suffix_and_directory_slash(tmp_path, monkeypatch) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.chdir(tmp_path)
    result = complete_line("scr", 3, builtins=(), aliases=())
    assert result.candidates == ("scripts/",)
    assert apply_single_completion("scr", result) == ("scripts/", 8)


def test_non_directory_single_match_appends_space(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("sys_", 4, builtins=BUILTINS, aliases=())
    assert result.candidates == ("sys_info",)
    assert apply_single_completion("sys_", result) == ("sys_info ", 9)


def test_multiple_matches_do_not_mutate_buffer(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("s", 1, builtins=BUILTINS, aliases=())
    assert len(result.candidates) > 1
    assert apply_single_completion("s", result) == ("s", 1)

