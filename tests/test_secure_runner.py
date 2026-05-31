# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_secure_runner.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the explicit secure PTY runner."""
from __future__ import annotations

import os
import pty
import re
import select
import sys
import termios
import threading

import pytest

import pysh.secure_runner as secure_runner
from pysh.secure_runner import (
    KeypressIndicator,
    SecureRunner,
    SensitiveIndicatorConfig,
    colors_enabled_for_fd,
)

ANSI_RE = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
ERASE = b"\x08 \x08"


def _config(*, enabled: bool = True) -> SensitiveIndicatorConfig:
    return SensitiveIndicatorConfig(
        enabled=enabled,
        symbol="*",
        idle_color="white",
        active_color="lime",
        vga=True,
    )


def _visible(data: bytes) -> bytes:
    text = ANSI_RE.sub(b"", data)
    cells = bytearray()
    cursor = 0
    for byte in text:
        if byte == 0x08:
            cursor = max(0, cursor - 1)
            continue
        if cursor == len(cells):
            cells.append(byte)
        else:
            cells[cursor] = byte
        cursor += 1
    return bytes(cells).rstrip(b" ")


def _read_available(fd: int, timeout: float = 1.0) -> bytes:
    out = bytearray()
    while True:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return bytes(out)
        chunk = os.read(fd, 4096)
        if not chunk:
            return bytes(out)
        out.extend(chunk)
        timeout = 0.05


def test_indicator_renders_one_visible_symbol() -> None:
    indicator = KeypressIndicator(_config(), colors=False)

    assert indicator.show_idle() == "*"
    assert indicator.show_active() == "*"
    assert indicator.erase() == "\b \b"


def test_indicator_applies_colors_when_enabled() -> None:
    indicator = KeypressIndicator(_config(), colors=True)

    assert indicator.show_idle() == "\x1b[97m*\x1b[0m"
    assert indicator.show_active() == "\x1b[92m*\x1b[0m"
    assert ANSI_RE.sub(b"", indicator.show_idle().encode()) == b"*"
    assert ANSI_RE.sub(b"", indicator.show_active().encode()) == b"*"


def test_indicator_omits_colors_when_gate_disabled() -> None:
    indicator = KeypressIndicator(_config(), colors=False)

    assert indicator.show_idle() == "*"
    assert indicator.show_active() == "*"


def test_indicator_disabled_renders_nothing() -> None:
    indicator = KeypressIndicator(_config(enabled=False), colors=True)

    assert indicator.show_idle() == ""
    assert indicator.show_active() == ""


def test_color_gate_respects_no_color_and_dumb_terminal(monkeypatch) -> None:
    monkeypatch.setattr(secure_runner.os, "isatty", lambda _fd: True)

    assert colors_enabled_for_fd(1, {"TERM": "xterm-256color"}) is True
    assert colors_enabled_for_fd(1, {"TERM": "xterm-256color", "NO_COLOR": "1"}) is False
    assert colors_enabled_for_fd(1, {"TERM": "dumb"}) is False


@pytest.mark.skipif(os.name != "posix", reason="PTY tests require POSIX")
def test_secure_runner_simple_command_outputs_data() -> None:
    read_fd, write_fd = os.pipe()
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        status = SecureRunner(
            _config(enabled=False),
            input_fd=devnull,
            output_fd=write_fd,
        ).run([sys.executable, "-c", "print('hi')"])
        os.close(write_fd)
        write_fd = -1
        output = _read_available(read_fd)
    finally:
        os.close(read_fd)
        os.close(devnull)
        if write_fd != -1:
            os.close(write_fd)

    assert status == 0
    assert output.replace(b"\r\n", b"\n") == b"hi\n"


@pytest.mark.skipif(os.name != "posix", reason="PTY tests require POSIX")
def test_secure_runner_nonexistent_command_returns_127() -> None:
    read_fd, write_fd = os.pipe()
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        status = SecureRunner(
            _config(enabled=False),
            input_fd=devnull,
            output_fd=write_fd,
        ).run(["definitely_missing_pysh_secure_command"])
        os.close(write_fd)
        write_fd = -1
        output = _read_available(read_fd)
    finally:
        os.close(read_fd)
        os.close(devnull)
        if write_fd != -1:
            os.close(write_fd)

    assert status == 127
    assert b"command not found" in output


