# SPDX-License-Identifier: Apache-2.0
#
# Project: PYSH - Python-first interactive shell for Debian and Unix-like systems
# File: pysh/tests/test_shell.py
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from pysh.shell import PyShell


def test_python_expression_executes() -> None:
    shell = PyShell()
    assert shell.execute(":1 + 1") == 0


def test_python_assignment_executes() -> None:
    shell = PyShell()
    assert shell.execute(":x = 42") == 0
    assert shell.namespace["x"] == 42


def test_invalid_python_returns_error() -> None:
    shell = PyShell()
    assert shell.execute(":unknown_variable") == 1
