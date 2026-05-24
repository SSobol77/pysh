# SPDX-License-Identifier: Apache-2.0
#
# Project: PYSH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/__main__.py
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.

from pysh.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
