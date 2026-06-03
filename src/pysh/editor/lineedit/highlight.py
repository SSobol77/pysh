# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure shell-line syntax highlighting spans and ANSI rendering."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Highlight roles assigned to spans."""

    COMMAND_VALID = "command_valid"
    COMMAND_INVALID = "command_invalid"
    STRING = "string"
    OPERATOR = "operator"
    OPTION = "option"
    VARIABLE = "variable"
    PATH = "path"
    DEFAULT = "default"


@dataclass(frozen=True)
class Span:
    """One highlighted range over the original raw line."""

    start: int
    end: int
    role: Role


@dataclass(frozen=True)
class ColorScheme:
    """ANSI SGR sequences used by the raw line editor."""

    command_valid: str = "\033[32m"
    command_invalid: str = "\033[31m"
    string: str = "\033[33m"
    operator: str = "\033[35m"
    option: str = "\033[36m"
    variable: str = "\033[34m"
    path: str = ""
    default: str = ""
    suggestion: str = "\033[2m"
    reset: str = "\033[0m"


DEFAULT_SCHEME = ColorScheme()

_VARIABLE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_OPERATORS = ("&&", "||", ">>", "2>", "|", ";", ">", "<", "&")
_COMMAND_SEPARATORS = {"|", "||", "&&", ";"}


class LineHighlighter:
    """Tokenize and render a shell command line without terminal I/O."""

    def __init__(self, builtins: set[str] | frozenset[str]) -> None:
        self._builtins = frozenset(builtins)
        self._which_cache: dict[str, bool] = {}

    def tokenize(self, line: str) -> list[Span]:
        """Return role spans covering the raw input line."""
        tokens = self._scan_tokens(line)
        role_ranges: list[Span] = []
        expect_command = True
        for start, end, text, role in tokens:
            assigned = role
            if role is Role.DEFAULT and text.strip():
                if expect_command:
                    assigned = (
                        Role.COMMAND_VALID if self._is_command_valid(text) else Role.COMMAND_INVALID
                    )
                    expect_command = False
                elif text.startswith("-"):
                    assigned = Role.OPTION
                elif "/" in text or text.startswith(("~", ".")):
                    assigned = Role.PATH
            if assigned is Role.OPERATOR and text in _COMMAND_SEPARATORS:
                expect_command = True
            elif assigned not in {Role.DEFAULT, Role.OPERATOR} and text.strip():
                expect_command = False
            role_ranges.append(Span(start, end, assigned))
        return self._cover_defaults(line, role_ranges)

    def render(self, line: str, scheme: ColorScheme = DEFAULT_SCHEME, *, enabled: bool) -> str:
        """Render ``line`` with ANSI SGR sequences when ``enabled``."""
        if not enabled:
            return line
        out: list[str] = []
        for span in self.tokenize(line):
            text = line[span.start : span.end]
            code = getattr(scheme, span.role.value)
            if code:
                out.append(f"{code}{text}{scheme.reset}")
            else:
                out.append(text)
        return "".join(out)

    def _is_command_valid(self, token: str) -> bool:
        if token in self._builtins:
            return True
        cached = self._which_cache.get(token)
        if cached is not None:
            return cached
        found = shutil.which(token) is not None
        self._which_cache[token] = found
        return found

    def _scan_tokens(self, line: str) -> list[tuple[int, int, str, Role]]:
        tokens: list[tuple[int, int, str, Role]] = []
        i = 0
        n = len(line)
        while i < n:
            c = line[i]
            if c.isspace():
                i += 1
                continue
            if c in {"'", '"'}:
                end = self._scan_string(line, i)
                tokens.append((i, end, line[i:end], Role.STRING))
                i = end
                continue
            var = _VARIABLE_RE.match(line, i)
            if var is not None:
                tokens.append((i, var.end(), var.group(0), Role.VARIABLE))
                i = var.end()
                continue
            if c == "$":
                tokens.append((i, i + 1, c, Role.VARIABLE))
                i += 1
                continue
            op = self._match_operator(line, i)
            if op is not None:
                end = i + len(op)
                tokens.append((i, end, op, Role.OPERATOR))
                i = end
                continue
            start = i
            while i < n:
                if line[i].isspace() or line[i] in {"'", '"', "$"} or self._match_operator(line, i):
                    break
                i += 1
            tokens.append((start, i, line[start:i], Role.DEFAULT))
        return tokens

    @staticmethod
    def _scan_string(line: str, start: int) -> int:
        quote = line[start]
        i = start + 1
        while i < len(line):
            if quote == '"' and line[i] == "\\" and i + 1 < len(line):
                i += 2
                continue
            if line[i] == quote:
                return i + 1
            i += 1
        return len(line)

    @staticmethod
    def _match_operator(line: str, index: int) -> str | None:
        for op in _OPERATORS:
            if line.startswith(op, index):
                return op
        return None

    @staticmethod
    def _cover_defaults(line: str, spans: list[Span]) -> list[Span]:
        if not line:
            return []
        out: list[Span] = []
        pos = 0
        for span in sorted(spans, key=lambda item: item.start):
            if pos < span.start:
                out.append(Span(pos, span.start, Role.DEFAULT))
            out.append(span)
            pos = span.end
        if pos < len(line):
            out.append(Span(pos, len(line), Role.DEFAULT))
        return out
