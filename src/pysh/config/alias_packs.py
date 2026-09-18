# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/alias_packs.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Built-in declarative alias packs for PySH."""
from __future__ import annotations

from types import MappingProxyType

BUILTIN_ALIAS_PACKS: MappingProxyType[str, dict[str, str]] = MappingProxyType(
    {
        "git": {
            "gs": "git status --short",
            "gd": "git diff",
            "gl": "git log --oneline --decorate --graph -20",
            "ga": "git add",
            "gc": "git commit",
            "gp": "git push",
            "gb": "git branch",
            "gco": "git checkout",
        },
        "python": {
            "py": "python",
            "pyv": "python --version",
            "pip": "python -m pip",
            "pytest": "uv run pytest",
            "venv": "python -m venv .venv",
        },
        "project": {
            "lint": "uv run ruff check src tests",
            "test": "uv run pytest -q",
            "fmt": "uv run ruff format src tests",
        },
        "files": {
            "ll": "ls -la",
            "la": "ls -A",
            "lt": "tree",
            "md": "mkdir -p",
        },
    }
)


def alias_pack_names() -> list[str]:
    """Return known alias-pack names."""
    return sorted(BUILTIN_ALIAS_PACKS)


def alias_pack(name: str) -> dict[str, str]:
    """Return a copy of a built-in alias pack."""
    return dict(BUILTIN_ALIAS_PACKS[name])
