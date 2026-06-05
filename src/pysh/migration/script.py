# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Static shell-script migration analysis for Python-first PySH workflows.

The analyzer is intentionally non-executing. It does not source files, expand
variables, execute command substitution, or invoke shell interpreters.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    """Severity assigned to one migration finding."""

    INFO = "info"
    WARNING = "warning"
    UNSAFE = "unsafe"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MigrationFinding:
    """One deterministic line-level migration finding."""

    severity: Severity
    line_number: int
    kind: str
    message: str


@dataclass(frozen=True)
class MigrationReport:
    """Static migration report for shell-script-like content."""

    source: str
    detected_shell: str
    findings: tuple[MigrationFinding, ...] = field(default_factory=tuple)

    def count(self, severity: Severity) -> int:
        """Return the number of findings with ``severity``."""
        return sum(1 for finding in self.findings if finding.severity is severity)

    @property
    def unsupported_findings(self) -> tuple[MigrationFinding, ...]:
        """Return unsupported findings in deterministic report order."""
        return tuple(
            finding for finding in self.findings if finding.severity is Severity.UNSUPPORTED
        )


_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_SHEBANGS: dict[str, str] = {
    "#!/bin/sh": "sh",
    "#!/usr/bin/env sh": "sh",
    "#!/bin/bash": "bash",
    "#!/usr/bin/env bash": "bash",
}
_COMPLEX_EXPANSION_RE = re.compile(r"\$\{[^}]*([#%/!:?+]|:-|:=|:\+|:\?)[^}]*\}")
_FUNCTION_RE = re.compile(r"^(function\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{")
_CASE_RE = re.compile(r"^(case|esac)\b")
_WHILE_RE = re.compile(r"^(while|until|select)\b")


def analyze_migration(text: str, *, source: str = "<inline>") -> MigrationReport:
    """Analyze shell-script-like ``text`` without executing it."""
    lines = text.splitlines()
    findings: list[MigrationFinding] = []
    heredoc_until = ""
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if heredoc_until:
            if stripped == heredoc_until:
                heredoc_until = ""
            continue
        findings.extend(_classify_line(raw_line, line_number=line_number))
        heredoc_until = _heredoc_delimiter(stripped)
    return MigrationReport(
        source=source,
        detected_shell=_detect_shell(lines),
        findings=tuple(findings),
    )


def analyze_migration_file(path: Path) -> MigrationReport:
    """Read ``path`` as UTF-8 text and return a static migration report."""
    text = path.read_text(encoding="utf-8")
    return analyze_migration(text, source=str(path))


def render_migration_report(report: MigrationReport) -> str:
    """Render ``report`` in deterministic human-readable form."""
    lines = [
        "PySH Migration Report",
        f"Source: {report.source}",
        f"Detected shell: {report.detected_shell}",
        "",
        "Summary:",
    ]
    for severity in Severity:
        lines.append(f"  {severity.value}: {report.count(severity)}")

    lines.extend(["", "Findings:"])
    if report.findings:
        for finding in report.findings:
            lines.append(
                f"  [{finding.severity.value}] line {finding.line_number}: {finding.message}"
            )
    else:
        lines.append("  none")

    lines.extend(["", "Suggested migration notes:"])
    notes = _migration_notes(report)
    if notes:
        for note in notes:
            lines.append(f"  - {note}")
    else:
        lines.append("  - No migration findings were detected.")

    lines.extend(["", "Unsupported constructs:"])
    unsupported = report.unsupported_findings
    if unsupported:
        for finding in unsupported:
            lines.append(f"  - line {finding.line_number}: {finding.message}")
    else:
        lines.append("  none")
    return "\n".join(lines)


def _detect_shell(lines: list[str]) -> str:
    if not lines:
        return "unknown"
    return _SHEBANGS.get(lines[0].strip(), "unknown")


def _classify_line(raw_line: str, *, line_number: int) -> list[MigrationFinding]:
    stripped = raw_line.strip()
    if not stripped:
        return []
    if line_number == 1 and stripped in _SHEBANGS:
        shell = _SHEBANGS[stripped]
        return [
            MigrationFinding(
                Severity.INFO,
                line_number,
                "shebang",
                f"detected {shell} shebang",
            )
        ]
    if stripped.startswith("#"):
        return []

    findings: list[MigrationFinding] = []
    first_word = _first_shell_word(stripped)

    if first_word == "eval":
        findings.append(
            MigrationFinding(
                Severity.UNSAFE,
                line_number,
                "eval",
                "eval is unsafe and must be rewritten manually",
            )
        )
    elif first_word == "exec":
        findings.append(
            MigrationFinding(
                Severity.UNSAFE,
                line_number,
                "exec",
                "exec replaces shell process state and must be rewritten manually",
            )
        )

    if _contains_command_substitution(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "command_substitution",
                "command substitution should become explicit subprocess or Python API logic",
            )
        )

    if _has_heredoc(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "heredoc",
                "heredoc should be migrated to triple-quoted strings or template files",
            )
        )

    if _starts_if_block(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "if_block",
                "simple if/then/else/fi block should be migrated to Python control flow",
            )
        )
    elif _starts_for_loop(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "for_loop",
                "simple for loop should be migrated to Python iteration",
            )
        )

    if first_word == "export":
        findings.append(
            MigrationFinding(
                Severity.INFO,
                line_number,
                "export",
                "exported variable should become an os.environ assignment",
            )
        )
    elif _is_assignment_line(stripped):
        findings.append(
            MigrationFinding(
                Severity.INFO,
                line_number,
                "assignment",
                "shell variable assignment should become a Python variable or environment mapping",
            )
        )

    if _has_pipeline(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "pipeline",
                "pipeline should be migrated to Python subprocess composition",
            )
        )

    if _has_redirection(stripped):
        findings.append(
            MigrationFinding(
                Severity.WARNING,
                line_number,
                "redirection",
                "redirection should be migrated to pathlib/open() or subprocess file handles",
            )
        )

    if _is_unsupported(stripped):
        findings.append(
            MigrationFinding(
                Severity.UNSUPPORTED,
                line_number,
                "unsupported",
                "complex shell expansion is not automatically migrated",
            )
        )

    if _is_command_invocation(stripped, first_word):
        findings.append(
            MigrationFinding(
                Severity.INFO,
                line_number,
                "command",
                "command invocation should become subprocess.run([...], check=True)",
            )
        )
    return findings


