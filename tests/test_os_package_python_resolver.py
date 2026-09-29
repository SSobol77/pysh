# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_os_package_python_resolver.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for Debian/RPM installed-interpreter selection."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "packaging" / "wrappers" / "pysh.sh"


def _fake_python(path: Path, *, compatible: bool) -> None:
    """Create a candidate that answers the probe and identifies final exec."""
    probe_status = 0 if compatible else 1
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-c\" ]; then\n"
        f"    exit {probe_status}\n"
        "fi\n"
        f"printf 'selected:%s\\n' '{path.name}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_wrapper(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "PYSH_APP_PREFIX": "/nonexistent-test-prefix",
    }
    return subprocess.run(
        ["/bin/sh", str(WRAPPER), "--version"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_compatible_generic_python3_is_preferred(tmp_path: Path) -> None:
    _fake_python(tmp_path / "python3", compatible=True)
    _fake_python(tmp_path / "python3.13", compatible=True)

    result = _run_wrapper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "selected:python3\n"


def test_versioned_python_is_used_when_generic_python_is_too_old(tmp_path: Path) -> None:
    _fake_python(tmp_path / "python3", compatible=False)
    _fake_python(tmp_path / "python3.13", compatible=True)

    result = _run_wrapper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "selected:python3.13\n"


@pytest.mark.parametrize("minor", [13, 14, 15, 16, 99])
def test_compatible_newer_versioned_python_has_no_upper_bound(
    tmp_path: Path, minor: int
) -> None:
    _fake_python(tmp_path / "python3", compatible=False)
    _fake_python(tmp_path / f"python3.{minor}", compatible=True)

    result = _run_wrapper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"selected:python3.{minor}\n"


def test_only_incompatible_python_fails_with_stable_diagnostic(tmp_path: Path) -> None:
    _fake_python(tmp_path / "python3", compatible=False)
    _fake_python(tmp_path / "python3.12", compatible=False)

    result = _run_wrapper(tmp_path)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "PySH requires CPython >= 3.13" in result.stderr


def test_candidate_name_is_not_trusted_without_runtime_probe(tmp_path: Path) -> None:
    _fake_python(tmp_path / "python3.99", compatible=False)

    result = _run_wrapper(tmp_path)

    assert result.returncode == 1
    assert "PySH requires CPython >= 3.13" in result.stderr


def test_wrapper_probe_uses_cpython_semantic_version_floor() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert 'sys.implementation.name == "cpython"' in text
    assert "sys.version_info >= (3, 13)" in text
    assert "== (3, 13)" not in text
    assert "exec /usr/bin/python3" not in text
