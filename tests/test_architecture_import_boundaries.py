# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_architecture_import_boundaries.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Architecture import-boundary enforcement tests (Issue #3).

Strategy: AST-based static analysis — no pysh modules are imported at
collection time, so the tests do not trigger side effects.

Four gates:

A. No import cycles across tracked domain packages (hard gate, always fails).
B. pysh.contracts must not import implementation packages (hard gate).
C. Package __init__.py files are side-effect minimal (no heavy imports).
D. Cross-package dependency ratchet: KNOWN_VIOLATIONS are documented;
   new violations fail; the list may only shrink.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Filesystem roots
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).parent.parent / "src"
PYSH_SRC = SRC_ROOT / "pysh"

# ---------------------------------------------------------------------------
# Domain packages tracked by the cycle detector and ratchet
# ---------------------------------------------------------------------------

DOMAIN_PACKAGES: frozenset[str] = frozenset({
    "pysh.core",
    "pysh.parsing",
    "pysh.editor",
    "pysh.prompt",
    "pysh.python_layer",
    "pysh.config",
    "pysh.compat",
    "pysh.services",
    "pysh.security",
    "pysh.diagnostics",
    "pysh.contracts",
    "pysh.cli",
    "pysh.shell",
    "pysh.script_runner",
    "pysh.__main__",
})

# Implementation packages that pysh.contracts must never import.
IMPLEMENTATION_PACKAGES: frozenset[str] = frozenset({
    "pysh.core",
    "pysh.parsing",
    "pysh.editor",
    "pysh.prompt",
    "pysh.python_layer",
    "pysh.config",
    "pysh.compat",
    "pysh.services",
    "pysh.security",
    "pysh.diagnostics",
})

# Heavy modules that package __init__.py files must not import at the
# top level (they would be executed on every bare `import pysh.*`).
HEAVY_INIT_FORBIDDEN: frozenset[str] = frozenset({
    "subprocess",
    "threading",
    "multiprocessing",
    "asyncio",
    "socket",
    "ssl",
    "http",
    "urllib",
    "curses",
    "readline",
    "pygments",
})

# ---------------------------------------------------------------------------
# Ratchet: known cross-domain boundary violations
# ---------------------------------------------------------------------------
# Each entry is (importing_domain, imported_domain).
# The set may shrink as issues are resolved; it must NOT grow without
# architectural review (a new entry requires a corresponding Issue reference).
#
# Cleanup issue references:
#   Issue #6   – signal and PTY cleanup
#   Issue #8   – parser / expansion / editor boundary cleanup
#   Issue #14  – script-mode cleanup


class _Violation(NamedTuple):
    importing_pkg: str
    imported_pkg: str
    reason: str
    cleanup_issue: str


KNOWN_VIOLATIONS: frozenset[tuple[str, str]] = frozenset({
    # config.api uses _display_width from editor.lineedit.buffer
    ("pysh.config", "pysh.editor"),
    # config.api uses color_to_hex / parse_color from prompt.colors
    ("pysh.config", "pysh.prompt"),
    # config.rc (deferred import) uses is_block_opener / iter_logical_lines
    # from python_layer.runtime for py { ... } block handling in rc files
    ("pysh.config", "pysh.python_layer"),
    # editor.lineedit.reader uses split_paste_commands from parsing.parser
    ("pysh.editor", "pysh.parsing"),
    # python_layer.mode / .highlighting use editor.lineedit and editor.highlight
    ("pysh.python_layer", "pysh.editor"),
    # diagnostics.command_plan uses split_chain / split_pipeline from parsing.parser
    ("pysh.diagnostics", "pysh.parsing"),
    # diagnostics.command_plan uses is_block_opener from python_layer.runtime
    ("pysh.diagnostics", "pysh.python_layer"),
    # script_runner uses split_chain from parsing.parser
    ("pysh.script_runner", "pysh.parsing"),
    # script_runner uses is_block_opener / iter_logical_lines from python_layer.runtime
    ("pysh.script_runner", "pysh.python_layer"),
    # security.secure_runner uses colorize / parse_color from prompt.colors
    ("pysh.security", "pysh.prompt"),
})

