# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_system_info.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the system_info compact banner helper."""
from __future__ import annotations

import pytest

from pysh.diagnostics.system_info import (
    SystemSummary,
    _compact_cpu_model,
    _compact_kernel_release,
    _read_cpu_model,
    get_system_summary,
)


class TestSystemSummary:
    def test_format_compact_full(self) -> None:
        s = SystemSummary(
            os_name="Debian GNU/Linux",
            os_version="13",
            kernel="6.1.0",
            cpu_model="Ryzen 7 5700U",
            ram_gib=32,
        )
        result = s.format_compact()
        assert result.startswith("System: Debian GNU/Linux 13")
        assert "Kernel 6.1.0" in result
        assert "Ryzen 7 5700U" in result
        assert "RAM 32 GiB" in result

    def test_format_compact_no_ram(self) -> None:
        s = SystemSummary(
            os_name="Linux",
            os_version="",
            kernel="6.0.0",
            cpu_model="aarch64",
            ram_gib=None,
        )
        result = s.format_compact()
        assert "System: Linux" in result
        assert "Kernel 6.0.0" in result
        assert "aarch64" in result
        assert "RAM" not in result

    def test_format_compact_no_version(self) -> None:
        s = SystemSummary(
            os_name="Alpine",
            os_version="",
            kernel="5.15.0",
            cpu_model="x86_64",
            ram_gib=8,
        )
        result = s.format_compact()
        assert "System: Alpine" in result
        assert "Alpine " not in result.split("|")[0].replace("System: Alpine", "")

    def test_format_compact_separator(self) -> None:
        s = SystemSummary(
            os_name="Linux",
            os_version="",
            kernel="6.0",
            cpu_model="x86_64",
            ram_gib=16,
        )
        assert " | " in s.format_compact()

    def test_format_compact_starts_with_system(self) -> None:
        s = SystemSummary("A", "1", "k", "m", 4)
        assert s.format_compact().startswith("System:")


class TestCompactCpuModel:
    def test_amd_ryzen_strips_vendor_and_suffix(self) -> None:
        raw = "AMD Ryzen 7 5700U with Radeon Graphics"
        assert _compact_cpu_model(raw) == "Ryzen 7 5700U"

    def test_intel_core_strips_vendor_freq_suffix(self) -> None:
        raw = "Intel(R) Core(TM) i5-6500T CPU @ 2.50GHz"
        assert _compact_cpu_model(raw) == "Core i5-6500T"

    def test_intel_xeon_strips_vendor_freq_suffix(self) -> None:
        raw = "Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz"
        assert _compact_cpu_model(raw) == "Xeon Gold 6154"

    def test_apple_silicon(self) -> None:
        raw = "Apple M1"
        assert _compact_cpu_model(raw) == "M1"

    def test_arm_cortex(self) -> None:
        raw = "ARM Cortex-A72"
        assert _compact_cpu_model(raw) == "Cortex-A72"

    def test_plain_model_unchanged(self) -> None:
        raw = "Ryzen 5 3600"
        assert _compact_cpu_model(raw) == "Ryzen 5 3600"

    def test_whitespace_normalized(self) -> None:
        raw = "  AMD   Ryzen 9  5950X  "
        result = _compact_cpu_model(raw)
        assert result == "Ryzen 9 5950X"

    def test_trademark_markers_removed(self) -> None:
        raw = "Intel(R) Pentium(R) Gold G6400"
        result = _compact_cpu_model(raw)
        assert "(R)" not in result
        assert "(TM)" not in result


class TestCompactKernelRelease:
    def test_debian_kernel(self) -> None:
        assert _compact_kernel_release("6.12.90+deb13.1-amd64") == "6.12.90"

    def test_ubuntu_generic_kernel(self) -> None:
        assert _compact_kernel_release("6.8.0-63-generic") == "6.8.0"

    def test_freebsd_release(self) -> None:
        assert _compact_kernel_release("14.1-RELEASE-p6") == "14.1"

    def test_clean_version_unchanged(self) -> None:
        assert _compact_kernel_release("6.1.0") == "6.1.0"

    def test_two_part_version(self) -> None:
        assert _compact_kernel_release("14.1") == "14.1"

    def test_linuxkit_suffix_stripped(self) -> None:
        assert _compact_kernel_release("5.15.49-linuxkit") == "5.15.49"

    def test_empty_fallback(self) -> None:
        assert _compact_kernel_release("") == ""


class TestReadCpuModel:
    def test_returns_string(self) -> None:
        result = _read_cpu_model()
        assert isinstance(result, str)

    def test_no_vendor_prefix_in_result(self) -> None:
        result = _read_cpu_model()
        if result:
            assert not result.startswith("AMD ")
            assert not result.startswith("Intel ")


class TestGetSystemSummary:
    def test_returns_system_summary(self) -> None:
        result = get_system_summary()
        assert isinstance(result, SystemSummary)

    def test_os_name_nonempty(self) -> None:
        s = get_system_summary()
        assert s.os_name

    def test_kernel_nonempty(self) -> None:
        s = get_system_summary()
        assert s.kernel

    def test_kernel_compact(self) -> None:
        s = get_system_summary()
        assert "+" not in s.kernel
        assert s.kernel[0].isdigit()

    def test_cpu_model_nonempty(self) -> None:
        s = get_system_summary()
        assert s.cpu_model

    def test_format_compact_does_not_raise(self) -> None:
        s = get_system_summary()
        text = s.format_compact()
        assert text.startswith("System:")

    def test_ram_gib_is_none_or_positive(self) -> None:
        s = get_system_summary()
        if s.ram_gib is not None:
            assert s.ram_gib > 0

    def test_summary_is_frozen(self) -> None:
        s = get_system_summary()
        with pytest.raises((AttributeError, TypeError)):
            s.os_name = "injected"  # type: ignore[misc]
