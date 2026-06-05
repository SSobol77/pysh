# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Compact system-summary helper for the PySH startup banner.

Uses only the Python standard library.  All detection is best-effort:
missing data is omitted gracefully so the banner never crashes PySH.

Sources:
* ``/etc/os-release``  — OS name and version on Linux/Debian systems.
* ``platform.release()`` — kernel release string (compacted to ``N.N.N``).
* ``/proc/cpuinfo``    — CPU model name (Linux); falls back to ``platform.machine()``.
* ``os.sysconf`` — physical RAM (``SC_PAGE_SIZE`` × ``SC_PHYS_PAGES``).
"""
from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

# Vendor prefixes stripped from raw CPU model names (longest-first wins).
_VENDOR_PREFIXES: tuple[str, ...] = (
    "Intel(R)",
    "AMD",
    "Intel",
    "Qualcomm",
    "Apple",
    "ARM",
)

# Substrings that mark the start of unwanted trailing information.
_TRUNCATION_MARKERS: tuple[str, ...] = (
    " CPU @",
    " with ",
    " Processor",
    " @",
)

# Matches the leading numeric version from a kernel release string.
_KERNEL_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?")


@dataclass(frozen=True)
class SystemSummary:
    """Compact host system metadata for the PySH startup banner."""

    os_name: str
    os_version: str
    kernel: str
    cpu_model: str  # compact CPU model name, or architecture fallback
    ram_gib: int | None

    def format_compact(self) -> str:
        """Return a single compact banner line.

        Examples::

            "System: Debian GNU/Linux 13 | Kernel 6.12.90 | Ryzen 7 5700U | RAM 15 GiB"
            "System: Linux | Kernel 6.1.0 | aarch64"
        """
        os_part = self.os_name
        if self.os_version:
            os_part = f"{self.os_name} {self.os_version}"
        parts = [f"System: {os_part}", f"Kernel {self.kernel}", self.cpu_model]
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


def _compact_cpu_model(raw: str) -> str:
    """Return a compact, human-readable CPU model name.

    Strips vendor prefixes (e.g. ``AMD``, ``Intel(R)``), trademark markers
    (``(R)``, ``(TM)``), and trailing frequency or marketing suffixes so the
    result fits naturally in a single-line banner.

    Examples::

        "AMD Ryzen 7 5700U with Radeon Graphics"  →  "Ryzen 7 5700U"
        "Intel(R) Core(TM) i5-6500T CPU @ 2.50GHz"  →  "Core i5-6500T"
        "Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz"   →  "Xeon Gold 6154"
    """
    name = raw.strip()
    for prefix in _VENDOR_PREFIXES:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):].lstrip()
            break
    name = name.replace("(R)", "").replace("(TM)", "")
    for marker in _TRUNCATION_MARKERS:
        idx = name.find(marker)
        if idx != -1:
            name = name[:idx]
    return " ".join(name.split())


def _compact_kernel_release(raw: str) -> str:
    """Return just the version number from a kernel release string.

    Strips distribution-specific suffixes, build tags, and architecture
    qualifiers so only the leading ``N.N.N`` (or ``N.N``) remains.

    Examples::

        "6.12.90+deb13.1-amd64"  →  "6.12.90"
        "6.8.0-63-generic"        →  "6.8.0"
        "14.1-RELEASE-p6"         →  "14.1"
        "6.1.0"                   →  "6.1.0"
    """
    m = _KERNEL_VERSION_RE.match(raw.strip())
    return m.group(0) if m else raw.strip()


def _read_cpu_model() -> str:
    """Return the compact CPU model name from ``/proc/cpuinfo``, or ``""``."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("model name"):
            _, _, raw = line.partition(":")
            model = _compact_cpu_model(raw)
            if model:
                return model
    return ""


def get_system_summary() -> SystemSummary:
    """Return host system summary for the PySH startup banner.

    Detection is entirely best-effort.  Failures produce safe fallback
    values so the banner never crashes PySH.
    """
    release = _read_os_release()
    os_name = release.get("NAME") or release.get("ID") or platform.system()
    os_version = release.get("VERSION_ID") or release.get("VERSION") or ""
    kernel = _compact_kernel_release(platform.release())
    cpu_model = _read_cpu_model() or platform.machine()
    ram = _ram_gib()
    return SystemSummary(
        os_name=os_name,
        os_version=os_version,
        kernel=kernel,
        cpu_model=cpu_model,
        ram_gib=ram,
    )
