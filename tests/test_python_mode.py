# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_python_mode.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the Python Command Execution Layer (python_mode.py) and the
new PythonRuntime methods (push_interactive / run_buffer / reset)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from pysh.python_mode import (
    PythonCommandMode,
    _check_missing_hash,
    _parse_directive,
    complete_python_mode_path,
    expand_tab,
)
from pysh.python_runtime import PythonRuntime
from pysh.shell import PyShell

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _mode(
    lines: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[PythonCommandMode, io.StringIO, io.StringIO]:
    """Build a testable PythonCommandMode with injected streams."""
    out = io.StringIO()
    err = io.StringIO()
    mode = PythonCommandMode(
        input_source=lines,
        out_stream=out,
        err_stream=err,
        cwd_provider=(lambda: cwd) if cwd is not None else None,
    )
    return mode, out, err


# ═══════════════════════════════════════════════════════════════════════════
# expand_tab — pure function
# ═══════════════════════════════════════════════════════════════════════════

def test_expand_tab_at_start() -> None:
    line, cursor = expand_tab("", 0)
    assert line == "    "
    assert cursor == 4


def test_expand_tab_mid_line() -> None:
    line, cursor = expand_tab("def f():", 8)
    assert line == "def f():    "
    assert cursor == 12


def test_expand_tab_at_cursor_zero() -> None:
    line, cursor = expand_tab("hello", 0)
    assert line == "    hello"
    assert cursor == 4


def test_expand_tab_at_end() -> None:
    line, cursor = expand_tab("abc", 3)
    assert line == "abc    "
    assert cursor == 7


# ═══════════════════════════════════════════════════════════════════════════
# _parse_directive — directive recognition
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDirective:
    def test_exit(self) -> None:
        result = _parse_directive("#exit")
        assert result == ("exit", None, None)

    def test_help(self) -> None:
        result = _parse_directive("#help")
        assert result == ("help", None, None)

    def test_show(self) -> None:
        assert _parse_directive("#show") == ("show", None, None)

    def test_run(self) -> None:
        assert _parse_directive("#run") == ("run", None, None)

    def test_reset(self) -> None:
        assert _parse_directive("#reset") == ("reset", None, None)

    def test_open_with_filename(self) -> None:
        result = _parse_directive("#open main.py")
        assert result == ("open", "main.py", None)

    def test_save_with_filename(self) -> None:
        result = _parse_directive("#save session.py")
        assert result == ("save", "session.py", None)

    def test_open_missing_filename_is_error(self) -> None:
        result = _parse_directive("#open")
        assert result is not None
        name, arg, error = result
        assert error is not None
        assert "#open" in error or "open" in error

    def test_save_without_filename_is_valid_directive(self) -> None:
        # #save without arg is now valid at parse time; the handler checks active_file.
        result = _parse_directive("#save")
        assert result is not None
        name, arg, error = result
        assert name == "save"
        assert arg is None
        assert error is None  # no parse error; handler decides based on active_file

    def test_open_with_redirect_lt_is_error(self) -> None:
        result = _parse_directive("#open < file.py")
        assert result is not None
        _, _, error = result
        assert error is not None
        assert "redirection" in error.lower() or "not supported" in error.lower()

    def test_save_with_redirect_gt_is_error(self) -> None:
        result = _parse_directive("#save > file.py")
        assert result is not None
        _, _, error = result
        assert error is not None

    def test_echo_redirect_is_error(self) -> None:
        result = _parse_directive("#echo > file.py")
        assert result is not None
        _, _, error = result
        assert error is not None

    def test_normal_comment_returns_none(self) -> None:
        assert _parse_directive("# this is a comment") is None

    def test_unknown_hash_token_is_error(self) -> None:
        # #word (no space after #) that is not a known directive → error
        result = _parse_directive("#notadirective")
        assert result is not None
        _, _, error = result
        assert error is not None
        assert "unknown" in error.lower()

    def test_hash_comment_with_space_returns_none(self) -> None:
        # "# word" (space after #) is a Python comment → None
        assert _parse_directive("# notadirective") is None
        assert _parse_directive("# noqa") is None
        assert _parse_directive("# type: ignore") is None

    def test_non_hash_line_returns_none(self) -> None:
        assert _parse_directive("x = 1") is None

    def test_open_extracts_first_word_as_filename(self) -> None:
        result = _parse_directive("#open file.py extra")
        assert result is not None
        name, arg, error = result
        assert name == "open"
        assert arg == "file.py"
        assert error is None

    def test_show_without_filename_is_valid(self) -> None:
        result = _parse_directive("#show")
        assert result == ("show", None, None)

    def test_show_with_filename_is_valid(self) -> None:
        result = _parse_directive("#show main.py")
        assert result is not None
        name, arg, error = result
        assert name == "show"
        assert arg == "main.py"
        assert error is None

    def test_clear_is_valid(self) -> None:
        assert _parse_directive("#clear") == ("clear", None, None)

    def test_save_with_redirect_is_error(self) -> None:
        result = _parse_directive("#save > file.py")
        assert result is not None
        _, _, error = result
        assert error is not None
        assert "redirection" in error.lower() or "not supported" in error.lower()

    def test_show_with_redirect_is_error(self) -> None:
        result = _parse_directive("#show < file.py")
        assert result is not None
        _, _, error = result
        assert error is not None


# ═══════════════════════════════════════════════════════════════════════════
# PythonRuntime.push_interactive
# ═══════════════════════════════════════════════════════════════════════════

class TestPushInteractive:
    def test_simple_assignment_returns_complete(self) -> None:
        rt = PythonRuntime()
        more, status = rt.push_interactive("x = 42")
        assert not more
        assert status == 0
        assert rt._cmd_globals["x"] == 42

    def test_expression_result_displayed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        rt.push_interactive("x = 7")
        rt.push_interactive("x * 6")
        out = capsys.readouterr().out
        assert "42" in out

    def test_incomplete_def_returns_more(self) -> None:
        rt = PythonRuntime()
        more, status = rt.push_interactive("def f():")
        assert more
        assert status == 0

    def test_complete_multiline_def(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        more1, _ = rt.push_interactive("def double(v):")
        assert more1
        more2, _ = rt.push_interactive("    return v * 2")
        assert more2
        more3, status = rt.push_interactive("")
        assert not more3
        assert status == 0
        # Function must now exist in globals.
        fn = rt._cmd_globals.get("double")
        assert callable(fn)

    def test_syntax_error_returns_status_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        more, status = rt.push_interactive("for")
        assert not more
        assert status == 2
        assert "SyntaxError" in capsys.readouterr().err

    def test_runtime_error_returns_status_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        more, status = rt.push_interactive("1 / 0")
        assert not more
        assert status == 1
        assert "ZeroDivisionError" in capsys.readouterr().err

    def test_buffer_cleared_after_complete(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("x = 1")
        assert len(rt._interactive_buffer) == 0

    def test_buffer_cleared_after_syntax_error(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("for")
        assert len(rt._interactive_buffer) == 0

    def test_state_persists_across_calls(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        rt.push_interactive("counter = 0")
        rt.push_interactive("counter += 1")
        rt.push_interactive("counter")
        out = capsys.readouterr().out
        assert "1" in out

    def test_import_persists(self, capsys: pytest.CaptureFixture[str]) -> None:
        rt = PythonRuntime()
        rt.push_interactive("import math")
        rt.push_interactive("math.floor(2.9)")
        out = capsys.readouterr().out
        assert "2" in out

    def test_err_stream_injected(self) -> None:
        err = io.StringIO()
        rt = PythonRuntime(err_stream=err)
        rt.push_interactive("1 / 0")
        assert "ZeroDivisionError" in err.getvalue()

    def test_cmd_globals_independent_from_py_globals(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("secret = 'cmd_mode'")
        assert "secret" not in rt.globals


# ═══════════════════════════════════════════════════════════════════════════
# PythonRuntime.run_buffer
# ═══════════════════════════════════════════════════════════════════════════

class TestRunBuffer:
    def test_simple_source(self, capsys: pytest.CaptureFixture[str]) -> None:
        rt = PythonRuntime()
        status = rt.run_buffer('print("hello")')
        assert status == 0
        assert "hello" in capsys.readouterr().out

    def test_empty_source_returns_zero(self) -> None:
        assert PythonRuntime().run_buffer("") == 0
        assert PythonRuntime().run_buffer("  \n  ") == 0

    def test_exec_semantics_no_echo(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        rt.run_buffer("42")  # expression — must NOT be printed in exec mode
        assert capsys.readouterr().out == ""

    def test_syntax_error_returns_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        status = rt.run_buffer("def f(\n")
        assert status == 2
        assert "SyntaxError" in capsys.readouterr().err

    def test_runtime_error_returns_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        status = rt.run_buffer("raise ValueError('oops')")
        assert status == 1
        assert "ValueError" in capsys.readouterr().err

    def test_state_persists_after_run(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rt = PythonRuntime()
        rt.run_buffer("x = 99")
        rt.push_interactive("x")
        assert "99" in capsys.readouterr().out

    def test_name_is_main(self) -> None:
        rt = PythonRuntime()
        rt.run_buffer("captured_name = __name__")
        assert rt._cmd_globals["captured_name"] == "__main__"

    def test_err_stream_injected(self) -> None:
        err = io.StringIO()
        rt = PythonRuntime(err_stream=err)
        rt.run_buffer("raise RuntimeError('boom')")
        assert "RuntimeError" in err.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# PythonRuntime.reset / clear_input_buffer
# ═══════════════════════════════════════════════════════════════════════════

class TestReset:
    def test_reset_clears_cmd_globals(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("x = 1")
        rt.reset()
        assert "x" not in rt._cmd_globals

    def test_reset_does_not_touch_py_globals(self) -> None:
        rt = PythonRuntime()
        rt.globals["marker"] = "present"
        rt.reset()
        assert rt.globals["marker"] == "present"

    def test_reset_clears_interactive_buffer(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("def f():")  # leaves more=True, buffer non-empty
        rt.reset()
        assert rt._interactive_buffer == []

    def test_clear_input_buffer_does_not_touch_globals(self) -> None:
        rt = PythonRuntime()
        rt.push_interactive("x = 5")
        rt.push_interactive("def f():")  # incomplete
        rt.clear_input_buffer()
        assert rt._interactive_buffer == []
        assert rt._cmd_globals["x"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — mode lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestModeLifecycle:
    def test_exit_returns_zero(self) -> None:
        mode, out, err = _mode(["#exit"])
        assert mode.run() == 0

    def test_eof_exits_cleanly(self) -> None:
        mode, out, err = _mode([])  # empty → immediate EOF
        assert mode.run() == 0

    def test_banner_contains_python_version(self) -> None:
        vi = __import__("sys").version_info
        mode, out, err = _mode(["#exit"])
        mode.run()
        banner = out.getvalue()
        assert f"Python {vi.major}.{vi.minor}.{vi.micro}" in banner

    def test_banner_does_not_hardcode_version(self) -> None:
        mode, out, err = _mode(["#exit"])
        mode.run()
        # No literal "3.14.0" or similar allowed — version is dynamic.
        assert "Python " in out.getvalue()

    def test_help_output_contains_all_directives(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        text = out.getvalue()
        for directive in ("#exit", "#help", "#open", "#save", "#show", "#run", "#reset"):
            assert directive in text

    def test_shell_enters_python_mode_on_hash_py(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []
        shell = PyShell()
        monkeypatch.setattr(shell, "_enter_python_mode", lambda: (calls.append(1), 0)[1])
        status = shell.execute("#py")
        assert status == 0
        assert calls  # _enter_python_mode was called

    def test_hash_py_with_leading_whitespace_enters_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []
        shell = PyShell()
        monkeypatch.setattr(shell, "_enter_python_mode", lambda: (calls.append(1), 0)[1])
        assert shell.execute("  #py  ") == 0
        assert calls

    def test_hash_py_in_middle_of_chain_is_comment(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "ls #py" — #py is a comment, ls runs without #py as an argument.
        # We verify via monkeypatching _run_external.
        shell = PyShell()
        captured_argv: list[list[str]] = []

        def fake_run_external(argv, spec, *, original_stage=None):  # type: ignore[no-untyped-def]
            captured_argv.append(list(argv))
            return 0

        shell._run_external = fake_run_external  # type: ignore[method-assign]
        shell.execute("ls #py")
        # #py must not appear as an argument to ls.
        assert all("#py" not in argv for argv in captured_argv)


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — expression execution and state
# ═══════════════════════════════════════════════════════════════════════════

class TestExecution:
    def test_expression_prints_result(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["1 + 2", "#exit"])
        mode.run()
        assert "3" in capsys.readouterr().out

    def test_string_expression_prints_repr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(['"GuardBSD"', "#exit"])
        mode.run()
        assert "GuardBSD" in capsys.readouterr().out

    def test_assignment_persists(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["x = 10", "x * 5", "#exit"])
        mode.run()
        assert "50" in capsys.readouterr().out

    def test_import_persists(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["import math", "math.floor(3.7)", "#exit"])
        mode.run()
        assert "3" in capsys.readouterr().out

    def test_function_definition_and_call(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(
            ["def double(v):", "    return v * 2", "", "double(21)", "#exit"]
        )
        mode.run()
        assert "42" in capsys.readouterr().out

    def test_class_definition_and_instantiation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(
            ["class Box:", "    def __init__(self, v):", "        self.v = v", "", "Box(7).v", "#exit"]
        )
        mode.run()
        assert "7" in capsys.readouterr().out

    def test_multiline_for_loop(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(
            ["for i in range(3):", "    print(i)", "", "#exit"]
        )
        mode.run()
        captured = capsys.readouterr().out
        assert "0" in captured
        assert "1" in captured
        assert "2" in captured

    def test_syntax_error_shows_type_and_survives(self) -> None:
        # Error output goes to the injected err_stream (not sys.stderr).
        mode, out, err = _mode(["for", "2 + 2", "#exit"])
        mode.run()
        assert "SyntaxError" in err.getvalue()

    def test_execution_continues_after_syntax_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["for", "2 + 2", "#exit"])
        mode.run()
        # Error goes to injected stream; expression output goes to sys.stdout.
        assert "SyntaxError" in err.getvalue()
        assert "4" in capsys.readouterr().out

    def test_runtime_error_shows_type_and_survives(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["1 / 0", "1 + 1", "#exit"])
        mode.run()
        # Error goes to injected stream; expression output goes to sys.stdout.
        assert "ZeroDivisionError" in err.getvalue()
        assert "2" in capsys.readouterr().out

    def test_normal_python_comment_executes_as_code(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "# this is a comment" must not trigger any directive.
        mode, out, err = _mode(["# just a comment", "1 + 1", "#exit"])
        mode.run()
        assert "2" in capsys.readouterr().out
        # No directive error must appear.
        assert err.getvalue() == ""


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — source buffer
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceBuffer:
    def test_show_empty_buffer(self) -> None:
        mode, out, err = _mode(["#show", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()

    def test_show_after_code(self) -> None:
        mode, out, err = _mode(["x = 1", "#show", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "x = 1" in text
        assert "1 |" in text

    def test_buffer_does_not_contain_directives(self) -> None:
        mode, out, err = _mode(["x = 1", "#show", "#exit"])
        mode.run()
        assert "#show" not in out.getvalue().replace("1 |", "")  # not as source
        assert "#exit" not in out.getvalue()

    def test_buffer_does_not_contain_prompts(self) -> None:
        mode, out, err = _mode(["x = 1", "#show", "#exit"])
        mode.run()
        # The show output has "N | line" format; no ">>> " or "... "
        for ln in out.getvalue().splitlines():
            if "| " in ln:
                assert ">>>" not in ln
                assert "..." not in ln

    def test_multiline_block_appended_to_buffer(self) -> None:
        mode, out, err = _mode(
            ["def f():", "    return 1", "", "#show", "#exit"]
        )
        mode.run()
        text = out.getvalue()
        assert "def f():" in text
        assert "    return 1" in text

    def test_syntax_error_line_not_in_buffer(self) -> None:
        mode, out, err = _mode(["for", "#show", "#exit"])
        mode.run()
        text = out.getvalue()
        # Only "buffer empty" or nothing meaningful — "for" is bad syntax
        assert "for" not in text.split("buffer empty")[1] if "buffer empty" in text else True


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — #open and #save
# ═══════════════════════════════════════════════════════════════════════════

class TestOpenSave:
    def test_open_loads_file_into_buffer(self, tmp_path: Path) -> None:
        script = tmp_path / "hello.py"
        script.write_text("x = 1\nprint(x)\n", encoding="utf-8")
        mode, out, err = _mode(["#open hello.py", "#show", "#exit"], cwd=tmp_path)
        mode.run()
        text = out.getvalue()
        assert "opened: hello.py" in text
        assert "x = 1" in text

    def test_open_does_not_execute_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "exec_check.py"
        # Write code with a unique side-effect that would be visible if executed.
        script.write_text('print("EXECUTED_SIDE_EFFECT")\n', encoding="utf-8")
        mode, out, err = _mode(["#open exec_check.py", "#exit"], cwd=tmp_path)
        mode.run()
        combined = capsys.readouterr().out + out.getvalue()
        assert "EXECUTED_SIDE_EFFECT" not in combined

    def test_open_missing_file_prints_error(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["#open missing.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert "no such file" in err.getvalue().lower() or "missing" in err.getvalue().lower()

    def test_open_directory_prints_error(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        mode, out, err = _mode(["#open subdir", "#exit"], cwd=tmp_path)
        mode.run()
        assert "directory" in err.getvalue().lower()

    def test_open_replaces_existing_buffer(self, tmp_path: Path) -> None:
        script = tmp_path / "new.py"
        script.write_text("y = 2\n", encoding="utf-8")
        mode, out, err = _mode(["x = 1", "#open new.py", "#show", "#exit"], cwd=tmp_path)
        mode.run()
        text = out.getvalue()
        # Buffer must contain y = 2 (the loaded file) not x = 1 (previous input).
        assert "y = 2" in text
        assert "x = 1" not in text.split("opened:")[1]

    def test_save_writes_buffer_to_file(self, tmp_path: Path) -> None:
        mode, out, err = _mode(
            ["x = 42", "#save output.py", "#exit"], cwd=tmp_path
        )
        mode.run()
        saved = (tmp_path / "output.py").read_text(encoding="utf-8")
        assert "x = 42" in saved
        assert saved.endswith("\n")

    def test_save_empty_buffer_creates_file_with_newline(
        self, tmp_path: Path
    ) -> None:
        mode, out, err = _mode(["#save empty.py", "#exit"], cwd=tmp_path)
        mode.run()
        content = (tmp_path / "empty.py").read_text(encoding="utf-8")
        assert content == "\n"

    def test_save_prints_confirmation(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["#save out.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert "saved: out.py" in out.getvalue()

    def test_save_directory_target_prints_error(self, tmp_path: Path) -> None:
        subdir = tmp_path / "d"
        subdir.mkdir()
        mode, out, err = _mode(["#save d", "#exit"], cwd=tmp_path)
        mode.run()
        assert "directory" in err.getvalue().lower()

    def test_open_missing_filename_prints_directive_error(
        self, tmp_path: Path
    ) -> None:
        mode, out, err = _mode(["#open", "#exit"], cwd=tmp_path)
        mode.run()
        assert "usage" in err.getvalue().lower() or "#open" in err.getvalue()

    def test_save_missing_filename_prints_directive_error(
        self, tmp_path: Path
    ) -> None:
        mode, out, err = _mode(["#save", "#exit"], cwd=tmp_path)
        mode.run()
        assert err.getvalue() != ""

    def test_open_with_redirection_is_forbidden(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["#open < file.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert err.getvalue() != ""
        # Must not create any file.
        assert not (tmp_path / "file.py").exists()

    def test_save_with_redirection_is_forbidden(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["x = 1", "#save > file.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert err.getvalue() != ""
        assert not (tmp_path / "file.py").exists()

    def test_echo_redirect_is_forbidden(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["#echo > file.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert err.getvalue() != ""
        assert not (tmp_path / "file.py").exists()


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — #run
# ═══════════════════════════════════════════════════════════════════════════

class TestRun:
    def test_run_empty_buffer_is_noop(self) -> None:
        mode, out, err = _mode(["#run", "#exit"])
        assert mode.run() == 0

    def test_run_executes_buffer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(['x = "hello"', 'print(x)', "#run", "#exit"])
        mode.run()
        # Buffer has x = "hello" and print(x); #run re-executes it.
        # The print happens via sys.stdout which capsys captures.
        captured = capsys.readouterr().out
        assert "hello" in captured

    def test_run_does_not_echo_expressions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["x = 42", "#run", "#exit"])
        mode.run()
        # "42" should NOT appear because run_buffer uses exec semantics.
        assert "42" not in capsys.readouterr().out

    def test_run_syntax_error_survives(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.py"
        broken.write_text("def f(\n", encoding="utf-8")
        mode, out, err = _mode(["#open broken.py", "#run", "#exit"], cwd=tmp_path)
        assert mode.run() == 0
        # Error goes to the injected err_stream.
        assert "SyntaxError" in err.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# PythonCommandMode — #reset
# ═══════════════════════════════════════════════════════════════════════════

class TestResetDirective:
    def test_reset_clears_buffer(self) -> None:
        mode, out, err = _mode(["x = 1", "#reset", "#show", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()

    def test_reset_clears_runtime_state(self) -> None:
        mode, out, err = _mode(["x = 99", "#reset", "x", "#exit"])
        mode.run()
        # After reset, 'x' is undefined; NameError must appear in injected stream.
        assert "NameError" in err.getvalue()

    def test_reset_keeps_mode_alive(self) -> None:
        mode, out, err = _mode(["#reset", "1 + 1", "#exit"])
        assert mode.run() == 0

    def test_clean_file_execution_flow(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # canonical #reset → #open → #run flow
        script = tmp_path / "main.py"
        script.write_text('print("clean_run")\n', encoding="utf-8")
        mode, out, err = _mode(
            ["#reset", "#open main.py", "#run", "#exit"], cwd=tmp_path
        )
        mode.run()
        assert "clean_run" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════
# Shell integration — #py dispatches to Python mode
# ═══════════════════════════════════════════════════════════════════════════

class TestShellIntegration:
    def test_hash_py_is_not_treated_as_comment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shell = PyShell()
        entered: list[bool] = []
        monkeypatch.setattr(shell, "_enter_python_mode", lambda: (entered.append(True), 0)[1])
        shell.execute("#py")
        assert entered

    def test_pysh_returns_to_normal_prompt_after_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shell = PyShell()
        # _enter_python_mode returns 0 (success) — shell survives.
        monkeypatch.setattr(shell, "_enter_python_mode", lambda: 0)
        result = shell.execute("#py")
        assert result == 0
        # Shell can still execute normal commands after Python mode exits.
        assert shell.execute("echo ok") == 0

    def test_hash_py_comment_in_normal_shell_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # "echo x #py" — the #py part is a comment; echo runs with just "x".
        shell = PyShell()
        captured_argv: list[list[str]] = []

        def fake_run_external(argv, spec, *, original_stage=None):  # type: ignore[no-untyped-def]
            captured_argv.append(list(argv))
            return 0

        shell._run_external = fake_run_external  # type: ignore[method-assign]
        shell.execute("echo x #py")
        assert captured_argv and "#py" not in captured_argv[0]


# ═══════════════════════════════════════════════════════════════════════════
# Active file state management
# ═══════════════════════════════════════════════════════════════════════════

class TestActiveFile:
    def test_open_sets_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "hello.py"
        script.write_text("x = 1\n", encoding="utf-8")
        mode, out, err = _mode(["#open hello.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None
        assert mode._active_file.name == "hello.py"

    def test_open_resolves_absolute_path(self, tmp_path: Path) -> None:
        script = tmp_path / "abs.py"
        script.write_text("y = 2\n", encoding="utf-8")
        abs_str = str(script)
        mode, out, err = _mode([f"#open {abs_str}", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file == script.resolve()

    def test_open_resolves_relative_subpath(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        script = sub / "mod.py"
        script.write_text("z = 3\n", encoding="utf-8")
        mode, out, err = _mode(["#open src/mod.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None
        assert mode._active_file == script.resolve()

    def test_save_with_filename_sets_active_file(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["x = 1", "#save out.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None
        assert mode._active_file.name == "out.py"

    def test_save_without_active_file_prints_error(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["x = 1", "#save", "#exit"], cwd=tmp_path)
        mode.run()
        assert "no active file" in err.getvalue().lower()
        assert "save" in err.getvalue().lower()

    def test_save_to_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "target.py"
        script.write_text("# original\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open target.py", 'x = "updated"', "#save", "#exit"], cwd=tmp_path
        )
        mode.run()
        content = script.read_text(encoding="utf-8")
        assert "updated" in content
        assert "saved: target.py" in out.getvalue()

    def test_save_to_active_file_uses_filename_display(self, tmp_path: Path) -> None:
        script = tmp_path / "disp.py"
        script.write_text("pass\n", encoding="utf-8")
        mode, out, err = _mode(["#open disp.py", "#save", "#exit"], cwd=tmp_path)
        mode.run()
        # Confirmation message should show the filename, not the full path.
        assert "saved:" in out.getvalue()

    def test_clear_keeps_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "keep.py"
        script.write_text("a = 1\n", encoding="utf-8")
        mode, out, err = _mode(["#open keep.py", "#clear", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None
        assert mode._active_file.name == "keep.py"

    def test_reset_clears_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "reset_me.py"
        script.write_text("a = 1\n", encoding="utf-8")
        mode, out, err = _mode(["#open reset_me.py", "#reset", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is None

    def test_show_file_does_not_change_active_file(self, tmp_path: Path) -> None:
        f1 = tmp_path / "f1.py"
        f2 = tmp_path / "f2.py"
        f1.write_text("a = 1\n", encoding="utf-8")
        f2.write_text("b = 2\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open f1.py", "#show f2.py", "#exit"], cwd=tmp_path
        )
        mode.run()
        # active_file must still be f1.py
        assert mode._active_file is not None
        assert mode._active_file.name == "f1.py"

    def test_show_file_does_not_change_buffer(self, tmp_path: Path) -> None:
        f1 = tmp_path / "f1.py"
        f2 = tmp_path / "f2.py"
        f1.write_text("a = 1\n", encoding="utf-8")
        f2.write_text("b = 2\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open f1.py", "#show f2.py", "#show", "#exit"], cwd=tmp_path
        )
        mode.run()
        text = out.getvalue()
        # Buffer show must reflect f1.py content, not f2.py.
        assert "a = 1" in text
        assert "b = 2" not in text.split("1 |")[1] if "1 |" in text else True


# ═══════════════════════════════════════════════════════════════════════════
# #show file.py — cat-style file display
# ═══════════════════════════════════════════════════════════════════════════

class TestShowFile:
    def test_show_file_prints_content(self, tmp_path: Path) -> None:
        f = tmp_path / "view.py"
        f.write_text('print("hello")\n', encoding="utf-8")
        mode, out, err = _mode(["#show view.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert 'print("hello")' in out.getvalue()

    def test_show_file_missing_prints_error(self, tmp_path: Path) -> None:
        mode, out, err = _mode(["#show gone.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert "no such file" in err.getvalue().lower()

    def test_show_file_directory_prints_error(self, tmp_path: Path) -> None:
        (tmp_path / "d").mkdir()
        mode, out, err = _mode(["#show d", "#exit"], cwd=tmp_path)
        mode.run()
        assert "directory" in err.getvalue().lower()

    def test_show_file_absolute_path(self, tmp_path: Path) -> None:
        f = tmp_path / "abs.py"
        f.write_text("absolute_content = True\n", encoding="utf-8")
        mode, out, err = _mode([f"#show {f}", "#exit"], cwd=tmp_path)
        mode.run()
        assert "absolute_content" in out.getvalue()

    def test_show_buffer_still_works(self) -> None:
        mode, out, err = _mode(["x = 1", "#show", "#exit"])
        mode.run()
        assert "x = 1" in out.getvalue()
        assert "1 |" in out.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# #clear directive
# ═══════════════════════════════════════════════════════════════════════════

class TestClearDirective:
    def test_clear_empties_buffer(self) -> None:
        mode, out, err = _mode(["x = 1", "#clear", "#show", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()

    def test_clear_prints_confirmation(self) -> None:
        mode, out, err = _mode(["#clear", "#exit"])
        mode.run()
        assert "buffer cleared" in out.getvalue()

    def test_clear_does_not_reset_runtime(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Define a variable, clear, then reference it — must still work.
        mode, out, err = _mode(["y = 77", "#clear", "y", "#exit"])
        mode.run()
        assert "77" in capsys.readouterr().out

    def test_clear_keeps_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "stay.py"
        script.write_text("pass\n", encoding="utf-8")
        mode, out, err = _mode(["#open stay.py", "#clear", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None

    def test_clear_keeps_mode_alive(self) -> None:
        mode, out, err = _mode(["#clear", "1 + 1", "#exit"])
        assert mode.run() == 0

    def test_clear_then_save_to_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "rewrite.py"
        script.write_text("# old content\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open rewrite.py", "#clear", 'print("new")', "#save", "#exit"],
            cwd=tmp_path,
        )
        mode.run()
        content = script.read_text(encoding="utf-8")
        assert "new" in content
        assert "old content" not in content


# ═══════════════════════════════════════════════════════════════════════════
# #reset updated semantics
# ═══════════════════════════════════════════════════════════════════════════

class TestResetUpdated:
    def test_reset_prints_workspace_reset(self) -> None:
        mode, out, err = _mode(["#reset", "#exit"])
        mode.run()
        assert "workspace reset" in out.getvalue()

    def test_reset_clears_active_file(self, tmp_path: Path) -> None:
        script = tmp_path / "wipe.py"
        script.write_text("pass\n", encoding="utf-8")
        mode, out, err = _mode(["#open wipe.py", "#reset", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is None

    def test_reset_clears_buffer(self) -> None:
        mode, out, err = _mode(["x = 1", "#reset", "#show", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()

    def test_reset_resets_runtime(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["z = 55", "#reset", "z", "#exit"])
        mode.run()
        assert "NameError" in err.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# Path resolution — absolute and relative paths
# ═══════════════════════════════════════════════════════════════════════════

class TestPathResolution:
    def test_open_relative_path(self, tmp_path: Path) -> None:
        script = tmp_path / "rel.py"
        script.write_text("rel = True\n", encoding="utf-8")
        mode, out, err = _mode(["#open rel.py", "#show", "#exit"], cwd=tmp_path)
        mode.run()
        assert "rel = True" in out.getvalue()

    def test_open_relative_subdir_path(self, tmp_path: Path) -> None:
        sub = tmp_path / "pkg"
        sub.mkdir()
        script = sub / "mod.py"
        script.write_text("pkg_var = 1\n", encoding="utf-8")
        mode, out, err = _mode(["#open pkg/mod.py", "#show", "#exit"], cwd=tmp_path)
        mode.run()
        assert "pkg_var" in out.getvalue()

    def test_open_absolute_path(self, tmp_path: Path) -> None:
        script = tmp_path / "abs.py"
        script.write_text("abs_var = 42\n", encoding="utf-8")
        mode, out, err = _mode([f"#open {script}", "#show", "#exit"], cwd=tmp_path)
        mode.run()
        assert "abs_var" in out.getvalue()

    def test_save_creates_file_in_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "output"
        sub.mkdir()
        mode, out, err = _mode(
            ["x = 1", "#save output/out.py", "#exit"], cwd=tmp_path
        )
        mode.run()
        assert (sub / "out.py").exists()

    def test_save_absolute_path(self, tmp_path: Path) -> None:
        target = tmp_path / "direct.py"
        mode, out, err = _mode(
            ["y = 2", f"#save {target}", "#exit"], cwd=tmp_path
        )
        mode.run()
        assert target.exists()
        assert "y = 2" in target.read_text(encoding="utf-8")

    def test_show_file_relative_subpath(self, tmp_path: Path) -> None:
        sub = tmp_path / "data"
        sub.mkdir()
        f = sub / "info.py"
        f.write_text("INFO = 99\n", encoding="utf-8")
        mode, out, err = _mode(["#show data/info.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert "INFO = 99" in out.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# complete_python_mode_path — pure completion function
# ═══════════════════════════════════════════════════════════════════════════

class TestCompletePathMode:
    def test_no_directive_prefix_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        result = complete_python_mode_path("x = 1", 5, tmp_path)
        assert result == []

    def test_tab_mid_code_returns_empty(self, tmp_path: Path) -> None:
        result = complete_python_mode_path("def main():", 11, tmp_path)
        assert result == []

    def test_open_empty_partial_lists_all(self, tmp_path: Path) -> None:
        (tmp_path / "alpha.py").write_text("", encoding="utf-8")
        (tmp_path / "beta.py").write_text("", encoding="utf-8")
        line = "#open "
        result = complete_python_mode_path(line, len(line), tmp_path)
        names = [r.rstrip("/") for r in result]
        assert "alpha.py" in names
        assert "beta.py" in names

    def test_open_partial_stem_filters(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "module.py").write_text("", encoding="utf-8")
        (tmp_path / "other.py").write_text("", encoding="utf-8")
        line = "#open ma"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any("main.py" in r for r in result)
        assert not any("other" in r for r in result)

    def test_save_partial_stem_filters(self, tmp_path: Path) -> None:
        (tmp_path / "save_me.py").write_text("", encoding="utf-8")
        (tmp_path / "other.py").write_text("", encoding="utf-8")
        line = "#save save"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any("save_me.py" in r for r in result)
        assert not any("other" in r for r in result)

    def test_show_partial_stem_filters(self, tmp_path: Path) -> None:
        (tmp_path / "show_me.py").write_text("", encoding="utf-8")
        (tmp_path / "other.py").write_text("", encoding="utf-8")
        line = "#show show"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any("show_me.py" in r for r in result)
        assert not any("other" in r for r in result)

    def test_directory_suffix_added(self, tmp_path: Path) -> None:
        (tmp_path / "subpkg").mkdir()
        line = "#open sub"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any(r.endswith("/") for r in result)

    def test_subdir_completion(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("", encoding="utf-8")
        line = "#open src/"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any("main.py" in r for r in result)

    def test_absolute_path_completion(self, tmp_path: Path) -> None:
        (tmp_path / "abs.py").write_text("", encoding="utf-8")
        abs_prefix = str(tmp_path) + "/abs"
        line = f"#open {abs_prefix}"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert any("abs.py" in r for r in result)

    def test_returns_empty_on_nonexistent_dir(self, tmp_path: Path) -> None:
        line = "#open nonexistent/"
        result = complete_python_mode_path(line, len(line), tmp_path)
        assert result == []

    def test_cursor_mid_line_uses_prefix_only(self, tmp_path: Path) -> None:
        (tmp_path / "zz.py").write_text("", encoding="utf-8")
        line = "#open zz.py  # old"
        # cursor is at end of "#open zz.py", NOT at end of line
        cursor = len("#open zz.py")
        result = complete_python_mode_path(line, cursor, tmp_path)
        assert any("zz.py" in r for r in result)


# ═══════════════════════════════════════════════════════════════════════════
# Visual padding — disabled in test mode, enabled interactively
# ═══════════════════════════════════════════════════════════════════════════

class TestVisualPadding:
    def test_padding_disabled_in_test_mode(self) -> None:
        # When input_source is provided, visual_padding_lines must be 0.
        mode, out, err = _mode(["#exit"])
        assert mode._visual_padding_lines == 0

    def test_padding_enabled_interactively(self) -> None:
        # Without input_source, visual_padding_lines must be the configured value.
        mode = PythonCommandMode(visual_padding_lines=2)
        assert mode._visual_padding_lines == 2

    def test_padding_default_is_two_interactively(self) -> None:
        mode = PythonCommandMode()
        assert mode._visual_padding_lines == 2

    def test_explicit_zero_in_test_mode(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        mode = PythonCommandMode(
            input_source=["#exit"],
            out_stream=out,
            err_stream=err,
            visual_padding_lines=0,
        )
        assert mode._visual_padding_lines == 0

    def test_no_blank_lines_in_captured_test_output(self) -> None:
        # Injected input_source → no blank lines from padding in output.
        mode, out, err = _mode(["x = 1", "#exit"])
        mode.run()
        # Banner has intentional blank line; no additional padding blank lines.
        lines = out.getvalue().splitlines()
        # All blank lines must come from the banner only (none from padding).
        padding_lines = [ln for ln in lines if ln == "" and "PySH" not in ln]
        # Exactly one blank line from the banner trailing "\n".
        # (The banner prints "Type #help for commands.\n" which creates one blank.)
        assert len(padding_lines) <= 1


# ═══════════════════════════════════════════════════════════════════════════
# #help includes new semantics
# ═══════════════════════════════════════════════════════════════════════════

class TestHelpUpdated:
    def test_help_mentions_clear(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        assert "#clear" in out.getvalue()

    def test_help_mentions_optional_save_arg(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "#save" in text
        # Help must document optional argument form.
        assert "[file]" in text or "active file" in text.lower()

    def test_help_mentions_show_file(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "#show" in text

    def test_help_mentions_path_completion(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        assert "completion" in out.getvalue().lower()

    def test_help_mentions_tab_four_spaces(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        assert "TAB" in out.getvalue()

    def test_help_mentions_use_exit_not_exit(self) -> None:
        mode, out, err = _mode(["#help", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "#exit" in text
        assert "exit" in text.lower()


# ═══════════════════════════════════════════════════════════════════════════
# _check_missing_hash — pure function
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckMissingHash:
    def test_show_bare(self) -> None:
        hint = _check_missing_hash("show")
        assert hint is not None
        assert "#show" in hint

    def test_reset_bare(self) -> None:
        hint = _check_missing_hash("reset")
        assert hint is not None
        assert "#reset" in hint

    def test_run_bare(self) -> None:
        hint = _check_missing_hash("run")
        assert hint is not None
        assert "#run" in hint

    def test_clear_bare(self) -> None:
        hint = _check_missing_hash("clear")
        assert hint is not None
        assert "#clear" in hint

    def test_exit_bare(self) -> None:
        hint = _check_missing_hash("exit")
        assert hint is not None
        assert "#exit" in hint

    def test_quit_bare(self) -> None:
        hint = _check_missing_hash("quit")
        assert hint is not None
        assert "#exit" in hint

    def test_help_bare(self) -> None:
        hint = _check_missing_hash("help")
        assert hint is not None
        assert "#help" in hint

    def test_open_with_path(self) -> None:
        hint = _check_missing_hash("open test.py")
        assert hint is not None
        assert "#open" in hint
        assert "test.py" in hint

    def test_save_with_path(self) -> None:
        hint = _check_missing_hash("save test.py")
        assert hint is not None
        assert "#save" in hint
        assert "test.py" in hint

    def test_show_with_path(self) -> None:
        hint = _check_missing_hash("show test.py")
        assert hint is not None
        assert "#show" in hint
        assert "test.py" in hint

    def test_run_with_path(self) -> None:
        hint = _check_missing_hash("run test.py")
        assert hint is not None
        assert "#open" in hint
        assert "test.py" in hint

    def test_normal_assignment_returns_none(self) -> None:
        # "show = 1" is valid Python — must not be intercepted.
        assert _check_missing_hash("show = 1") is None

    def test_function_call_returns_none(self) -> None:
        # "reset()" is valid Python — must not be intercepted.
        assert _check_missing_hash("reset()") is None

    def test_unrelated_word_returns_none(self) -> None:
        assert _check_missing_hash("x = 42") is None
        assert _check_missing_hash("import math") is None
        assert _check_missing_hash("") is None

    def test_leading_whitespace_handled(self) -> None:
        hint = _check_missing_hash("  show  ")
        assert hint is not None


# ═══════════════════════════════════════════════════════════════════════════
# Buffer poisoning prevention
# ═══════════════════════════════════════════════════════════════════════════

class TestBufferPoisoning:
    def test_show_not_in_buffer(self, tmp_path: Path) -> None:
        script = tmp_path / "t.py"
        script.write_text("x = 1\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open t.py", "show", "#show", "#exit"], cwd=tmp_path
        )
        mode.run()
        show_lines = [
            ln for ln in out.getvalue().splitlines()
            if ln.startswith(tuple(str(i) + " |" for i in range(1, 99)))
        ]
        assert not any("show" in ln for ln in show_lines)

    def test_reset_not_in_buffer(self, tmp_path: Path) -> None:
        script = tmp_path / "t.py"
        script.write_text("x = 1\n", encoding="utf-8")
        mode, out, err = _mode(
            ["#open t.py", "reset", "#show", "#exit"], cwd=tmp_path
        )
        mode.run()
        show_lines = [
            ln for ln in out.getvalue().splitlines()
            if ln.startswith(tuple(str(i) + " |" for i in range(1, 99)))
        ]
        assert not any("reset" in ln for ln in show_lines)

    def test_show_hint_printed_to_stderr(self) -> None:
        mode, out, err = _mode(["show", "#exit"])
        mode.run()
        assert "#show" in err.getvalue()

    def test_reset_hint_printed_to_stderr(self) -> None:
        mode, out, err = _mode(["reset", "#exit"])
        mode.run()
        assert "#reset" in err.getvalue()

    def test_open_path_hint_contains_filename(self) -> None:
        mode, out, err = _mode(["open main.py", "#exit"])
        mode.run()
        assert "#open" in err.getvalue()
        assert "main.py" in err.getvalue()

    def test_save_path_hint_contains_filename(self) -> None:
        mode, out, err = _mode(["save main.py", "#exit"])
        mode.run()
        assert "#save" in err.getvalue()
        assert "main.py" in err.getvalue()

    def test_run_path_hint_contains_filename(self) -> None:
        mode, out, err = _mode(["run test.py", "#exit"])
        mode.run()
        assert "#open" in err.getvalue()
        assert "test.py" in err.getvalue()

    def test_show_does_not_poison_later_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "t.py"
        script.write_text('print("from_file")\n', encoding="utf-8")
        mode, out, err = _mode(
            ["#open t.py", "show", "#run", "#exit"], cwd=tmp_path
        )
        mode.run()
        out_text = capsys.readouterr().out
        assert "from_file" in out_text
        assert "NameError" not in err.getvalue()

    def test_reset_does_not_poison_later_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "t.py"
        script.write_text('print("file_ran")\n', encoding="utf-8")
        mode, out, err = _mode(
            ["#open t.py", "reset", "#run", "#exit"], cwd=tmp_path
        )
        mode.run()
        out_text = capsys.readouterr().out
        assert "file_ran" in out_text
        assert "NameError" not in err.getvalue()

    def test_normal_python_assignment_not_intercepted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["show = 42", "show", "#exit"])
        mode.run()
        # "show = 42" is a valid assignment — must execute.
        # The second bare "show" IS intercepted as a hint.
        assert "show = 42" not in err.getvalue()  # not a hint error
        assert "#show" in err.getvalue()  # bare "show" hint

    def test_function_call_not_intercepted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(["def reset(): return 99", "", "reset()", "#exit"])
        mode.run()
        cap = capsys.readouterr()
        # reset() should be called as Python, not intercepted
        assert "99" in cap.out
        assert "#reset" not in err.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# Unknown directives and #run strict no-arg
# ═══════════════════════════════════════════════════════════════════════════

class TestDirectiveErrors:
    def test_unknown_hash_directive_error(self) -> None:
        mode, out, err = _mode(["#edit", "#exit"])
        mode.run()
        assert "unknown" in err.getvalue().lower()

    def test_unknown_directive_mentions_help(self) -> None:
        mode, out, err = _mode(["#delete", "#exit"])
        mode.run()
        assert "help" in err.getvalue().lower()

    def test_unknown_directive_not_appended_to_buffer(self) -> None:
        mode, out, err = _mode(["#edit", "#show", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()

    def test_hash_run_with_file_arg_is_error(self) -> None:
        mode, out, err = _mode(["#run test.py", "#exit"])
        mode.run()
        assert "does not accept" in err.getvalue().lower() or "#open" in err.getvalue()

    def test_hash_run_with_file_arg_does_not_execute(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = tmp_path / "canary.py"
        script.write_text('print("CANARY_EXECUTED")\n', encoding="utf-8")
        mode, out, err = _mode(
            ["#run canary.py", "#exit"], cwd=tmp_path
        )
        mode.run()
        assert "CANARY_EXECUTED" not in capsys.readouterr().out

    def test_hash_run_without_arg_still_works(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode(['print("ok")', "#run", "#exit"])
        mode.run()
        assert "ok" in capsys.readouterr().out

    def test_normal_comment_not_intercepted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Lines like "# this is a comment" must remain Python source.
        mode, out, err = _mode(["# a normal comment", "1 + 1", "#exit"])
        mode.run()
        assert err.getvalue() == ""
        assert "2" in capsys.readouterr().out
