# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_stable_api.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Stable public API, embedding, and deprecation tests for Issue #45."""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import warnings
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

import pysh
import pysh.api as api
from pysh.plugins.isolated.manifest import (
    ISOLATED_MANIFEST_VERSION,
    ISOLATED_PROTOCOL_VERSION,
)
from pysh.plugins.isolated.protocol import IPC_PROTOCOL_VERSION

_FORBIDDEN_PUBLIC_TYPE_PREFIXES = (
    "pysh.core",
    "pysh.config",
    "pysh.editor",
    "pysh.diagnostics",
    "pysh.plugins.models",
    "pysh.plugins.isolated",
)


def _public_callables() -> dict[str, object]:
    callables: dict[str, object] = {"ShellSession": api.ShellSession}
    for export_name in api.__all__:
        exported = getattr(api, export_name)
        if not inspect.isclass(exported):
            continue
        for member_name, member in vars(exported).items():
            if member_name.startswith("_") and member_name not in {"__enter__", "__exit__"}:
                continue
            if isinstance(member, property):
                assert member.fget is not None
                callables[f"{export_name}.{member_name}"] = member.fget
            elif callable(member):
                callables[f"{export_name}.{member_name}"] = member
    return callables


def _walk_annotation(annotation: object) -> tuple[object, ...]:
    origin = get_origin(annotation)
    if origin is None:
        return (annotation,)
    nested: list[object] = [origin]
    for argument in get_args(annotation):
        nested.extend(_walk_annotation(argument))
    return tuple(nested)


def test_public_signatures_do_not_leak_internal_types() -> None:
    """Every stable annotation must resolve only to public or stdlib types."""
    leaks: list[str] = []
    for qualified_name, callable_object in _public_callables().items():
        for annotation in get_type_hints(callable_object).values():
            for item in _walk_annotation(annotation):
                module_name = getattr(item, "__module__", "")
                if module_name.startswith(_FORBIDDEN_PUBLIC_TYPE_PREFIXES):
                    leaks.append(f"{qualified_name}: {module_name}.{getattr(item, '__name__', '')}")
    assert not leaks, "Internal types leaked through pysh.api:\n" + "\n".join(leaks)


def test_api_import_is_side_effect_light_in_clean_process(tmp_path: Path) -> None:
    """Importing pysh.api must not initialize runtime/config or create files."""
    code = """
import json
import pathlib
import sys
import pysh.api

forbidden = [
    name for name in sorted(sys.modules)
    if name.startswith((
        "pysh.core",
        "pysh.config",
        "pysh.editor",
        "pysh.diagnostics",
        "pysh.plugins.isolated",
    ))
]
print(json.dumps({
    "forbidden": forbidden,
    "subprocess_loaded": "subprocess" in sys.modules,
    "home_entries": sorted(path.name for path in pathlib.Path.home().iterdir()),
}))
"""
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"forbidden": [], "subprocess_loaded": false, "home_entries": []}'
    )
    assert result.stderr == ""


def test_embedding_lifecycle_and_command_status(capfd: pytest.CaptureFixture[str]) -> None:
    """A session executes commands, returns statuses, and closes explicitly."""
    session = api.ShellSession()
    assert not session.closed
    assert session.execute("echo embedded") == 0
    assert capfd.readouterr().out == "embedded\n"
    assert session.execute("definitely-not-an-issue45-command") == 127
    assert capfd.readouterr().err.endswith(": command not found\n")

    session.close()
    assert session.closed
    session.close()
    with pytest.raises(RuntimeError, match="ShellSession is closed"):
        session.execute("echo after-close")


def test_embedding_context_manager_closes_session() -> None:
    """Context-manager exit deterministically closes the session."""
    with api.ShellSession() as session:
        assert session.execute("") == 0
        assert not session.closed
    assert session.closed


def test_embedding_exit_is_status_not_process_exit() -> None:
    """The exit builtin returns its status and closes only the session."""
    session = api.ShellSession()
    assert session.execute("exit 7") == 7
    assert session.closed


def test_embedding_system_exit_is_status_not_process_exit() -> None:
    """Embedded Python SystemExit cannot escape into the host application."""
    session = api.ShellSession()
    assert session.execute("py raise SystemExit(9)") == 9
    assert session.closed


def test_embedding_runs_native_script(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    """run_script executes native PySH input and returns its final status."""
    script = tmp_path / "embedded.pysh"
    script.write_text("echo script-ok\nfalse\n", encoding="utf-8")

    with api.ShellSession() as session:
        assert session.run_script(script, ("one", "two")) == 1
    assert capfd.readouterr().out == "script-ok\n"


def test_embedding_does_not_load_user_startup(tmp_path: Path) -> None:
    """Embedding never executes HOME startup code implicitly."""
    marker = tmp_path / "startup-ran"
    (tmp_path / ".pyshrc.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('unsafe', encoding='utf-8')\n",
        encoding="utf-8",
    )
    code = "from pysh.api import ShellSession; print(ShellSession().execute('echo safe'))"
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "safe\n0\n"
    assert not marker.exists()


def test_legacy_shell_symbol_emits_precise_deprecation_warning() -> None:
    """The genuine legacy import warns at the external caller location."""
    sys.modules.pop("pysh.shell", None)
    with pytest.warns(DeprecationWarning, match="will not be removed before PySH 1.2.0") as records:
        from pysh.shell import PyShell

    assert PyShell.__module__ == "pysh.core.shell"
    assert Path(records[0].filename) == Path(__file__)


def test_importing_legacy_module_without_symbol_access_does_not_warn() -> None:
    """Unrelated module import must not emit the symbol deprecation warning."""
    sys.modules.pop("pysh.shell", None)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        __import__("pysh.shell")
    assert not records


def test_version_domains_remain_independent() -> None:
    """Package, Plugin API, manifest, and IPC versions are distinct domains."""
    assert pysh.__version__ == "0.9.0"
    assert api.PLUGIN_API_VERSION == (1, 0)
    assert ISOLATED_MANIFEST_VERSION == 1
    assert ISOLATED_PROTOCOL_VERSION == 1
    assert IPC_PROTOCOL_VERSION == 1
    assert isinstance(api.PLUGIN_API_VERSION, tuple)
    assert isinstance(ISOLATED_MANIFEST_VERSION, int)