def _migration_notes(report: MigrationReport) -> list[str]:
    kinds = {finding.kind for finding in report.findings}
    notes: list[str] = []
    if "assignment" in kinds:
        notes.append("Replace shell variables with Python variables or typed configuration objects.")
    if "export" in kinds:
        notes.append("Replace exported environment variables with os.environ assignments.")
    if "command" in kinds:
        notes.append("Replace simple command calls with subprocess.run([...], check=True).")
    if "pipeline" in kinds:
        notes.append(
            "Replace pipelines with explicit subprocess.Popen chains or Python-native file processing."
        )
    if "redirection" in kinds:
        notes.append("Replace redirections with pathlib/open() or subprocess stdin/stdout handles.")
    if "command_substitution" in kinds:
        notes.append(
            "Replace command substitution with subprocess.run(..., capture_output=True, text=True)."
        )
    if "if_block" in kinds:
        notes.append("Replace shell conditionals with Python if/elif/else blocks.")
    if "for_loop" in kinds:
        notes.append("Replace shell for loops with Python iteration over lists, pathlib paths, or ranges.")
    if "heredoc" in kinds:
        notes.append("Replace heredocs with triple-quoted Python strings or pathlib-managed template files.")
    if "eval" in kinds or "exec" in kinds:
        notes.append("Rewrite eval/exec-style dynamic behavior manually with explicit validation boundaries.")
    if "unsupported" in kinds:
        notes.append("Review unsupported constructs manually; PySH does not perform automatic conversion.")
    return notes


def _first_shell_word(text: str) -> str:
    try:
        tokens = shlex.split(text, posix=True, comments=True)
    except ValueError:
        return ""
    return tokens[0] if tokens else ""


def _is_assignment_line(text: str) -> bool:
    try:
        tokens = shlex.split(text, posix=True, comments=True)
    except ValueError:
        return False
    return len(tokens) == 1 and bool(_ASSIGNMENT_RE.fullmatch(tokens[0]))


def _contains_command_substitution(text: str) -> bool:
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        char = text[i]
        if in_single:
            if char == "'":
                in_single = False
            i += 1
            continue
        if char == "\\" and i + 1 < len(text):
            i += 2
            continue
        if char == "'" and not in_double:
            in_single = True
            i += 1
            continue
        if char == '"':
            in_double = not in_double
            i += 1
            continue
        if char == "`":
            return True
        if char == "$" and i + 1 < len(text) and text[i + 1] == "(":
            return True
        i += 1
    return False


def _has_pipeline(text: str) -> bool:
    return _contains_unquoted_any(text, {"|"})


def _has_redirection(text: str) -> bool:
    return _contains_unquoted_any(text, {"<", ">"})


def _has_heredoc(text: str) -> bool:
    return bool(_heredoc_delimiter(text))


def _heredoc_delimiter(text: str) -> str:
    in_single = False
    in_double = False
    i = 0
    while i < len(text) - 1:
        char = text[i]
        if in_single:
            if char == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if char == "\\" and i + 1 < len(text):
                i += 2
                continue
            if char == '"':
                in_double = False
            i += 1
            continue
        if char == "\\" and i + 1 < len(text):
            i += 2
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif text.startswith("<<<", i):
            i += 3
            continue
        elif text.startswith("<<", i):
            return _parse_heredoc_delimiter(text[i + 2 :])
        i += 1
    return ""


def _parse_heredoc_delimiter(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("-"):
        stripped = stripped[1:].lstrip()
    if not stripped:
        return ""
    try:
        tokens = shlex.split(stripped, posix=True, comments=True)
    except ValueError:
        return ""
    return tokens[0] if tokens else ""


def _contains_unquoted_any(text: str, targets: set[str]) -> bool:
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        char = text[i]
        if in_single:
            if char == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if char == "\\" and i + 1 < len(text):
                i += 2
                continue
            if char == '"':
                in_double = False
            i += 1
            continue
        if char == "\\" and i + 1 < len(text):
            i += 2
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char in targets:
            if char == "|" and i + 1 < len(text) and text[i + 1] == "|":
                i += 2
                continue
            return True
        i += 1
    return False


def _starts_if_block(text: str) -> bool:
    return _first_shell_word(text) in {"if", "then", "elif", "else", "fi"}


def _starts_for_loop(text: str) -> bool:
    return _first_shell_word(text) in {"for", "do", "done"}


def _is_command_invocation(text: str, first_word: str) -> bool:
    if not first_word:
        return False
    if _is_assignment_line(text) or first_word in {
        "export",
        "eval",
        "exec",
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "for",
        "do",
        "done",
        "case",
        "esac",
        "while",
        "until",
        "select",
    }:
        return False
    return not bool(_FUNCTION_RE.match(text))


def _is_unsupported(text: str) -> bool:
    return bool(
        _COMPLEX_EXPANSION_RE.search(text)
        or _FUNCTION_RE.match(text)
        or _CASE_RE.match(text)
        or _WHILE_RE.match(text)
    )
