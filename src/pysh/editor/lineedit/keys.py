# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure incremental key decoder for the raw-mode line editor."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Key(StrEnum):
    """Logical key events understood by the line editor."""

    PRINTABLE = "printable"
    ENTER = "enter"
    TAB = "tab"
    BACKSPACE = "backspace"
    DELETE = "delete"
    ESC = "esc"
    CTRL_A = "ctrl_a"
    CTRL_B = "ctrl_b"
    CTRL_C = "ctrl_c"
    CTRL_D = "ctrl_d"
    CTRL_E = "ctrl_e"
    CTRL_F = "ctrl_f"
    CTRL_G = "ctrl_g"
    CTRL_K = "ctrl_k"
    CTRL_L = "ctrl_l"
    CTRL_R = "ctrl_r"
    CTRL_U = "ctrl_u"
    CTRL_W = "ctrl_w"
    UP = "up"
    DOWN = "down"
    RIGHT = "right"
    LEFT = "left"
    HOME = "home"
    END = "end"
    PASTE_START = "paste_start"
    PASTE_END = "paste_end"


@dataclass(frozen=True)
class KeyEvent:
    """One decoded key event."""

    key: Key
    text: str = ""


_CONTROL_KEYS: dict[int, Key] = {
    0x01: Key.CTRL_A,
    0x02: Key.CTRL_B,
    0x03: Key.CTRL_C,
    0x04: Key.CTRL_D,
    0x05: Key.CTRL_E,
    0x06: Key.CTRL_F,
    0x07: Key.CTRL_G,
    0x0B: Key.CTRL_K,
    0x0C: Key.CTRL_L,
    0x12: Key.CTRL_R,
    0x15: Key.CTRL_U,
    0x17: Key.CTRL_W,
}

_CSI_KEYS: dict[bytes, Key] = {
    b"\x1b[A": Key.UP,
    b"\x1b[B": Key.DOWN,
    b"\x1b[C": Key.RIGHT,
    b"\x1b[D": Key.LEFT,
    b"\x1b[H": Key.HOME,
    b"\x1b[1~": Key.HOME,
    b"\x1b[7~": Key.HOME,
    b"\x1b[F": Key.END,
    b"\x1b[4~": Key.END,
    b"\x1b[8~": Key.END,
    b"\x1b[3~": Key.DELETE,
    # Bracketed paste mode markers (XTerm / VTE / most modern terminals).
    b"\x1b[200~": Key.PASTE_START,
    b"\x1b[201~": Key.PASTE_END,
}


class KeyDecoder:
    """Incrementally decode bytes into :class:`KeyEvent` values.

    The decoder never blocks. If an ESC byte may be a bare Escape key or the
    beginning of a CSI sequence, it buffers it until more bytes arrive or the
    caller invokes :meth:`flush_pending`.
    """

    def __init__(self) -> None:
        self._pending = bytearray()

    def feed(self, data: bytes) -> list[KeyEvent]:
        """Decode available bytes into zero or more key events."""
        out: list[KeyEvent] = []
        for b in data:
            self._pending.append(b)
            out.extend(self._drain_pending(final=False))
        return out

    def flush_pending(self) -> list[KeyEvent]:
        """Flush buffered bytes when the caller knows no more bytes are ready."""
        return self._drain_pending(final=True)

    def _drain_pending(self, *, final: bool) -> list[KeyEvent]:
        out: list[KeyEvent] = []
        while self._pending:
            event = self._decode_one(final=final)
            if event is None:
                break
            out.append(event)
        return out

    def _decode_one(self, *, final: bool) -> KeyEvent | None:
        first = self._pending[0]
        if first == 0x1B:
            return self._decode_escape(final=final)
        if first in (0x0D, 0x0A):
            del self._pending[0]
            return KeyEvent(Key.ENTER)
        if first == 0x09:
            del self._pending[0]
            return KeyEvent(Key.TAB)
        if first in (0x7F, 0x08):
            del self._pending[0]
            return KeyEvent(Key.BACKSPACE)
        if first in _CONTROL_KEYS:
            del self._pending[0]
            return KeyEvent(_CONTROL_KEYS[first])
        return self._decode_utf8_printable(final=final)

    def _decode_escape(self, *, final: bool) -> KeyEvent | None:
        data = bytes(self._pending)
        for seq, key in _CSI_KEYS.items():
            if data.startswith(seq):
                del self._pending[: len(seq)]
                return KeyEvent(key)
        if any(seq.startswith(data) for seq in _CSI_KEYS):
            if not final:
                return None
        del self._pending[0]
        return KeyEvent(Key.ESC)

    def _decode_utf8_printable(self, *, final: bool) -> KeyEvent | None:
        first = self._pending[0]
        needed = self._utf8_length(first)
        if needed == 0:
            del self._pending[0]
            return KeyEvent(Key.PRINTABLE, chr(first) if first >= 0x20 else "")
        if len(self._pending) < needed:
            return None if not final else self._flush_invalid_byte()
        raw = bytes(self._pending[:needed])
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return self._flush_invalid_byte()
        del self._pending[:needed]
        return KeyEvent(Key.PRINTABLE, text)

    def _flush_invalid_byte(self) -> KeyEvent:
        first = self._pending[0]
        del self._pending[0]
        return KeyEvent(Key.PRINTABLE, chr(first) if first >= 0x20 else "")

    @staticmethod
    def _utf8_length(first: int) -> int:
        if first < 0x80:
            return 1
        if 0xC2 <= first <= 0xDF:
            return 2
        if 0xE0 <= first <= 0xEF:
            return 3
        if 0xF0 <= first <= 0xF4:
            return 4
        return 0
