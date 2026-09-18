# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resize.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""End-to-end SIGWINCH regression tests for Issue #36 (Phase 8).

Unlike tests/test_editor_state_integration.py (which calls
``RawLineReader._on_winch`` directly to test the flag/redraw logic in
isolation), these tests spawn a real ``python -m pysh`` subprocess as the
session leader and controlling-terminal owner of a fresh PTY, then resize
that PTY with a real ``TIOCSWINSZ`` ioctl. The kernel delivers a genuine
SIGWINCH to the pysh process exactly as a real terminal emulator would.

Making the child the controlling-terminal owner requires ``setsid()`` +
``TIOCSCTTY`` in a ``preexec_fn`` (the standard pty-spawn recipe): plain
``subprocess.Popen(..., stdin=slave_fd, ...)`` does not, on its own, give the
child a controlling terminal, so a plain ioctl-triggered SIGWINCH would never
reach it.
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

import pytest

if not hasattr(pty, "openpty") or not hasattr(signal, "SIGWINCH"):
    pytest.skip("PTY/SIGWINCH not available on this platform", allow_module_level=True)

_PYSH_CMD: list[str] = [sys.executable, "-m", "pysh"]
_PTY_ENV: dict[str, str] = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
_PTY_ENV["TERM"] = "xterm-256color"
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(data: bytes) -> bytes:
    return _ANSI_RE.sub(b"", data)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _make_controlling_pty_child(slave_fd: int) -> subprocess.Popen:
    """Spawn pysh as the session leader and controlling-terminal owner of *slave_fd*.

    ``os.setsid()`` detaches from any existing controlling terminal and makes
    the child a new session leader; ``TIOCSCTTY`` then explicitly assigns
    *slave_fd* as its controlling terminal (required since the fd reached the
    child via inherited dup, not a fresh ``open()``, which is the only case
    the kernel would auto-assign it). This makes the child's process group
    the PTY's foreground process group, which is what SIGWINCH delivery on
    ``TIOCSWINSZ`` targets.
    """

    def _preexec() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    return subprocess.Popen(
        _PYSH_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=_PTY_ENV,
        close_fds=True,
        preexec_fn=_preexec,
    )


def _wait_for_prompt(master_fd: int, timeout: float = 15.0) -> bytes:
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master_fd], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf.extend(chunk)
        if b"> " in _strip_ansi(bytes(buf)):
            time.sleep(0.15)
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.15)
                if ready:
                    buf.extend(os.read(master_fd, 4096))
            except OSError:
                pass
            return bytes(buf)
    return bytes(buf)


def _read_nonblocking(master_fd: int, settle: float, timeout: float) -> bytes:
    buf = bytearray()
    deadline = time.monotonic() + timeout
    last_data = time.monotonic()
    while time.monotonic() < deadline:
        if time.monotonic() - last_data > settle:
            break
        ready, _, _ = select.select([master_fd], [], [], min(0.05, settle))
        if ready:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            last_data = time.monotonic()
    return bytes(buf)


@pytest.mark.skipif(os.name != "posix", reason="pty/SIGWINCH are POSIX-only")
def test_resize_mid_typing_preserves_buffer_and_executes_correctly() -> None:
    """Resizing the real terminal mid-command must not corrupt or drop input."""
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd, rows=24, cols=80)
    proc = _make_controlling_pty_child(slave_fd)
    os.close(slave_fd)
    try:
        _wait_for_prompt(master_fd)

        os.write(master_fd, b"echo resize")
        _read_nonblocking(master_fd, settle=0.2, timeout=1.0)

        # Real kernel-level resize: the child is the PTY's controlling
        # process, so this delivers a genuine SIGWINCH to it.
        _set_winsize(master_fd, rows=40, cols=40)
        time.sleep(0.2)

        os.write(master_fd, b"-ok\r\n")
        output = bytearray()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            chunk = _read_nonblocking(master_fd, settle=0.3, timeout=1.0)
            if not chunk:
                break
            output.extend(chunk)

        os.write(master_fd, b"exit\n")
        output.extend(_read_nonblocking(master_fd, settle=0.3, timeout=2.0))

        stripped = _strip_ansi(bytes(output))
        assert b"resize-ok" in stripped, (
            "Resize mid-typing corrupted or dropped the input buffer.\n"
            f"Raw output:\n{output!r}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        try:
            os.close(master_fd)
        except OSError:
            pass


@pytest.mark.skipif(os.name != "posix", reason="pty/SIGWINCH are POSIX-only")
def test_resize_does_not_crash_shell_or_leave_it_unresponsive() -> None:
    """After a resize the shell must keep accepting and executing commands."""
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd, rows=24, cols=80)
    proc = _make_controlling_pty_child(slave_fd)
    os.close(slave_fd)
    try:
        _wait_for_prompt(master_fd)

        for cols in (120, 30, 100, 20):
            _set_winsize(master_fd, rows=24, cols=cols)
            time.sleep(0.1)

        os.write(master_fd, b"echo still-alive\n")
        output = bytearray()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            chunk = _read_nonblocking(master_fd, settle=0.3, timeout=1.0)
            if not chunk:
                break
            output.extend(chunk)

        os.write(master_fd, b"exit\n")
        output.extend(_read_nonblocking(master_fd, settle=0.3, timeout=2.0))

        stripped = _strip_ansi(bytes(output))
        assert b"still-alive" in stripped, (
            "Shell did not remain responsive after repeated resizes.\n"
            f"Raw output:\n{output!r}"
        )
        assert proc.poll() is None or proc.returncode in (0, None), (
            f"pysh crashed after resize (returncode={proc.returncode}).\n"
            f"Raw output:\n{output!r}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        try:
            os.close(master_fd)
        except OSError:
            pass


@pytest.mark.skipif(os.name != "posix", reason="pty/SIGWINCH are POSIX-only")
def test_resize_while_completion_menu_is_displayed() -> None:
    """A real SIGWINCH while a TAB candidate menu is on-screen must not corrupt it."""
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd, rows=24, cols=80)
    proc = _make_controlling_pty_child(slave_fd)
    os.close(slave_fd)
    try:
        _wait_for_prompt(master_fd)

        os.write(master_fd, b"e\t")
        menu = _read_nonblocking(master_fd, settle=0.3, timeout=1.0)
        stripped_menu = _strip_ansi(menu)
        assert b"echo" in stripped_menu and b"exit" in stripped_menu, (
            "TAB did not display the expected candidate menu before resize.\n"
            f"Raw output:\n{menu!r}"
        )

        _set_winsize(master_fd, rows=30, cols=50)
        time.sleep(0.2)

        os.write(master_fd, b"cho hi\r\n")
        output = bytearray()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            chunk = _read_nonblocking(master_fd, settle=0.3, timeout=1.0)
            if not chunk:
                break
            output.extend(chunk)

        os.write(master_fd, b"exit\n")
        output.extend(_read_nonblocking(master_fd, settle=0.3, timeout=2.0))

        stripped = _strip_ansi(bytes(output))
        assert b"hi" in stripped, (
            "Command typed after a resize during an open completion menu did "
            "not execute correctly.\n"
            f"Raw output:\n{output!r}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        try:
            os.close(master_fd)
        except OSError:
            pass
