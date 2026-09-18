# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/__main__.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""``python -m pysh`` entry point."""
from __future__ import annotations

from pysh.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
