# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_error_exit_code_contract.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Error and exit-code contract tests (Issue #5).

Covers:
- ExitCode canonical numeric values.
- signal_exit_code mapping.
- PyShError taxonomy (exception types and exit codes).
- Diagnostic / exception_to_diagnostic boundary function.
- External command exit propagation.
- Command-not-found → 127.
- Found-but-not-executable → 126.
- Builtin misuse → 2.
- Parse/syntax error → 2.
- $? propagation after success, failure, missing command, exit 7.
- SIGINT mapping (via signal_exit_code; no flaky process tests).
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

from pysh.core.errors import (
    BuiltinUsageError,
    CommandNotExecutableError,
    CommandNotFoundError,
    Diagnostic,
    ExecutionError,
    ExitCode,
    PyShError,
    PyShInterruptedError,
    PyShParseError,
    diagnostic_to_exit_code,
    exception_to_diagnostic,
    signal_exit_code,
)
from pysh.core.shell import PyShell
from pysh.parsing.parser import expand_variables

# ---------------------------------------------------------------------------
# ExitCode canonical values
# ---------------------------------------------------------------------------


class TestExitCodeValues:
    def test_success(self) -> None:
        assert int(ExitCode.SUCCESS) == 0

    def test_general_error(self) -> None:
        assert int(ExitCode.GENERAL_ERROR) == 1

    def test_builtin_misuse(self) -> None:
        assert int(ExitCode.BUILTIN_MISUSE) == 2

    def test_cannot_execute(self) -> None:
        assert int(ExitCode.CANNOT_EXECUTE) == 126

    def test_command_not_found(self) -> None:
        assert int(ExitCode.COMMAND_NOT_FOUND) == 127

    def test_signal_base(self) -> None:
        assert int(ExitCode.SIGNAL_BASE) == 128

    def test_sigint(self) -> None:
        assert int(ExitCode.SIGINT) == 130

    def test_exit_code_is_int(self) -> None:
        assert isinstance(ExitCode.SUCCESS, int)
        assert isinstance(ExitCode.COMMAND_NOT_FOUND, int)


# ---------------------------------------------------------------------------
# signal_exit_code mapping
# ---------------------------------------------------------------------------


class TestSignalExitCode:
    def test_sigint_is_130(self) -> None:
        assert signal_exit_code(2) == 130

    def test_sigterm_is_143(self) -> None:
        assert signal_exit_code(15) == 143

    def test_sighup_is_129(self) -> None:
        assert signal_exit_code(1) == 129

    def test_formula_is_128_plus_signum(self) -> None:
        for sig in range(1, 32):
            assert signal_exit_code(sig) == 128 + sig


# ---------------------------------------------------------------------------
# PyShError taxonomy
# ---------------------------------------------------------------------------


class TestPyShErrorTaxonomy:
    def test_pysh_error_is_exception(self) -> None:
        assert issubclass(PyShError, Exception)

    def test_pysh_error_default_exit_code(self) -> None:
        err = PyShError("oops")
        assert err.exit_code == ExitCode.GENERAL_ERROR

    def test_pysh_error_custom_exit_code(self) -> None:
        err = PyShError("bad", exit_code=42)
        assert err.exit_code == 42

    def test_command_not_found_error_code(self) -> None:
        err = CommandNotFoundError("missing_cmd")
        assert err.exit_code == ExitCode.COMMAND_NOT_FOUND
        assert err.command == "missing_cmd"
        assert "missing_cmd" in str(err)

    def test_command_not_executable_error_code(self) -> None:
        err = CommandNotExecutableError("locked_cmd")
        assert err.exit_code == ExitCode.CANNOT_EXECUTE
        assert err.command == "locked_cmd"

    def test_command_not_executable_with_detail(self) -> None:
        err = CommandNotExecutableError("cmd", "Permission denied")
        assert "Permission denied" in str(err)

    def test_builtin_usage_error_code(self) -> None:
        err = BuiltinUsageError("cd")
        assert err.exit_code == ExitCode.BUILTIN_MISUSE
        assert err.builtin == "cd"

    def test_builtin_usage_error_with_detail(self) -> None:
        err = BuiltinUsageError("export", "too many arguments")
        assert "too many arguments" in str(err)

    def test_parse_error_code(self) -> None:
        err = PyShParseError("unexpected token")
        assert err.exit_code == ExitCode.BUILTIN_MISUSE
        assert "unexpected token" in str(err)

    def test_parse_error_empty(self) -> None:
        err = PyShParseError()
        assert "parse error" in str(err)

    def test_execution_error_default_code(self) -> None:
        err = ExecutionError("failed")
        assert err.exit_code == ExitCode.GENERAL_ERROR

    def test_execution_error_custom_code(self) -> None:
        err = ExecutionError("terminated", exit_code=ExitCode.SIGINT)
        assert err.exit_code == ExitCode.SIGINT

    def test_interrupted_error_code(self) -> None:
        err = PyShInterruptedError()
        assert err.exit_code == ExitCode.SIGINT

    def test_all_errors_are_pysh_errors(self) -> None:
        for cls in (
            CommandNotFoundError,
            CommandNotExecutableError,
            BuiltinUsageError,
            PyShParseError,
            ExecutionError,
            PyShInterruptedError,
        ):
            assert issubclass(cls, PyShError)


