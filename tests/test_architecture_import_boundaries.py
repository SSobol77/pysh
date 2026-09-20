# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_architecture_import_boundaries.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Declarative architecture-boundary enforcement for PySH (Issue #46).

The checker reads source files with :mod:`ast`; it never imports application
modules.  ``architecture.toml`` is the machine-readable source of truth for
domain ownership, public/internal classification, permitted dependencies, and
the finite set of temporary dependency exceptions.
"""
from __future__ import annotations

import ast
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parent.parent
SRC_ROOT = REPOSITORY_ROOT / "src"
PYSH_SRC = SRC_ROOT / "pysh"
POLICY_PATH = REPOSITORY_ROOT / "architecture.toml"

HEAVY_INIT_FORBIDDEN: frozenset[str] = frozenset({
    "asyncio",
    "curses",
    "http",
    "multiprocessing",
    "pygments",
    "readline",
    "socket",
    "ssl",
    "subprocess",
    "threading",
    "urllib",
})

CONTRACTS_SIDE_EFFECT_FORBIDDEN: frozenset[str] = HEAVY_INIT_FORBIDDEN | {
    "ctypes",
    "pathlib",
    "selectors",
    "signal",
}

CONTRACTS_IO_CALLS_FORBIDDEN: frozenset[str] = frozenset({
    "__import__",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
    "print",
})


@dataclass(frozen=True)
class DomainRule:
    """One exact architecture domain and its permitted outgoing edges."""

    module: str
    layer: str
    classification: str
    owner: str
    extension_status: str
    allowed_dependencies: frozenset[str]


@dataclass(frozen=True)
class ExceptionRule:
    """One exact, temporary dependency exception."""

    importer: str
    imported: str
    reason: str
    cleanup_issue: str


@dataclass(frozen=True)
class ArchitecturePolicy:
    """Validated architecture policy loaded from ``architecture.toml``."""

    schema_version: int
    stable_modules: frozenset[str]
    compatibility_modules: frozenset[str]
    internal_type_prefixes: tuple[str, ...]
    versioned_external_protocols: frozenset[str]
    domains: tuple[DomainRule, ...]
    exceptions: tuple[ExceptionRule, ...]

    @property
    def domains_by_module(self) -> dict[str, DomainRule]:
        """Return domain rules keyed by their exact module names."""
        return {domain.module: domain for domain in self.domains}


@dataclass(frozen=True)
class ImportRecord:
    """A cross-domain import recovered statically from one source file."""

    importer_module: str
    importer_domain: str
    imported_module: str
    imported_domain: str
    path: Path
    line: int


@dataclass(frozen=True)
class ImportGraph:
    """Static domain graph and evidence for every cross-domain edge."""

    edges: dict[str, frozenset[str]]
    records: tuple[ImportRecord, ...]
    unclassified_sources: tuple[str, ...]
    unclassified_imports: tuple[str, ...]
    parse_errors: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryViolation:
    """A dependency edge rejected by the architecture policy."""

    importer: str
    imported: str
    category: str


def _require_string_list(value: object, field: str) -> list[str]:
    """Validate and return a TOML array containing only non-empty strings."""
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    return value


def _has_wildcard(value: str) -> bool:
    """Return whether a policy module name contains a wildcard token."""
    return any(token in value for token in ("*", "?", "[", "]"))


def _load_policy(path: Path = POLICY_PATH) -> ArchitecturePolicy:
    """Load and structurally validate the declarative architecture policy."""
    with path.open("rb") as stream:
        raw = tomllib.load(stream)

    if raw.get("schema_version") != 1:
        raise ValueError("architecture policy schema_version must be 1")

    public_api = raw.get("public_api")
    if not isinstance(public_api, dict):
        raise ValueError("architecture policy requires a [public_api] table")

    stable_modules = frozenset(
        _require_string_list(public_api.get("stable_modules"), "stable_modules")
    )
    compatibility_modules = frozenset(
        _require_string_list(
            public_api.get("compatibility_modules"), "compatibility_modules"
        )
    )
    internal_type_prefixes = tuple(
        _require_string_list(
            public_api.get("internal_type_prefixes"), "internal_type_prefixes"
        )
    )
    versioned_protocols = frozenset(
        _require_string_list(
            public_api.get("versioned_external_protocols"),
            "versioned_external_protocols",
        )
    )

    raw_domains = raw.get("domains")
    if not isinstance(raw_domains, list) or not raw_domains:
        raise ValueError("architecture policy requires at least one [[domains]] table")

    domains: list[DomainRule] = []
    seen_domains: set[str] = set()
    for index, item in enumerate(raw_domains):
        if not isinstance(item, dict):
            raise ValueError(f"domains[{index}] must be a TOML table")
        required = ("module", "layer", "classification", "owner", "extension_status")
        values: dict[str, str] = {}
        for field in required:
            value = item.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"domains[{index}].{field} must be a non-empty string")
            values[field] = value
        module = values["module"]
        if not (module == "pysh" or module.startswith("pysh.")):
            raise ValueError(f"invalid architecture domain: {module!r}")
        if _has_wildcard(module):
            raise ValueError(f"architecture domains must be exact: {module!r}")
        if module in seen_domains:
            raise ValueError(f"duplicate architecture domain: {module!r}")
        if values["classification"] not in {
            "stable_public",
            "compatibility_public",
            "internal",
        }:
            raise ValueError(
                f"invalid classification for {module}: {values['classification']!r}"
            )
        seen_domains.add(module)
        allowed = frozenset(
            _require_string_list(
                item.get("allowed_dependencies"),
                f"domains[{index}].allowed_dependencies",
            )
        )
        domains.append(
            DomainRule(
                module=module,
                layer=values["layer"],
                classification=values["classification"],
                owner=values["owner"],
                extension_status=values["extension_status"],
                allowed_dependencies=allowed,
            )
        )

    for domain in domains:
        unknown = domain.allowed_dependencies - seen_domains
        if unknown:
            raise ValueError(
                f"{domain.module} permits unknown domains: {sorted(unknown)!r}"
            )
        wildcard = sorted(
            dependency
            for dependency in domain.allowed_dependencies
            if _has_wildcard(dependency)
        )
        if wildcard:
            raise ValueError(
                f"{domain.module} has wildcard dependencies: {wildcard!r}"
            )

    classifications = {domain.module: domain.classification for domain in domains}
    declared_stable = {
        module for module, value in classifications.items() if value == "stable_public"
    }
    declared_compatibility = {
        module
        for module, value in classifications.items()
        if value == "compatibility_public"
    }
    if stable_modules != declared_stable:
        raise ValueError("public_api.stable_modules disagrees with domain classifications")
    if compatibility_modules != declared_compatibility:
        raise ValueError(
            "public_api.compatibility_modules disagrees with domain classifications"
        )
    if stable_modules & compatibility_modules:
        raise ValueError("stable and compatibility module sets must be disjoint")
    for prefix in internal_type_prefixes:
        if not prefix.startswith("pysh.") or _has_wildcard(prefix):
            raise ValueError(f"invalid internal type prefix: {prefix!r}")
    internal_domains = {
        module for module, value in classifications.items() if value == "internal"
    }
    uncovered_internal = {
        module
        for module in internal_domains
        if not any(module.startswith(prefix) for prefix in internal_type_prefixes)
    }
    if uncovered_internal:
        raise ValueError(
            f"internal domains lack an internal type prefix: {sorted(uncovered_internal)!r}"
        )
    public_covered_as_internal = {
        module
        for module in stable_modules | compatibility_modules
        if any(module.startswith(prefix) for prefix in internal_type_prefixes)
    }
    if public_covered_as_internal:
        raise ValueError(
            "public domains covered by an internal type prefix: "
            f"{sorted(public_covered_as_internal)!r}"
        )

    raw_exceptions = raw.get("exceptions", [])
    if not isinstance(raw_exceptions, list):
        raise ValueError("exceptions must be an array of tables")
    exceptions: list[ExceptionRule] = []
    seen_exceptions: set[tuple[str, str]] = set()
    by_module = {domain.module: domain for domain in domains}
    for index, item in enumerate(raw_exceptions):
        if not isinstance(item, dict):
            raise ValueError(f"exceptions[{index}] must be a TOML table")
        fields: dict[str, str] = {}
        for field in ("importer", "imported", "reason", "cleanup_issue"):
            value = item.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"exceptions[{index}].{field} must be non-empty")
            fields[field] = value
        importer = fields["importer"]
        imported = fields["imported"]
        if _has_wildcard(importer) or _has_wildcard(imported):
            raise ValueError("architecture exceptions must use exact domain names")
        if importer not in by_module or imported not in by_module:
            raise ValueError(f"exception references an unknown domain: {importer} -> {imported}")
        edge = (importer, imported)
        if edge in seen_exceptions:
            raise ValueError(f"duplicate architecture exception: {importer} -> {imported}")
        if imported in by_module[importer].allowed_dependencies:
            raise ValueError(f"redundant architecture exception: {importer} -> {imported}")
        seen_exceptions.add(edge)
        exceptions.append(ExceptionRule(**fields))

    return ArchitecturePolicy(
        schema_version=1,
        stable_modules=stable_modules,
        compatibility_modules=compatibility_modules,
        internal_type_prefixes=internal_type_prefixes,
        versioned_external_protocols=versioned_protocols,
        domains=tuple(domains),
        exceptions=tuple(exceptions),
    )


def _domain_for_module(module: str, policy: ArchitecturePolicy) -> str | None:
    """Resolve *module* to its longest matching exact policy domain."""
    matches = [
        domain.module
        for domain in policy.domains
        if module == domain.module
        or (domain.module != "pysh" and module.startswith(domain.module + "."))
    ]
    return max(matches, key=len, default=None)


def _module_for_file(path: Path, pysh_root: Path) -> str:
    """Return the fully qualified module represented by a Python source file."""
    relative = path.relative_to(pysh_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("pysh", *parts)) if parts else "pysh"


def _absolute_from_module(
    importer_module: str,
    importer_is_package: bool,
    node: ast.ImportFrom,
) -> str:
    """Resolve an ``ImportFrom`` node without importing the target."""
    if node.level == 0:
        return node.module or ""
    package = importer_module if importer_is_package else importer_module.rpartition(".")[0]
    parts = package.split(".") if package else []
    remove = node.level - 1
    if remove > len(parts):
        return ""
    if remove:
        parts = parts[:-remove]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _import_targets(
    tree: ast.AST,
    importer_module: str,
    importer_is_package: bool,
    policy: ArchitecturePolicy,
) -> list[tuple[str, int]]:
    """Return all statically visible PySH import targets, including local imports."""
    targets: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pysh" or alias.name.startswith("pysh."):
                    targets.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_from_module(importer_module, importer_is_package, node)
            if not (base == "pysh" or base.startswith("pysh.")):
                continue
            base_domain = _domain_for_module(base, policy)
            base_is_target = False
            specific_targets: list[str] = []
            for alias in node.names:
                if alias.name == "*":
                    base_is_target = True
                    continue
                candidate = f"{base}.{alias.name}"
                candidate_domain = _domain_for_module(candidate, policy)
                if candidate_domain is not None and candidate_domain != base_domain:
                    specific_targets.append(candidate)
                else:
                    base_is_target = True
            targets.extend((target, node.lineno) for target in specific_targets)
            if base_is_target or not specific_targets:
                targets.append((base, node.lineno))
    return targets


def _build_import_graph(pysh_root: Path, policy: ArchitecturePolicy) -> ImportGraph:
    """Build a complete cross-domain import graph from a PySH source tree."""
    mutable_edges: dict[str, set[str]] = defaultdict(set)
    records: list[ImportRecord] = []
    unclassified_sources: list[str] = []
    unclassified_imports: list[str] = []
    parse_errors: list[str] = []

    for path in sorted(pysh_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        importer_module = _module_for_file(path, pysh_root)
        importer_domain = _domain_for_module(importer_module, policy)
        if importer_domain is None:
            unclassified_sources.append(importer_module)
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            parse_errors.append(f"{path}:{error.lineno}: {error.msg}")
            continue
        for imported_module, line in _import_targets(
            tree,
            importer_module,
            path.name == "__init__.py",
            policy,
        ):
            imported_domain = _domain_for_module(imported_module, policy)
            if imported_domain is None:
                unclassified_imports.append(
                    f"{importer_module}:{line} imports {imported_module}"
                )
                continue
            if imported_domain == importer_domain:
                continue
            mutable_edges[importer_domain].add(imported_domain)
            records.append(
                ImportRecord(
                    importer_module=importer_module,
                    importer_domain=importer_domain,
                    imported_module=imported_module,
                    imported_domain=imported_domain,
                    path=path,
                    line=line,
                )
            )

    edges = {
        importer: frozenset(imported)
        for importer, imported in sorted(mutable_edges.items())
    }
    return ImportGraph(
        edges=edges,
        records=tuple(records),
        unclassified_sources=tuple(sorted(set(unclassified_sources))),
        unclassified_imports=tuple(sorted(set(unclassified_imports))),
        parse_errors=tuple(sorted(set(parse_errors))),
    )


def _edge_set(graph: ImportGraph) -> set[tuple[str, str]]:
    """Return graph edges as exact importer/imported tuples."""
    return {
        (importer, imported)
        for importer, dependencies in graph.edges.items()
        for imported in dependencies
    }


def _find_cycles(graph: dict[str, frozenset[str]]) -> list[list[str]]:
    """Return domain cycles using iterative depth-first traversal."""
    nodes = set(graph) | {dependency for values in graph.values() for dependency in values}
    white, gray, black = 0, 1, 2
    color = {node: white for node in nodes}
    cycles: list[list[str]] = []
    for start in sorted(nodes):
        if color[start] != white:
            continue
        color[start] = gray
        path = [start]
        stack = [(start, iter(sorted(graph.get(start, frozenset()))))]
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                color[node] = black
                path.pop()
                stack.pop()
                continue
            if color.get(child, white) == gray:
                cycles.append(path[path.index(child) :] + [child])
            elif color.get(child, white) == white:
                color[child] = gray
                path.append(child)
                stack.append((child, iter(sorted(graph.get(child, frozenset())))))
    return cycles


def _boundary_violations(
    graph: ImportGraph,
    policy: ArchitecturePolicy,
) -> list[BoundaryViolation]:
    """Return policy violations with architecture-specific failure categories."""
    domains = policy.domains_by_module
    exceptions = {(item.importer, item.imported) for item in policy.exceptions}
    violations: list[BoundaryViolation] = []
    for importer, imported in sorted(_edge_set(graph)):
        if imported in domains[importer].allowed_dependencies:
            continue
        if (importer, imported) in exceptions:
            continue
        if imported == "pysh.api" and domains[importer].classification != "stable_public":
            category = "internal_api_consumption"
        elif importer == "pysh.contracts":
            category = "contracts_upward_dependency"
        elif importer == "pysh.parsing":
            category = "parser_upward_dependency"
        elif "pysh.plugins.isolated" in (importer, imported):
            category = "isolated_plugin_boundary"
        else:
            category = "forbidden_dependency"
        violations.append(BoundaryViolation(importer, imported, category))
    return violations


def _assert_graph_complete(graph: ImportGraph) -> None:
    """Fail if the checker could not classify or parse the complete source tree."""
    failures: list[str] = []
    if graph.unclassified_sources:
        failures.append(f"unclassified source modules: {graph.unclassified_sources!r}")
    if graph.unclassified_imports:
        failures.append(f"unclassified PySH imports: {graph.unclassified_imports!r}")
    if graph.parse_errors:
        failures.append(f"source parse errors: {graph.parse_errors!r}")
    assert not failures, "\n".join(failures)


def _repository_graph() -> tuple[ArchitecturePolicy, ImportGraph]:
    """Load the repository policy and statically scan its source tree."""
    policy = _load_policy()
    graph = _build_import_graph(PYSH_SRC, policy)
    _assert_graph_complete(graph)
    return policy, graph


def _write_module(root: Path, relative_path: str, source: str) -> None:
    """Create one source module in a synthetic PySH tree."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _synthetic_violations(
    tmp_path: Path,
    relative_path: str,
    source: str,
) -> list[BoundaryViolation]:
    """Scan one synthetic source module using the repository policy."""
    root = tmp_path / "pysh"
    _write_module(root, relative_path, source)
    policy = _load_policy()
    graph = _build_import_graph(root, policy)
    _assert_graph_complete(graph)
    return _boundary_violations(graph, policy)