@pytest.mark.skipif(os.name != "posix", reason="PTY tests require POSIX")
def test_indicator_does_not_grow_and_input_byte_is_not_echoed() -> None:
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    code = (
        "import os, sys, termios;"
        "fd=sys.stdin.fileno();"
        "old=termios.tcgetattr(fd);"
        "new=list(old);"
        "new[3]=new[3] & ~(termios.ECHO | termios.ICANON);"
        "termios.tcsetattr(fd, termios.TCSADRAIN, new);"
        "sys.stdout.write('ready\\n'); sys.stdout.flush();"
        "os.read(fd, 1);"
        "termios.tcsetattr(fd, termios.TCSADRAIN, old);"
        "sys.stdout.write('done\\n'); sys.stdout.flush()"
    )
    result: dict[str, int] = {}

    def target() -> None:
        result["status"] = SecureRunner(
            _config(enabled=True),
            input_fd=input_read,
            output_fd=output_write,
        ).run([sys.executable, "-c", code])

    thread = threading.Thread(target=target)
    thread.start()
    first = _read_available(output_read, 1.0)
    assert b"ready" in first
    os.write(input_write, b"p")
    os.close(input_write)
    thread.join(3)
    os.close(output_write)
    rest = _read_available(output_read)
    os.close(input_read)
    os.close(output_read)

    output = first + rest
    visible = _visible(output)
    assert result["status"] == 0
    assert b"done" in visible
    assert b"p" not in visible
    assert visible.count(b"*") <= 1


@pytest.mark.skipif(os.name != "posix", reason="PTY tests require POSIX")
def test_indicator_blinks_active_then_idle_on_echo_disabled_input(monkeypatch) -> None:
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    monkeypatch.setattr(secure_runner.os, "isatty", lambda fd: fd == output_write)
    code = (
        "import os, sys, termios;"
        "fd=sys.stdin.fileno();"
        "old=termios.tcgetattr(fd);"
        "new=list(old);"
        "new[3]=new[3] & ~(termios.ECHO | termios.ICANON);"
        "termios.tcsetattr(fd, termios.TCSADRAIN, new);"
        "sys.stdout.write('ready\\n'); sys.stdout.flush();"
        "os.read(fd, 2);"
        "termios.tcsetattr(fd, termios.TCSADRAIN, old);"
        "sys.stdout.write('done\\n'); sys.stdout.flush()"
    )
    result: dict[str, int] = {}

    def target() -> None:
        result["status"] = SecureRunner(
            _config(enabled=True),
            input_fd=input_read,
            output_fd=output_write,
            env={"TERM": "xterm-256color"},
            blink_delay=0,
        ).run([sys.executable, "-c", code])

    thread = threading.Thread(target=target)
    thread.start()
    first = _read_available(output_read, 1.0)
    assert b"ready" in first
    os.write(input_write, b"pw")
    os.close(input_write)
    thread.join(3)
    os.close(output_write)
    output = first + _read_available(output_read)
    os.close(input_read)
    os.close(output_read)

    idle = b"\x1b[97m*\x1b[0m"
    active = b"\x1b[92m*\x1b[0m"
    active_pos = output.find(active)
    assert result["status"] == 0
    assert active_pos != -1
    assert output.find(idle, active_pos + len(active)) != -1
    assert b"p" not in _visible(output)
    assert _visible(output).count(b"*") <= 1


@pytest.mark.skipif(os.name != "posix", reason="PTY tests require POSIX")
def test_secure_runner_restores_input_terminal_state() -> None:
    master_fd, slave_fd = pty.openpty()
    output_read, output_write = os.pipe()
    before = termios.tcgetattr(slave_fd)
    result: dict[str, int] = {}

    def target() -> None:
        result["status"] = SecureRunner(
            _config(enabled=False),
            input_fd=slave_fd,
            output_fd=output_write,
        ).run([sys.executable, "-c", "print('restore')"])

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(3)
    after = termios.tcgetattr(slave_fd)
    os.close(output_write)
    output = _read_available(output_read)
    os.close(output_read)
    os.close(master_fd)
    os.close(slave_fd)

    assert result["status"] == 0
    assert b"restore" in output
    assert before == after
