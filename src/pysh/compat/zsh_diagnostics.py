# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Conservative diagnostics for unsupported zsh transition syntax."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class ZshDiagnostic:
    """User-facing diagnostic for a clear unsupported zsh construct."""

    message: str
    hint: str


_ARRAY_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\([^)]*\)$")
_ZSH_ARRAY_REF_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\[[^\]]+\]\}")
_ZSH_PARAM_FLAG_RE = re.compile(r"\$\{\([^}]+\)[^}]+\}")
_ZSH_PARAM_MODIFIER_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:[A-Za-z][^}]*\}")
_ZSH_PROMPT_RE = re.compile(r"%[~mdn#?]|\%F\{[^}]+\}|\%K\{[^}]+\}|%[fk]")
_ZSH_GLOB_QUALIFIER_RE = re.compile(r"(?:^|/|[ \t])(?:\*\*?/)?[^ \t'\";|&]*\*[^ \t'\";|&]*\([.N/^@=+-]+\)")
_ZSH_STARTUP_FILENAMES: frozenset[str] = frozenset(
    {
        ".zshenv",
        ".zprofile",
        ".zshrc",
        ".zlogin",
        ".zlogout",
    }
)


def detect_unsupported_zsh_syntax(line: str) -> ZshDiagnostic | None:
    """Return a deterministic diagnostic for clear zsh-only syntax."""
    stripped = line.strip()
    if not stripped:
        return None

    first = _first_word(stripped)
    if first == "compinit":
        return ZshDiagnostic(
            "pysh: unsupported zsh config command: compinit",
            "hint: PySH does not run zsh completion initialization. Use PySH-native completion.",
        )
    if first == "autoload":
        return ZshDiagnostic(
            "pysh: unsupported zsh config command: autoload",
            "hint: PySH does not load zsh autoload functions. Use PySH-native configuration in ~/.pyshrc.",
        )
    if first in {"setopt", "unsetopt"}:
        return ZshDiagnostic(
            f"pysh: unsupported zsh config command: {first}",
            "hint: PySH does not apply zsh shell options. Use PySH-native configuration in ~/.pyshrc.",
        )

    if _contains_zsh_parameter_expansion(stripped):
        return ZshDiagnostic(
            "pysh: unsupported zsh syntax: ${( ... )}",
            "hint: PySH does not evaluate zsh parameter expansion. Use Python mode or explicit Python expressions.",
        )
    if _contains_zsh_array(stripped):
        return ZshDiagnostic(
            "pysh: unsupported zsh syntax: array",
            "hint: PySH does not evaluate zsh arrays. Use Python lists in py mode or explicit files/config.",
        )
    if _contains_zsh_glob_qualifier(stripped):
        return ZshDiagnostic(
            "pysh: unsupported zsh syntax: glob qualifier",
            "hint: PySH supports native glob paths, not zsh glob qualifiers such as *(.) or *(N).",
        )
    if _contains_zsh_prompt_expansion(stripped):
        return ZshDiagnostic(
            "pysh: unsupported zsh syntax: prompt expansion",
            "hint: PySH does not evaluate zsh prompt escapes. Configure the PySH prompt in ~/.pyshrc.",
        )
    return None


def is_zsh_config_path(path_text: str) -> bool:
    """Return True when ``path_text`` names a zsh startup/profile file."""
    return path_text.rstrip("/").split("/")[-1] in _ZSH_STARTUP_FILENAMES


def zsh_config_file_diagnostic(path_text: str) -> ZshDiagnostic:
    """Return the standard diagnostic for rejected zsh startup files."""
    return ZshDiagnostic(
        f"pysh: unsupported zsh configuration file: {path_text}",
        "hint: PySH does not source zsh startup files. Put PySH configuration in ~/.pyshrc or use source_zsh_profile for safe static import.",
    )


def _first_word(text: str) -> str:
    try:
        tokens = shlex.split(text, posix=True, comments=True)
    except ValueError:
        return ""
    return tokens[0] if tokens else ""


def _contains_zsh_parameter_expansion(text: str) -> bool:
    if not _contains_unquoted(text, "${"):
        return False
    return bool(_ZSH_PARAM_FLAG_RE.search(text) or _ZSH_PARAM_MODIFIER_RE.search(text))


def _contains_zsh_array(text: str) -> bool:
    return bool(_ARRAY_ASSIGNMENT_RE.fullmatch(text) or _ZSH_ARRAY_REF_RE.search(text))


def _contains_zsh_glob_qualifier(text: str) -> bool:
    return bool(_ZSH_GLOB_QUALIFIER_RE.search(text))


def _contains_zsh_prompt_expansion(text: str) -> bool:
    first = _first_word(text)
    if first not in {"PROMPT", "RPROMPT", "PS1"} and not text.startswith(
        ("PROMPT=", "RPROMPT=", "PS1=")
    ):
        return False
    return bool(_ZSH_PROMPT_RE.search(text))


def _contains_unquoted(text: str, needle: str) -> bool:
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
            if text.startswith(needle, i):
                return True
            i += 1
            continue
        if char == "\\" and i + 1 < len(text):
            i += 2
            continue
        if char == "'":
            in_single = True
            i += 1
            continue
        if char == '"':
            in_double = True
            i += 1
            continue
        if text.startswith(needle, i):
            return True
        i += 1
    return False
