# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Stdlib-only color parsing and ANSI SGR conversion."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RGB:
    """RGB color value."""

    r: int
    g: int
    b: int


@dataclass(frozen=True)
class AnsiColor:
    """Rendered ANSI SGR sequence."""

    sgr: str


HTML_NAMED_COLORS: dict[str, RGB] = {
    "black": RGB(0, 0, 0),
    "silver": RGB(192, 192, 192),
    "gray": RGB(128, 128, 128),
    "white": RGB(255, 255, 255),
    "maroon": RGB(128, 0, 0),
    "red": RGB(255, 0, 0),
    "purple": RGB(128, 0, 128),
    "fuchsia": RGB(255, 0, 255),
    "green": RGB(0, 128, 0),
    "lime": RGB(0, 255, 0),
    "olive": RGB(128, 128, 0),
    "orange": RGB(255, 165, 0),
    "yellow": RGB(255, 255, 0),
    "navy": RGB(0, 0, 128),
    "blue": RGB(0, 0, 255),
    "teal": RGB(0, 128, 128),
    "aqua": RGB(0, 255, 255),
}

ANSI16_PALETTE: dict[str, tuple[int, RGB]] = {
    "black": (30, RGB(0, 0, 0)),
    "red": (31, RGB(128, 0, 0)),
    "green": (32, RGB(0, 128, 0)),
    "yellow": (33, RGB(128, 128, 0)),
    "blue": (34, RGB(0, 0, 128)),
    "magenta": (35, RGB(128, 0, 128)),
    "cyan": (36, RGB(0, 128, 128)),
    "white": (37, RGB(192, 192, 192)),
    "bright_black": (90, RGB(128, 128, 128)),
    "bright_red": (91, RGB(255, 0, 0)),
    "bright_green": (92, RGB(0, 255, 0)),
    "bright_yellow": (93, RGB(255, 255, 0)),
    "bright_blue": (94, RGB(0, 0, 255)),
    "bright_magenta": (95, RGB(255, 0, 255)),
    "bright_cyan": (96, RGB(0, 255, 255)),
    "bright_white": (97, RGB(255, 255, 255)),
}

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def parse_color(value: str) -> RGB:
    """Parse a canonical HTML color name or ``#RRGGBB`` value."""
    if not isinstance(value, str):
        raise ValueError("color must be a string")
    text = value.strip()
    if not text:
        raise ValueError("color must not be empty")
    named = HTML_NAMED_COLORS.get(text.lower())
    if named is not None:
        return named
    if _HEX_RE.fullmatch(text):
        return RGB(
            int(text[1:3], 16),
            int(text[3:5], 16),
            int(text[5:7], 16),
        )
    raise ValueError(f"invalid color: {value!r}")


def nearest_ansi16(rgb: RGB) -> int:
    """Return the nearest ANSI 16-color foreground SGR code."""
    best_code = 37
    best_distance: int | None = None
    for code, candidate in ANSI16_PALETTE.values():
        distance = (
            (rgb.r - candidate.r) ** 2
            + (rgb.g - candidate.g) ** 2
            + (rgb.b - candidate.b) ** 2
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_code = code
    return best_code


def sgr_truecolor(rgb: RGB) -> str:
    """Return an ANSI 24-bit foreground SGR sequence."""
    return f"\x1b[38;2;{rgb.r};{rgb.g};{rgb.b}m"


def sgr_ansi16(rgb: RGB) -> str:
    """Return the nearest ANSI 16-color foreground SGR sequence."""
    return f"\x1b[{nearest_ansi16(rgb)}m"


def sgr_reset() -> str:
    """Return the ANSI reset sequence."""
    return "\x1b[0m"


def rgb_to_hex(rgb: RGB) -> str:
    """Return ``rgb`` as canonical uppercase ``#RRGGBB`` text."""
    return f"#{rgb.r:02X}{rgb.g:02X}{rgb.b:02X}"


def color_to_hex(value: str) -> str:
    """Parse ``value`` and return canonical uppercase ``#RRGGBB`` text."""
    return rgb_to_hex(parse_color(value))


def colorize(text: str, rgb: RGB | None, *, enabled: bool, vga: bool) -> str:
    """Wrap ``text`` in SGR color if enabled and a color is configured."""
    if not enabled or rgb is None or not text:
        return text
    sgr = sgr_ansi16(rgb) if vga else sgr_truecolor(rgb)
    return f"{sgr}{text}{sgr_reset()}"
