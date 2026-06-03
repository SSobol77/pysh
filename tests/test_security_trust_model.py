# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Security and trust model tests (Issue #7).

Covers:
A. Trust model policy predicates (policy.py).
B. Static profile import safety — profile_importer does not execute code.
C. Explicit delegation — zsh_fallback off by default, ZshBridge uses zsh -lc.
D. Sensitive input boundary — normal command path does not use SecureRunner.
E. Diagnostics non-mutation — plan/env_audit/apt_check non-executing.
F. Python runtime trust — py executes in-process; is_python_runtime_sandboxed()
   returns False.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pysh.security.policy import (
    ExecutionMode,
    SecurityBoundary,
    TrustLevel,
    is_foreign_profile_execution_forbidden_by_default,
    is_pty_bridge_opt_in,
    is_python_runtime_sandboxed,
)

# ---------------------------------------------------------------------------
# A. Trust model policy predicates
# ---------------------------------------------------------------------------


class TestTrustModel:
    def test_foreign_profile_execution_forbidden_by_default(self) -> None:
        assert is_foreign_profile_execution_forbidden_by_default() is True

    def test_pty_bridge_is_opt_in(self) -> None:
        assert is_pty_bridge_opt_in() is True

    def test_python_runtime_is_not_sandboxed(self) -> None:
        assert is_python_runtime_sandboxed() is False

    def test_trust_levels_are_distinct(self) -> None:
        levels = list(TrustLevel)
        assert len(levels) == len(set(str(lv) for lv in levels))

    def test_execution_modes_are_distinct(self) -> None:
        modes = list(ExecutionMode)
        assert len(modes) == len(set(str(m) for m in modes))

    def test_security_boundaries_are_distinct(self) -> None:
        bounds = list(SecurityBoundary)
        assert len(bounds) == len(set(str(b) for b in bounds))

    def test_trusted_local_value(self) -> None:
        assert TrustLevel.TRUSTED_LOCAL == "trusted_local"

    def test_static_import_value(self) -> None:
        assert TrustLevel.STATIC_IMPORT == "static_import"

    def test_in_process_execution_mode(self) -> None:
        assert ExecutionMode.IN_PROCESS == "in_process"

    def test_pty_bridge_mode(self) -> None:
        assert ExecutionMode.PTY_BRIDGE == "pty_bridge"


# ---------------------------------------------------------------------------
# B. Static profile import safety
# ---------------------------------------------------------------------------


