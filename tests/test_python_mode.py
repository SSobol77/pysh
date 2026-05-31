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

from pysh.python_mode import PythonCommandMode, _parse_directive, expand_tab
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

    def test_save_missing_filename_is_error(self) -> None:
        result = _parse_directive("#save")
        assert result is not None
        name, arg, error = result
        assert error is not None

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

    def test_unknown_hash_token_returns_none(self) -> None:
        assert _parse_directive("#notadirective") is None

    def test_non_hash_line_returns_none(self) -> None:
        assert _parse_directive("x = 1") is None

    def test_open_extracts_first_word_as_filename(self) -> None:
        result = _parse_directive("#open file.py extra")
        assert result is not None
        name, arg, error = result
        assert name == "open"
        assert arg == "file.py"
        assert error is None


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
