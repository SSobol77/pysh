# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/migration/__init__.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Python-first shell script migration analysis for PySH."""
from __future__ import annotations

from pysh.migration.script import (
    MigrationFinding,
    MigrationReport,
    Severity,
    analyze_migration,
    analyze_migration_file,
    render_migration_report,
)

__all__ = [
    "MigrationFinding",
    "MigrationReport",
    "Severity",
    "analyze_migration",
    "analyze_migration_file",
    "render_migration_report",
]
