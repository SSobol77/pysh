# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_migration.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the Python-first script migration analyzer."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.core.shell import PyShell
from pysh.migration.script import Severity, analyze_migration, render_migration_report


def _kinds(text: str) -> set[str]:
    return {finding.kind for finding in analyze_migration(text).findings}


def test_migration_detects_bash_shebang() -> None:
    report = analyze_migration("#!/usr/bin/env bash\necho ok\n", source="script.sh")

    assert report.detected_shell == "bash"
    assert report.findings[0].kind == "shebang"
    assert report.findings[0].message == "detected bash shebang"


def test_migration_detects_sh_shebang() -> None:
    report = analyze_migration("#!/bin/sh\n", source="script.sh")

    assert report.detected_shell == "sh"
    assert report.findings[0].message == "detected sh shebang"


def test_migration_detects_exports() -> None:
    assert "export" in _kinds("export EDITOR=nano\n")


def test_migration_detects_variable_assignment() -> None:
    assert "assignment" in _kinds("NAME=value\n")


def test_migration_detects_pipelines() -> None:
    kinds = _kinds("printf '%s\\n' a b | wc -l\n")
    assert "command" in kinds
    assert "pipeline" in kinds


def test_migration_detects_redirections() -> None:
    assert "redirection" in _kinds("echo hi > out.txt\n")


def test_migration_detects_command_substitution() -> None:
    assert "command_substitution" in _kinds("name=$(hostname)\n")
    assert "command_substitution" in _kinds("name=`hostname`\n")


def test_migration_detects_eval_as_unsafe() -> None:
    report = analyze_migration('eval "$(tool init)"\n')

    finding = report.findings[0]
    assert finding.kind == "eval"
    assert finding.severity is Severity.UNSAFE


def test_migration_detects_heredoc() -> None:
    report = analyze_migration("cat <<EOF\nbody\nEOF\n")
    assert {finding.kind for finding in report.findings} == {
        "command",
        "heredoc",
        "redirection",
    }


def test_migration_detects_if_block() -> None:
    assert "if_block" in _kinds("if [ -f file ]; then\n")


def test_migration_detects_for_loop() -> None:
    assert "for_loop" in _kinds("for item in a b; do\n")


def test_migration_output_order_is_deterministic() -> None:
    text = "#!/bin/bash\nexport A=1\necho hi | wc -c > out\n"

    first = render_migration_report(analyze_migration(text, source="script.sh"))
    second = render_migration_report(analyze_migration(text, source="script.sh"))

    assert first == second
    assert first.splitlines()[:10] == [
        "PySH Migration Report",
        "Source: script.sh",
        "Detected shell: bash",
        "",
        "Summary:",
        "  info: 3",
        "  warning: 2",
        "  unsafe: 0",
        "  unsupported: 0",
        "",
    ]


def test_migrate_builtin_reports_missing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.sh"

    assert PyShell().execute(f"migrate {missing}") == 1
    captured = capsys.readouterr()
    assert f"migrate: {missing}: file not found" in captured.err


def test_migration_empty_input_has_zero_counts() -> None:
    report = analyze_migration("", source="<inline>")
    output = render_migration_report(report)

    assert report.detected_shell == "unknown"
    assert report.findings == ()
    assert "  info: 0\n  warning: 0\n  unsafe: 0\n  unsupported: 0" in output
    assert "Findings:\n  none" in output


def test_migrate_builtin_reads_file_without_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "executed"
    script = tmp_path / "script.sh"
    script.write_text(f"#!/bin/bash\necho $(touch {marker})\n", encoding="utf-8")

    assert PyShell().execute(f"migrate {script}") == 0

    captured = capsys.readouterr()
    assert "PySH Migration Report" in captured.out
    assert "command substitution should become explicit subprocess" in captured.out
    assert not marker.exists()


def test_migrate_inline_text_bypasses_command_substitution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "executed"

    assert PyShell().execute(f"migrate --text 'echo $(touch {marker})'") == 0

    captured = capsys.readouterr()
    assert "Source: <inline>" in captured.out
    assert "command substitution should become explicit subprocess" in captured.out
    assert not marker.exists()


def test_migrate_file_argument_bypasses_command_substitution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "executed"

    assert PyShell().execute(f"migrate $(touch {marker})") == 1

    captured = capsys.readouterr()
    assert "file not found" in captured.err
    assert not marker.exists()


def test_migrate_quoted_argument_bypasses_command_substitution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "executed"

    assert PyShell().execute(f'migrate "$(touch {marker})"') == 1

    captured = capsys.readouterr()
    assert "file not found" in captured.err
    assert not marker.exists()
