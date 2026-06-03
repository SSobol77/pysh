# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Static zsh/sh profile import and migration compatibility reporting."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class ImportKind(StrEnum):
    """Kinds emitted by the static profile parser."""

    BLANK = "blank"
    ALIAS = "alias"
    EXPORT = "export"
    ASSIGNMENT = "assignment"
    UNSUPPORTED = "unsupported"


class CompatAction(StrEnum):
    """Migration action assigned to one static compatibility finding."""

    SUPPORTED = "supported"
    DELEGATED = "delegated"
    SKIPPED = "skipped"
    RISKY = "risky"


@dataclass(frozen=True)
class StaticEntry:
    """One safely parsed static profile entry."""

    kind: ImportKind
    name: str = ""
    value: str = ""


@dataclass(frozen=True)
class ProfileImportResult:
    """Static import result for one profile-like file."""

    aliases: dict[str, str]
    exports: dict[str, str]
    variables: dict[str, str]
    skipped: int


@dataclass(frozen=True)
class CompatFinding:
    """One line-level compatibility finding."""

    line_number: int
    kind: str
    action: CompatAction


@dataclass(frozen=True)
class CompatReport:
    """Static migration report for a profile or script file."""

    findings: tuple[CompatFinding, ...] = field(default_factory=tuple)

    @property
    def supported(self) -> int:
        """Return the number of supported static lines."""
        return self._count(CompatAction.SUPPORTED)

    @property
    def delegated(self) -> int:
        """Return the number of lines best handled by interpreter delegation."""
        return self._count(CompatAction.DELEGATED)

    @property
    def skipped(self) -> int:
        """Return the number of unsupported but non-risky lines."""
        return self._count(CompatAction.SKIPPED)

    @property
    def risky(self) -> int:
        """Return the number of risky lines."""
        return self._count(CompatAction.RISKY)

    def _count(self, action: CompatAction) -> int:
        return sum(1 for finding in self.findings if finding.action is action)


def import_profile_file(path: Path) -> ProfileImportResult:
    """Read and statically import supported profile entries from ``path``."""
    text = path.read_text(encoding="utf-8")
    return parse_profile(text)


def parse_profile(text: str) -> ProfileImportResult:
    """Parse safe static aliases, exports and assignments without execution."""
    aliases: dict[str, str] = {}
    exports: dict[str, str] = {}
    variables: dict[str, str] = {}
    skipped = 0

    for raw_line in text.splitlines():
        entry = parse_static_entry(raw_line)
        if entry.kind is ImportKind.BLANK:
            continue
        if entry.kind is ImportKind.UNSUPPORTED:
            skipped += 1
            continue
        if entry.kind is ImportKind.ALIAS:
            aliases[entry.name] = entry.value
        elif entry.kind is ImportKind.EXPORT:
            exports[entry.name] = entry.value
        elif entry.kind is ImportKind.ASSIGNMENT:
            variables[entry.name] = entry.value

    return ProfileImportResult(
        aliases=aliases,
        exports=exports,
        variables=variables,
        skipped=skipped,
    )


def parse_static_entry(raw_line: str) -> StaticEntry:
    """Parse one supported static profile line without evaluating it."""
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        return StaticEntry(ImportKind.BLANK)
    if _contains_command_substitution(stripped):
        return StaticEntry(ImportKind.UNSUPPORTED)

    try:
        tokens = shlex.split(stripped, posix=True, comments=True)
    except ValueError:
        return StaticEntry(ImportKind.UNSUPPORTED)
    if not tokens:
        return StaticEntry(ImportKind.BLANK)

    if tokens[0] == "alias":
        return _parse_alias_tokens(tokens)
    if tokens[0] == "export":
        return _parse_export_tokens(tokens)
    if len(tokens) == 1:
        return _parse_assignment_token(tokens[0])
    return StaticEntry(ImportKind.UNSUPPORTED)


def analyze_compatibility(text: str) -> CompatReport:
    """Classify static migration compatibility for a shell/profile/script file."""
    findings: list[CompatFinding] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        finding = classify_line(raw_line, line_number=line_number)
        if finding is not None:
            findings.append(finding)
    return CompatReport(tuple(findings))


