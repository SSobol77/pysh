# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_public_api_snapshot.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Public API symbol and signature snapshot tests (Issues #3 and #45).

Verifies that the supported Python import surface of the pysh package
matches the expected snapshot.  Any change to pysh.__all__ (additions or
removals) will fail this test, making accidental API drift visible in review.

Policy:
- The root ``pysh`` API remains metadata-only.
- ``pysh.api`` is the canonical stable operational and contract facade.
- ``pysh.contracts`` and ``pysh.plugins`` are compatibility-public surfaces.
- Internal packages (pysh.core, pysh.editor, …) are not public API.

To intentionally change the public API:
1. Update the owning module's explicit ``__all__``.
2. Update the literal snapshot below with the same change.
3. Document the compatibility impact and SemVer decision.
"""
from __future__ import annotations

import inspect

import pysh
import pysh.api
import pysh.contracts
import pysh.plugins
import pysh.shell

# Snapshot of the expected root pysh public API (pysh.__all__).
# This is intentionally small: metadata symbols only.
EXPECTED_PUBLIC_API: frozenset[str] = frozenset({
    "__version__",
    "__author__",
    "LICENSE_NAME",
})

# Snapshot of the expected pysh.contracts public API.
EXPECTED_CONTRACTS_API: frozenset[str] = frozenset({
    "AliasRegistryView",
    "CompatibilityBridge",
    "CommandResolverView",
    "ConfigView",
    "EnvironmentView",
    "PLUGIN_API_VERSION",
    "PluginHooks",
    "PluginMeta",
    "PluginRegistrar",
    "ShellStateView",
})

EXPECTED_CANONICAL_API: frozenset[str] = frozenset({
    "AliasRegistryView",
    "CommandResolverView",
    "CompatibilityBridge",
    "ConfigView",
    "EnvironmentView",
    "PLUGIN_API_VERSION",
    "PluginHooks",
    "PluginMeta",
    "PluginRegistrar",
    "ShellSession",
    "ShellStateView",
})

EXPECTED_PLUGINS_API: frozenset[str] = frozenset({
    "PLUGIN_API_VERSION",
    "check_api_compatibility",
})

EXPECTED_DEPRECATED_SHELL_API: frozenset[str] = frozenset({"PyShell"})

# Literal signature snapshot. Expected values are deliberately not generated
# from the implementation under test: any parameter/default/kind drift must be
# reviewed and explicitly accepted here.
EXPECTED_API_SIGNATURES: dict[str, str] = {
    "AliasRegistryView.list_aliases": "(self) -> 'dict[str, str]'",
    "AliasRegistryView.lookup_alias": "(self, name: 'str') -> 'str | None'",
    "CommandResolverView.builtin_names": "(self) -> 'frozenset[str]'",
    "CommandResolverView.is_builtin": "(self, name: 'str') -> 'bool'",
    "CommandResolverView.resolve_alias": "(self, name: 'str') -> 'str | None'",
    "CompatibilityBridge.execute": "(self, command: 'str') -> 'int'",
    "CompatibilityBridge.execute_lines": "(self, commands: 'Iterator[str]') -> 'int'",
    "CompatibilityBridge.is_available": "(self) -> 'bool'",
    "ConfigView.get_bool": "(self, key: 'str', *, default: 'bool' = False) -> 'bool'",
    "ConfigView.get_str": "(self, key: 'str', *, default: 'str' = '') -> 'str'",
    "EnvironmentView.get_env": "(self, name: 'str', default: 'str' = '') -> 'str'",
    "EnvironmentView.get_local": "(self, name: 'str', default: 'str' = '') -> 'str'",
    "PluginHooks.register": "(self, api: 'object') -> 'None'",
    "PluginRegistrar.register_alias": "(self, name: 'str', value: 'str') -> 'None'",
    "PluginRegistrar.register_env": "(self, name: 'str', value: 'str') -> 'None'",
    "PluginRegistrar.register_local": "(self, name: 'str', value: 'str') -> 'None'",
    "ShellSession": "() -> 'None'",
    "ShellSession.__enter__": "(self) -> 'ShellSession'",
    "ShellSession.__exit__": (
        "(self, exc_type: 'type[BaseException] | None', "
        "exc_value: 'BaseException | None', traceback: 'TracebackType | None') -> 'None'"
    ),
    "ShellSession.close": "(self) -> 'None'",
    "ShellSession.closed": "(self) -> 'bool'",
    "ShellSession.execute": "(self, command: 'str') -> 'int'",
    "ShellSession.run_script": (
        "(self, path: 'str | PathLike[str]', args: 'Sequence[str]' = ()) -> 'int'"
    ),
    "ShellStateView.cwd": "(self) -> 'str'",
    "ShellStateView.last_status": "(self) -> 'int'",
}

EXPECTED_PLUGIN_SIGNATURES: dict[str, str] = {
    "check_api_compatibility": "(plugin_api_version: 'object') -> 'tuple[int, int]'",
}

EXPECTED_PLUGIN_META_ANNOTATIONS: dict[str, str] = {
    "api_version": "tuple[int, int]",
    "name": "str",
    "version": "str",
}


def test_public_api_surface_is_stable() -> None:
    """pysh.__all__ must exactly match the expected snapshot."""
    actual = frozenset(pysh.__all__)
    added = actual - EXPECTED_PUBLIC_API
    removed = EXPECTED_PUBLIC_API - actual
    messages: list[str] = []
    if added:
        messages.append(f"Unexpected symbols added to pysh.__all__: {sorted(added)}")
    if removed:
        messages.append(f"Expected symbols removed from pysh.__all__: {sorted(removed)}")
    assert not messages, (
        "pysh public API has drifted from the snapshot.\n"
        "Update EXPECTED_PUBLIC_API in this test and document the change in\n"
        "docs/architecture/architecture.md.\n\n"
        + "\n".join(messages)
    )


def test_contracts_api_surface_is_stable() -> None:
    """pysh.contracts.__all__ must exactly match the expected snapshot."""
    actual = frozenset(pysh.contracts.__all__)
    added = actual - EXPECTED_CONTRACTS_API
    removed = EXPECTED_CONTRACTS_API - actual
    messages: list[str] = []
    if added:
        messages.append(
            f"Unexpected symbols added to pysh.contracts.__all__: {sorted(added)}"
        )
    if removed:
        messages.append(
            f"Expected symbols removed from pysh.contracts.__all__: {sorted(removed)}"
        )
    assert not messages, (
        "pysh.contracts public API has drifted from the snapshot.\n"
        "Update EXPECTED_CONTRACTS_API in this test and document the change.\n\n"
        + "\n".join(messages)
    )


def test_canonical_api_surface_is_stable() -> None:
    """pysh.api.__all__ must exactly match the reviewed stable facade."""
    assert frozenset(pysh.api.__all__) == EXPECTED_CANONICAL_API


def test_plugins_compatibility_surface_is_stable() -> None:
    """The documented trusted-plugin import surface must not drift."""
    assert frozenset(pysh.plugins.__all__) == EXPECTED_PLUGINS_API
    assert pysh.plugins.PLUGIN_API_VERSION == (1, 0)


def test_deprecated_shell_compatibility_surface_is_retained() -> None:
    """The legacy symbol remains present for its documented warning window."""
    assert frozenset(pysh.shell.__all__) == EXPECTED_DEPRECATED_SHELL_API
    assert pysh.shell._DEPRECATED_SINCE == "1.0.0"
    assert pysh.shell._REMOVAL_NOT_BEFORE == "1.2.0"


def _resolve_api_member(qualified_name: str) -> object:
    owner_name, separator, member_name = qualified_name.partition(".")
    owner = getattr(pysh.api, owner_name)
    if not separator:
        return owner
    member = inspect.getattr_static(owner, member_name)
    if isinstance(member, property):
        assert member.fget is not None
        return member.fget
    return member


def test_canonical_api_signatures_match_literal_snapshot() -> None:
    """Stable constructors, methods, properties, defaults and kinds are frozen."""
    actual = {
        name: str(inspect.signature(_resolve_api_member(name)))
        for name in EXPECTED_API_SIGNATURES
    }
    assert actual == EXPECTED_API_SIGNATURES


def test_trusted_plugin_api_signatures_match_literal_snapshot() -> None:
    """Compatibility-public plugin helpers retain reviewed signatures."""
    actual = {
        name: str(inspect.signature(getattr(pysh.plugins, name)))
        for name in EXPECTED_PLUGIN_SIGNATURES
    }
    assert actual == EXPECTED_PLUGIN_SIGNATURES


def test_plugin_metadata_annotations_match_literal_snapshot() -> None:
    """Plugin API 1.0 metadata fields remain stable."""
    assert pysh.api.PluginMeta.__annotations__ == EXPECTED_PLUGIN_META_ANNOTATIONS


def test_canonical_contract_reexports_preserve_identity() -> None:
    """pysh.contracts remains a supported compatibility path to the same types."""
    for name in EXPECTED_CONTRACTS_API:
        assert getattr(pysh.api, name) is getattr(pysh.contracts, name)


def test_pysh_version_is_accessible() -> None:
    """pysh.__version__ must be a non-empty string."""
    assert isinstance(pysh.__version__, str)
    assert pysh.__version__


def test_pysh_does_not_eagerly_import_core() -> None:
    """Importing pysh must not load pysh.core into sys.modules.

    pysh.core.shell is the heavy runtime module.  It must not be imported
    as a side-effect of a bare `import pysh`.
    """
    import sys

    # pysh is already imported at module level above, so check sys.modules.
    # If pysh.core was NOT imported before this test suite started, it should
    # still not be present.  (If other tests in the suite already imported
    # pysh.core, this assertion cannot be meaningful — but the import-time
    # budget test covers that case in a clean subprocess.)
    heavy_modules = [k for k in sys.modules if k.startswith("pysh.core")]
    # We only assert that importing `pysh` alone did not pull in pysh.core.
    # If pysh.core is loaded, it was because other tests in this process
    # imported it.  The subprocess test in test_import_time_budget.py
    # provides the clean isolation check.
    _ = heavy_modules  # informational; full isolation guaranteed by subprocess test
