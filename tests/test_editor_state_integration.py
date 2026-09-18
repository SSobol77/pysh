# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_editor_state_integration.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Integration regression tests for Issue #36 (editor state machine).

Covers gaps not already exercised by test_multiline_paste.py,
test_heredoc.py, or test_pty_integration.py:

- RawLineReader.editor_mode reflects MULTILINE/HEREDOC/PASTE_STAGED set by
  the shell collector helpers, and REVERSE_SEARCH/COMPLETION set internally.
- Reverse search ESC and Ctrl+G restore the exact original buffer text and
  let editing continue (not treated as a submitted empty command).
- Repeated Ctrl+R cycles through older matches deterministically.
- Interactive py { ... } block collection is cancellable with Ctrl+C and
  leaves the shell able to run a normal command immediately after
  ("echo clean" after every cancelled mode).
"""
from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.reader import RawLineReader
from pysh.editor.lineedit.state import EditorMode

if not hasattr(pty, "openpty"):
    pytest.skip("PTY not available on this platform", allow_module_level=True)

_PYSH_CMD: list[str] = [sys.executable, "-m", "pysh"]
_PTY_ENV: dict[str, str] = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
_PTY_ENV["TERM"] = "xterm-256color"
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(data: bytes) -> bytes:
    return _ANSI_RE.sub(b"", data)


def _make_options(*, autosuggest: bool = False, syntax_highlight: bool = False) -> SimpleNamespace:
    return SimpleNamespace(autosuggest=autosuggest, syntax_highlight=syntax_highlight)


def _read_until(master_fd: int, marker: bytes, timeout: float = 1.0) -> bytes:
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


def _run_pty_session(input_bytes: bytes, *, env=None, collect_timeout: float = 3.0) -> bytes:
    """Spawn `python -m pysh` on a PTY, feed *input_bytes*, and return all output."""
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        _PYSH_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env if env is not None else _PTY_ENV,
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        os.write(master_fd, input_bytes)
        deadline = time.monotonic() + collect_timeout
        chunks = bytearray()
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([master_fd], [], [], min(0.2, remaining))
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        os.close(master_fd)


# --------------------------------------------------------------- editor_mode


def test_editor_mode_defaults_to_normal() -> None:
    reader = RawLineReader()
    assert reader.editor_mode is EditorMode.NORMAL


def test_editor_mode_reflects_multiline_collection_helper() -> None:
    reader = RawLineReader()
    reader.enter_multiline_mode(opener="py {")
    assert reader.editor_mode is EditorMode.MULTILINE
    reader.clear_editor_state()
    assert reader.editor_mode is EditorMode.NORMAL


def test_editor_mode_reflects_heredoc_collection_helper() -> None:
    reader = RawLineReader()
    reader.enter_heredoc_mode(opener="cat <<EOF", delimiters=["EOF"])
    assert reader.editor_mode is EditorMode.HEREDOC
    reader.clear_editor_state()
    assert reader.editor_mode is EditorMode.NORMAL


def test_editor_mode_reflects_staged_paste_helper() -> None:
    reader = RawLineReader()
    reader.enter_paste_mode("echo one\necho two\n")
    assert reader.editor_mode is EditorMode.PASTE_STAGED
    reader.clear_editor_state()
    assert reader.editor_mode is EditorMode.NORMAL


def test_editor_mode_reverse_search_takes_precedence_over_staged_paste() -> None:
    """A transient sub-interaction (reverse search) must report itself over an
    outer collection mode (PASTE_STAGED) without EditorState raising — the two
    axes are tracked independently precisely so legitimate nesting cannot
    trigger the strict active-to-active transition guard.
    """
    reader = RawLineReader()
    reader.enter_paste_mode("echo one\n")
    reader._in_reverse_search = True
    assert reader.editor_mode is EditorMode.REVERSE_SEARCH
    reader._in_reverse_search = False
    assert reader.editor_mode is EditorMode.PASTE_STAGED


def test_editor_mode_completion_takes_precedence_over_staged_paste() -> None:
    reader = RawLineReader()
    reader.enter_paste_mode("echo one\n")
    reader._completion_displayed = True
    assert reader.editor_mode is EditorMode.COMPLETION
    reader._completion_displayed = False
    assert reader.editor_mode is EditorMode.PASTE_STAGED


def test_editor_mode_reverse_search_flag_cleared_after_cancel() -> None:
    """Ctrl+C during reverse search must reset _in_reverse_search even though
    the call raises KeyboardInterrupt.
    """
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)

    def target() -> None:
        try:
            reader.read_line(
                "> ",
                history=["echo old-command"],
                suggester=AutoSuggester(),
                highlighter=LineHighlighter(()),
                scheme=DEFAULT_SCHEME,
                options=_make_options(),
            )
        except KeyboardInterrupt:
            pass

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_until(master, b"\x1b[?2004h")
        os.write(master, b"\x12")
        _read_until(master, b"reverse-i-search")
        os.write(master, b"\x03")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert reader.editor_mode is EditorMode.NORMAL
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


# ------------------------------------------------------ reverse search restore


def test_reverse_search_esc_restores_exact_original_buffer_and_cursor() -> None:
    """ESC must restore the exact pre-search buffer text/cursor, not submit ''."""
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    result: dict[str, str] = {}

    def target() -> None:
        result["line"] = reader.read_line(
            "> ",
            history=["echo old-command"],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_until(master, b"\x1b[?2004h")
        os.write(master, b"echo partial")
        _read_until(master, b"echo partial")
        os.write(master, b"\x12old")
        _read_until(master, b"echo old-command")
        os.write(master, b"\x1b")
        # Search must end while the thread stays alive (still editing, not a
        # submitted empty command); Enter now must submit the ORIGINAL text.
        time.sleep(0.1)
        assert thread.is_alive()
        os.write(master, b"\r")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["line"] == "echo partial"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_reverse_search_ctrl_g_restores_exact_original_buffer() -> None:
    """Ctrl+G must restore the exact pre-search buffer, like ESC."""
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    result: dict[str, str] = {}

    def target() -> None:
        result["line"] = reader.read_line(
            "> ",
            history=["echo old-command"],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_until(master, b"\x1b[?2004h")
        os.write(master, b"echo keep-me")
        _read_until(master, b"echo keep-me")
        os.write(master, b"\x12old")
        _read_until(master, b"echo old-command")
        os.write(master, b"\x07")  # Ctrl+G
        time.sleep(0.1)
        assert thread.is_alive()
        os.write(master, b"\r")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["line"] == "echo keep-me"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_reverse_search_repeated_ctrl_r_cycles_older_matches() -> None:
    """Repeated Ctrl+R with a non-empty query cycles deterministically."""
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    result: dict[str, str] = {}

    def target() -> None:
        result["line"] = reader.read_line(
            "> ",
            history=["echo alpha", "echo beta-x", "echo gamma-x"],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )

    thread = threading.Thread(target=target)
    try:
        thread.start()
        _read_until(master, b"\x1b[?2004h")
        os.write(master, b"\x12-x")
        output = _read_until(master, b"echo gamma-x")
        assert b"echo gamma-x" in output, (
            "First Ctrl+R match must be the newest matching entry.\n"
            f"Raw output: {output!r}"
        )
        os.write(master, b"\x12")  # cycle to the next-older match
        output = _read_until(master, b"echo beta-x")
        assert b"echo beta-x" in output, (
            "Second Ctrl+R press did not cycle to the next-older match.\n"
            f"Raw output: {output!r}"
        )
        os.write(master, b"\r")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["line"] == "echo beta-x"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


# ------------------------------------------------------------------- resize


def test_resize_pending_flag_triggers_extra_redraw_before_next_key() -> None:
    """A SIGWINCH-style flag must trigger one extra redraw, buffer untouched.

    Calls the real ``_on_winch`` handler directly (exactly what a delivered
    SIGWINCH would invoke) rather than sending a real signal, so this test is
    deterministic and independent of controlling-terminal/session-leader
    plumbing. The real end-to-end OS signal path is covered separately by
    tests/test_resize.py.
    """
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
        os.write(master, b"ab")
        baseline = _read_until(master, b"ab", timeout=0.3)
        baseline_redraws = baseline.count(b"\x1b[J")
        assert baseline_redraws >= 1

        # Simulate SIGWINCH: this is the exact call the OS-installed handler
        # makes; only a flag is set here (signal-safe minimal work).
        reader._on_winch(0, None)
        assert reader._resize_pending is True

        os.write(master, b"c")
        output = _read_until(master, b"c", timeout=0.3)
        # The pending-resize redraw plus the normal per-key redraw must both
        # fire for this one keystroke.
        assert output.count(b"\x1b[J") >= 2, (
            "Pending resize did not produce an extra redraw before the next "
            f"key event was processed.\nRaw output: {output!r}"
        )
        assert reader._resize_pending is False

        os.write(master, b"\r")
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["line"] == "abc", "Buffer must survive a pending resize unchanged"
    finally:
        if thread.is_alive():
            os.write(master, b"\x04")
            thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_resize_handler_registration_is_restored_after_read_line() -> None:
    """The SIGWINCH handler installed for one read_line() call must not leak.

    Signal registration only succeeds on the main thread, so this test calls
    read_line() directly on the main test thread (unlike the rest of this
    file) and uses a helper thread only to feed input bytes.
    """
    if not hasattr(signal, "SIGWINCH"):
        pytest.skip("SIGWINCH not available on this platform")

    previous = signal.getsignal(signal.SIGWINCH)
    master, slave = pty.openpty()
    reader = RawLineReader(input_fd=slave, output_fd=slave)
    installed_handler: dict[str, object] = {}

    def feed_input() -> None:
        _read_until(master, b"\x1b[?2004h")
        # The handler must be installed (differ from the pre-call handler)
        # while read_line() is actively reading.
        installed_handler["during"] = signal.getsignal(signal.SIGWINCH)
        os.write(master, b"\r")

    try:
        writer = threading.Thread(target=feed_input)
        writer.start()
        reader.read_line(
            "> ",
            history=[],
            suggester=AutoSuggester(),
            highlighter=LineHighlighter(()),
            scheme=DEFAULT_SCHEME,
            options=_make_options(),
        )
        writer.join(timeout=3)
        assert installed_handler.get("during") == reader._on_winch, (
            "SIGWINCH handler was not installed during read_line()."
        )
        assert signal.getsignal(signal.SIGWINCH) == previous, (
            "SIGWINCH handler leaked past read_line() return."
        )
    finally:
        os.close(master)
        os.close(slave)


# ------------------------------------------------------------- py block Ctrl+C


def test_pty_py_block_ctrl_c_then_echo_clean() -> None:
    """Ctrl+C mid `py { ... }` body must discard the fragment; next command runs clean."""
    output = _run_pty_session(
        b"py {\n"
        b"print('SHOULD_NOT_RUN')\n"
        b"\x03"
        b"echo clean\n"
        b"exit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    assert b"clean" in stripped, (
        "'echo clean' did not appear to run normally after py-block Ctrl+C.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"SHOULD_NOT_RUN" not in stripped, (
        "Interrupted py block body leaked into execution.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert stripped.count(b"py>") <= 1, (
        "py continuation prompt/state persisted after Ctrl+C cancellation.\n"
        f"Raw PTY output:\n{output!r}"
    )
