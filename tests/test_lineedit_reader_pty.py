from __future__ import annotations

import os
import pty
import select
import termios
import threading
from types import SimpleNamespace

import pytest

from pysh.completion import Completer
from pysh.lineedit.autosuggest import AutoSuggester
from pysh.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.lineedit.reader import RawLineReader


def _run_reader(master: int, slave: int, history: list[str], data: bytes):
    result: dict[str, object] = {}
    before = termios.tcgetattr(slave)

    def target() -> None:
        try:
            result["line"] = RawLineReader(input_fd=slave, output_fd=slave).read_line(
                "> ",
                history=history,
                suggester=AutoSuggester(),
                highlighter=LineHighlighter({"echo"}),
                scheme=DEFAULT_SCHEME,
                options=SimpleNamespace(autosuggest=True, syntax_highlight=False),
                completer=Completer(lambda: []),
            )
        except BaseException as exc:  # noqa: BLE001 - test captures reader outcome
            result["exc"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    select.select([master], [], [], 1)
    try:
        os.read(master, 4096)
    except OSError:
        pass
    os.write(master, data)
    thread.join(2)
    after = termios.tcgetattr(slave)
    return result, before, after, thread.is_alive()


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_accepts_autosuggestion_and_restores_termios() -> None:
    master_fd, slave = pty.openpty()
    try:
        result, before, after, alive = _run_reader(master_fd, slave, ["echo hi"], b"ec\x06\r")
        assert not alive
        assert result["line"] == "echo hi"
        assert before == after
    finally:
        os.close(master_fd)
        os.close(slave)

    master_fd, slave = pty.openpty()
    try:
        result, before, after, alive = _run_reader(master_fd, slave, [], b"\x04")
        assert not alive
        assert isinstance(result["exc"], EOFError)
        assert before == after
    finally:
        os.close(master_fd)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_ctrl_c_and_ctrl_d() -> None:
    master_fd, slave = pty.openpty()
    try:
        result, before, after, alive = _run_reader(master_fd, slave, [], b"\x03")
        assert not alive
        assert isinstance(result["exc"], KeyboardInterrupt)
        assert before == after
    finally:
        os.close(master_fd)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_handles_variable_operator_and_editing_keys() -> None:
    master_fd, slave = pty.openpty()
    try:
        result, before, after, alive = _run_reader(
            master_fd,
            slave,
            [],
            b"echo 's' --flag $HOME | nosuch\r",
        )
        assert not alive
        assert result["line"] == "echo 's' --flag $HOME | nosuch"
        assert before == after
    finally:
        os.close(master_fd)
        os.close(slave)

    master_fd, slave = pty.openpty()
    try:
        result, before, after, alive = _run_reader(
            master_fd,
            slave,
            [],
            b"abX\x1b[D\x1b[3~c\x01echo keys \x05 ok\r",
        )
        assert not alive
        assert result["line"] == "echo keys abc ok"
        assert before == after
    finally:
        os.close(master_fd)
        os.close(slave)