# ---------------------------------------------------------------------------
# Diagnostic and boundary functions
# ---------------------------------------------------------------------------


class TestDiagnostic:
    def test_format_stderr(self) -> None:
        d = Diagnostic(message="something went wrong", exit_code=1)
        assert d.format_stderr() == "pysh: something went wrong"

    def test_format_stderr_custom_prefix(self) -> None:
        d = Diagnostic(message="oops", exit_code=1, prefix="myapp")
        assert d.format_stderr() == "myapp: oops"

    def test_diagnostic_to_exit_code(self) -> None:
        d = Diagnostic(message="err", exit_code=127)
        assert diagnostic_to_exit_code(d) == 127

    def test_exception_to_diagnostic_pysh_error(self) -> None:
        err = CommandNotFoundError("missing")
        d = exception_to_diagnostic(err)
        assert d.exit_code == ExitCode.COMMAND_NOT_FOUND
        assert "missing" in d.message

    def test_exception_to_diagnostic_builtin_error(self) -> None:
        err = BuiltinUsageError("cd", "too many args")
        d = exception_to_diagnostic(err)
        assert d.exit_code == ExitCode.BUILTIN_MISUSE

    def test_exception_to_diagnostic_keyboard_interrupt(self) -> None:
        d = exception_to_diagnostic(KeyboardInterrupt())
        assert d.exit_code == ExitCode.SIGINT
        assert "interrupted" in d.message.lower()

    def test_exception_to_diagnostic_file_not_found(self) -> None:
        exc = FileNotFoundError(2, "No such file or directory", "my_cmd")
        d = exception_to_diagnostic(exc)
        assert d.exit_code == ExitCode.COMMAND_NOT_FOUND

    def test_exception_to_diagnostic_permission_error(self) -> None:
        exc = PermissionError(13, "Permission denied", "no_exec")
        d = exception_to_diagnostic(exc)
        assert d.exit_code == ExitCode.CANNOT_EXECUTE

    def test_exception_to_diagnostic_generic(self) -> None:
        d = exception_to_diagnostic(RuntimeError("something unexpected"))
        assert d.exit_code == ExitCode.GENERAL_ERROR
        assert "something unexpected" in d.message

    def test_exception_to_diagnostic_no_traceback_leak(self) -> None:
        d = exception_to_diagnostic(ValueError("bad value"))
        # Message should be the exception string, not a traceback
        assert "Traceback" not in d.message
        assert d.exit_code == ExitCode.GENERAL_ERROR

    def test_exception_to_diagnostic_empty_message(self) -> None:
        d = exception_to_diagnostic(RuntimeError(""))
        # Falls back to "internal error"
        assert d.message == "internal error"


# ---------------------------------------------------------------------------
# External command exit propagation
# ---------------------------------------------------------------------------


