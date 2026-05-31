# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_colors.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

import pytest

from pysh.colors import (
    RGB,
    colorize,
    nearest_ansi16,
    parse_color,
    sgr_ansi16,
    sgr_reset,
    sgr_truecolor,
)


def test_parse_named_colors_case_insensitive() -> None:
    assert parse_color("red") == RGB(255, 0, 0)
    assert parse_color(" RED ") == RGB(255, 0, 0)
    assert parse_color("Fuchsia") == RGB(255, 0, 255)


def test_parse_hex_lowercase_and_uppercase() -> None:
    assert parse_color("#33ccff") == RGB(51, 204, 255)
    assert parse_color("#33CCFF") == RGB(51, 204, 255)


@pytest.mark.parametrize("value", ["#RGB", "red;", "rgb(1,2,3)", "", "unknown", "#12zz45"])
def test_parse_rejects_invalid_colors(value: str) -> None:
    with pytest.raises(ValueError):
        parse_color(value)


def test_truecolor_sgr_exact_output() -> None:
    assert sgr_truecolor(RGB(51, 204, 255)) == "\x1b[38;2;51;204;255m"
    assert sgr_reset() == "\x1b[0m"


def test_ansi16_nearest_mapping_for_canonical_colors() -> None:
    assert nearest_ansi16(parse_color("red")) == 91
    assert nearest_ansi16(parse_color("blue")) == 94
    assert nearest_ansi16(parse_color("aqua")) == 96
    assert nearest_ansi16(parse_color("fuchsia")) == 95


def test_colorize_disabled_returns_original() -> None:
    assert colorize("text", RGB(255, 0, 0), enabled=False, vga=True) == "text"


def test_colorize_enabled_wraps_with_sgr_and_reset() -> None:
    assert colorize("text", RGB(255, 0, 0), enabled=True, vga=True) == "\x1b[91mtext\x1b[0m"


def test_vga_true_uses_ansi16_and_false_uses_truecolor() -> None:
    rgb = RGB(51, 204, 255)
    assert colorize("x", rgb, enabled=True, vga=True).startswith(sgr_ansi16(rgb))
    assert colorize("x", rgb, enabled=True, vga=False).startswith(sgr_truecolor(rgb))
