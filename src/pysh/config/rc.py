# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/rc.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Loader and mini-interpreter for ``~/.pyshrc`` and plugin files.

The rc file is a list of shell commands, one per line. Blank lines and lines
whose first non-whitespace character is ``#`` are skipped. Each remaining line
is executed through the normal shell execution path, so all features
(``alias``, ``export``, ``source``, pipelines, etc.) are available.

In addition to ordinary commands, this loader recognises a small set of
control-flow constructs that make rc files more useful:

    if [ condition ]; then
        ...
    else
        ...
    fi

    for var in item1 item2; do
        ...
    done

    while [ condition ]; do
        ...
    done

The canonical else keyword is ``else``. ``else:`` is accepted as a
compatibility alias.

Conditions are evaluated in pure Python — they never spawn an external
``test`` binary. Supported test operators:

    [ -f path ]       file exists and is a regular file
    [ -d path ]       file exists and is a directory
    [ -e path ]       file exists
    [ -z value ]      value is empty
    [ -n value ]      value is non-empty
    [ "$A" = "$B" ]   string equality
    [ "$A" == "$B" ]  string equality
    [ "$A" != "$B" ]  string inequality
    [ ! -f path ]     negation of any of the above

``while`` loops are bounded by ``WHILE_ITER_LIMIT`` to keep a broken
condition from hanging the shell.

The loader never raises on a per-line error; failures are reported on stderr
and execution continues.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

RC_PATH = Path("~/.pyshrc").expanduser()

WHILE_ITER_LIMIT = 10_000


def iter_rc_lines(lines: Iterable[str]) -> list[str]:
    """Return executable lines from ``lines`` (comments and blanks dropped).

    Multi-line ``py { ... }`` blocks are coalesced into a single logical
    line (joined by ``\\n``) so that the mini-interpreter passes the whole
    block straight to the executor.
    """
    from pysh.python_layer.runtime import is_block_opener, iter_logical_lines

    cleaned: list[str] = []
    raw_text = list(lines)
    try:
        logical = list(iter_logical_lines(raw_text))
    except ValueError as exc:
        print(f"pysh: rc: {exc}", file=sys.stderr)
        logical = []
    for raw in logical:
        if "\n" in raw and is_block_opener(raw.split("\n", 1)[0]):
            cleaned.append(raw)
            continue
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned.append(line)
    return cleaned


