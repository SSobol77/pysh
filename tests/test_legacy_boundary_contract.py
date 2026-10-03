# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_legacy_boundary_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 2: legacy execution-boundary inventory and drift guard.

The inventory records current behavior; it does not endorse it. Nothing here
changes production, and no legacy shell is executed.
"""
from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.differential import boundaries as bnd

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "compatibility" / "legacy-shell-migration.md"
RAW: dict[str, Any] = json.loads(bnd.DEFAULT_INVENTORY.read_text(encoding="utf-8"))


def _pairs(inventory: tuple[bnd.Boundary, ...], category: str) -> set[tuple[str, str]]:
    return {
        (b.production_path, symbol)
        for b in inventory if b.category == category for symbol in b.symbols
    }


# --- inventory ---------------------------------------------------------------------------------


def test_shipped_inventory_is_valid_and_covers_every_category() -> None:
    inventory = bnd.load_inventory()
    assert {b.category for b in inventory} == bnd.CATEGORIES
    assert all(not b.automatic or b.category == bnd.AUTOMATIC_CATEGORY for b in inventory)
    assert all(b.policy and b.trigger and b.notes for b in inventory)


def test_automatic_fallback_entry_points_are_pinned_exactly() -> None:
    inventory = bnd.load_inventory()
    assert _pairs(inventory, "AUTOMATIC_LEGACY_FALLBACK") == {
        ("src/pysh/core/shell.py", "PyShell.__init__"),
        ("src/pysh/core/shell.py", "PyShell._builtin_zsh_fallback"),
        ("src/pysh/core/shell.py", "PyShell._assign_local"),
        ("src/pysh/core/shell.py", "PyShell._set_exported_environment"),
        ("src/pysh/core/shell.py", "PyShell._run_simple"),
        ("src/pysh/core/shell.py", "PyShell._run_pipeline"),
        ("src/pysh/core/shell.py", "PyShell._run_external"),
        ("src/pysh/core/shell.py", "PyShell._run_zsh_fallback"),
        ("src/pysh/parsing/expansion.py", "_default_runner"),
    }


def test_explicit_bridge_and_shebang_entry_points_are_distinct_from_automatic_ones() -> None:
    inventory = bnd.load_inventory()
    bridge = _pairs(inventory, "EXPLICIT_MIGRATION_BRIDGE")
    shebang = _pairs(inventory, "EXPLICIT_SHEBANG_DELEGATION")
    assert ("src/pysh/core/shell.py", "PyShell._builtin_zsh") in bridge
    assert ("src/pysh/compat/zsh_bridge.py", "ZshBridge.execute") in bridge
    assert ("src/pysh/script_runner.py", "ScriptRunner._run_interpreter_script") in shebang
    assert ("src/pysh/script_runner.py", "ScriptRunner.run") in shebang
    assert not bridge & shebang
    assert not (bridge | shebang) & _pairs(inventory, "AUTOMATIC_LEGACY_FALLBACK")


def test_every_classified_symbol_belongs_to_exactly_one_category() -> None:
    inventory = bnd.load_inventory()
    pairs = [(b.production_path, s) for b in inventory for s in b.symbols]
    assert len(pairs) == len(set(pairs))


def _mutated(mutate) -> Any:
    data = copy.deepcopy(RAW)
    mutate(data)
    return data


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(extra=1), "unknown"),
        (lambda d: d["boundaries"][0].update(extra=1), "unknown"),
        (lambda d: d["boundaries"][0].pop("policy"), "missing"),
        (lambda d: d["boundaries"][1].update(id=d["boundaries"][0]["id"]), "duplicate boundary ID"),
        (lambda d: d["boundaries"][0].update(id="Bad_ID"), "invalid ID"),
        (lambda d: d["boundaries"][0].update(category="BASH_COMPAT"), "unknown category"),
        (lambda d: d["boundaries"][0].update(production_path="src/pysh/nope.py"), "does not exist"),
        (lambda d: d["boundaries"][0].update(symbols=["NoSuch.symbol"]), "unresolved"),
        (lambda d: d["boundaries"][0].update(symbols=[]), "symbols"),
        (lambda d: d["boundaries"][0].update(automatic=True), "automatic"),
        (lambda d: d["boundaries"][0].update(semantic_authority=True), "semantic authority"),
        (lambda d: d["boundaries"][0].update(product_dependency=True), "product dependency"),
        (lambda d: d["boundaries"][0].update(automatic="yes"), "boolean"),
        (lambda d: d["boundaries"][4].update(automatic=False), "automatic"),
        (lambda d: d["boundaries"][1].update(symbols=d["boundaries"][0]["symbols"][:1]
                                             ) or d["boundaries"][1].update(
            production_path=d["boundaries"][0]["production_path"]), "already classified"),
        (lambda d: d.update(boundaries=[]), "boundaries"),
    ],
)
def test_invalid_inventory_is_rejected(mutate, message: str) -> None:
    with pytest.raises(bnd.BoundaryError, match=re.escape(message)):
        bnd.parse_inventory(_mutated(mutate))


# --- drift guard -------------------------------------------------------------------------------


def test_production_tree_has_no_unreviewed_legacy_execution_signal() -> None:
    drift = bnd.unreviewed_signals(bnd.load_inventory(), bnd.scan_tree())
    assert drift == {}, f"unreviewed legacy-execution signals (inventory them or remove): {drift}"


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\ndef f(c):\n    subprocess.run(['bash', '-c', c])\n",
        "import subprocess\ndef f(c):\n    subprocess.Popen(['/bin/zsh', c])\n",
        "import subprocess\ndef f(c):\n    subprocess.run(['fish', '-c', c])\n",
        "import subprocess\ndef f(c):\n    subprocess.run(['/usr/bin/env', 'bash'])\n" if False else
        "def f():\n    x = '#!/usr/bin/env bash'\n",
        "import subprocess\ndef f(c):\n    subprocess.run(c, shell=True)\n",
        "import os\ndef f(c):\n    os.system(c)\n",
        "import os\ndef f(c):\n    os.popen(c)\n",
        "def f(self):\n    return self._run_zsh_fallback('x')\n",
        "def f(self):\n    return self.zsh_fallback_enabled\n",
        "from pysh.compat.zsh_bridge import ZshBridge\n",
        "def f():\n    return ZshBridge()\n",
        "X = frozenset({'zsh', 'bash', 'sh'})\n",
        "def f():\n    return 'PYSH_ZSH_FALLBACK'\n",
    ],
)
def test_new_legacy_execution_signals_are_detected(source: str) -> None:
    assert bnd.scan_source(source), source


@pytest.mark.parametrize(
    "source",
    [
        '"""zsh bash fish /bin/sh PYSH_ZSH_FALLBACK"""\n',
        "def f():\n    '''Runs bash via /bin/sh and zsh'''\n    return 1\n",
        "# subprocess.run(['bash'])\nx = 1\n",
        "def f():\n    return 'pysh: unsupported zsh syntax: array'\n",
        "def f():\n    return 'hint: PySH does not source zsh startup files.'\n",
        "def f():\n    return 'Bash-style interactive REPL'\n",
        "import subprocess\ndef f(argv):\n    subprocess.run(argv, shell=False)\n",
        "def f():\n    return ['git', 'status']\n",
        "def shell_name():\n    return 'shell'\n",
    ],
)
def test_documentation_comments_and_prose_are_not_signals(source: str) -> None:
    assert bnd.scan_source(source) == frozenset()


def test_signal_is_attributed_to_the_enclosing_qualified_name() -> None:
    source = "class A:\n    def m(self):\n        return self._run_zsh_fallback('x')\n\nY = 'zsh'\n"
    assert bnd.scan_source(source) == frozenset({"A.m", "<module>"})


def test_a_new_signal_in_an_inventoried_file_still_fails_the_guard() -> None:
    inventory = bnd.load_inventory()
    scanned = bnd.scan_tree()
    scanned["src/pysh/core/shell.py"] = scanned["src/pysh/core/shell.py"] | {"PyShell._brand_new"}
    scanned["src/pysh/brand_new.py"] = frozenset({"<module>"})
    assert bnd.unreviewed_signals(inventory, scanned) == {
        "src/pysh/core/shell.py": ["PyShell._brand_new"],
        "src/pysh/brand_new.py": ["<module>"],
    }


def test_the_os_package_launcher_is_the_only_unscanned_shell_surface() -> None:
    # The AST scanner is Python-only; the packaging launcher is inventoried by hand.
    launcher = REPO_ROOT / "packaging" / "wrappers" / "pysh.sh"
    assert launcher.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    assert any(b.production_path == "packaging/wrappers/pysh.sh" for b in bnd.load_inventory())
    shell_files = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "src").rglob("*")
        if p.is_file() and p.suffix in {".sh", ".bash", ".zsh", ".fish"}
    ]
    assert shell_files == []


# --- facts about current behavior the inventory relies on --------------------------------------


def test_automatic_zsh_fallback_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysh.core.shell import PyShell

    monkeypatch.delenv("PYSH_ZSH_FALLBACK", raising=False)
    assert PyShell().zsh_fallback_enabled is False
    monkeypatch.setenv("PYSH_ZSH_FALLBACK", "1")
    assert PyShell().zsh_fallback_enabled is True


def test_direct_script_mode_ignores_the_shebang_and_run_script_delegates() -> None:
    cli = (REPO_ROOT / "src" / "pysh" / "cli.py").read_text(encoding="utf-8")
    assert "native_only=True" in cli
    shell = (REPO_ROOT / "src" / "pysh" / "core" / "shell.py").read_text(encoding="utf-8")
    assert "native_only=False" in shell


# --- documentation and dependency boundary -----------------------------------------------------


def test_policies_and_the_unresolved_decision_are_documented() -> None:
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    for anchor in ("PYSH-MIG-BOUNDARIES", "PYSH-MIG-SHEBANG", "PYSH-MIG-BRIDGE",
                   "PYSH-MIG-AUTOMATIC-FALLBACK"):
        assert f'<a id="{anchor}"></a>' in DOC.read_text(encoding="utf-8")
    for phrase in (
        "is an explicit request by that script for an external interpreter",
        "is **not** a fallback from PySH language semantics",
        "never silently substitutes a different legacy shell",
        "`zsh <cmd>` is an explicit migration and interoperability request",
        "is not used internally as a fallback for ordinary PySH execution",
        "is **not** part of the target PySH 1.0 architecture",
        "(A) remove it, (B) deprecate then remove it, or (C) retain it only as",
        "No option is chosen here",
        "`/bin/sh -c`",
    ):
        assert phrase in text, phrase


def test_slice_two_adds_no_runtime_dependency_and_no_production_import() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []
    for control in ("packaging/debian/control", "packaging/rpm/pysh-shell.spec"):
        for line in (REPO_ROOT / control).read_text(encoding="utf-8").splitlines():
            if re.match(r"(Depends|Pre-Depends|Recommends|Requires|BuildRequires):", line):
                assert not re.search(r"\b(bash|zsh|fish)\b", line), (control, line)
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "src").rglob("*.py")
        if re.search(r"(?m)^\s*(import|from)\s+tests\b|differential", p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