class TestStaticProfileImportSafety:
    """Static importers parse text; they never execute shell code."""

    def test_parse_profile_skips_eval_line(self) -> None:
        from pysh.compat.profile_importer import parse_profile

        result = parse_profile("eval $(brew shellenv)\n")
        assert result.skipped >= 1
        assert len(result.aliases) == 0

    def test_parse_profile_skips_command_substitution(self) -> None:
        from pysh.compat.profile_importer import parse_profile

        result = parse_profile('export PATH="$(python3 -m site --user-base)/bin:$PATH"\n')
        assert result.skipped >= 1

    def test_parse_profile_imports_alias_without_execution(self) -> None:
        from pysh.compat.profile_importer import parse_profile

        result = parse_profile("alias ll='ls -lah'\n")
        assert result.aliases["ll"] == "ls -lah"
        assert result.skipped == 0

    def test_parse_profile_imports_export_without_execution(self) -> None:
        from pysh.compat.profile_importer import parse_profile

        result = parse_profile("export EDITOR=nano\n")
        assert result.exports["EDITOR"] == "nano"

    def test_classify_line_marks_eval_as_risky(self) -> None:
        from pysh.compat.profile_importer import CompatAction, classify_line

        finding = classify_line("eval $(brew shellenv)", line_number=1)
        assert finding is not None
        assert finding.action is CompatAction.RISKY

    def test_classify_line_marks_source_as_risky(self) -> None:
        from pysh.compat.profile_importer import CompatAction, classify_line

        finding = classify_line("source ~/.zshrc", line_number=1)
        assert finding is not None
        assert finding.action is CompatAction.RISKY

    def test_classify_line_marks_function_as_risky(self) -> None:
        from pysh.compat.profile_importer import CompatAction, classify_line

        finding = classify_line("myfunc() { echo hello; }", line_number=1)
        assert finding is not None
        assert finding.action is CompatAction.RISKY

    def test_parse_profile_does_not_call_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parse_profile must never spawn a subprocess."""
        from pysh.compat import profile_importer

        calls: list[object] = []

        def _mock_run(*args: object, **kwargs: object) -> object:
            calls.append(args)
            raise AssertionError("subprocess.run must not be called by parse_profile")

        def _mock_popen(*args: object, **kwargs: object) -> object:
            calls.append(args)
            raise AssertionError("subprocess.Popen must not be called by parse_profile")

        monkeypatch.setattr(subprocess, "run", _mock_run)
        monkeypatch.setattr(subprocess, "Popen", _mock_popen)

        # Even with risky content, no subprocess is spawned.
        profile_importer.parse_profile(
            "eval $(brew shellenv)\n"
            "alias ll='ls -lah'\n"
            "export EDITOR=vim\n"
            "source ~/.extra.sh\n"
        )
        assert len(calls) == 0

    def test_static_entry_rejects_command_substitution(self) -> None:
        from pysh.compat.profile_importer import ImportKind, parse_static_entry

        entry = parse_static_entry('export PATH="$(python3 -m site --user-base)/bin:$PATH"')
        assert entry.kind is ImportKind.UNSUPPORTED

    def test_analyze_compatibility_classifies_eval_risky(self) -> None:
        from pysh.compat.profile_importer import CompatAction, analyze_compatibility

        report = analyze_compatibility("eval $(something)\nalias g=git\n")
        risky = [f for f in report.findings if f.action is CompatAction.RISKY]
        assert len(risky) >= 1
        assert any(f.kind == "eval" or "eval" in f.kind for f in risky)


# ---------------------------------------------------------------------------
# C. Explicit delegation — zsh_fallback off by default
# ---------------------------------------------------------------------------


class TestExplicitDelegation:
    def test_zsh_fallback_off_by_default(self) -> None:
        from pysh.core.shell import PyShell

        shell = PyShell()
        assert shell.zsh_fallback_enabled is False

    def test_pysh_zsh_fallback_env_not_set_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PYSH_ZSH_FALLBACK", raising=False)
        from pysh.core.shell import PyShell

        shell = PyShell()
        assert not shell.zsh_fallback_enabled

    def test_zsh_bridge_uses_lc_flag(self) -> None:
        """ZshBridge must pass -lc to zsh — never bare exec or shell=True."""
        from pysh.compat.zsh_bridge import ZshBridge

        captured_argv: list[list[str]] = []

        def _fake_run(
            argv: list[str], **_kwargs: object
        ) -> object:
            captured_argv.append(list(argv))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        bridge = ZshBridge.__new__(ZshBridge)
        bridge.executable = "/usr/bin/zsh"

        with patch("subprocess.run", side_effect=_fake_run):
            bridge.execute("echo hello")

        assert len(captured_argv) == 1
        argv = captured_argv[0]
        assert argv[0] == "/usr/bin/zsh"
        assert "-lc" in argv
        assert "echo hello" in argv

    def test_zsh_bridge_missing_returns_127(self) -> None:
        """ZshBridge returns 127 deterministically when zsh is absent."""
        from pysh.compat.zsh_bridge import ZSH_MISSING_STATUS, ZshBridge

        bridge = ZshBridge.__new__(ZshBridge)
        bridge.executable = None
        result = bridge.execute("echo test")
        assert result.returncode == ZSH_MISSING_STATUS

    def test_unknown_command_without_fallback_returns_127(
        self, tmp_path: Path
    ) -> None:
        """Without zsh_fallback, unknown command → 127, not silent delegation."""
        from pysh.core.shell import PyShell

        shell = PyShell()
        assert not shell.zsh_fallback_enabled
        status = shell.execute("__pysh_no_such_command_xyz_abc__")
        assert status == 127


# ---------------------------------------------------------------------------
# D. Sensitive input boundary
# ---------------------------------------------------------------------------


class TestSensitiveInputBoundary:
    """Normal external command path does not use SecureRunner."""

    def test_normal_external_does_not_invoke_secure_runner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_run_external must not call SecureRunner.run for normal commands."""
        from pysh.core.shell import PyShell
        from pysh.security import secure_runner as sr_module

        calls: list[object] = []

        original_run = sr_module.SecureRunner.run

        def _spy_run(self_: object, argv: list[str]) -> int:
            calls.append(argv)
            return original_run(self_, argv)  # type: ignore[arg-type]

        monkeypatch.setattr(sr_module.SecureRunner, "run", _spy_run)
        shell = PyShell()
        shell.execute("echo hello")
        assert len(calls) == 0, "SecureRunner must not be called for normal commands"

    def test_secure_builtin_is_required_for_pty_bridge(self) -> None:
        """The 'secure' builtin name must exist in PyShell.BUILTINS."""
        from pysh.core.shell import PyShell

        assert "secure" in PyShell.BUILTINS

    def test_is_pty_bridge_opt_in_contract(self) -> None:
        """Policy contract: PTY bridge is always opt-in."""
        assert is_pty_bridge_opt_in() is True

    def test_secure_runner_not_called_for_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline execution must not use SecureRunner."""
        from pysh.core.shell import PyShell
        from pysh.security import secure_runner as sr_module

        calls: list[object] = []

        def _spy_run(self_: object, argv: list[str]) -> int:
            calls.append(argv)
            raise AssertionError("SecureRunner must not be called for pipelines")

        monkeypatch.setattr(sr_module.SecureRunner, "run", _spy_run)
        shell = PyShell()
        shell.execute("echo hello | cat")
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# E. Diagnostics non-mutation
# ---------------------------------------------------------------------------


class TestDiagnosticsNonMutation:
    """Diagnostic builtins are advisory and non-mutating."""

    def test_plan_classify_does_not_execute(self) -> None:
        """classify() never spawns a process."""
        from pysh.diagnostics.command_plan import classify

        with patch("subprocess.run") as mock_run:
            with patch("subprocess.Popen") as mock_popen:
                classify("sudo rm -rf /")
                classify("echo hello | wc -l")
                classify("py import os; os.system('rm -rf /')")

        mock_run.assert_not_called()
        mock_popen.assert_not_called()

    def test_plan_classify_returns_plan_not_none(self) -> None:
        from pysh.diagnostics.command_plan import classify

        plan = classify("echo hello")
        assert plan is not None
        assert plan.kind in {"builtin", "external", "pipeline", "chain",
                             "python", "zsh-delegation", "script", "unknown"}

    def test_env_audit_redacts_secret_variables(self) -> None:
        """env_audit redacts variables with sensitive names."""
        from pysh.prompt.system_profile import REDACTED_PLACEHOLDER, env_audit

        stream = io.StringIO()
        env_audit(
            env={
                "MY_API_KEY": "s3cr3t",
                "DATABASE_PASSWORD": "hunter2",
                "GITHUB_TOKEN": "ghp_xxxx",
                "HOME": "/home/user",
                "SHELL": "/usr/bin/pysh",
            },
            stream=stream,
        )
        output = stream.getvalue()
        assert "s3cr3t" not in output
        assert "hunter2" not in output
        assert "ghp_xxxx" not in output
        assert REDACTED_PLACEHOLDER in output

    def test_env_audit_does_not_mutate_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env_audit reads env but must not write to os.environ."""
        import os

        from pysh.prompt.system_profile import env_audit

        before = dict(os.environ)
        env_audit(stream=io.StringIO())
        after = dict(os.environ)
        assert before == after

    def test_apt_check_does_not_call_sudo(self) -> None:
        """apt_check must not invoke sudo."""
        from pysh.prompt.system_profile import apt_check

        captured: list[list[str]] = []

        def _mock_runner(argv: list[str]) -> int:
            captured.append(list(argv))
            return 0

        apt_check(
            apt_resolver=lambda _: "/usr/bin/apt",
            runner=_mock_runner,
        )
        for argv in captured:
            assert "sudo" not in argv, f"sudo must not appear in apt argv: {argv}"

    def test_apt_search_does_not_call_sudo(self) -> None:
        """apt_search must not invoke sudo."""
        from pysh.prompt.system_profile import apt_search

        captured: list[list[str]] = []

        def _mock_runner(argv: list[str]) -> int:
            captured.append(list(argv))
            return 0

        apt_search(
            "python3",
            apt_resolver=lambda _: "/usr/bin/apt",
            runner=_mock_runner,
        )
        for argv in captured:
            assert "sudo" not in argv, f"sudo must not appear in apt argv: {argv}"

    def test_apt_check_uses_list_not_install(self) -> None:
        """apt_check must use 'apt list --upgradable', not 'apt install' or 'apt upgrade'."""
        from pysh.prompt.system_profile import apt_check

        captured: list[list[str]] = []

        def _mock_runner(argv: list[str]) -> int:
            captured.append(list(argv))
            return 0

        apt_check(
            apt_resolver=lambda _: "/usr/bin/apt",
            runner=_mock_runner,
        )
        assert len(captured) == 1
        argv = captured[0]
        assert "list" in argv
        assert "install" not in argv
        assert "upgrade" not in argv


# ---------------------------------------------------------------------------
# F. Python runtime trust
# ---------------------------------------------------------------------------


class TestPythonRuntimeTrust:
    """py builtin executes in-process; is not sandboxed."""

    def test_python_runtime_is_not_sandboxed_predicate(self) -> None:
        assert is_python_runtime_sandboxed() is False

    def test_py_builtin_executes_in_process(self) -> None:
        """py <code> runs in the PySH process, not in a subprocess."""
        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("x = 42")
        assert status == 0
        assert runtime.globals.get("x") == 42

    def test_py_builtin_has_full_os_access(self) -> None:
        """Python runtime has OS access — no sandboxing."""

        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("import os; _cwd = os.getcwd()")
        assert status == 0
        assert "_cwd" in runtime.globals

    def test_py_ordinary_exception_returns_1(self) -> None:
        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("raise ValueError('boom')")
        assert status == 1

    def test_py_keyboard_interrupt_returns_130(self) -> None:
        from pysh.python_layer.runtime import PythonRuntime

        runtime = PythonRuntime()
        status = runtime.execute("raise KeyboardInterrupt()")
        assert status == 130
