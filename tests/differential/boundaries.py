# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/boundaries.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Legacy-shell execution-boundary inventory loader and AST drift scanner (Issue #54).

The inventory (``legacy-boundaries-v1.json``) classifies every place where PySH
production code can hand work to Bash, Zsh, Fish or a POSIX ``sh``. The scanner
reads ``src/pysh`` with :mod:`ast` (it never imports it) and reports every
*legacy-execution signal*; an unreviewed signal fails the drift guard.

Signals (per enclosing qualified name, never per line):

* a string constant naming a legacy shell: a bare name (``zsh``), a path
  (``/bin/sh``), a shebang (``#!/usr/bin/env bash``) or ``PYSH_ZSH_FALLBACK``;
* ``shell=True``, ``os.system`` or ``os.popen``;
* a reference to a known bridge/fallback/delegation symbol.

Docstrings, comments and prose strings are not signals. Limits: executables
assembled dynamically (concatenation, environment, configuration), non-Python
files, and third-party code are invisible to the scanner; the packaging launcher
is therefore inventoried by hand and pinned by its own test.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
DEFAULT_INVENTORY = Path(__file__).with_name("legacy-boundaries-v1.json")
SCHEMA_VERSION = 1

CATEGORIES = frozenset({
    "PYSH_NATIVE",
    "EXPLICIT_MIGRATION_BRIDGE",
    "EXPLICIT_SHEBANG_DELEGATION",
    "AUTOMATIC_LEGACY_FALLBACK",
    "BUILD_OR_TEST_TOOLING",
    "DOCUMENTATION_ONLY",
})
AUTOMATIC_CATEGORY = "AUTOMATIC_LEGACY_FALLBACK"
TOP_FIELDS = frozenset({"schema_version", "boundaries"})
BOUNDARY_FIELDS = frozenset({
    "id", "category", "production_path", "symbols", "trigger", "automatic",
    "product_dependency", "semantic_authority", "policy", "notes",
})
ID_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
MODULE_SYMBOL = "<module>"

LEGACY_NAMES = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh"})
LEGACY_ENV_CONSTANTS = frozenset({"PYSH_ZSH_FALLBACK"})
LEGACY_SYMBOL_REFERENCES = frozenset({
    "ZshBridge", "zsh_bridge", "_run_zsh_command", "_run_zsh_fallback",
    "zsh_fallback_enabled", "_run_interpreter_script", "SUPPORTED_INTERPRETERS",
})
SHELL_CALLS = frozenset({("os", "system"), ("os", "popen")})


class BoundaryError(ValueError):
    """The boundary inventory violates its closed contract."""


@dataclass(frozen=True, slots=True)
class Boundary:
    boundary_id: str
    category: str
    production_path: str
    symbols: tuple[str, ...]
    trigger: str
    automatic: bool
    policy: str
    notes: str


def _is_legacy_constant(value: str) -> bool:
    text = value.strip()
    if text in LEGACY_ENV_CONSTANTS:
        return True
    if text.startswith("#!"):
        text = text[2:].strip().split()[-1] if text[2:].strip() else ""
    if "\n" in text or " " in text:
        return False
    return text.rsplit("/", 1)[-1] in LEGACY_NAMES and (
        "/" not in text or text.startswith(("/bin/", "/usr/bin/", "/usr/local/bin/"))
    )


class _Scanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.found: set[str] = set()
        self._docstrings: set[int] = set()

    def _qualname(self) -> str:
        return ".".join(self.stack) if self.stack else MODULE_SYMBOL

    def _mark_docstring(self, node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            self._docstrings.add(id(body[0].value))

    def visit_Module(self, node: ast.Module) -> None:
        self._mark_docstring(node)
        self.generic_visit(node)

    def _scope(self, node: ast.AST, name: str) -> None:
        self._mark_docstring(node)
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            isinstance(node.value, str)
            and id(node) not in self._docstrings
            and _is_legacy_constant(node.value)
        ):
            self.found.add(self._qualname())

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in LEGACY_SYMBOL_REFERENCES:
            self.found.add(self._qualname())

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in LEGACY_SYMBOL_REFERENCES:
            self.found.add(self._qualname())
        if (
            isinstance(node.value, ast.Name)
            and (node.value.id, node.attr) in SHELL_CALLS
        ):
            self.found.add(self._qualname())
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg == "shell" and isinstance(node.value, ast.Constant) and node.value.value is True:
            self.found.add(self._qualname())
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        if node.name.rsplit(".", 1)[-1] in LEGACY_SYMBOL_REFERENCES:
            self.found.add(self._qualname())

    def visit_arg(self, node: ast.arg) -> None:
        if node.arg in LEGACY_SYMBOL_REFERENCES:
            self.found.add(self._qualname())


def scan_source(source: str) -> frozenset[str]:
    """Qualified names (``<module>`` for module level) carrying a legacy signal."""
    scanner = _Scanner()
    scanner.visit(ast.parse(source))
    return frozenset(scanner.found)


def scan_tree(root: Path = SRC_ROOT) -> dict[str, frozenset[str]]:
    """Scan every ``*.py`` under ``root``; keys are repository-relative POSIX paths."""
    result: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.py")):
        found = scan_source(path.read_text(encoding="utf-8"))
        if found:
            result[path.relative_to(REPO_ROOT).as_posix()] = found
    return result


def defined_symbols(source: str) -> frozenset[str]:
    """Qualified names of every class/function in ``source`` plus ``<module>``."""
    names = {MODULE_SYMBOL}

    def walk(node: ast.AST, prefix: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = (*prefix, child.name)
                names.add(".".join(qualified))
                walk(child, qualified)
            else:
                walk(child, prefix)

    walk(ast.parse(source), ())
    return frozenset(names)


def _flag(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise BoundaryError(f"{context}: expected a boolean")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BoundaryError(f"{context}: expected a non-empty string")
    return value


def parse_inventory(data: object, *, repo_root: Path = REPO_ROOT) -> tuple[Boundary, ...]:
    """Validate a decoded inventory against the closed schema and the source tree."""
    if not isinstance(data, dict):
        raise BoundaryError("inventory root: expected an object")
    missing, unknown = sorted(TOP_FIELDS - set(data)), sorted(set(data) - TOP_FIELDS)
    if missing or unknown:
        raise BoundaryError(f"inventory root: missing {missing!r}; unknown {unknown!r}")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise BoundaryError(f"unsupported schema_version {data['schema_version']!r}")
    if not isinstance(data["boundaries"], list) or not data["boundaries"]:
        raise BoundaryError("boundaries: expected a non-empty list")
    seen: set[str] = set()
    owner: dict[tuple[str, str], str] = {}
    boundaries: list[Boundary] = []
    for index, raw in enumerate(data["boundaries"]):
        context = f"boundaries[{index}]"
        if not isinstance(raw, dict):
            raise BoundaryError(f"{context}: expected an object")
        missing, unknown = sorted(BOUNDARY_FIELDS - set(raw)), sorted(set(raw) - BOUNDARY_FIELDS)
        if missing or unknown:
            raise BoundaryError(f"{context}: missing {missing!r}; unknown {unknown!r}")
        boundary_id = _text(raw["id"], f"{context}.id")
        if not ID_RE.fullmatch(boundary_id):
            raise BoundaryError(f"{context}.id: invalid ID {boundary_id!r}")
        if boundary_id in seen:
            raise BoundaryError(f"duplicate boundary ID: {boundary_id}")
        seen.add(boundary_id)
        category = _text(raw["category"], f"{context}.category")
        if category not in CATEGORIES:
            raise BoundaryError(f"{context}.category: unknown category {category!r}")
        if category == AUTOMATIC_CATEGORY and MAX_AUTOMATIC_ENTRIES == 0:
            raise BoundaryError(
                f"{context}.category: PySH 1.0 permits no {AUTOMATIC_CATEGORY} entries"
            )
        automatic = _flag(raw["automatic"], f"{context}.automatic")
        if automatic != (category == AUTOMATIC_CATEGORY):
            raise BoundaryError(
                f"{context}.automatic: must be true exactly for {AUTOMATIC_CATEGORY}"
            )
        if _flag(raw["semantic_authority"], f"{context}.semantic_authority"):
            raise BoundaryError(f"{context}: a legacy boundary is never a semantic authority")
        if _flag(raw["product_dependency"], f"{context}.product_dependency"):
            raise BoundaryError(f"{context}: a legacy boundary is never a product dependency")
        path_text = _text(raw["production_path"], f"{context}.production_path")
        path = repo_root / path_text
        if not path.is_file():
            raise BoundaryError(f"{context}.production_path: {path_text!r} does not exist")
        symbols = raw["symbols"]
        if not isinstance(symbols, list) or not symbols or any(
            not isinstance(s, str) or not s for s in symbols
        ) or len(set(symbols)) != len(symbols):
            raise BoundaryError(f"{context}.symbols: expected a non-empty unique string list")
        if path.suffix == ".py":
            defined = defined_symbols(path.read_text(encoding="utf-8"))
            unresolved = sorted(set(symbols) - defined)
            if unresolved:
                raise BoundaryError(f"{context}.symbols: unresolved {unresolved!r} in {path_text}")
        for symbol in symbols:
            key = (path_text, symbol)
            if key in owner:
                raise BoundaryError(
                    f"{context}: {path_text}:{symbol} is already classified by {owner[key]!r}"
                )
            owner[key] = boundary_id
        boundaries.append(Boundary(
            boundary_id, category, path_text, tuple(symbols),
            _text(raw["trigger"], f"{context}.trigger"), automatic,
            _text(raw["policy"], f"{context}.policy"),
            _text(raw["notes"], f"{context}.notes"),
        ))
    return tuple(boundaries)


def load_inventory(path: Path = DEFAULT_INVENTORY) -> tuple[Boundary, ...]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BoundaryError(f"cannot load {path}: {error}") from error
    return parse_inventory(data)


def unreviewed_signals(
    inventory: tuple[Boundary, ...], scanned: dict[str, frozenset[str]]
) -> dict[str, list[str]]:
    """Signals found in source that no inventory entry covers (the drift set)."""
    covered: dict[str, set[str]] = {}
    for boundary in inventory:
        covered.setdefault(boundary.production_path, set()).update(boundary.symbols)
    drift: dict[str, list[str]] = {}
    for path, symbols in scanned.items():
        extra = sorted(symbols - covered.get(path, set()))
        if extra:
            drift[path] = extra
    return drift


#: Maximum inventory entries allowed in the automatic-fallback category. PySH 1.0
#: has no automatic hand-off from PySH execution to a legacy shell, so this is
#: zero and cannot be raised by editing the inventory alone.
MAX_AUTOMATIC_ENTRIES = 0
#: Names that only the explicit ``zsh <cmd>`` bridge may reference.
BRIDGE_NAMES = frozenset({"ZshBridge", "zsh_bridge", "_run_zsh_command"})
_FALLBACK_NAME_RE = re.compile(
    r"(zsh|bash|fish|legacy|posix_?sh)\w*fallback|fallback\w*(zsh|bash|fish|legacy)",
    re.IGNORECASE,
)
_FALLBACK_CONSTANTS = frozenset({"PYSH_ZSH_FALLBACK", "zsh_fallback"})


def forbidden_fallback_signals(source: str) -> frozenset[str]:
    """Qualified names that define or use an automatic legacy-shell fallback.

    These can never be blessed by an inventory entry: a function, class,
    attribute or variable whose name pairs "fallback" with a legacy shell, or the
    removed ``PYSH_ZSH_FALLBACK`` / ``zsh_fallback`` names as string constants.
    """
    found: set[str] = set()

    class Finder(_Scanner):
        def _hit(self) -> None:
            found.add(self._qualname())

        def _scope(self, node: ast.AST, name: str) -> None:
            if _FALLBACK_NAME_RE.search(name):
                found.add(".".join([*self.stack, name]))
            super()._scope(node, name)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and node.value.strip() in _FALLBACK_CONSTANTS:
                if id(node) not in self._docstrings:
                    self._hit()

        def visit_Name(self, node: ast.Name) -> None:
            if _FALLBACK_NAME_RE.search(node.id):
                self._hit()

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if _FALLBACK_NAME_RE.search(node.attr):
                self._hit()
            self.generic_visit(node)

        def visit_keyword(self, node: ast.keyword) -> None:
            self.generic_visit(node)

        def visit_alias(self, node: ast.alias) -> None:
            return None

        def visit_arg(self, node: ast.arg) -> None:
            if _FALLBACK_NAME_RE.search(node.arg):
                self._hit()

    finder = Finder()
    finder.visit(ast.parse(source))
    return frozenset(found)


def bridge_references(source: str) -> frozenset[str]:
    """Qualified names that reference the explicit zsh bridge machinery."""
    found: set[str] = set()

    class Finder(_Scanner):
        def visit_Constant(self, node: ast.Constant) -> None:
            return None

        def visit_Name(self, node: ast.Name) -> None:
            if node.id in BRIDGE_NAMES:
                found.add(self._qualname())

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if node.attr in BRIDGE_NAMES:
                found.add(self._qualname())
            self.generic_visit(node)

        def visit_keyword(self, node: ast.keyword) -> None:
            self.generic_visit(node)

        def visit_alias(self, node: ast.alias) -> None:
            if node.name.rsplit(".", 1)[-1] in BRIDGE_NAMES:
                found.add(self._qualname())

        def visit_arg(self, node: ast.arg) -> None:
            if node.arg in BRIDGE_NAMES:
                found.add(self._qualname())

    finder = Finder()
    finder.visit(ast.parse(source))
    return frozenset(found)


def scan_forbidden(root: Path = SRC_ROOT) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.py")):
        found = forbidden_fallback_signals(path.read_text(encoding="utf-8"))
        if found:
            result[path.relative_to(REPO_ROOT).as_posix()] = found
    return result


def scan_bridge_references(root: Path = SRC_ROOT) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.py")):
        found = bridge_references(path.read_text(encoding="utf-8"))
        if found:
            result[path.relative_to(REPO_ROOT).as_posix()] = found
    return result
