# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/parsing/heredoc.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Here-document and here-string parsing helpers.

This module is a parser leaf: it performs quote-aware operator detection,
body collection, and text expansion policy only. It does not execute commands,
perform terminal I/O, or import shell runtime modules.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import StrEnum

from pysh.parsing.errors import ParseError
from pysh.parsing.expansion import expand_command_substitution, expand_variables


class HereDocOperator(StrEnum):
    """Supported stdin inline-data operators."""

    HEREDOC = "<<"
    HEREDOC_STRIP_TABS = "<<-"
    HERE_STRING = "<<<"


class HereDocExpansionMode(StrEnum):
    """Expansion policy for inline stdin content."""

    EXPAND = "expand"
    LITERAL = "literal"


@dataclass(frozen=True)
class HereDocSpec:
    """A heredoc or here-string operator found in a command line."""

    operator: HereDocOperator
    raw_word: str
    delimiter: str
    quoted_delimiter: bool
    expansion_mode: HereDocExpansionMode
    start_index: int
    end_index: int

    @property
    def strips_tabs(self) -> bool:
        return self.operator is HereDocOperator.HEREDOC_STRIP_TABS

    @property
    def needs_body(self) -> bool:
        return self.operator is not HereDocOperator.HERE_STRING


@dataclass(frozen=True)
class HereDocBody:
    """Collected bytes for one stdin inline-data operator."""

    operator: HereDocOperator
    data: str


def pending_heredoc_specs(command_line: str) -> list[HereDocSpec]:
    """Return heredoc specs from *command_line* that require following body lines."""
    return [spec for spec in parse_heredoc_specs(command_line) if spec.needs_body]


def collect_heredoc_bodies(
    text: str,
    local_vars: dict[str, str],
    *,
    special_vars: dict[str, str] | None = None,
) -> tuple[str, list[HereDocBody]]:
    """Collect heredoc bodies from *text* and return ``(command_line, bodies)``.

    The first physical line is the command line. Subsequent physical lines are
    consumed as heredoc bodies for each pending ``<<`` or ``<<-`` operator in
    left-to-right order. Here-strings are converted to a body immediately from
    their word. Missing delimiter words or terminator lines raise ``ParseError``.
    """
    command_line, body_text = _split_command_and_body(text)
    specs = parse_heredoc_specs(command_line)
    if not specs:
        return text, []
    bodies: list[HereDocBody] = []
    body_lines = body_text.split("\n") if body_text else []
    line_index = 0

    for spec in specs:
        if spec.operator is HereDocOperator.HERE_STRING:
            body = apply_heredoc_expansion(spec.raw_word, spec, local_vars, special_vars=special_vars)
            bodies.append(HereDocBody(spec.operator, body + "\n"))
            continue

        collected: list[str] = []
        found = False
        while line_index < len(body_lines):
            line = body_lines[line_index]
            line_index += 1
            if heredoc_line_matches(line, spec):
                found = True
                break
            if spec.strips_tabs:
                line = line.lstrip("\t")
            collected.append(line + "\n")
        if not found:
            raise ParseError(f"missing heredoc terminator: {spec.delimiter}")
        body = "".join(collected)
        body = apply_heredoc_expansion(body, spec, local_vars, special_vars=special_vars)
        bodies.append(HereDocBody(spec.operator, body))

    return _mask_heredoc_words(command_line, specs), bodies


def apply_heredoc_expansion(
    text: str,
    spec: HereDocSpec,
    local_vars: dict[str, str],
    *,
    special_vars: dict[str, str] | None = None,
) -> str:
    """Apply Issue #10 expansion policy to heredoc or here-string content."""
    if spec.expansion_mode is HereDocExpansionMode.LITERAL:
        return _unquote_word(text) if spec.operator is HereDocOperator.HERE_STRING else text
    expanded = expand_command_substitution(text)
    expanded = expand_variables(expanded, local_vars, special_vars=special_vars)
    return _unquote_word(expanded) if spec.operator is HereDocOperator.HERE_STRING else expanded


def parse_heredoc_operator(text: str, index: int) -> HereDocOperator | None:
    """Return the heredoc operator at *index*, or ``None`` when absent."""
    if text.startswith("<<<", index):
        return HereDocOperator.HERE_STRING
    if text.startswith("<<-", index):
        return HereDocOperator.HEREDOC_STRIP_TABS
    if text.startswith("<<", index):
        return HereDocOperator.HEREDOC
    return None


def parse_heredoc_specs(command_line: str) -> list[HereDocSpec]:
    """Return all heredoc and here-string specs in a command line."""
    specs: list[HereDocSpec] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command_line)
    while i < n:
        c = command_line[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n and command_line[i + 1] in ('"', "\\", "$", "`"):
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "'":
            in_single = True
            i += 1
            continue
        if c == '"':
            in_double = True
            i += 1
            continue
        operator = parse_heredoc_operator(command_line, i)
        if operator is None:
            i += 1
            continue
        raw_word, end = _read_word(command_line, i + len(operator.value))
        if not raw_word:
            raise ParseError(f"missing heredoc delimiter after {operator.value}")
        delimiter = _unquote_word(raw_word)
        if not delimiter:
            raise ParseError(f"missing heredoc delimiter after {operator.value}")
        quoted = _word_has_quote(raw_word)
        mode = HereDocExpansionMode.EXPAND
        if operator is not HereDocOperator.HERE_STRING and quoted:
            mode = HereDocExpansionMode.LITERAL
        specs.append(
            HereDocSpec(
                operator=operator,
                raw_word=raw_word,
                delimiter=delimiter,
                quoted_delimiter=quoted,
                expansion_mode=mode,
                start_index=i,
                end_index=end,
            )
        )
        i = end
    return specs


def heredoc_line_matches(line: str, spec: HereDocSpec) -> bool:
    """Return True when *line* terminates *spec*'s body."""
    candidate = line.lstrip("\t") if spec.strips_tabs else line
    return candidate == spec.delimiter


def _split_command_and_body(text: str) -> tuple[str, str]:
    command_line, sep, body = text.partition("\n")
    if not sep:
        return text, ""
    return command_line, body


def _mask_heredoc_words(command_line: str, specs: list[HereDocSpec]) -> str:
    if not specs:
        return command_line
    chunks: list[str] = []
    offset = 0
    for spec in specs:
        operator_end = spec.start_index + len(spec.operator.value)
        chunks.append(command_line[offset:operator_end])
        chunks.append(" PYSH_HEREDOC")
        offset = spec.end_index
    chunks.append(command_line[offset:])
    return "".join(chunks)


def _read_word(text: str, index: int) -> tuple[str, int]:
    n = len(text)
    while index < n and text[index] in " \t":
        index += 1
    start = index
    in_single = False
    in_double = False
    while index < n:
        c = text[index]
        if in_single:
            if c == "'":
                in_single = False
            index += 1
            continue
        if in_double:
            if c == "\\" and index + 1 < n and text[index + 1] in ('"', "\\", "$", "`"):
                index += 2
                continue
            if c == '"':
                in_double = False
            index += 1
            continue
        if c == "\\" and index + 1 < n:
            index += 2
            continue
        if c == "'":
            in_single = True
            index += 1
            continue
        if c == '"':
            in_double = True
            index += 1
            continue
        if c in " \t<>&;|":
            break
        index += 1
    return text[start:index], index


def _unquote_word(word: str) -> str:
    try:
        parts = shlex.split(word, posix=True)
    except ValueError:
        return word
    return "".join(parts) if parts else ""


def _word_has_quote(word: str) -> bool:
    return "'" in word or '"' in word or "\\" in word