def test_architecture_policy_is_coherent() -> None:
    """The declarative policy must satisfy its complete schema and invariants."""
    policy = _load_policy()
    assert len(policy.domains_by_module) == len(policy.domains)
    assert policy.versioned_external_protocols == {
        "trusted_plugin_api",
        "isolated_plugin_manifest",
        "isolated_plugin_ipc",
    }


def test_no_import_cycles() -> None:
    """The actual cross-domain dependency graph must remain acyclic."""
    _, graph = _repository_graph()
    cycles = _find_cycles(graph.edges)
    assert not cycles, "import cycles detected:\n  " + "\n  ".join(
        " -> ".join(cycle) for cycle in cycles
    )


def test_cross_domain_ratchet() -> None:
    """Every actual cross-domain edge must be allowed or exactly excepted."""
    policy, graph = _repository_graph()
    violations = _boundary_violations(graph, policy)
    assert not violations, "architecture boundary violations:\n  " + "\n  ".join(
        f"{item.importer} -> {item.imported} [{item.category}]"
        for item in violations
    )


def test_known_exceptions_are_present_and_exact() -> None:
    """A resolved temporary exception must be removed instead of going stale."""
    policy, graph = _repository_graph()
    actual = _edge_set(graph)
    stale = [
        item
        for item in policy.exceptions
        if (item.importer, item.imported) not in actual
    ]
    assert not stale, "stale architecture exceptions:\n  " + "\n  ".join(
        f"{item.importer} -> {item.imported} ({item.cleanup_issue})" for item in stale
    )


