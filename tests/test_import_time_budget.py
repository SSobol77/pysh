# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_import_time_budget.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Import-time cold-start budget test (Issue #3).

Measures the time to import `pysh` in a clean subprocess (no warm caches,
no contamination from other modules already loaded in the test process).

Purpose:
- Guard against heavy imports, terminal I/O, config reads, git probing,
  or subprocess calls added to package initializers.
- pysh.__init__ is intentionally minimal (metadata only).  A bare
  `import pysh` must not trigger the shell runtime.

Budget:
- HARD_BUDGET_S = 2.0 s  — fails the test; clear regression.
- The subprocess creation overhead alone (~50–150 ms on modern hardware)
  dominates the measurement.  Typical measured import time for `pysh`
  itself is < 5 ms; the remaining budget covers interpreter startup,
  filesystem I/O, and conservative CI headroom.

Stability:
- The test is run once per suite invocation.
- No sleep or retry loops.
- The budget is conservative enough to survive slow CI environments.
"""
from __future__ import annotations

import subprocess
import sys

# Conservative CI-safe budget.  Typical subprocess overhead: 50–150 ms.
# Typical pysh.__init__ import time: < 5 ms.
# Budget includes 10× headroom for cold-filesystem CI environments.
HARD_BUDGET_S: float = 2.0

# Code executed in the child process.
_MEASURE_CODE = (
    "import time; "
    "_t = time.perf_counter(); "
    "import pysh; "
    "print(f'{time.perf_counter() - _t:.6f}')"
)


def test_pysh_cold_import_within_budget() -> None:
    """Cold import of pysh must complete within HARD_BUDGET_S seconds.

    Failure indicates that a package initializer has begun performing
    heavy work (loading curses, readline, pygments, subprocess, or similar)
    during a bare `import pysh`.  Fix the initializer, not the budget.
    """
    result = subprocess.run(
        [sys.executable, "-c", _MEASURE_CODE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"pysh import subprocess failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    elapsed = float(result.stdout.strip())
    assert elapsed < HARD_BUDGET_S, (
        f"Cold import of pysh took {elapsed:.3f}s, exceeding budget {HARD_BUDGET_S}s.\n"
        "A package initializer is likely performing heavy work at import time.\n"
        "Profile with: python -X importtime -c 'import pysh'"
    )


def test_pysh_contracts_cold_import_within_budget() -> None:
    """Cold import of pysh.contracts must also be fast.

    pysh.contracts contains only Protocol definitions and standard-library
    imports.  It must never pull in heavy runtime machinery.
    """
    code = (
        "import time; "
        "_t = time.perf_counter(); "
        "import pysh.contracts; "
        "print(f'{time.perf_counter() - _t:.6f}')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"pysh.contracts import subprocess failed:\n{result.stderr}"
    )
    elapsed = float(result.stdout.strip())
    assert elapsed < HARD_BUDGET_S, (
        f"Cold import of pysh.contracts took {elapsed:.3f}s, "
        f"exceeding budget {HARD_BUDGET_S}s."
    )
