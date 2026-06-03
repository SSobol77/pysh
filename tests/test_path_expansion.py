# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Native path and glob expansion tests (Issue #9).

Covers:
A. Pure helper functions (has_glob_metacharacters, expand_tilde).
B. Glob matching (expand_path_word, expand_path_words).
C. Tokenizer / quoting (tokenize_and_glob_expand).
D. Shell integration (PyShell.execute with real filesystem via tmp_path).
E. Redirection targets (tilde expansion; no glob on redirect targets).
F. Regression (existing variable/command-substitution tests still pass;
   no expansion inside single/double quotes).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from pysh.parsing.path_expansion import (
    NoMatchPolicy,
    PathExpansionOptions,
    expand_path_word,
    expand_path_words,
    expand_tilde,
    has_glob_metacharacters,
    tokenize_and_glob_expand,
)

# ---------------------------------------------------------------------------
# A. Pure helper tests
# ---------------------------------------------------------------------------


class TestHasGlobMetacharacters:
    def test_star_is_meta(self) -> None:
        assert has_glob_metacharacters("*.py")

    def test_question_mark_is_meta(self) -> None:
        assert has_glob_metacharacters("?.txt")

    def test_bracket_is_meta(self) -> None:
        assert has_glob_metacharacters("[abc].txt")

    def test_plain_word_no_meta(self) -> None:
        assert not has_glob_metacharacters("hello.txt")

    def test_empty_string_no_meta(self) -> None:
        assert not has_glob_metacharacters("")

    def test_tilde_only_no_meta(self) -> None:
        assert not has_glob_metacharacters("~")

    def test_path_no_meta(self) -> None:
        assert not has_glob_metacharacters("/usr/local/bin/python3")

    def test_brace_not_meta(self) -> None:
        # Brace expansion is unsupported; { is not a glob metachar in PySH
        assert not has_glob_metacharacters("{a,b}")

    def test_double_star_is_meta(self) -> None:
        assert has_glob_metacharacters("**/*.py")


class TestExpandTilde:
    def test_home_only(self) -> None:
        result = expand_tilde("~")
        assert result == os.path.expanduser("~")
        assert not result.endswith("~")

    def test_home_with_path(self) -> None:
        result = expand_tilde("~/projects")
        assert result == os.path.join(os.path.expanduser("~"), "projects")

    def test_no_tilde_unchanged(self) -> None:
        assert expand_tilde("hello") == "hello"
        assert expand_tilde("/absolute/path") == "/absolute/path"
        assert expand_tilde("*.py") == "*.py"

    def test_tilde_not_at_start_unchanged(self) -> None:
        # Only leading ~ is special
        assert expand_tilde("a~b") == "a~b"

    def test_empty_string_unchanged(self) -> None:
        assert expand_tilde("") == ""


# ---------------------------------------------------------------------------
# B. Glob matching
# ---------------------------------------------------------------------------


