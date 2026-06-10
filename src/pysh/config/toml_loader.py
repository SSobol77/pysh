# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/toml_loader.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Non-executing TOML loader for declarative PySH configuration."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pysh.config.diagnostics import ConfigDiagnostic, error

MAX_TOML_BYTES = 256 * 1024


@dataclass(frozen=True)
class LoadedToml:
    """Result of reading one TOML file."""

    path: Path
    data: dict[str, Any]
    diagnostics: tuple[ConfigDiagnostic, ...] = ()
    loaded: bool = False


def load_toml_file(path: Path, *, max_bytes: int = MAX_TOML_BYTES) -> LoadedToml:
    """Parse *path* as TOML data only.

    Missing files are not diagnostics. Oversized, unreadable, or malformed files
    return diagnostics and empty data so shell startup can continue safely.
    """
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return LoadedToml(path, {}, (), False)
    except OSError as exc:
        return LoadedToml(path, {}, (error(path, None, None, None, f"cannot stat file: {exc}"),), False)
    if not path.is_file():
        return LoadedToml(path, {}, (error(path, None, None, None, "not a regular file"),), False)
    if stat_result.st_size > max_bytes:
        return LoadedToml(
            path,
            {},
            (error(path, None, None, stat_result.st_size, f"TOML file exceeds {max_bytes} bytes"),),
            False,
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return LoadedToml(path, {}, (error(path, None, None, None, f"cannot read file: {exc}"),), False)
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        return LoadedToml(path, {}, (error(path, None, None, None, f"invalid UTF-8: {exc}"),), False)
    except tomllib.TOMLDecodeError as exc:
        return LoadedToml(path, {}, (error(path, None, None, None, f"invalid TOML: {exc}"),), False)
    return LoadedToml(path, data, (), True)
