# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fuzz_atheris_smoke.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 2: one bounded coverage-guided smoke (engine-specific, Linux x86_64)."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("atheris") is None,
    reason="Atheris is the Linux x86_64 'fuzz' dependency group; portable replay tests cover other platforms",
)


def test_bounded_engine_run_finds_nothing_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, str(REPO / "scripts" / "fuzz_atheris.py"),
         "--target", "split_chain", "--max-total-time", "2"],
        capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "fuzz: no findings" in done.stdout
    assert list(tmp_path.iterdir()) == []