class TestExternalCommandPropagation:
    def test_exit_0_propagated(self) -> None:
        shell = PyShell()
        assert shell.execute("true") == 0

    def test_exit_1_propagated(self) -> None:
        shell = PyShell()
        assert shell.execute("false") == 1

    def test_exit_code_7_propagated(self) -> None:
        shell = PyShell()
        status = shell.execute(f"{sys.executable} -c 'import sys; sys.exit(7)'")
        assert status == 7

    def test_exit_code_42_propagated(self) -> None:
        shell = PyShell()
        status = shell.execute(f"{sys.executable} -c 'import sys; sys.exit(42)'")
        assert status == 42


# ---------------------------------------------------------------------------
# Command-not-found → 127
# ---------------------------------------------------------------------------


class TestCommandNotFound:
    def test_missing_command_returns_127(self) -> None:
        shell = PyShell()
        status = shell.execute("__pysh_no_such_command_xyz_12345")
        assert status == ExitCode.COMMAND_NOT_FOUND

    def test_missing_command_in_pipeline_returns_127(self) -> None:
        shell = PyShell()
        status = shell.execute("echo hello | __pysh_no_such_command_abc")
        assert status == ExitCode.COMMAND_NOT_FOUND


# ---------------------------------------------------------------------------
# Found-but-not-executable → 126
# ---------------------------------------------------------------------------


class TestCannotExecute:
    def test_non_executable_file_returns_126(self, tmp_path: Path) -> None:
        script = tmp_path / "not_executable.sh"
        script.write_text("#!/bin/sh\necho hi\n")
        # Ensure file is NOT executable
        script.chmod(stat.S_IRUSR | stat.S_IWUSR)
        shell = PyShell()
        status = shell.execute(str(script))
        assert status == ExitCode.CANNOT_EXECUTE


# ---------------------------------------------------------------------------
# Builtin misuse → 2
# ---------------------------------------------------------------------------


class TestBuiltinMisuse:
    def test_cd_missing_target_is_not_2(self) -> None:
        # cd with no args is valid (goes home); with nonexistent dir is 1
        shell = PyShell()
        status = shell.execute("cd /nonexistent_path_xyz_12345")
        assert status == ExitCode.GENERAL_ERROR  # OSError → 1

    def test_pushd_missing_arg_returns_2(self) -> None:
        shell = PyShell()
        assert shell.execute("pushd") == ExitCode.BUILTIN_MISUSE

    def test_popd_empty_stack_returns_1(self) -> None:
        shell = PyShell()
        status = shell.execute("popd")
        assert status == ExitCode.GENERAL_ERROR  # empty stack

    def test_export_no_args_is_0(self) -> None:
        shell = PyShell()
        assert shell.execute("export") == ExitCode.SUCCESS

    def test_unalias_no_args_returns_2(self) -> None:
        shell = PyShell()
        assert shell.execute("unalias") == ExitCode.BUILTIN_MISUSE

    def test_parse_error_returns_2(self) -> None:
        shell = PyShell()
        # shlex.split raises ValueError on unclosed quote
        status = shell.execute("echo 'unclosed")
        assert status == ExitCode.BUILTIN_MISUSE


# ---------------------------------------------------------------------------
# $? propagation
# ---------------------------------------------------------------------------


