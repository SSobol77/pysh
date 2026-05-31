from __future__ import annotations

from pysh.lineedit.keys import Key, KeyDecoder, KeyEvent


def _keys(data: bytes) -> list[KeyEvent]:
    decoder = KeyDecoder()
    return decoder.feed(data)


def test_arrows_home_end_delete() -> None:
    assert _keys(b"\x1b[A\x1b[B\x1b[C\x1b[D") == [
        KeyEvent(Key.UP),
        KeyEvent(Key.DOWN),
        KeyEvent(Key.RIGHT),
        KeyEvent(Key.LEFT),
    ]
    assert _keys(b"\x1b[H\x1b[1~\x1b[7~\x1b[F\x1b[4~\x1b[8~\x1b[3~") == [
        KeyEvent(Key.HOME),
        KeyEvent(Key.HOME),
        KeyEvent(Key.HOME),
        KeyEvent(Key.END),
        KeyEvent(Key.END),
        KeyEvent(Key.END),
        KeyEvent(Key.DELETE),
    ]


def test_backspace_ctrl_tab_enter() -> None:
    assert _keys(b"\x7f\x08\t\r\n") == [
        KeyEvent(Key.BACKSPACE),
        KeyEvent(Key.BACKSPACE),
        KeyEvent(Key.TAB),
        KeyEvent(Key.ENTER),
        KeyEvent(Key.ENTER),
    ]
    assert _keys(b"\x01\x02\x03\x04\x05\x06\x0b\x0c\x12\x15\x17") == [
        KeyEvent(Key.CTRL_A),
        KeyEvent(Key.CTRL_B),
        KeyEvent(Key.CTRL_C),
        KeyEvent(Key.CTRL_D),
        KeyEvent(Key.CTRL_E),
        KeyEvent(Key.CTRL_F),
        KeyEvent(Key.CTRL_K),
        KeyEvent(Key.CTRL_L),
        KeyEvent(Key.CTRL_R),
        KeyEvent(Key.CTRL_U),
        KeyEvent(Key.CTRL_W),
    ]


def test_utf8_incremental_and_bare_escape_flush() -> None:
    decoder = KeyDecoder()
    assert decoder.feed("ą".encode()[:1]) == []
    assert decoder.feed("ą".encode()[1:]) == [KeyEvent(Key.PRINTABLE, "ą")]
    assert decoder.feed(b"\x1b") == []
    assert decoder.flush_pending() == [KeyEvent(Key.ESC)]

