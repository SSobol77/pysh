# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_cli.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the pysh CLI entry point."""
from __future__ import annotations

import pytest

from pysh import __version__
from pysh.cli import main


def test_version_flag_prints_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_short_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_dash_c_runs_command(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo cli-runs"])
    assert status == 0
    captured = capfd.readouterr()
    assert "cli-runs" in captured.out