class TestExpandPathWord:
    def test_star_matches_py_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()
        result = expand_path_word("*.py", cwd=tmp_path)
        assert sorted(result) == ["a.py", "b.py"]

    def test_question_mark_matches_one_char(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").touch()
        (tmp_path / "ab.txt").touch()
        (tmp_path / "b.txt").touch()
        result = expand_path_word("?.txt", cwd=tmp_path)
        assert sorted(result) == ["a.txt", "b.txt"]

    def test_bracket_class_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()
        (tmp_path / "c.txt").touch()
        result = expand_path_word("[ab].txt", cwd=tmp_path)
        assert sorted(result) == ["a.txt", "b.txt"]

    def test_bracket_range_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()
        (tmp_path / "z.txt").touch()
        result = expand_path_word("[a-b].txt", cwd=tmp_path)
        assert sorted(result) == ["a.txt", "b.txt"]

    def test_no_match_returns_literal(self, tmp_path: Path) -> None:
        result = expand_path_word("no-such-*.xyz", cwd=tmp_path)
        assert result == ["no-such-*.xyz"]

    def test_no_match_empty_policy(self, tmp_path: Path) -> None:
        opts = PathExpansionOptions(no_match=NoMatchPolicy.EMPTY)
        result = expand_path_word("no-such-*.xyz", cwd=tmp_path, options=opts)
        assert result == []

    def test_no_match_error_policy(self, tmp_path: Path) -> None:
        opts = PathExpansionOptions(no_match=NoMatchPolicy.ERROR)
        with pytest.raises(ValueError, match="no match"):
            expand_path_word("no-such-*.xyz", cwd=tmp_path, options=opts)

    def test_star_does_not_match_dotfiles_by_default(self, tmp_path: Path) -> None:
        (tmp_path / "visible.py").touch()
        (tmp_path / ".hidden.py").touch()
        result = expand_path_word("*.py", cwd=tmp_path)
        assert "visible.py" in result
        assert ".hidden.py" not in result

    def test_explicit_dot_pattern_matches_dotfiles(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.py").touch()
        (tmp_path / ".other.py").touch()
        (tmp_path / "visible.py").touch()
        result = expand_path_word(".*.py", cwd=tmp_path)
        assert ".hidden.py" in result
        assert ".other.py" in result
        assert "visible.py" not in result

    def test_results_sorted_by_default(self, tmp_path: Path) -> None:
        for name in ["c.py", "a.py", "b.py"]:
            (tmp_path / name).touch()
        result = expand_path_word("*.py", cwd=tmp_path)
        assert result == sorted(result)

    def test_no_sort_when_disabled(self, tmp_path: Path) -> None:
        for name in ["a.py", "b.py", "c.py"]:
            (tmp_path / name).touch()
        opts = PathExpansionOptions(sort=False)
        result = expand_path_word("*.py", cwd=tmp_path, options=opts)
        # Just verify all files are present (order is filesystem-dependent)
        assert sorted(result) == ["a.py", "b.py", "c.py"]

    def test_plain_word_returned_as_is(self, tmp_path: Path) -> None:
        result = expand_path_word("hello.txt", cwd=tmp_path)
        assert result == ["hello.txt"]

    def test_recursive_globstar(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.py").touch()
        (sub / "nested.py").touch()
        result = expand_path_word("**/*.py", cwd=tmp_path)
        names = {Path(p).name for p in result}
        assert "nested.py" in names

    def test_tilde_then_glob(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        result = expand_path_word("~/*.py")
        # Results should be absolute paths under tmp_path
        assert all(Path(r).is_absolute() for r in result)
        names = {Path(r).name for r in result}
        assert "a.py" in names
        assert "b.py" in names


class TestExpandPathWords:
    def test_multiple_words(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.txt").touch()
        result = expand_path_words(["*.py", "*.txt"], cwd=tmp_path)
        assert "a.py" in result
        assert "b.txt" in result

    def test_no_meta_words_unchanged(self, tmp_path: Path) -> None:
        result = expand_path_words(["hello", "world"], cwd=tmp_path)
        assert result == ["hello", "world"]


# ---------------------------------------------------------------------------
# C. Tokenizer / quoting
# ---------------------------------------------------------------------------


class TestTokenizeAndGlobExpand:
    def test_plain_word(self) -> None:
        assert tokenize_and_glob_expand("hello world") == ["hello", "world"]

    def test_single_quoted_glob_remains_literal(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        result = tokenize_and_glob_expand("'*.py'", cwd=tmp_path)
        assert result == ["*.py"]

    def test_double_quoted_glob_remains_literal(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        result = tokenize_and_glob_expand('"*.py"', cwd=tmp_path)
        assert result == ["*.py"]

    def test_backslash_escaped_star_remains_literal(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        result = tokenize_and_glob_expand(r"\*.py", cwd=tmp_path)
        assert result == ["*.py"]

    def test_unquoted_glob_expands(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        result = tokenize_and_glob_expand("*.py", cwd=tmp_path)
        assert sorted(result) == ["a.py", "b.py"]

    def test_no_match_returns_literal(self, tmp_path: Path) -> None:
        result = tokenize_and_glob_expand("no-such-*.xyz", cwd=tmp_path)
        assert result == ["no-such-*.xyz"]

    def test_mixed_quoted_and_unquoted(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        result = tokenize_and_glob_expand('echo "*.py"', cwd=tmp_path)
        assert result == ["echo", "*.py"]

    def test_single_quoted_content_preserved(self) -> None:
        result = tokenize_and_glob_expand("echo 'hello world'")
        assert result == ["echo", "hello world"]

    def test_double_quoted_content_preserved(self) -> None:
        result = tokenize_and_glob_expand('echo "hello world"')
        assert result == ["echo", "hello world"]

    def test_tilde_in_unquoted_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/tmp/fakehome")
        result = tokenize_and_glob_expand("echo ~")
        assert result == ["echo", "/tmp/fakehome"]

    def test_tilde_in_single_quotes_stays_literal(self) -> None:
        result = tokenize_and_glob_expand("echo '~'")
        assert result == ["echo", "~"]

    def test_tilde_in_double_quotes_stays_literal(self) -> None:
        result = tokenize_and_glob_expand('echo "~"')
        assert result == ["echo", "~"]

    def test_backslash_escaped_tilde_stays_literal(self) -> None:
        result = tokenize_and_glob_expand(r"echo \~")
        assert result == ["echo", "~"]

    def test_empty_string_returns_empty(self) -> None:
        assert tokenize_and_glob_expand("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert tokenize_and_glob_expand("   ") == []

    def test_unterminated_single_quote_raises(self) -> None:
        with pytest.raises(ValueError, match="single quote"):
            tokenize_and_glob_expand("echo 'unterminated")

    def test_unterminated_double_quote_raises(self) -> None:
        with pytest.raises(ValueError, match="double quote"):
            tokenize_and_glob_expand('echo "unterminated')

    def test_brace_expansion_stays_literal(self) -> None:
        # Brace expansion is unsupported; { is not a glob metachar
        result = tokenize_and_glob_expand("echo {a,b}")
        assert result == ["echo", "{a,b}"]

    def test_multiple_spaces_between_tokens(self) -> None:
        result = tokenize_and_glob_expand("a   b   c")
        assert result == ["a", "b", "c"]

    def test_backslash_space_in_word(self) -> None:
        result = tokenize_and_glob_expand(r"a\ b")
        assert result == ["a b"]

    def test_glob_in_multiple_token_context(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()
        result = tokenize_and_glob_expand("echo *.py *.txt", cwd=tmp_path)
        assert result[0] == "echo"
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" in result

    def test_dotfiles_not_matched_by_star(self, tmp_path: Path) -> None:
        (tmp_path / "visible.py").touch()
        (tmp_path / ".hidden.py").touch()
        result = tokenize_and_glob_expand("*.py", cwd=tmp_path)
        assert "visible.py" in result
        assert ".hidden.py" not in result


# ---------------------------------------------------------------------------
# D. Shell integration — check Popen argv (subprocess output not captured by capsys)
# ---------------------------------------------------------------------------


def _mock_popen(returncode: int = 0) -> mock.MagicMock:
    proc = mock.MagicMock()
    proc.wait.return_value = returncode
    proc.stdout = None
    return mock.MagicMock(return_value=proc)


def _run_in_dir(shell_cmd: str, cwd: Path) -> list[str] | None:
    """Run shell_cmd in cwd with a mock Popen and return the captured argv, or None."""
    from pysh.core.shell import PyShell

    popen_mock = _mock_popen()
    old_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        with mock.patch.object(subprocess, "Popen", popen_mock):
            PyShell().execute(shell_cmd)
    finally:
        os.chdir(old_cwd)
    if popen_mock.called:
        return list(popen_mock.call_args.args[0])
    return None


class TestShellGlobIntegration:
    """Integration: verify that Popen receives correctly glob-expanded argv."""

    def test_echo_star_py_expands(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        argv = _run_in_dir("echo *.py", tmp_path)
        assert argv is not None
        assert argv[0] == "echo"
        assert "a.py" in argv
        assert "b.py" in argv

    def test_echo_quoted_star_py_literal(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        argv = _run_in_dir('echo "*.py"', tmp_path)
        assert argv == ["echo", "*.py"]

    def test_echo_single_quoted_star_py_literal(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        argv = _run_in_dir("echo '*.py'", tmp_path)
        assert argv == ["echo", "*.py"]

    def test_echo_no_match_returns_literal(self, tmp_path: Path) -> None:
        argv = _run_in_dir("echo no-such-*.xyz", tmp_path)
        assert argv == ["echo", "no-such-*.xyz"]

    def test_echo_brace_expansion_stays_literal(self, tmp_path: Path) -> None:
        argv = _run_in_dir("echo {a,b}", tmp_path)
        assert argv == ["echo", "{a,b}"]

    def test_echo_dot_star_matches_dotfiles(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").touch()
        argv = _run_in_dir("echo .*", tmp_path)
        assert argv is not None
        assert ".hidden" in argv

    def test_glob_results_sorted(self, tmp_path: Path) -> None:
        for name in ["c.py", "a.py", "b.py"]:
            (tmp_path / name).touch()
        argv = _run_in_dir("echo *.py", tmp_path)
        assert argv is not None
        files = argv[1:]
        assert files == sorted(files)

    def test_glob_does_not_match_hidden_by_default(self, tmp_path: Path) -> None:
        (tmp_path / "visible.py").touch()
        (tmp_path / ".hidden.py").touch()
        argv = _run_in_dir("echo *.py", tmp_path)
        assert argv is not None
        assert "visible.py" in argv
        assert ".hidden.py" not in argv

    def test_recursive_globstar_finds_nested(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").touch()
        argv = _run_in_dir("echo **/*.py", tmp_path)
        assert argv is not None
        assert any("nested.py" in a for a in argv)

    def test_question_mark_matches_single_char(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "ab.py").touch()
        argv = _run_in_dir("echo ?.py", tmp_path)
        assert argv is not None
        assert "a.py" in argv
        assert "ab.py" not in argv

    def test_bracket_class_expansion(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.py").touch()
        argv = _run_in_dir("echo [ab].py", tmp_path)
        assert argv is not None
        assert "a.py" in argv
        assert "b.py" in argv
        assert "c.py" not in argv


# ---------------------------------------------------------------------------
# E. Redirection targets — tilde expansion; no glob expansion
# ---------------------------------------------------------------------------


class TestRedirectionTargets:
    def test_tilde_expanded_in_stdout_redirect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        from pysh.core.shell import PyShell

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            shell = PyShell()
            status = shell.execute("echo hello > ~/output.txt")
        finally:
            os.chdir(old_cwd)
        assert status == 0
        out_file = tmp_path / "output.txt"
        assert out_file.exists()
        assert out_file.read_text().strip() == "hello"

    def test_glob_in_redirect_target_stays_literal(
        self, tmp_path: Path
    ) -> None:
        """Redirect target *.out must NOT glob-expand; it becomes a literal filename."""
        from pysh.core.shell import PyShell

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            shell = PyShell()
            status = shell.execute("echo hello > test.out")
        finally:
            os.chdir(old_cwd)
        assert status == 0
        assert (tmp_path / "test.out").exists()


# ---------------------------------------------------------------------------
# F. Regression — existing expansion behavior unchanged
# ---------------------------------------------------------------------------


class TestRegression:
    def test_variable_expansion_unchanged(self) -> None:
        from pysh.parsing.expansion import expand_variables

        result = expand_variables("$A $B", {"A": "hello", "B": "world"}, {})
        assert result == "hello world"

    def test_command_substitution_unchanged(self) -> None:
        from pysh.parsing.expansion import expand_command_substitution

        result = expand_command_substitution("$(echo hi)", runner=lambda c, t: "hi")
        assert result == "hi"

    def test_existing_glob_patterns_as_literals_via_double_quote(self) -> None:
        """Regression: test_expansion_foundation 'echo "*.py"' still passes."""
        popen = mock.MagicMock()
        proc = mock.MagicMock()
        proc.wait.return_value = 0
        proc.stdout = None
        popen.return_value = proc
        with mock.patch.object(subprocess, "Popen", popen):
            from pysh.core.shell import PyShell
            assert PyShell().execute('echo "*.py"') == 0
        assert popen.call_args.args[0] == ["echo", "*.py"]

    def test_brace_expansion_literal_via_double_quote(self) -> None:
        """Regression: test_expansion_foundation 'echo "{a,b}"' still passes."""
        popen = mock.MagicMock()
        proc = mock.MagicMock()
        proc.wait.return_value = 0
        proc.stdout = None
        popen.return_value = proc
        with mock.patch.object(subprocess, "Popen", popen):
            from pysh.core.shell import PyShell
            assert PyShell().execute('echo "{a,b}"') == 0
        assert popen.call_args.args[0] == ["echo", "{a,b}"]

    def test_variable_then_glob_expansion(self, tmp_path: Path) -> None:
        """Variable expansion result is eligible for glob expansion."""
        (tmp_path / "hello.py").touch()
        popen_mock = _mock_popen()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with mock.patch.object(subprocess, "Popen", popen_mock):
                from pysh.core.shell import PyShell
                shell = PyShell()
                shell.local_vars["PAT"] = "*.py"
                status = shell.execute("echo $PAT")
        finally:
            os.chdir(old_cwd)
        assert status == 0
        argv = list(popen_mock.call_args.args[0])
        assert "hello.py" in argv

    def test_parser_foundation_tests_still_pass(self) -> None:
        from pysh.parsing.redirection import parse_redirections

        command, spec = parse_redirections("echo hello > out.txt 2>> err.txt")
        assert command == "echo hello"
        assert spec.stdout_path == "out.txt"
        assert spec.stderr_path == "err.txt"
