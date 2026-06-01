# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/system_info.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Compact system-summary helper for the PySH startup banner.

Uses only the Python standard library.  All detection is best-effort:
missing data is omitted gracefully so the banner never crashes PySH.

Sources:
* ``/etc/os-release``  — OS name and version on Linux/Debian systems.
* ``platform.release()`` — kernel release string.
* ``platform.machine()`` — CPU architecture.
* ``os.sysconf`` — physical RAM (``SC_PAGE_SIZE`` × ``SC_PHYS_PAGES``).
"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SystemSummary:
    """Compact host system metadata for the PySH startup banner."""

    os_name: str
    os_version: str
    kernel: str
    machine: str
    ram_gib: int | None

    def format_compact(self) -> str:
        """Return a single compact banner line.

        Examples::

            "System: Debian GNU/Linux 13 | Kernel 6.1.0 | x86_64 | RAM 32 GiB"
            "System: Linux | Kernel 6.1.0 | aarch64"
        """
        os_part = self.os_name
        if self.os_version:
            os_part = f"{self.os_name} {self.os_version}"
        parts = [f"System: {os_part}", f"Kernel {self.kernel}", self.machine]
        if self.ram_gib is not None:
            parts.append(f"RAM {self.ram_gib} GiB")
        return " | ".join(parts)


def _read_os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into a key→value mapping.  Never raises."""
    result: dict[str, str] = {}
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"')
    return result


def _ram_gib() -> int | None:
    """Return physical RAM in GiB rounded to nearest integer, or ``None``."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and phys_pages > 0:
            bytes_total = page_size * phys_pages
            return round(bytes_total / (1024 ** 3))
    except (AttributeError, ValueError, OSError):
        pass
    return None


def get_system_summary() -> SystemSummary:
    """Return host system summary for the PySH startup banner.

    Detection is entirely best-effort.  Failures produce safe fallback
    values so the banner never crashes PySH.
    """
    release = _read_os_release()
    os_name = release.get("NAME") or release.get("ID") or platform.system()
    os_version = release.get("VERSION_ID") or release.get("VERSION") or ""
    kernel = platform.release()
    machine = platform.machine()
    ram = _ram_gib()
    return SystemSummary(
        os_name=os_name,
        os_version=os_version,
        kernel=kernel,
        machine=machine,
        ram_gib=ram,
    )
