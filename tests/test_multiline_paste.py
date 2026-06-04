# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for multiline paste and bracketed paste support.

Covers:
- split_paste_commands() parser function
- RawLineReader._enqueue_from_events()
- RawLineReader._command_queue drain (no TTY required)
- KeyDecoder PASTE_START / PASTE_END decoding
"""
from __future__ import annotations

import os
import pty
import select
import threading
import time
from types import SimpleNamespace

from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.keys import Key, KeyDecoder, KeyEvent
from pysh.editor.lineedit.reader import QueuedCommand, RawLineReader
from pysh.parsing.parser import ChainOp, split_chain, split_paste_commands

# ---------------------------------------------------------------- split_paste_commands


def _read_until(master_fd: int, marker: bytes, timeout: float = 1.0) -> bytes:
    """Drain PTY output until *marker* appears or the deadline expires."""
    deadline = time.monotonic() + timeout
    chunks = bytearray()
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = select.select([master_fd], [], [], min(0.05, remaining))
        if not ready:
            continue
        chunk = os.read(master_fd, 4096)
        if not chunk:
            break
        chunks.extend(chunk)
        if marker in chunks:
            break
    return bytes(chunks)


def test_split_two_lines() -> None:
    cmds = split_paste_commands("echo one\necho two\n")
    assert cmds == ["echo one", "echo two"]


def test_split_three_lines() -> None:
    cmds = split_paste_commands("export FOO=bar\nenv\nls\n")
    assert cmds == ["export FOO=bar", "env", "ls"]


def test_split_no_trailing_newline() -> None:
    cmds = split_paste_commands("echo one\necho two")
    assert cmds == ["echo one", "echo two"]


def test_split_empty_input() -> None:
    assert split_paste_commands("") == []


def test_split_blank_lines_omitted() -> None:
    cmds = split_paste_commands("echo one\n\necho two\n")
    assert cmds == ["echo one", "echo two"]


def test_newline_inside_double_quotes_not_split() -> None:
    """A newline inside double quotes must not split the command."""
    cmds = split_paste_commands('echo "hello\nworld"\n')
    assert cmds == ['echo "hello\nworld"']


def test_newline_inside_single_quotes_not_split() -> None:
    cmds = split_paste_commands("echo 'hello\nworld'\n")
    assert cmds == ["echo 'hello\nworld'"]


def test_windows_line_endings_split_correctly() -> None:
    cmds = split_paste_commands("echo one\r\necho two\r\n")
    assert cmds == ["echo one", "echo two"]


def test_export_and_mc_pattern() -> None:
    cmds = split_paste_commands('export SHELL="$(command -v pysh)"\nmc -u\n')
    assert cmds == ['export SHELL="$(command -v pysh)"', "mc -u"]


def test_env_assignment_then_command() -> None:
    cmds = split_paste_commands("FOO=bar env\nBAR=baz env\n")
    assert cmds == ["FOO=bar env", "BAR=baz env"]


# ---------------------------------------------------------------- KeyDecoder: paste markers


def test_paste_start_decoded() -> None:
    decoder = KeyDecoder()
    events = decoder.feed(b"\x1b[200~")
    assert len(events) == 1
    assert events[0].key is Key.PASTE_START


def test_paste_end_decoded() -> None:
    decoder = KeyDecoder()
    events = decoder.feed(b"\x1b[201~")
    assert len(events) == 1
    assert events[0].key is Key.PASTE_END


def test_paste_start_and_end_both_decoded() -> None:
    decoder = KeyDecoder()
    events = decoder.feed(b"\x1b[200~hello\x1b[201~")
    keys = [e.key for e in events]
    assert Key.PASTE_START in keys
    assert Key.PASTE_END in keys
    # The paste markers themselves do not appear as printable text.
    printable = "".join(e.text for e in events if e.key is Key.PRINTABLE)
    assert "200" not in printable
    assert "201" not in printable
    assert printable == "hello"


# ---------------------------------------------------------------- RawLineReader: command queue


def _make_reader() -> RawLineReader:
    return RawLineReader()


def _make_options(*, autosuggest: bool = False, syntax_highlight: bool = False) -> SimpleNamespace:
    return SimpleNamespace(autosuggest=autosuggest, syntax_highlight=syntax_highlight)


def test_queue_drains_first_command() -> None:
    reader = _make_reader()
    reader._command_queue = [
        QueuedCommand("cmd1"),
        QueuedCommand("cmd2"),
        QueuedCommand("cmd3"),
    ]
    result = reader.read_line(
        "> ",
        history=[],
        suggester=AutoSuggester(),
        highlighter=LineHighlighter(frozenset()),
        scheme=DEFAULT_SCHEME,
        options=_make_options(),
    )
    assert result == "cmd1"
    assert [cmd.text for cmd in reader._command_queue] == ["cmd2", "cmd3"]


def test_queue_drain_echoes_prompt_and_command_once() -> None:
    reader = _make_reader()
    reader._command_queue = [QueuedCommand("cmd1", echo=True)]
    master, slave = pty.openpty()
    try:
        reader.output_fd = slave
        assert reader.read_line(
            "> ",
            history=[],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        ) == "cmd1"
        os.close(slave)
        slave = -1
        echoed = os.read(master, 1024)
        assert echoed == b"> cmd1\r\n"
    finally:
        os.close(master)
        if slave >= 0:
            os.close(slave)


def test_queue_drains_in_order() -> None:
    reader = _make_reader()
    reader._command_queue = [
        QueuedCommand("first", echo=False),
        QueuedCommand("second", echo=False),
        QueuedCommand("third", echo=False),
    ]
    results = []
    for _ in range(3):
        results.append(
            reader.read_line(
                "> ",
                history=[],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter(frozenset()),
                scheme=DEFAULT_SCHEME,
                options=_make_options(),
            )
        )
    assert results == ["first", "second", "third"]
    assert reader._command_queue == []


def test_no_command_lost_after_first_newline() -> None:
    """Commands queued via _enqueue_from_events must all be retained."""
    reader = _make_reader()
    events = [
        KeyEvent(Key.PRINTABLE, "l"),
        KeyEvent(Key.PRINTABLE, "s"),
        KeyEvent(Key.ENTER),
        KeyEvent(Key.PRINTABLE, "p"),
        KeyEvent(Key.PRINTABLE, "w"),
        KeyEvent(Key.PRINTABLE, "d"),
        KeyEvent(Key.ENTER),
    ]
    # Enqueue as if two commands arrived in one paste batch after "ls" was returned.
    reader._enqueue_from_events(events[3:])
    assert [cmd.text for cmd in reader._command_queue] == ["pwd"]


def test_enqueue_from_events_basic() -> None:
    reader = _make_reader()
    events = [
        KeyEvent(Key.PRINTABLE, "m"),
        KeyEvent(Key.PRINTABLE, "c"),
        KeyEvent(Key.ENTER),
        KeyEvent(Key.PRINTABLE, "l"),
        KeyEvent(Key.PRINTABLE, "s"),
        KeyEvent(Key.ENTER),
    ]
    reader._enqueue_from_events(events)
    assert [cmd.text for cmd in reader._command_queue] == ["mc", "ls"]


def test_enqueue_from_events_ignores_paste_markers() -> None:
    reader = _make_reader()
    events = [
        KeyEvent(Key.PASTE_START),
        KeyEvent(Key.PRINTABLE, "e"),
        KeyEvent(Key.PRINTABLE, "c"),
        KeyEvent(Key.PRINTABLE, "h"),
        KeyEvent(Key.PRINTABLE, "o"),
        KeyEvent(Key.ENTER),
        KeyEvent(Key.PASTE_END),
    ]
    reader._enqueue_from_events(events)
    # "echo" should be queued; paste markers must be dropped.
    assert [cmd.text for cmd in reader._command_queue] == ["echo"]


def test_enqueue_from_events_respects_quoted_newlines() -> None:
    """_enqueue_from_events must not split commands on newlines inside quotes."""
    reader = _make_reader()
    # Simulate what arrives after the first ENTER in a bracketed paste of:
    #   echo "hello\nworld"\n
    # The events for 'echo "hello\nworld"\n' include ENTER for the \n in quotes.
    events = [
        KeyEvent(Key.PRINTABLE, "e"),
        KeyEvent(Key.PRINTABLE, "c"),
        KeyEvent(Key.PRINTABLE, "h"),
        KeyEvent(Key.PRINTABLE, "o"),
        KeyEvent(Key.PRINTABLE, " "),
        KeyEvent(Key.PRINTABLE, '"'),
        KeyEvent(Key.PRINTABLE, "h"),
        KeyEvent(Key.PRINTABLE, "e"),
        KeyEvent(Key.PRINTABLE, "l"),
        KeyEvent(Key.PRINTABLE, "l"),
        KeyEvent(Key.PRINTABLE, "o"),
        KeyEvent(Key.ENTER),   # \n inside double quotes
        KeyEvent(Key.PRINTABLE, "w"),
        KeyEvent(Key.PRINTABLE, "o"),
        KeyEvent(Key.PRINTABLE, "r"),
        KeyEvent(Key.PRINTABLE, "l"),
        KeyEvent(Key.PRINTABLE, "d"),
        KeyEvent(Key.PRINTABLE, '"'),
        KeyEvent(Key.ENTER),   # trailing newline — command boundary
    ]
    reader._enqueue_from_events(events)
    assert [cmd.text for cmd in reader._command_queue] == ['echo "hello\nworld"']


def test_non_bracketed_three_command_events_queue_all_remaining() -> None:
    reader = _make_reader()
    events = KeyDecoder().feed(b"echo FIRST\necho SECOND\necho THIRD\n")
    first_enter = next(i for i, event in enumerate(events) if event.key is Key.ENTER)
    reader._enqueue_from_events(events[first_enter + 1 :])
    assert [cmd.text for cmd in reader._command_queue] == ["echo SECOND", "echo THIRD"]


def test_bracketed_three_command_events_queue_all_remaining() -> None:
    reader = _make_reader()
    events = KeyDecoder().feed(
        b"\x1b[200~echo FIRST\necho SECOND\necho THIRD\n\x1b[201~"
    )
    paste_text: list[str] = []
    in_paste = False
    for event in events:
        if event.key is Key.PASTE_START:
            in_paste = True
        elif event.key is Key.PASTE_END:
            break
        elif in_paste and event.key is Key.ENTER:
            paste_text.append("\n")
        elif in_paste and event.key is Key.PRINTABLE:
            paste_text.append(event.text)
    commands = split_paste_commands("".join(paste_text))
    reader._queue_commands(commands[1:], echo=True)
    assert commands[0] == "echo FIRST"
    assert [cmd.text for cmd in reader._command_queue] == ["echo SECOND", "echo THIRD"]


def test_read_line_enables_and_disables_bracketed_paste() -> None:
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    result: dict[str, str] = {}

    def target() -> None:
        result["line"] = reader.read_line(
            "> ",
            history=[],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )

    thread = threading.Thread(target=target)
    try:
        thread.start()
        output = _read_until(master, b"\x1b[?2004h")
        assert b"\x1b[?2004h" in output
        os.write(master, b"echo OK\n")
        thread.join(timeout=3)
        assert not thread.is_alive()
        output += _read_until(master, b"\x1b[?2004l")
        assert b"\x1b[?2004l" in output
        assert result["line"] == "echo OK"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_bracketed_paste_waits_for_explicit_enter() -> None:
    """Bracketed paste must edit the buffer, not execute on paste-end alone."""
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    result: dict[str, str] = {}

    def target() -> None:
        result["line"] = reader.read_line(
            "> ",
            history=[],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_until(master, b"\x1b[?2004h")
        os.write(master, b"\x1b[200~echo SAFE\x1b[201~")
        time.sleep(0.2)
        assert thread.is_alive(), (
            "Bracketed paste returned a command before explicit Enter; pasted "
            "text must remain in the editable buffer until Enter is pressed."
        )

        os.write(master, b"\n")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["line"] == "echo SAFE"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_ctrl_r_opens_visible_reverse_search_mode() -> None:
    """Ctrl+R on an empty prompt must display a reverse-search UI."""
    master, slave = pty.openpty()
    reader = RawLineReader(output_fd=slave)
    buffer = LineBuffer()
    try:
        result = reader._handle_event(
            KeyEvent(Key.CTRL_R),
            "> ",
            buffer,
            ["echo old-command"],
            AutoSuggester(),
            LineHighlighter(()),
            DEFAULT_SCHEME,
            False,
            _make_options(),
            None,
            None,
            None,
        )
        output = _read_until(master, b"search", timeout=0.2)
        assert not isinstance(result, str)
        assert b"search" in output.lower(), (
            "Ctrl+R did not render a visible reverse-search prompt.\n"
            f"Raw PTY output: {output!r}"
        )
    finally:
        os.close(master)
        os.close(slave)


def test_no_unrelated_commands_concatenated() -> None:
    """Each pasted line must become a separate queued command."""
    reader = _make_reader()
    reader._enqueue_from_events([
        KeyEvent(Key.PRINTABLE, "c"),
        KeyEvent(Key.PRINTABLE, "d"),
        KeyEvent(Key.PRINTABLE, " "),
        KeyEvent(Key.PRINTABLE, "/"),
        KeyEvent(Key.PRINTABLE, "t"),
        KeyEvent(Key.PRINTABLE, "m"),
        KeyEvent(Key.PRINTABLE, "p"),
        KeyEvent(Key.ENTER),
        KeyEvent(Key.PRINTABLE, "p"),
        KeyEvent(Key.PRINTABLE, "w"),
        KeyEvent(Key.PRINTABLE, "d"),
        KeyEvent(Key.ENTER),
    ])
    assert [cmd.text for cmd in reader._command_queue] == ["cd /tmp", "pwd"]


# ---------------------------------------------------------------- semicolon (Part E)


def test_semicolon_executes_both_commands() -> None:
    """echo one; echo two must split on the semicolon."""
    chain = split_chain("echo one; echo two")
    assert len(chain) == 2
    assert chain[0].command == "echo one"
    assert chain[0].operator is ChainOp.SEMI
    assert chain[1].command == "echo two"
    assert chain[1].operator is None


def test_semicolon_inside_quotes_is_literal_in_chain() -> None:
    chain = split_chain('echo "a;b"')
    assert len(chain) == 1
    assert chain[0].command == 'echo "a;b"'


def test_export_semicolon_mc_u_chain_splits_correctly() -> None:
    """export SHELL=...; mc -u must be parsed as two separate commands."""
    line = 'export SHELL="$(command -v pysh)"; mc -u'
    chain = split_chain(line)
    assert len(chain) == 2
    assert chain[0].command == 'export SHELL="$(command -v pysh)"'
    assert chain[0].operator is ChainOp.SEMI
    assert chain[1].command == "mc -u"
