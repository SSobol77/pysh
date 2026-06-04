# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Canonical PySH builtin command names.

This module is intentionally data-only.  It is consumed by the shell runtime,
completion engine, syntax highlighter, and tests without importing the heavy
runtime implementation.
"""
from __future__ import annotations

BUILTIN_NAMES: frozenset[str] = frozenset(
    {
        ".",
        "alias",
        "apt_check",
        "apt_search",
        "bg",
        "cd",
        "command",
        "compat_check",
        "dirs",
        "env_audit",
        "exit",
        "export",
        "fg",
        "jobs",
        "mc",
        "path_audit",
        "paste_cancel",
        "paste_run",
        "paste_show",
        "plan",
        "popd",
        "pushd",
        "pwd",
        "py",
        "quit",
        "run_script",
        "secure",
        "source",
        "source_sh_aliases",
        "source_zsh",
        "source_zsh_profile",
        "svc",
        "sys_info",
        "unalias",
        "which_all",
        "zsh",
        "zsh_fallback",
    }
)

BUILTIN_NAME_LIST: tuple[str, ...] = tuple(sorted(BUILTIN_NAMES))
