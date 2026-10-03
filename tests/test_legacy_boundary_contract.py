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


def test_shipped_inventory_is_valid_and_non_empty() -> None:
    inventory = bnd.load_inventory()
    # The automatic-fallback and migration-bridge categories exist in the schema but stay empty.
    assert {b.category for b in inventory} <= bnd.CATEGORIES - {bnd.AUTOMATIC_CATEGORY}
    assert not any(b.automatic for b in inventory)
    assert all(b.policy and b.trigger and b.notes for b in inventory)


def test_no_automatic_legacy_fallback_boundary_exists() -> None:
    inventory = bnd.load_inventory()
    assert _pairs(inventory, "AUTOMATIC_LEGACY_FALLBACK") == set()
    assert bnd.MAX_AUTOMATIC_ENTRIES == 0
    assert RAW["boundaries"] and all(b["automatic"] is False for b in RAW["boundaries"])


def test_command_substitution_is_no_longer_a_legacy_boundary() -> None:
    inventory = bnd.load_inventory()
    assert all(b.production_path != "src/pysh/parsing/expansion.py" for b in inventory)
    assert "src/pysh/parsing/expansion.py" not in bnd.scan_tree()


def test_no_production_migration_bridge_boundary_exists() -> None:
    inventory = bnd.load_inventory()
    assert _pairs(inventory, "EXPLICIT_MIGRATION_BRIDGE") == set()
    assert {b.category for b in inventory} == {
        "EXPLICIT_SHEBANG_DELEGATION", "PYSH_NATIVE", "BUILD_OR_TEST_TOOLING", "DOCUMENTATION_ONLY",
    }


def test_shebang_delegation_is_the_only_legacy_interpreter_boundary() -> None:
    inventory = bnd.load_inventory()
    shebang = _pairs(inventory, "EXPLICIT_SHEBANG_DELEGATION")
    assert ("src/pysh/script_runner.py", "ScriptRunner.run") in shebang
    assert ("src/pysh/script_runner.py", "ScriptRunner._run_interpreter_script") in shebang
    assert {path for path, _ in shebang} == {"src/pysh/script_runner.py"}


def test_inventory_has_no_stale_python_entries() -> None:
    assert bnd.stale_entries(bnd.load_inventory(), bnd.scan_tree()) == []


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
        (lambda d: d["boundaries"][0].update(category="AUTOMATIC_LEGACY_FALLBACK", automatic=True),
         "permits no AUTOMATIC_LEGACY_FALLBACK"),
        (lambda d: d["boundaries"][0].update(semantic_authority=True), "semantic authority"),
        (lambda d: d["boundaries"][0].update(product_dependency=True), "product dependency"),
        (lambda d: d["boundaries"][0].update(automatic="yes"), "boolean"),
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


def test_production_has_no_automatic_fallback_signal_of_any_kind() -> None:
    assert bnd.scan_forbidden() == {}, "an automatic legacy-shell fallback was reintroduced"


def test_production_has_no_zsh_bridge_reference_of_any_kind() -> None:
    assert bnd.scan_bridge_references() == {}, "the removed Zsh bridge was reintroduced"
    assert not (REPO_ROOT / "src" / "pysh" / "compat" / "zsh_bridge.py").exists()


def test_no_legacy_shell_is_a_builtin_or_receives_login_flags() -> None:
    from pysh.contracts.builtins import BUILTIN_NAMES

    assert not BUILTIN_NAMES & {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh"}
    flagged = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(f'"{flag}"' in text or f"'{flag}'" in text for flag in bnd.LEGACY_FLAG_BUNDLES):
            flagged.append(path.name)
    assert flagged == []


@pytest.mark.parametrize(
    "source",
    [
        "def _run_zsh_fallback(self, c):\n    return 1\n",
        "def _run_legacy_fallback(c):\n    return 1\n",
        "class A:\n    def m(self):\n        return self.zsh_fallback_enabled\n",
        "def f(env):\n    return env.get('PYSH_ZSH_FALLBACK')\n",
        "def f():\n    return 'zsh_fallback'\n",
        "bash_fallback = True\n",
        "def f(zsh_fallback=False):\n    return 1\n",
    ],
)
def test_reintroduced_fallback_machinery_is_detected(source: str) -> None:
    assert bnd.forbidden_fallback_signals(source)


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    return 'fallback'\n",
        "def retry_with_fallback_encoding(x):\n    return x\n",
        "def f(self):\n    return self._builtin_zsh([])\n",
        '"""Documents the removed zsh_fallback feature."""\n',
        "# zsh_fallback is gone\nx = 1\n",
    ],
)
def test_ordinary_fallback_wording_and_the_explicit_builtin_are_not_flagged(source: str) -> None:
    assert bnd.forbidden_fallback_signals(source) == frozenset()


