# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Static import support for simple zsh-compatible alias files."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

_ALIAS_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ZshAliasDiagnostic:
    """A deterministic parser diagnostic for one skipped alias line."""

    line_number: int
    message: str


@dataclass(frozen=True)
class ZshAliasImport:
    """Result of parsing one zsh-compatible alias file."""

    aliases: dict[str, str]
    skipped: int
    diagnostics: tuple[ZshAliasDiagnostic, ...] = field(default_factory=tuple)

    @property
    def imported(self) -> int:
        """Return the number of supported aliases parsed from the file."""
        return len(self.aliases)


def parse_zsh_aliases(text: str) -> ZshAliasImport:
    """Parse simple ``alias name=value`` definitions without executing code."""
    aliases: dict[str, str] = {}
    skipped = 0
    diagnostics: list[ZshAliasDiagnostic] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        parsed = _parse_alias_line(raw_line)
        if parsed.kind == "blank":
            continue
        if parsed.kind == "unsupported":
            skipped += 1
            continue
        if parsed.kind == "malformed":
            skipped += 1
            diagnostics.append(ZshAliasDiagnostic(line_number, parsed.message))
            continue
        assert parsed.name is not None
        assert parsed.value is not None
        aliases[parsed.name] = parsed.value
    return ZshAliasImport(
        aliases=aliases,
        skipped=skipped,
        diagnostics=tuple(diagnostics),
    )


@dataclass(frozen=True)
class _ParsedAliasLine:
    kind: str
    name: str | None = None
    value: str | None = None
    message: str = ""


def _parse_alias_line(raw_line: str) -> _ParsedAliasLine:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        return _ParsedAliasLine("blank")
    try:
        tokens = shlex.split(stripped, posix=True, comments=True)
    except ValueError as exc:
        if stripped.startswith("alias"):
            return _ParsedAliasLine("malformed", message=str(exc))
        return _ParsedAliasLine("unsupported")
    if not tokens:
        return _ParsedAliasLine("blank")
    if tokens[0] != "alias":
        return _ParsedAliasLine("unsupported")
    if len(tokens) != 2:
        if len(tokens) > 1 and tokens[1].startswith("-"):
            return _ParsedAliasLine("unsupported")
        return _ParsedAliasLine("malformed", message="expected exactly one alias assignment")
    assignment = tokens[1]
    if "=" not in assignment:
        return _ParsedAliasLine("malformed", message="expected alias NAME=VALUE")
    name, value = assignment.split("=", 1)
    if not _ALIAS_NAME_RE.fullmatch(name):
        return _ParsedAliasLine("malformed", message=f"invalid alias name: {name}")
    return _ParsedAliasLine("alias", name=name, value=value)