def analyze_compatibility_file(path: Path) -> CompatReport:
    """Read and statically classify ``path`` for migration compatibility."""
    text = path.read_text(encoding="utf-8")
    return analyze_compatibility(text)


def classify_line(raw_line: str, *, line_number: int) -> CompatFinding | None:
    """Classify one non-executed shell/profile line for migration planning."""
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    first_word = _first_shell_word(stripped)
    if first_word == "eval":
        return CompatFinding(line_number, "eval", CompatAction.RISKY)
    if first_word in {"source", "."}:
        return CompatFinding(line_number, "source", CompatAction.RISKY)
    if _looks_like_shell_function(stripped):
        return CompatFinding(line_number, "function", CompatAction.RISKY)
    if _contains_command_substitution(stripped):
        return CompatFinding(line_number, "command_substitution", CompatAction.RISKY)

    entry = parse_static_entry(raw_line)
    if entry.kind is ImportKind.ALIAS:
        return CompatFinding(line_number, "alias", CompatAction.SUPPORTED)
    if entry.kind is ImportKind.EXPORT:
        return CompatFinding(line_number, "export", CompatAction.SUPPORTED)
    if entry.kind is ImportKind.ASSIGNMENT:
        return CompatFinding(line_number, "assignment", CompatAction.SUPPORTED)

    if _looks_like_array(stripped):
        kind = "zsh_plugins" if stripped.startswith("plugins=") else "array"
        return CompatFinding(line_number, kind, CompatAction.SKIPPED)
    if first_word in {"if", "elif", "else", "fi", "case", "esac"}:
        return CompatFinding(line_number, "conditional", CompatAction.DELEGATED)
    if first_word in {"for", "while", "until", "do", "done", "select"}:
        return CompatFinding(line_number, "loop", CompatAction.DELEGATED)
    if _has_unquoted_pipeline(stripped):
        return CompatFinding(line_number, "pipeline", CompatAction.DELEGATED)
    if _has_unquoted_redirect(stripped):
        return CompatFinding(line_number, "redirect", CompatAction.DELEGATED)
    return CompatFinding(line_number, "unsupported", CompatAction.SKIPPED)


def _parse_alias_tokens(tokens: list[str]) -> StaticEntry:
    if len(tokens) != 2:
        return StaticEntry(ImportKind.UNSUPPORTED)
    assignment = tokens[1]
    if "=" not in assignment:
        return StaticEntry(ImportKind.UNSUPPORTED)
    name, value = assignment.split("=", 1)
    if not _NAME_RE.fullmatch(name):
        return StaticEntry(ImportKind.UNSUPPORTED)
    return StaticEntry(ImportKind.ALIAS, name, value)


def _parse_export_tokens(tokens: list[str]) -> StaticEntry:
    if len(tokens) != 2:
        return StaticEntry(ImportKind.UNSUPPORTED)
    parsed = _parse_assignment_token(tokens[1])
    if parsed.kind is not ImportKind.ASSIGNMENT:
        return StaticEntry(ImportKind.UNSUPPORTED)
    return StaticEntry(ImportKind.EXPORT, parsed.name, parsed.value)


def _parse_assignment_token(token: str) -> StaticEntry:
    match = _ASSIGNMENT_RE.fullmatch(token)
    if match is None:
        return StaticEntry(ImportKind.UNSUPPORTED)
    name, value = match.groups()
    if _looks_like_array_value(value):
        return StaticEntry(ImportKind.UNSUPPORTED)
    return StaticEntry(ImportKind.ASSIGNMENT, name, value)


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


def _first_shell_word(text: str) -> str:
    try:
        tokens = shlex.split(text, posix=True, comments=True)
    except ValueError:
        return ""
    return tokens[0] if tokens else ""


def _looks_like_shell_function(text: str) -> bool:
    if text.startswith("function "):
        return True
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{", text))


def _looks_like_array(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=\(", text))


def _looks_like_array_value(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("(") and stripped.endswith(")")


def _has_unquoted_pipeline(text: str) -> bool:
    return _contains_unquoted_any(text, {"|"})


def _has_unquoted_redirect(text: str) -> bool:
    return _contains_unquoted_any(text, {"<", ">"})


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