@pytest.mark.parametrize(
    "source",
    [
        "def f(self, c):\n    return self._run_zsh_command(c)\n",
        "def _builtin_zsh(self, args):\n    return 0\n",
        "from pysh.compat.zsh_bridge import ZshBridge\n",
        "def f():\n    return ZshBridge()\n",
        "def f(self):\n    return self.zsh_bridge.execute('x')\n",
    ],
)
def test_bridge_reference_detection(source: str) -> None:
    assert bnd.bridge_references(source)


def test_production_tree_has_no_unreviewed_legacy_execution_signal() -> None:
    drift = bnd.unreviewed_signals(bnd.load_inventory(), bnd.scan_tree())
    assert drift == {}, f"unreviewed legacy-execution signals (inventory them or remove): {drift}"


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\ndef f(c):\n    subprocess.run(['bash', '-c', c])\n",
        "import subprocess\ndef f(c):\n    subprocess.Popen(['/bin/zsh', c])\n",
        "import subprocess\ndef f(c):\n    subprocess.run(['fish', '-c', c])\n",
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
    scanned["src/pysh/script_runner.py"] = scanned["src/pysh/script_runner.py"] | {"ScriptRunner._brand_new"}
    scanned["src/pysh/brand_new.py"] = frozenset({"<module>"})
    assert bnd.unreviewed_signals(inventory, scanned) == {
        "src/pysh/script_runner.py": ["ScriptRunner._brand_new"],
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


def test_shell_has_no_fallback_state_even_if_the_old_variable_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pysh.core.shell import PyShell

    monkeypatch.setenv("PYSH_ZSH_FALLBACK", "1")
    shell = PyShell()
    assert not hasattr(shell, "zsh_fallback_enabled")
    assert "zsh_fallback" not in PyShell.BUILTINS
    assert "zsh" not in PyShell.BUILTINS  # no dedicated bridge builtin either


def test_direct_script_mode_ignores_the_shebang_and_run_script_delegates() -> None:
    cli = (REPO_ROOT / "src" / "pysh" / "cli.py").read_text(encoding="utf-8")
    assert "native_only=True" in cli
    shell = (REPO_ROOT / "src" / "pysh" / "core" / "shell.py").read_text(encoding="utf-8")
    assert "native_only=False" in shell


# --- documentation and dependency boundary -----------------------------------------------------


def test_policies_and_the_fallback_removal_are_documented() -> None:
    raw = DOC.read_text(encoding="utf-8")
    text = " ".join(raw.split())
    for anchor in ("PYSH-MIG-BOUNDARIES", "PYSH-MIG-SHEBANG", "PYSH-MIG-BRIDGE",
                   "PYSH-MIG-AUTOMATIC-FALLBACK"):
        assert f'<a id="{anchor}"></a>' in raw
    for phrase in (
        "is an explicit request by that script for an external interpreter",
        "is **not** a fallback from PySH language semantics",
        "never silently substitutes a different legacy shell",
        "PySH has no dedicated `zsh` builtin and no `ZshBridge`",
        "ordinary program name",
        "injects no flags",
        "automatic fallback from PySH language execution to Bash, Zsh or Fish is not part of the PySH 1.0 architecture, and it has been removed",
        "`PYSH_ZSH_FALLBACK` has no meaning",
        "The `zsh_fallback` builtin does not exist",
        "No external legacy shell is required for ordinary PySH operation",
        "no longer a legacy boundary",
    ):
        assert phrase in text, phrase
    for stale in ("(A) remove it", "No option is chosen here", "technical debt. Before PySH 1.0"):
        assert stale not in text, stale


def test_user_facing_docs_no_longer_instruct_enabling_the_removed_feature() -> None:
    enable = re.compile(r"zsh_fallback\s+(on|off)\b|PYSH_ZSH_FALLBACK=1")
    offenders = []
    for path in [REPO_ROOT / "README.md", *(REPO_ROOT / "docs").rglob("*.md")]:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith("docs/issues/"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if enable.search(line) and "removed" not in line and "no effect" not in line and "unknown command" not in line:
                offenders.append(f"{relative}:{number}")
    assert offenders == []


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