KNOWN_VIOLATION_DETAILS: list[_Violation] = [
    _Violation(
        "pysh.config", "pysh.editor",
        "config.api uses _display_width from editor.lineedit.buffer (prompt width)",
        "Issue #8",
    ),
    _Violation(
        "pysh.config", "pysh.prompt",
        "config.api uses color_to_hex, parse_color from prompt.colors",
        "Issue #8",
    ),
    _Violation(
        "pysh.config", "pysh.python_layer",
        "config.rc uses is_block_opener, iter_logical_lines from python_layer.runtime "
        "(deferred local import) for py { ... } block coalescing in rc files",
        "Issue #8",
    ),
    _Violation(
        "pysh.editor", "pysh.parsing",
        "editor.lineedit.reader uses split_paste_commands from parsing.parser",
        "Issue #8",
    ),
    _Violation(
        "pysh.python_layer", "pysh.editor",
        "python_layer.mode uses editor.lineedit (reader/buffer/highlight/autosuggest) for #py REPL;"
        " python_layer.highlighting uses editor.highlight for ANSI colors",
        "Issue #8",
    ),
    _Violation(
        "pysh.diagnostics", "pysh.parsing",
        "diagnostics.command_plan uses ChainOp, split_chain, split_pipeline from parsing.parser",
        "Issue #8",
    ),
    _Violation(
        "pysh.diagnostics", "pysh.python_layer",
        "diagnostics.command_plan uses PY_BLOCK_OPENER, is_block_opener from python_layer.runtime",
        "Issue #8",
    ),
    _Violation(
        "pysh.script_runner", "pysh.parsing",
        "script_runner uses ChainOp, split_chain from parsing.parser",
        "Issue #14",
    ),
    _Violation(
        "pysh.script_runner", "pysh.python_layer",
        "script_runner uses is_block_opener, iter_logical_lines from python_layer.runtime",
        "Issue #14",
    ),
    _Violation(
        "pysh.security", "pysh.prompt",
        "security.secure_runner uses colorize, parse_color from prompt.colors",
        "Issue #6",
    ),
]

# ---------------------------------------------------------------------------
# AST-based import graph builder
# ---------------------------------------------------------------------------


def _domain_of_file(path: Path) -> str:
    """Return the domain package name (e.g. 'pysh.core') for a source file."""
    try:
        rel = path.relative_to(PYSH_SRC)
    except ValueError:
        return ""
    parts = list(rel.parts)
    if not parts:
        return ""
    first = parts[0]
    if first == "__init__.py":
        return "pysh"
    if len(parts) == 1:
        # Top-level module: pysh/cli.py → pysh.cli
        return "pysh." + first.removesuffix(".py")
    # Subdirectory module: pysh/core/shell.py → pysh.core
    return "pysh." + first


def _domain_of_import(module: str) -> str:
    """Return the domain package for an import string.

    'pysh.editor.lineedit.buffer' → 'pysh.editor'
    'pysh.cli' → 'pysh.cli'
    """
    parts = module.split(".")
    if len(parts) <= 2:
        return module
    return ".".join(parts[:2])


def _pysh_imports(path: Path) -> list[str]:
    """Return all pysh.* import targets found in *path*, via AST."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pysh" or alias.name.startswith("pysh."):
                    targets.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "pysh" or node.module.startswith("pysh.")
            ):
                targets.append(node.module)
    return targets


def _build_cross_domain_graph() -> dict[str, set[str]]:
    """Return a package-level dependency graph built from source AST."""
    graph: dict[str, set[str]] = defaultdict(set)
    for py_file in PYSH_SRC.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        owner = _domain_of_file(py_file)
        if not owner:
            continue
        for import_target in _pysh_imports(py_file):
            target = _domain_of_import(import_target)
            if target != owner and target.startswith("pysh"):
                graph[owner].add(target)
    return dict(graph)


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return all cycles in *graph* using iterative DFS (avoids recursion limit)."""
    all_nodes: set[str] = set(graph) | {n for nbrs in graph.values() for n in nbrs}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in all_nodes}
    cycles: list[list[str]] = []

    for start in sorted(all_nodes):
        if color[start] != WHITE:
            continue
        stack = [(start, iter(sorted(graph.get(start, set()))))]
        path: list[str] = [start]
        color[start] = GRAY

        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if color.get(child, WHITE) == GRAY:
                    idx = path.index(child)
                    cycles.append(path[idx:] + [child])
                elif color.get(child, WHITE) == WHITE:
                    color[child] = GRAY
                    path.append(child)
                    stack.append((child, iter(sorted(graph.get(child, set())))))
            except StopIteration:
                color[node] = BLACK
                path.pop()
                stack.pop()

    return cycles


