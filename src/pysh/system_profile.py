# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/system_profile.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Debian/system diagnostic helpers used by PySH builtins.

This module deliberately avoids any privileged or mutating operation: it
never calls ``sudo``, never modifies system state, and limits itself to the
Python standard library. The helpers are designed to be safe to run on a
fresh Debian system and to fail deterministically when the underlying tool
(such as ``apt``) is not available.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO

REDACTED_TOKENS: tuple[str, ...] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
    "AUTH",
)

SAFE_ENV_KEYS: tuple[str, ...] = (
    "SHELL",
    "TERM",
    "LANG",
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "VIRTUAL_ENV",
    "PYTHONPATH",
)

REDACTED_PLACEHOLDER = "<redacted>"


@dataclass(frozen=True)
class PathEntryStatus:
    """Status report for a single ``PATH`` entry."""

    entry: str
    status: str  # "ok", "missing", "not_dir", "duplicate"


def _writer(stream: IO[str] | None) -> IO[str]:
    return stream if stream is not None else sys.stdout


def sys_info(stream: IO[str] | None = None) -> int:
    """Print a concise system information report.

    Output is intentionally non-secret: it never includes environment values
    other than safe identifiers (user, home, shell) and the length of the
    ``PATH`` list rather than its content.
    """
    out = _writer(stream)
    path_value = os.environ.get("PATH", "")
    path_entries = [p for p in path_value.split(os.pathsep) if p]
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    home = os.environ.get("HOME") or str(Path.home())
    shell = os.environ.get("SHELL", "")
    info = [
        f"platform={platform.platform()}",
        f"python={platform.python_version()}",
        f"executable={sys.executable}",
        f"cwd={os.getcwd()}",
        f"user={user}",
        f"home={home}",
        f"shell={shell}",
        f"path_entries={len(path_entries)}",
    ]
    for line in info:
        print(line, file=out)
    return 0


def _redact_key(key: str) -> bool:
    upper = key.upper()
    return any(token in upper for token in REDACTED_TOKENS)


def env_audit(
    env: Mapping[str, str] | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Print a redacted environment audit summary.

    Variables whose name contains a sensitive token (KEY, TOKEN, SECRET,
    PASSWORD, PASS, CREDENTIAL, AUTH) are replaced with ``<redacted>``.
    Only a curated whitelist of safe variables is printed by value.
    """
    source = dict(env) if env is not None else dict(os.environ)
    out = _writer(stream)
    print(f"total={len(source)}", file=out)
    for key in SAFE_ENV_KEYS:
        if key not in source:
            print(f"{key}=<unset>", file=out)
            continue
        if _redact_key(key):
            print(f"{key}={REDACTED_PLACEHOLDER}", file=out)
        else:
            print(f"{key}={source[key]}", file=out)
    redacted = sorted(k for k in source if _redact_key(k))
    for key in redacted:
        print(f"{key}={REDACTED_PLACEHOLDER}", file=out)
    return 0


def _classify_path_entries(entries: Iterable[str]) -> list[PathEntryStatus]:
    seen: set[str] = set()
    results: list[PathEntryStatus] = []
    for entry in entries:
        if not entry:
            continue
        if entry in seen:
            results.append(PathEntryStatus(entry, "duplicate"))
            continue
        seen.add(entry)
        path = Path(entry)
        if not path.exists():
            results.append(PathEntryStatus(entry, "missing"))
        elif not path.is_dir():
            results.append(PathEntryStatus(entry, "not_dir"))
        else:
            results.append(PathEntryStatus(entry, "ok"))
    return results


def path_audit(
    env: Mapping[str, str] | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Print per-entry ``PATH`` status. Return 0 only when all entries are ok."""
    source = env if env is not None else os.environ
    out = _writer(stream)
    path_value = source.get("PATH", "")
    entries = path_value.split(os.pathsep)
    statuses = _classify_path_entries(entries)
    if not statuses:
        print("path: <empty>", file=out)
        return 1
    bad = 0
    for status in statuses:
        print(f"{status.status}\t{status.entry}", file=out)
        if status.status != "ok":
            bad += 1
    return 0 if bad == 0 else 1


def which_all(
    command: str,
    env: Mapping[str, str] | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Print every executable match for ``command`` along ``PATH``."""
    if not command:
        print("which_all: command argument required", file=sys.stderr)
        return 2
    source = env if env is not None else os.environ
    path_value = source.get("PATH", "")
    out = _writer(stream)
    seen: set[str] = set()
    found = 0
    for raw in path_value.split(os.pathsep):
        if not raw or raw in seen:
            continue
        seen.add(raw)
        candidate = Path(raw) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            print(str(candidate), file=out)
            found += 1
    return 0 if found > 0 else 1


def _resolve_apt(resolver: object | None) -> str | None:
    if resolver is None:
        return shutil.which("apt")
    if callable(resolver):
        return resolver("apt")  # type: ignore[call-arg]
    return None


def apt_check(
    *,
    apt_resolver: object | None = None,
    runner: object | None = None,
) -> int:
    """Report Debian package upgrade availability without modifying anything.

    ``apt_resolver`` and ``runner`` are dependency-injection hooks used by
    tests; production callers should leave them ``None``.
    """
    apt_path = _resolve_apt(apt_resolver)
    if apt_path is None:
        print("pysh: apt_check: apt not found", file=sys.stderr)
        return 127
    argv = [apt_path, "list", "--upgradable"]
    return _run_apt(argv, runner=runner)


def apt_search(
    query: str,
    *,
    apt_resolver: object | None = None,
    runner: object | None = None,
) -> int:
    """Run ``apt search <query>`` safely without ``shell=True``."""
    if not query:
        print("pysh: apt_search: query argument required", file=sys.stderr)
        return 2
    apt_path = _resolve_apt(apt_resolver)
    if apt_path is None:
        print("pysh: apt_search: apt not found", file=sys.stderr)
        return 127
    argv = [apt_path, "search", query]
    return _run_apt(argv, runner=runner)


def _run_apt(argv: list[str], *, runner: object | None) -> int:
    if runner is not None and callable(runner):
        return int(runner(argv))  # type: ignore[call-arg]
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell
            argv,
            check=False,
        )
    except FileNotFoundError:
        print(f"pysh: {argv[0]}: command not found", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"pysh: {argv[0]}: {exc}", file=sys.stderr)
        return 1
    return completed.returncode