def test_contracts_isolation() -> None:
    """Contracts may import only the standard library and their own package."""
    violations: list[str] = []
    for path in sorted((PYSH_SRC / "contracts").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                root = module.split(".", maxsplit=1)[0]
                is_self = module == "pysh.contracts" or module.startswith("pysh.contracts.")
                is_stdlib = root in sys.stdlib_module_names or root == "__future__"
                if not (is_self or is_stdlib):
                    violations.append(f"{path.relative_to(SRC_ROOT)} imports {module}")
                if root in CONTRACTS_SIDE_EFFECT_FORBIDDEN:
                    violations.append(
                        f"{path.relative_to(SRC_ROOT)} imports side-effect-heavy {module}"
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in CONTRACTS_IO_CALLS_FORBIDDEN
            ):
                violations.append(
                    f"{path.relative_to(SRC_ROOT)} calls forbidden {node.func.id}()"
                )
    assert not violations, "contracts isolation violations:\n  " + "\n  ".join(violations)


def test_init_files_are_side_effect_minimal() -> None:
    """Package initializers must not eagerly import side-effect-heavy modules."""
    violations: list[str] = []
    for path in sorted(PYSH_SRC.rglob("__init__.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module.split(".", maxsplit=1)[0] in HEAVY_INIT_FORBIDDEN:
                    violations.append(f"{path.relative_to(SRC_ROOT)} imports {module}")
    assert not violations, "heavy package initializer imports:\n  " + "\n  ".join(
        violations
    )


@pytest.mark.parametrize("imported", ["pysh.core", "pysh.editor"])
def test_parser_upward_edges_are_rejected(tmp_path: Path, imported: str) -> None:
    """The shared parser remains a low-level leaf below runtime and editor."""
    violations = _synthetic_violations(
        tmp_path,
        "parsing/synthetic.py",
        f"import {imported}\n",
    )
    assert violations == [
        BoundaryViolation("pysh.parsing", imported, "parser_upward_dependency")
    ]


def test_contracts_to_implementation_edge_is_rejected(tmp_path: Path) -> None:
    """Contracts cannot depend on an implementation domain."""
    violations = _synthetic_violations(
        tmp_path,
        "contracts/synthetic.py",
        "from pysh.core import shell\n",
    )
    assert violations == [
        BoundaryViolation(
            "pysh.contracts",
            "pysh.core",
            "contracts_upward_dependency",
        )
    ]


@pytest.mark.parametrize(
    "statement",
    ["import pysh.api\n", "from pysh import api\n"],
)
def test_internal_modules_cannot_consume_public_facade(
    tmp_path: Path,
    statement: str,
) -> None:
    """Internal modules cannot reverse-depend on the canonical public facade."""
    violations = _synthetic_violations(tmp_path, "core/synthetic.py", statement)
    assert violations == [
        BoundaryViolation(
            "pysh.core",
            "pysh.api",
            "internal_api_consumption",
        )
    ]


def test_multi_name_from_import_checks_every_domain(tmp_path: Path) -> None:
    """One from-import cannot hide a forbidden domain behind an allowed name."""
    violations = _synthetic_violations(
        tmp_path,
        "core/synthetic.py",
        "from pysh import __version__, api\n",
    )
    assert violations == [
        BoundaryViolation(
            "pysh.core",
            "pysh.api",
            "internal_api_consumption",
        )
    ]


def test_generic_reverse_edge_is_rejected(tmp_path: Path) -> None:
    """An undeclared dependency is rejected even when it is cycle-free."""
    violations = _synthetic_violations(
        tmp_path,
        "prompt/synthetic.py",
        "import pysh.core\n",
    )
    assert violations == [
        BoundaryViolation("pysh.prompt", "pysh.core", "forbidden_dependency")
    ]


def test_declared_dependency_is_accepted(tmp_path: Path) -> None:
    """A dependency listed for a domain passes without an exception."""
    violations = _synthetic_violations(
        tmp_path,
        "editor/synthetic.py",
        "from pysh.parsing import parser\n",
    )
    assert violations == []


def test_synthetic_cycle_is_detected(tmp_path: Path) -> None:
    """Cycle detection operates on the AST graph independently of policy acceptance."""
    root = tmp_path / "pysh"
    _write_module(root, "contracts/synthetic.py", "import pysh.parsing\n")
    _write_module(root, "parsing/synthetic.py", "import pysh.contracts\n")
    graph = _build_import_graph(root, _load_policy())
    assert _find_cycles(graph.edges) == [
        ["pysh.contracts", "pysh.parsing", "pysh.contracts"]
    ]


def test_exact_known_exception_is_accepted(tmp_path: Path) -> None:
    """A listed temporary edge is accepted by exact domain pair only."""
    violations = _synthetic_violations(
        tmp_path,
        "security/synthetic.py",
        "import pysh.prompt.colors\n",
    )
    assert violations == []


def test_similar_unlisted_edge_is_rejected(tmp_path: Path) -> None:
    """An exception does not grant broader permission to adjacent domains."""
    violations = _synthetic_violations(
        tmp_path,
        "services/synthetic.py",
        "import pysh.prompt.colors\n",
    )
    assert violations == [
        BoundaryViolation("pysh.services", "pysh.prompt", "forbidden_dependency")
    ]


def test_isolated_plugin_seam_allows_only_declared_direction(tmp_path: Path) -> None:
    """The isolated implementation may use trusted metadata; runtime may not reach in."""
    root = tmp_path / "pysh"
    _write_module(root, "plugins/isolated/synthetic.py", "import pysh.plugins.names\n")
    _write_module(root, "core/synthetic.py", "import pysh.plugins.isolated.runtime\n")
    policy = _load_policy()
    graph = _build_import_graph(root, policy)
    assert _boundary_violations(graph, policy) == [
        BoundaryViolation(
            "pysh.core",
            "pysh.plugins.isolated",
            "isolated_plugin_boundary",
        )
    ]


def test_deferred_local_import_is_detected(tmp_path: Path) -> None:
    """Imports inside functions cannot evade the architecture checker."""
    violations = _synthetic_violations(
        tmp_path,
        "services/synthetic.py",
        "def deferred():\n    import pysh.core\n",
    )
    assert violations == [
        BoundaryViolation("pysh.services", "pysh.core", "forbidden_dependency")
    ]


def test_wildcard_exception_is_rejected(tmp_path: Path) -> None:
    """Policy exceptions must never become package-wide wildcard exemptions."""
    policy_text = POLICY_PATH.read_text(encoding="utf-8")
    policy_text += """

[[exceptions]]
importer = "pysh.config.*"
imported = "pysh.editor"
reason = "Synthetic invalid exception."
cleanup_issue = "Issue #46"
"""
    path = tmp_path / "architecture.toml"
    path.write_text(policy_text, encoding="utf-8")
    with pytest.raises(ValueError, match="exact domain names"):
        _load_policy(path)