# ---------------------------------------------------------------------------
# Gate A: No import cycles
# ---------------------------------------------------------------------------


def test_no_import_cycles() -> None:
    """Gate A (hard): no import cycles across tracked domain packages."""
    graph = _build_cross_domain_graph()
    cycles = _find_cycles(graph)
    if cycles:
        formatted = "\n  ".join(" → ".join(c) for c in cycles)
        pytest.fail(f"Import cycles detected:\n  {formatted}")


# ---------------------------------------------------------------------------
# Gate B: contracts isolation
# ---------------------------------------------------------------------------


def test_contracts_isolation() -> None:
    """Gate B (hard): pysh.contracts must not import implementation packages."""
    contracts_dir = PYSH_SRC / "contracts"
    assert contracts_dir.is_dir(), "pysh.contracts package directory not found"
    violations: list[str] = []
    for py_file in contracts_dir.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        for import_target in _pysh_imports(py_file):
            target_domain = _domain_of_import(import_target)
            if target_domain in IMPLEMENTATION_PACKAGES:
                rel = py_file.relative_to(SRC_ROOT)
                violations.append(f"  {rel}: imports {import_target!r}")
    assert not violations, (
        "pysh.contracts must not import implementation packages:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Gate C: __init__.py side-effect policy
# ---------------------------------------------------------------------------


def test_init_files_are_side_effect_minimal() -> None:
    """Gate C: package __init__.py files must not import heavy modules."""
    violations: list[str] = []
    for init_file in PYSH_SRC.rglob("__init__.py"):
        if "__pycache__" in init_file.parts:
            continue
        try:
            tree = ast.parse(
                init_file.read_text(encoding="utf-8"), filename=str(init_file)
            )
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module_name: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in HEAVY_INIT_FORBIDDEN:
                        module_name = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in HEAVY_INIT_FORBIDDEN:
                        module_name = node.module
            if module_name is not None:
                rel = init_file.relative_to(SRC_ROOT)
                violations.append(f"  {rel}: imports {module_name!r}")
    assert not violations, (
        "__init__.py files must not import heavy modules at package load time:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Gate D: cross-domain ratchet
# ---------------------------------------------------------------------------

# Cross-domain edges that are architecturally expected (not ratcheted).
_PERMITTED_SOURCES: frozenset[str] = frozenset({
    "pysh.core",      # fan-in hub: imports from all leaf packages
    "pysh.cli",       # entry point → core
    "pysh.shell",     # compatibility shim → core
    "pysh.__main__",  # module entry point → cli
    "pysh",           # root package
})


def test_cross_domain_ratchet() -> None:
    """Gate D (ratchet): no new cross-domain violations beyond KNOWN_VIOLATIONS.

    Permitted cross-domain imports (never ratcheted):
    - pysh.core imports from any leaf package (fan-in role).
    - pysh.cli and pysh.shell import from pysh.core (entry points / shim).
    - pysh.__main__ imports from pysh.cli.

    Everything else is either in KNOWN_VIOLATIONS (documented, awaiting cleanup)
    or is a new violation that fails this test.
    """
    graph = _build_cross_domain_graph()
    actual: set[tuple[str, str]] = set()
    for importer, importees in graph.items():
        if importer in _PERMITTED_SOURCES:
            continue
        for importee in importees:
            if importee in _PERMITTED_SOURCES:
                continue
            if importer == importee:
                continue
            actual.add((importer, importee))

    new_violations = actual - KNOWN_VIOLATIONS
    if new_violations:
        lines = [
            "New cross-domain boundary violations detected.",
            "Add to KNOWN_VIOLATIONS with reason and cleanup issue:",
        ]
        for imp, dep in sorted(new_violations):
            lines.append(f"  {imp} → {dep}")
        pytest.fail("\n".join(lines))

    # Informational: violations present in KNOWN_VIOLATIONS but absent from
    # the actual graph have been resolved.  They should be removed from
    # KNOWN_VIOLATIONS to keep the ratchet accurate.
    resolved = KNOWN_VIOLATIONS - actual
    if resolved:
        lines = [
            "The following KNOWN_VIOLATIONS no longer appear in the code.",
            "Remove them from KNOWN_VIOLATIONS in this file:",
        ]
        for imp, dep in sorted(resolved):
            lines.append(f"  {imp} → {dep}")
        # This is informational only; do not fail here.
        # The test author should clean up KNOWN_VIOLATIONS manually.
        _ = lines  # suppress unused-variable lint
