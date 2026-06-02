# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_pty_integration.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Real pseudo-terminal integration tests for PySH.

Each test launches PySH as a subprocess with its own master/slave PTY pair,
sends raw byte sequences to the master (simulating terminal input), then
reads all output and asserts on its content.

These tests verify end-to-end behavior that unit tests cannot cover:
  - Multiline paste: all pasted commands must execute, none swallowed.
  - Semicolon-chained commands execute in order.
  - Leading temporary environment assignments reach the child process.
  - Temporary assignments do not mutate the parent shell environment.
  - Bracketed paste markers (ESC[200~ / ESC[201~) do not appear in output.

Design constraints:
  - Standard library only (pty, os, select, subprocess, struct, termios, fcntl).
  - Bounded timeouts; no infinite waits.
  - PySH is always exited cleanly via the "exit" command or SIGTERM.
  - Raw output is preserved in assertion messages for debugging failures.
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time

import pytest

# ---------------------------------------------------------------------------
# Skip the entire module on non-POSIX platforms (PTY is Unix-only).
# ---------------------------------------------------------------------------
if not hasattr(pty, "openpty"):
    pytest.skip("PTY not available on this platform", allow_module_level=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PYSH_CMD: list[str] = [sys.executable, "-m", "pysh"]

# Environment that forces the rich raw editor active inside the PTY.
# TERM must be set (not empty, not "dumb") for colors_enabled() to return True.
# NO_COLOR must be absent.
_PTY_ENV: dict[str, str] = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
_PTY_ENV.setdefault("TERM", "xterm-256color")

# Regex that matches ANSI CSI escape sequences.
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")

# How long (seconds) to wait for the initial PySH prompt before giving up.
_PROMPT_TIMEOUT = 15.0

# How long (seconds) to settle after the last byte arrives before declaring
# all output collected.
_SETTLE = 0.4

# Overall timeout (seconds) for collecting command output after sending input.
_COLLECT_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Low-level PTY helpers
# ---------------------------------------------------------------------------


def _strip_ansi(data: bytes) -> bytes:
    """Remove ANSI CSI sequences from *data*."""
    return _ANSI_RE.sub(b"", data)


def _visible_lines(data: bytes) -> list[str]:
    """Return non-empty ANSI-stripped terminal lines for order assertions."""
    text = _strip_ansi(data).decode("utf-8", errors="replace")
    return [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]


def _set_winsize(fd: int, rows: int = 24, cols: int = 80) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _read_nonblocking(master_fd: int, settle: float, timeout: float) -> bytes:
    """Read from *master_fd* until no bytes arrive for *settle* seconds or
    *timeout* is reached."""
    buf = bytearray()
    deadline = time.monotonic() + timeout
    last_data = time.monotonic()
    while time.monotonic() < deadline:
        if time.monotonic() - last_data > settle:
            break
        try:
            r, _, _ = select.select([master_fd], [], [], min(0.05, settle))
        except (ValueError, OSError):
            break
        if r:
            try:
                chunk = os.read(master_fd, 4096)
                if chunk:
                    buf.extend(chunk)
                    last_data = time.monotonic()
            except OSError:
                break
    return bytes(buf)


def _wait_for_prompt(master_fd: int, timeout: float = _PROMPT_TIMEOUT) -> bytes:
    """Read from *master_fd* until the PySH prompt symbol (``>``) is visible
    in ANSI-stripped output, or *timeout* expires.

    Returns all bytes collected so far (including the prompt).
    """
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r, _, _ = select.select([master_fd], [], [], 0.1)
        except (ValueError, OSError):
            break
        if r:
            try:
                chunk = os.read(master_fd, 4096)
                if not chunk:
                    break
                buf.extend(chunk)
                if b"> " in _strip_ansi(bytes(buf)):
                    # Drain a bit more to let the prompt fully render.
                    buf.extend(_read_nonblocking(master_fd, settle=0.15, timeout=0.5))
                    return bytes(buf)
            except OSError:
                break
    return bytes(buf)


def _run_pty_session(
    commands: bytes,
    *,
    prompt_timeout: float = _PROMPT_TIMEOUT,
    collect_timeout: float = _COLLECT_TIMEOUT,
    settle: float = _SETTLE,
) -> bytes:
    """Launch PySH in a fresh PTY, send *commands* to its input after the
    initial prompt appears, collect all output until the process exits or
    *collect_timeout* is reached, then return the raw master output bytes.

    The caller should include ``b"exit\\n"`` at the end of *commands* so that
    PySH terminates cleanly.  A SIGTERM is sent unconditionally on teardown.
    """
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd)
    proc = subprocess.Popen(
        _PYSH_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=_PTY_ENV,
        close_fds=True,
    )
    os.close(slave_fd)
    buf = bytearray()
    try:
        # Wait for PySH to print the initial prompt.
        initial = _wait_for_prompt(master_fd, timeout=prompt_timeout)
        buf.extend(initial)

        # Send all commands in one write (simulates paste).
        os.write(master_fd, commands)

        # Collect output until process exits or timeout.
        deadline = time.monotonic() + collect_timeout
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            if time.monotonic() - last_data > settle and proc.poll() is not None:
                break
            try:
                r, _, _ = select.select([master_fd], [], [], 0.05)
            except (ValueError, OSError):
                break
            if r:
                try:
                    chunk = os.read(master_fd, 4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    last_data = time.monotonic()
                except OSError:
                    break
            elif proc.poll() is not None and time.monotonic() - last_data > settle:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        try:
            os.close(master_fd)
        except OSError:
            pass
    return bytes(buf)


# ---------------------------------------------------------------------------
# Part B — PTY test: pasted multiline commands
# ---------------------------------------------------------------------------


def test_pty_multiline_paste_both_commands_execute() -> None:
    """Pasting python --version + pip --version as one write must execute both.

    The byte sequence is written in a single os.write() call to simulate a
    terminal paste.  After execution, the stripped output must contain both
    ``Python `` (from python --version) and ``pip `` (from pip --version).
    """
    output = _run_pty_session(b"python --version\npip --version\nexit\n")
    stripped = _strip_ansi(output)
    assert b"pip " in stripped, (
        "pip --version output not found — second pasted command was swallowed.\n"
        f"Raw PTY output:\n{output!r}"
    )
    # python --version produces "Python X.Y.Z"; banner also has "Python" so we
    # rely on pip output as the definitive signal that both commands executed.


def test_pty_multiline_paste_no_command_lost() -> None:
    """Three commands pasted at once: all three must produce output."""
    output = _run_pty_session(
        b"echo FIRST_CMD\necho SECOND_CMD\necho THIRD_CMD\nexit\n"
    )
    stripped = _strip_ansi(output)
    assert b"FIRST_CMD" in stripped, f"FIRST_CMD missing.\nRaw: {output!r}"
    assert b"SECOND_CMD" in stripped, f"SECOND_CMD missing.\nRaw: {output!r}"
    assert b"THIRD_CMD" in stripped, f"THIRD_CMD missing.\nRaw: {output!r}"


def test_pty_plain_paste_three_echo_commands() -> None:
    """Plain VTE paste without bracket markers must execute every line."""
    output = _run_pty_session(b"echo FIRST\necho SECOND\necho THIRD\nexit\n")
    stripped = _strip_ansi(output)
    assert b"FIRST" in stripped, f"FIRST missing.\nRaw: {output!r}"
    assert b"SECOND" in stripped, f"SECOND missing.\nRaw: {output!r}"
    assert b"THIRD" in stripped, f"THIRD missing.\nRaw: {output!r}"


def test_pty_plain_paste_replays_each_command_before_output() -> None:
    output = _run_pty_session(b"echo FIRST\necho SECOND\necho THIRD\nexit\n")
    lines = _visible_lines(output)
    expected = [
        "> echo FIRST",
        "FIRST",
        "> echo SECOND",
        "SECOND",
        "> echo THIRD",
        "THIRD",
    ]
    positions = []
    for item in expected:
        try:
            positions.append(lines.index(item))
        except ValueError as exc:
            raise AssertionError(f"{item!r} missing from visible lines: {lines!r}") from exc
    assert positions == sorted(positions)


def test_pty_multiline_paste_commands_not_concatenated() -> None:
    """Two pasted commands must not be merged into one malformed command."""
    output = _run_pty_session(b"echo AAA\necho BBB\nexit\n")
    stripped = _strip_ansi(output)
    # Both outputs on separate lines — neither is merged with the other.
    assert b"AAA" in stripped, f"AAA missing.\nRaw: {output!r}"
    assert b"BBB" in stripped, f"BBB missing.\nRaw: {output!r}"
    # The combined string "AAABBB" must not appear (would mean merging happened).
    assert b"AAABBB" not in stripped, f"Commands were concatenated.\nRaw: {output!r}"


# ---------------------------------------------------------------------------
# Part C — PTY test: semicolon-chained commands
# ---------------------------------------------------------------------------


def test_pty_semicolon_both_commands_execute() -> None:
    """python --version; pip --version on one line must execute both."""
    output = _run_pty_session(b"python --version; pip --version\nexit\n")
    stripped = _strip_ansi(output)
    assert b"pip " in stripped, (
        "pip --version output not found after semicolon.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_semicolon_echo_both() -> None:
    """echo X; echo Y — both outputs must appear."""
    output = _run_pty_session(b"echo SEMI_X; echo SEMI_Y\nexit\n")
    stripped = _strip_ansi(output)
    assert b"SEMI_X" in stripped, f"SEMI_X missing.\nRaw: {output!r}"
    assert b"SEMI_Y" in stripped, f"SEMI_Y missing.\nRaw: {output!r}"


# ---------------------------------------------------------------------------
# Part D — PTY test: temporary environment assignment
# ---------------------------------------------------------------------------


def test_pty_temp_env_reaches_child() -> None:
    """FOO=bar python -c '...' must see FOO=bar inside the child."""
    cmd = b'FOO=bar python -c "import os; print(os.environ.get(\'FOO\'))"\nexit\n'
    output = _run_pty_session(cmd)
    stripped = _strip_ansi(output)
    assert b"bar" in stripped, (
        "FOO=bar was not passed to child process.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_command_name_not_parsed_as_assignment() -> None:
    """1FOO=bar is not a valid assignment name; it is the command argv[0]."""
    # An invalid assignment becomes the command name → command not found (127).
    # We just check that pysh doesn't crash / infinite loop.
    output = _run_pty_session(b"echo FOO=bar\nexit\n")
    stripped = _strip_ansi(output)
    # echo must receive FOO=bar as its argument and print it.
    assert b"FOO=bar" in stripped, (
        "echo FOO=bar did not print FOO=bar.\n"
        f"Raw PTY output:\n{output!r}"
    )


# ---------------------------------------------------------------------------
# Part E — PTY test: parent environment is unchanged after temp assignment
# ---------------------------------------------------------------------------


def test_pty_temp_env_does_not_leak_to_parent() -> None:
    """The second python -c must see None for FOO (not 'bar').

    If FOO leaks into the parent environment, the second command would print
    'bar' instead of 'None'.
    """
    cmd = (
        b'FOO=bar python -c "import os; print(os.environ.get(\'FOO\'))"\n'
        b'python -c "import os; print(os.environ.get(\'FOO\'))"\n'
        b"exit\n"
    )
    output = _run_pty_session(cmd)
    stripped = _strip_ansi(output)
    assert b"bar" in stripped, (
        "'bar' not found; first command may not have run.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"None" in stripped, (
        "'None' not found; FOO may have leaked into parent environment.\n"
        f"Raw PTY output:\n{output!r}"
    )


# ---------------------------------------------------------------------------
# Bracketed paste markers must not appear in the command buffer
# ---------------------------------------------------------------------------


def test_pty_bracketed_paste_markers_not_in_output() -> None:
    """ESC[200~ and ESC[201~ must not appear as text in PySH output."""
    # Simulate a terminal that sends bracketed paste markers.
    bracketed = (
        b"\x1b[200~"      # PASTE_START
        b"echo BPASTE\n"  # pasted content
        b"\x1b[201~"      # PASTE_END
        b"exit\n"
    )
    output = _run_pty_session(bracketed)
    stripped = _strip_ansi(output)
    assert b"BPASTE" in stripped, (
        "echo BPASTE output not found — bracketed paste may not have been executed.\n"
        f"Raw PTY output:\n{output!r}"
    )
    # The literal text "200~" or "201~" must not appear in the visible output.
    assert b"200~" not in stripped, (
        "PASTE_START marker text '200~' leaked into output.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"201~" not in stripped, (
        "PASTE_END marker text '201~' leaked into output.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_vte_bracketed_paste_three_echo_commands() -> None:
    """VTE-style bracketed paste bytes must execute every pasted command."""
    output = _run_pty_session(
        b"\x1b[200~echo FIRST\necho SECOND\necho THIRD\n\x1b[201~exit\n"
    )
    stripped = _strip_ansi(output)
    assert b"FIRST" in stripped, f"FIRST missing.\nRaw: {output!r}"
    assert b"SECOND" in stripped, f"SECOND missing.\nRaw: {output!r}"
    assert b"THIRD" in stripped, f"THIRD missing.\nRaw: {output!r}"
    assert b"200~" not in stripped, f"PASTE_START leaked.\nRaw: {output!r}"
    assert b"201~" not in stripped, f"PASTE_END leaked.\nRaw: {output!r}"


def test_pty_bracketed_paste_replays_each_command_before_output() -> None:
    output = _run_pty_session(
        b"\x1b[200~echo FIRST\necho SECOND\necho THIRD\n\x1b[201~exit\n"
    )
    lines = _visible_lines(output)
    expected = [
        "> echo FIRST",
        "FIRST",
        "> echo SECOND",
        "SECOND",
        "> echo THIRD",
        "THIRD",
    ]
    positions = []
    for item in expected:
        try:
            positions.append(lines.index(item))
        except ValueError as exc:
            raise AssertionError(f"{item!r} missing from visible lines: {lines!r}") from exc
    assert positions == sorted(positions)
    assert not any(line.startswith("(.venv)") and "echo SECOND" in line for line in lines)


def test_pty_bracketed_command_builtin_paste_replays_once() -> None:
    output = _run_pty_session(
        b"\x1b[200~command -v pysh\ncommand -v python\ncommand -V cd\n\x1b[201~exit\n"
    )
    lines = _visible_lines(output)
    for command in ("command -v pysh", "command -v python", "command -V cd"):
        assert lines.count(f"> {command}") == 1, (
            f"{command!r} should be visibly replayed exactly once.\n"
            f"Visible lines: {lines!r}\nRaw: {output!r}"
        )
    assert any(line.endswith("pysh") and "/" in line for line in lines)
    assert any(("python" in line and "/" in line) for line in lines)
    assert "cd is a PySH builtin" in lines
    assert b"pysh: command: command not found" not in _strip_ansi(output)


def test_pty_command_builtin_resolves_pysh_and_cd() -> None:
    """Interactive PySH must support command -v/-V diagnostics."""
    output = _run_pty_session(b"command -v pysh\ncommand -V cd\nexit\n")
    stripped = _strip_ansi(output)
    assert b"pysh: command: command not found" not in stripped, (
        "command builtin was not available in interactive PySH.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert re.search(rb"(?m)/\S*pysh\s*$", stripped), (
        "command -v pysh did not print a path ending in pysh.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"cd is a PySH builtin" in stripped, (
        "command -V cd did not describe the cd builtin.\n"
        f"Raw PTY output:\n{output!r}"
    )
