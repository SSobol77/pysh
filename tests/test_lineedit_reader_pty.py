# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_lineedit_reader_pty.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
from __future__ import annotations

import os
import pty
import re
import select
import termios
import threading
from types import SimpleNamespace

import pytest

from pysh.editor.completion import Completer
from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.reader import RawLineReader

CSI_RE = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")


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


def _read_ready(master: int, timeout: float = 0.2) -> bytes:
    out = bytearray()
    while True:
        ready, _, _ = select.select([master], [], [], timeout)
        if not ready:
            return bytes(out)
        try:
            chunk = os.read(master, 4096)
        except OSError:
            return bytes(out)
        if not chunk:
            return bytes(out)
        out.extend(chunk)


def _visible_bytes(data: bytes) -> bytes:
    return CSI_RE.sub(b"", data)


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
def test_reader_uses_line_renderer_for_live_redraw() -> None:
    master_fd, slave = pty.openpty()
    result: dict[str, object] = {}
    try:
        def target() -> None:
            result["line"] = RawLineReader(input_fd=slave, output_fd=slave).read_line(
                ">>> ",
                history=[],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter(set()),
                scheme=DEFAULT_SCHEME,
                options=SimpleNamespace(autosuggest=False, syntax_highlight=False),
                line_renderer=lambda line: f"\x1b[31m{line}\x1b[0m",
            )

        thread = threading.Thread(target=target)
        thread.start()
        _read_ready(master_fd, 1.0)
        os.write(master_fd, b"1+3")
        output = _read_ready(master_fd, 1.0)
        os.write(master_fd, b"\r")
        thread.join(2)

        assert not thread.is_alive()
        assert result["line"] == "1+3"
        assert b"\x1b[31m1+3\x1b[0m" in output
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


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_tab_filters_and_redraws_command_line(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    master_fd, slave = pty.openpty()
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["line"] = RawLineReader(input_fd=slave, output_fd=slave).read_line(
                "> ",
                history=[],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter({"source", "source_zsh", "sys_info"}),
                scheme=DEFAULT_SCHEME,
                options=SimpleNamespace(autosuggest=True, syntax_highlight=False),
                completer=Completer(lambda: []),
            )
        except BaseException as exc:  # noqa: BLE001 - test captures reader outcome
            result["exc"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    _read_ready(master_fd, 0.5)
    os.write(master_fd, b"s\t")
    output = _read_ready(master_fd, 0.5)
    os.write(master_fd, b"\x03")
    thread.join(2)
    candidate_line = next(line for line in output.splitlines() if b"source" in line)
    candidates = set(candidate_line.split())
    assert b"source" in candidates
    assert b"sys_info" in candidates
    assert b"src/" in candidates
    assert b"cd" not in candidates
    assert b"pwd" not in candidates
    assert b"alias" not in candidates
    assert b"README.md" not in output
    assert _visible_bytes(output).rstrip().endswith(b"> s")
    os.close(master_fd)
    os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_tab_path_prefix_matches_dot_directory(tmp_path, monkeypatch) -> None:
    (tmp_path / ".venv").mkdir()
    monkeypatch.chdir(tmp_path)
    master_fd, slave = pty.openpty()
    result, before, after, alive = _run_reader(master_fd, slave, [], b".v\t\r")
    assert not alive
    assert result["line"] == ".venv/"
    assert before == after
    os.close(master_fd)
    os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_startup_cursor_after_prompt() -> None:
    master_fd, slave = pty.openpty()
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["line"] = RawLineReader(input_fd=slave, output_fd=slave).read_line(
                "> ",
                history=[],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter(set()),
                scheme=DEFAULT_SCHEME,
                options=SimpleNamespace(autosuggest=True, syntax_highlight=False),
                completer=Completer(lambda: []),
            )
        except BaseException as exc:  # noqa: BLE001 - test captures reader outcome
            result["exc"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    output = _read_ready(master_fd, 0.5)
    os.write(master_fd, b"\x04")
    thread.join(2)
    assert output.endswith(b"> \x1b[K\r\x1b[2C")
    os.close(master_fd)
    os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only")
def test_reader_handles_delete_home_end_keys() -> None:
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