class TestDollarQuestionPropagation:
    """$? expands to the last command exit status."""

    def test_dollar_question_after_success(self) -> None:
        shell = PyShell()
        shell.execute("true")
        assert shell.last_status == 0
        expanded = expand_variables("$?", {}, special_vars={"?": str(shell.last_status)})
        assert expanded == "0"

    def test_dollar_question_after_false(self) -> None:
        shell = PyShell()
        shell.execute("false")
        assert shell.last_status == 1
        expanded = expand_variables("$?", {}, special_vars={"?": str(shell.last_status)})
        assert expanded == "1"

    def test_dollar_question_after_missing_command(self) -> None:
        shell = PyShell()
        shell.execute("__no_such_cmd_xyz_999")
        assert shell.last_status == ExitCode.COMMAND_NOT_FOUND
        expanded = expand_variables("$?", {}, special_vars={"?": str(shell.last_status)})
        assert expanded == "127"

    def test_dollar_question_after_exit_7(self) -> None:
        shell = PyShell()
        shell.execute(f"{sys.executable} -c 'import sys; sys.exit(7)'")
        assert shell.last_status == 7
        expanded = expand_variables("$?", {}, special_vars={"?": str(shell.last_status)})
        assert expanded == "7"

    def test_dollar_question_in_command_arg(self) -> None:
        """$? expands in a command argument using shell execute."""
        shell = PyShell()
        shell.execute("false")
        assert shell.last_status == 1
        # $? should expand to "1" in the next command
        status = shell.execute(
            f"{sys.executable} -c "
            f"\"import sys; val=int('$?'); sys.exit(0 if val == 1 else 99)\""
        )
        # This tests that $? was expanded before the command ran
        assert status == 0

    def test_dollar_question_in_single_quotes_is_literal(self) -> None:
        expanded = expand_variables("'$?'", {}, special_vars={"?": "99"})
        assert expanded == "'$?'"  # single quotes suppress expansion

    def test_dollar_question_in_double_quotes_expands(self) -> None:
        expanded = expand_variables('"$?"', {}, special_vars={"?": "42"})
        assert expanded == '"42"'

    def test_dollar_question_without_special_vars_is_zero(self) -> None:
        # When no special_vars are passed, $? defaults to "0"
        expanded = expand_variables("$?", {})
        assert expanded == "0"


# ---------------------------------------------------------------------------
# expand_variables: $? specific tests (parser level)
# ---------------------------------------------------------------------------


class TestExpandVariablesDollarQuestion:
    def test_dollar_question_basic(self) -> None:
        out = expand_variables("$?", {}, special_vars={"?": "7"})
        assert out == "7"

    def test_dollar_question_in_string(self) -> None:
        out = expand_variables("status=$?", {}, special_vars={"?": "42"})
        assert out == "status=42"

    def test_dollar_question_next_to_text(self) -> None:
        out = expand_variables("exit:$?!", {}, special_vars={"?": "1"})
        assert out == "exit:1!"

    def test_dollar_question_default_zero(self) -> None:
        out = expand_variables("$?", {}, special_vars={})
        assert out == "0"

    def test_regular_vars_still_work(self) -> None:
        out = expand_variables("$NAME $?", {"NAME": "world"}, special_vars={"?": "0"})
        assert out == "world 0"

    def test_dollar_question_suppressed_in_single_quotes(self) -> None:
        out = expand_variables("'$?'", {}, special_vars={"?": "5"})
        assert out == "'$?'"


# ---------------------------------------------------------------------------
# Parse error mapping
# ---------------------------------------------------------------------------


class TestParseErrorMapping:
    def test_unclosed_quote_returns_2(self) -> None:
        shell = PyShell()
        assert shell.execute("echo 'not closed") == ExitCode.BUILTIN_MISUSE

    def test_unterminated_py_block_returns_2(self) -> None:
        shell = PyShell()
        # A bare py { without collected body is a usage error
        assert shell.execute("py {") == ExitCode.BUILTIN_MISUSE

    def test_pipe_with_empty_trailing_stage(self) -> None:
        shell = PyShell()
        # A trailing pipe with no command after it: the parser filters the
        # empty stage and runs the preceding command.  This is current
        # behavior; a stricter syntax error here is deferred to Issue #8.
        status = shell.execute("echo hello | ")
        # Currently succeeds (empty trailing stage ignored by split_pipeline)
        assert status == ExitCode.SUCCESS


# ---------------------------------------------------------------------------
# SIGINT mapping — tested via signal_exit_code (no flaky process interaction)
# ---------------------------------------------------------------------------


class TestSigintMapping:
    def test_signal_exit_code_for_sigint(self) -> None:
        """SIGINT (signal 2) maps to exit code 130 per 128+signum convention."""
        assert signal_exit_code(2) == 130

    def test_exit_code_sigint_equals_130(self) -> None:
        assert ExitCode.SIGINT == 130  # noqa: PLR2004

    def test_signal_exit_code_matches_sigint_constant(self) -> None:
        assert signal_exit_code(2) == ExitCode.SIGINT