def read_rc_file(path: Path) -> list[str]:
    """Read and pre-filter an rc file. Missing files yield an empty list."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        print(f"pysh: cannot read {path}: {exc}", file=sys.stderr)
        return []
    return iter_rc_lines(text.splitlines())


# ---------------------------------------------------------------- conditions
_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_for_test(value: str, env: dict[str, str]) -> str:
    """Expand ``$VAR`` / ``${VAR}`` references inside a test operand."""

    def repl(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return env.get(name, os.environ.get(name, ""))

    return _VAR_REF_RE.sub(repl, value)


def evaluate_condition(expr: str, env: dict[str, str]) -> bool:
    """Evaluate a ``[ ... ]`` style condition. Raises ValueError on syntax errors."""
    text = expr.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError(f"unsupported condition: {expr!r}")
    inner = text[1:-1].strip()
    try:
        tokens = shlex.split(inner, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid condition tokens: {exc}") from exc
    if not tokens:
        raise ValueError("empty condition")

    negate = False
    if tokens[0] == "!":
        negate = True
        tokens = tokens[1:]
    if not tokens:
        raise ValueError("condition has only negation")

    result: bool
    if len(tokens) == 2 and tokens[0] in {"-f", "-d", "-e", "-z", "-n"}:
        op, raw = tokens
        operand = _expand_for_test(raw, env)
        if op == "-f":
            result = Path(operand).is_file()
        elif op == "-d":
            result = Path(operand).is_dir()
        elif op == "-e":
            result = Path(operand).exists()
        elif op == "-z":
            result = operand == ""
        else:  # -n
            result = operand != ""
    elif len(tokens) == 3 and tokens[1] in {"=", "==", "!="}:
        left = _expand_for_test(tokens[0], env)
        right = _expand_for_test(tokens[2], env)
        if tokens[1] == "!=":
            result = left != right
        else:
            result = left == right
    else:
        raise ValueError(f"unsupported condition: {expr!r}")

    return (not result) if negate else result


# ------------------------------------------------------------- mini-interpreter
def _strip_inline_comment(line: str) -> str:
    """Drop a trailing comment that begins outside any quoted segment."""
    in_single = False
    in_double = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_single:
            if c == "'":
                in_single = False
        elif in_double:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_double = False
        else:
            if c == "'":
                in_single = True
            elif c == '"':
                in_double = True
            elif c == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i].rstrip()
        i += 1
    return line


def _normalize_keyword_lines(lines: list[str]) -> list[str]:
    """Split combined keyword lines like ``...; then`` into separate entries.

    For example ``if [ -d /tmp ]; then`` becomes two virtual lines so the
    line-oriented interpreter can process them uniformly.
    """
    normalized: list[str] = []
    for raw in lines:
        line = _strip_inline_comment(raw).rstrip()
        if not line:
            continue
        # Handle inline ``; then`` / ``; do`` only outside quotes.
        for keyword in ("then", "do"):
            marker = f"; {keyword}"
            if line.endswith(marker):
                head = line[: -len(marker)].rstrip()
                if head:
                    normalized.append(head)
                normalized.append(keyword)
                break
        else:
            normalized.append(line)
    return normalized


def _strip_trailing_semicolon(line: str) -> str:
    if line.endswith(";"):
        return line[:-1].rstrip()
    return line


def _split_for_header(header: str) -> tuple[str, list[str]]:
    """Parse a ``for VAR in ITEMS`` header. Returns (var, items)."""
    text = header.strip()
    if not text.startswith("for "):
        raise ValueError(f"invalid for header: {header!r}")
    body = text[4:].strip()
    if " in " not in body:
        raise ValueError(f"missing 'in' in for header: {header!r}")
    var, _, items_part = body.partition(" in ")
    var = var.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var):
        raise ValueError(f"invalid loop variable: {var!r}")
    items_part = _strip_trailing_semicolon(items_part).strip()
    try:
        items = shlex.split(items_part, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid for items: {exc}") from exc
    return var, items


def _condition_from_header(header: str, keyword: str) -> str:
    """Strip ``if``/``while`` keyword and any trailing ``;`` from a header."""
    text = header.strip()
    if not text.startswith(f"{keyword} "):
        raise ValueError(f"invalid {keyword} header: {header!r}")
    body = text[len(keyword) + 1 :].strip()
    return _strip_trailing_semicolon(body).strip()


def _interpret(
    lines: list[str],
    executor: Callable[[str], int],
    env: dict[str, str],
    *,
    path: Path,
) -> int:
    """Run a list of normalized rc lines through ``executor``."""
    idx = 0
    n = len(lines)
    last_status = 0
    while idx < n:
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            idx += 1
            continue
        first_word = stripped.split(maxsplit=1)[0]

        if first_word == "if":
            block, end = _collect_if_block(lines, idx, path)
            try:
                last_status = _run_if_block(block, executor, env, path=path)
            except Exception as exc:  # noqa: BLE001 - rc lines must not crash the shell
                print(f"pysh: {path}: {exc}", file=sys.stderr)
                last_status = 1
            idx = end
            continue

        if first_word == "for":
            block, end = _collect_block(lines, idx, "for", "done", path)
            try:
                last_status = _run_for_block(block, executor, env, path=path)
            except Exception as exc:  # noqa: BLE001
                print(f"pysh: {path}: {exc}", file=sys.stderr)
                last_status = 1
            idx = end
            continue

        if first_word == "while":
            block, end = _collect_block(lines, idx, "while", "done", path)
            try:
                last_status = _run_while_block(block, executor, env, path=path)
            except Exception as exc:  # noqa: BLE001
                print(f"pysh: {path}: {exc}", file=sys.stderr)
                last_status = 1
            idx = end
            continue

        try:
            last_status = executor(line)
        except Exception as exc:  # noqa: BLE001
            print(f"pysh: {path}: {exc}", file=sys.stderr)
            last_status = 1
        idx += 1
    return last_status


def _collect_block(
    lines: list[str],
    start: int,
    opener: str,
    closer: str,
    path: Path,
) -> tuple[list[str], int]:
    """Collect ``opener`` ... ``closer`` block. Supports nested blocks."""
    depth = 1
    body: list[str] = [lines[start]]
    idx = start + 1
    n = len(lines)
    while idx < n:
        line = lines[idx]
        stripped = line.strip()
        first = stripped.split(maxsplit=1)[0] if stripped else ""
        if first in {"if", "for", "while"}:
            depth += 1
            body.append(line)
            idx += 1
            continue
        if stripped in {"fi", "done"}:
            depth -= 1
            body.append(line)
            if depth == 0:
                if stripped != closer:
                    raise ValueError(
                        f"{path}: expected '{closer}', got '{stripped}'"
                    )
                return body, idx + 1
            idx += 1
            continue
        body.append(line)
        idx += 1
    raise ValueError(f"{path}: missing '{closer}' for '{opener}'")


def _collect_if_block(
    lines: list[str], start: int, path: Path
) -> tuple[list[str], int]:
    return _collect_block(lines, start, "if", "fi", path)


def _split_branches(body: list[str]) -> tuple[str, list[str], list[str] | None]:
    """Split an if-block body into (condition, then-branch, else-branch)."""
    if not body or not body[0].strip().startswith("if "):
        raise ValueError("invalid if block")
    header = body[0].strip()
    # The opening line is the bare ``if [ ... ]`` after normalization. The
    # next line must be ``then``.
    condition = _condition_from_header(header, "if")
    inner = body[1:-1]  # drop ``if ...`` and the closing ``fi``
    if not inner or inner[0].strip() != "then":
        raise ValueError("missing 'then' after if")
    inner = inner[1:]

    then_branch: list[str] = []
    else_branch: list[str] | None = None
    depth = 0
    in_else = False
    for line in inner:
        stripped = line.strip()
        first = stripped.split(maxsplit=1)[0] if stripped else ""
        if first in {"if", "for", "while"}:
            depth += 1
        elif first in {"fi", "done"}:
            depth = max(0, depth - 1)
        if depth == 0 and stripped in {"else", "else:"}:
            in_else = True
            else_branch = []
            continue
        if in_else:
            assert else_branch is not None
            else_branch.append(line)
        else:
            then_branch.append(line)
    return condition, then_branch, else_branch


def _run_if_block(
    body: list[str],
    executor: Callable[[str], int],
    env: dict[str, str],
    *,
    path: Path,
) -> int:
    condition, then_branch, else_branch = _split_branches(body)
    if evaluate_condition(condition, env):
        return _interpret(then_branch, executor, env, path=path)
    if else_branch is not None:
        return _interpret(else_branch, executor, env, path=path)
    return 0


def _run_for_block(
    body: list[str],
    executor: Callable[[str], int],
    env: dict[str, str],
    *,
    path: Path,
) -> int:
    if not body or not body[0].strip().startswith("for "):
        raise ValueError("invalid for block")
    var, items = _split_for_header(body[0])
    # Expect: for ...; do ... done
    inner = body[1:-1]
    if not inner or inner[0].strip() != "do":
        raise ValueError("missing 'do' after for")
    inner = inner[1:]
    last_status = 0
    for item in items:
        env[var] = item
        os.environ[var] = item
        last_status = _interpret(inner, executor, env, path=path)
    return last_status


def _run_while_block(
    body: list[str],
    executor: Callable[[str], int],
    env: dict[str, str],
    *,
    path: Path,
) -> int:
    if not body or not body[0].strip().startswith("while "):
        raise ValueError("invalid while block")
    condition = _condition_from_header(body[0], "while")
    inner = body[1:-1]
    if not inner or inner[0].strip() != "do":
        raise ValueError("missing 'do' after while")
    inner = inner[1:]
    last_status = 0
    guard = 0
    while evaluate_condition(condition, env):
        guard += 1
        if guard > WHILE_ITER_LIMIT:
            print(
                f"pysh: {path}: while loop exceeded {WHILE_ITER_LIMIT} iterations",
                file=sys.stderr,
            )
            return 1
        last_status = _interpret(inner, executor, env, path=path)
    return last_status


# ----------------------------------------------------------------- entrypoints
def execute_rc(
    path: Path,
    executor: Callable[[str], int],
    *,
    quiet_missing: bool = True,
    env: dict[str, str] | None = None,
) -> int:
    """Execute commands from ``path`` via ``executor``.

    ``executor`` is a callable that runs a single shell line and returns the
    exit status. Returns the exit status of the last executed line, or 0 if
    no lines were run.
    """
    if not path.exists():
        if not quiet_missing:
            print(f"pysh: {path}: no such file", file=sys.stderr)
        return 0
    raw_lines = read_rc_file(path)
    normalized = _normalize_keyword_lines(raw_lines)
    return _interpret(
        normalized,
        executor,
        env if env is not None else {},
        path=path,
    )


def load_default_rc(executor: Callable[[str], int]) -> int:
    """Load the user's default rc file (``~/.pyshrc``) if present."""
    return execute_rc(RC_PATH, executor, quiet_missing=True)
