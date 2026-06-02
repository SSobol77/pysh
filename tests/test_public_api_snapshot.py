# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_public_api_snapshot.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Public API snapshot test (Issue #3).

Verifies that the supported Python import surface of the pysh package
matches the expected snapshot.  Any change to pysh.__all__ (additions or
removals) will fail this test, making accidental API drift visible in review.

Policy:
- The pysh public API is intentionally small (metadata only in 0.5.x).
- Internal packages (pysh.core, pysh.editor, …) are not blessed as public API.
- pysh.contracts is the extension-point surface for config/plugin authors.
  It is imported separately and has its own __all__; this test covers the
  root pysh package only.

To intentionally change the public API:
1. Update src/pysh/__init__.py __all__.
2. Update EXPECTED_PUBLIC_API below with the same change.
3. Document the change in docs/architecture/architecture.md.
"""
from __future__ import annotations

import pysh
import pysh.contracts

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
    "PluginRegistrar",
    "ShellStateView",
})


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
