# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the system_info compact banner helper."""
from __future__ import annotations

import pytest

from pysh.diagnostics.system_info import SystemSummary, get_system_summary


class TestSystemSummary:
    def test_format_compact_full(self) -> None:
        s = SystemSummary(
            os_name="Debian GNU/Linux",
            os_version="13",
            kernel="6.1.0",
            machine="x86_64",
            ram_gib=32,
        )
        result = s.format_compact()
        assert result.startswith("System: Debian GNU/Linux 13")
        assert "Kernel 6.1.0" in result
        assert "x86_64" in result
        assert "RAM 32 GiB" in result

    def test_format_compact_no_ram(self) -> None:
        s = SystemSummary(
            os_name="Linux",
            os_version="",
            kernel="6.0.0",
            machine="aarch64",
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
            machine="x86_64",
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
            machine="x86_64",
            ram_gib=16,
        )
        assert " | " in s.format_compact()

    def test_format_compact_starts_with_system(self) -> None:
        s = SystemSummary("A", "1", "k", "m", 4)
        assert s.format_compact().startswith("System:")


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

    def test_machine_nonempty(self) -> None:
        s = get_system_summary()
        assert s.machine

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
