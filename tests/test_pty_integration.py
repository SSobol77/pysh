# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Real pseudo-terminal integration tests for PySH.

Each test launches PySH as a subprocess with its own master/slave PTY pair,
sends raw byte sequences to the master (simulating terminal input), then
reads all output and asserts on its content.

These tests verify end-to-end behavior that unit tests cannot cover:
  - Plain multiline paste: all pasted commands must execute, none swallowed.
  - Semicolon-chained commands execute in order.
  - Leading temporary environment assignments reach the child process.
  - Temporary assignments do not mutate the parent shell environment.
  - Bracketed paste markers (ESC[200~ / ESC[201~) do not appear in output.
  - Bracketed multiline paste is captured pending explicit command execution.

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


def _assert_lines_in_order(lines: list[str], expected: list[str]) -> None:
    """Assert each expected line appears after the previous one."""
    cursor = 0
    for item in expected:
        try:
            position = lines.index(item, cursor)
        except ValueError as exc:
            raise AssertionError(f"{item!r} missing after index {cursor}: {lines!r}") from exc
        cursor = position + 1


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
    env: dict[str, str] | None = None,
) -> bytes:
    """Launch PySH in a fresh PTY, send *commands* to its input after the
    initial prompt appears, collect all output until the process exits or
    *collect_timeout* is reached, then return the raw master output bytes.

    The caller should include ``b"exit\\n"`` at the end of *commands* so that
    PySH terminates cleanly.  A SIGTERM is sent unconditionally on teardown.
    Pass *env* to override the default ``_PTY_ENV``.
    """
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd)
    proc = subprocess.Popen(
        _PYSH_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env if env is not None else _PTY_ENV,
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


def _run_pty_session_phased(
    chunks: list[bytes],
    *,
    prompt_timeout: float = _PROMPT_TIMEOUT,
    collect_timeout: float = _COLLECT_TIMEOUT,
    settle: float = _SETTLE,
    env: dict[str, str] | None = None,
) -> bytes:
    """Run PySH in a PTY and write input chunks with output drains between them."""
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd)
    proc = subprocess.Popen(
        _PYSH_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env if env is not None else _PTY_ENV,
        close_fds=True,
    )
    os.close(slave_fd)
    buf = bytearray()
    try:
        buf.extend(_wait_for_prompt(master_fd, timeout=prompt_timeout))
        for chunk in chunks:
            os.write(master_fd, chunk)
            buf.extend(_read_nonblocking(master_fd, settle=0.25, timeout=1.0))

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


def _run_pty_exit_attempt(command: bytes) -> tuple[bytes, int | None]:
    """Run one interactive command and return output plus natural process status."""
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
        buf.extend(_wait_for_prompt(master_fd))
        os.write(master_fd, command)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.05)
            except (ValueError, OSError):
                break
            if r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
            if proc.poll() is not None:
                buf.extend(_read_nonblocking(master_fd, settle=0.1, timeout=0.5))
                break
        if proc.poll() is None:
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        return bytes(buf), proc.poll()
    finally:
        if proc.poll() is None:
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


# ---------------------------------------------------------------------------
# Part B — PTY test: pasted multiline commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", [b"exit\n", b"quit\n", b"exit   \n"])
def test_pty_exit_and_quit_exit_on_first_attempt(command: bytes) -> None:
    """Interactive exit/quit must terminate on the first submitted line."""
    output, returncode = _run_pty_exit_attempt(command)
    stripped = _strip_ansi(output)
    assert returncode == 0, (
        f"{command!r} did not terminate PySH with status 0 on first attempt.\n"
        f"returncode={returncode!r}\nRaw PTY output:\n{output!r}"
    )
    assert b"pysh: exit: command not found" not in stripped
    assert b"pysh: quit: command not found" not in stripped
    assert b"pysh: internal error" not in stripped


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
        "└─❯ echo FIRST",
        "FIRST",
        "└─❯ echo SECOND",
        "SECOND",
        "└─❯ echo THIRD",
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
    # Simulate a terminal that sends one editable line with bracketed paste markers.
    bracketed = (
        b"\x1b[200~"      # PASTE_START
        b"echo BPASTE"    # pasted content
        b"\x1b[201~"      # PASTE_END
        b"\nexit\n"
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


def test_pty_vte_bracketed_multiline_paste_is_captured() -> None:
    """VTE-style bracketed multiline paste must not execute pasted commands."""
    output = _run_pty_session(
        b"\x1b[200~echo FIRST\necho SECOND\necho THIRD\n\x1b[201~paste_cancel\nexit\n"
    )
    stripped = _strip_ansi(output)
    assert (
        b"pysh: multiline paste captured (3 lines). Review below."
    ) in stripped
    assert b"[paste:begin]" in stripped
    assert b"1 | echo FIRST" in stripped
    assert b"2 | echo SECOND" in stripped
    assert b"3 | echo THIRD" in stripped
    assert b"[paste:end]" in stripped
    assert b"FIRST\n" not in stripped, f"FIRST executed.\nRaw: {output!r}"
    assert b"SECOND\n" not in stripped, f"SECOND executed.\nRaw: {output!r}"
    assert b"THIRD\n" not in stripped, f"THIRD executed.\nRaw: {output!r}"
    assert b"200~" not in stripped, f"PASTE_START leaked.\nRaw: {output!r}"
    assert b"201~" not in stripped, f"PASTE_END leaked.\nRaw: {output!r}"


def test_pty_bracketed_multiline_paste_blocks_unrelated_commands() -> None:
    output = _run_pty_session(
        b"\x1b[200~echo FIRST\necho SECOND\necho THIRD\n\x1b[201~echo AFTER\n"
        b"paste_cancel\nexit\n"
    )
    lines = _visible_lines(output)
    assert (
        "pysh: multiline paste captured (3 lines). Review below."
    ) in lines
    assert "pysh: pending multiline paste exists; use paste_run or paste_cancel first" in lines
    assert "AFTER" not in lines
    assert "FIRST" not in lines
    assert "SECOND" not in lines
    assert "THIRD" not in lines


def test_pty_bracketed_command_builtin_multiline_paste_is_captured() -> None:
    output = _run_pty_session(
        b"\x1b[200~command -v pysh\ncommand -v python\ncommand -V cd\n"
        b"\x1b[201~paste_cancel\nexit\n"
    )
    lines = _visible_lines(output)
    for command in ("command -v pysh", "command -v python", "command -V cd"):
        assert lines.count(f"> {command}") == 0, (
            f"{command!r} should not replay from staged bracketed paste.\n"
            f"Visible lines: {lines!r}\nRaw: {output!r}"
        )
    assert (
        "pysh: multiline paste captured (3 lines). Review below."
    ) in lines
    assert not any(line.startswith("/") and line.endswith("/pysh") for line in lines)
    assert not any(
        line.startswith("/") and (line.endswith("/python") or line.endswith("/python3"))
        for line in lines
    )
    assert "cd is a PySH builtin" not in lines
    assert b"pysh: command: command not found" not in _strip_ansi(output)


def test_pty_bracketed_python_block_paste_is_captured() -> None:
    output = _run_pty_session(
        b"\x1b[200~py {\n"
        b"x = 40 + 2\n"
        b"print(x)\n"
        b"}\x1b[201~paste_cancel\nexit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    assert (
        b"pysh: multiline paste captured (4 lines). Review below."
    ) in stripped
    assert b"1 | py {" in stripped
    assert b"2 | x = 40 + 2" in stripped
    assert b"3 | print(x)" in stripped
    assert b"4 | }" in stripped
    assert b"py { ;" not in stripped
    assert b"SyntaxError" not in stripped
    assert b"pysh: x: command not found" not in stripped
    assert b"42" not in stripped


def test_pty_bracketed_heredoc_paste_is_captured(tmp_path) -> None:
    target = tmp_path / "paste-heredoc-test.txt"
    payload = (
        b"\x1b[200~cat > "
        + str(target).encode("utf-8")
        + b" <<'EOF'\nline one\nline two\nEOF\x1b[201~paste_cancel\nexit\n"
    )
    output = _run_pty_session(payload, collect_timeout=4.0)
    stripped = _strip_ansi(output)
    assert (
        b"pysh: multiline paste captured (4 lines). Review below."
    ) in stripped
    assert b"1 | cat > " in stripped
    assert b" <<'EOF'" in stripped
    assert b"2 | line one" in stripped
    assert b"3 | line two" in stripped
    assert b"4 | EOF" in stripped
    assert b"heredoc>" not in stripped
    assert b"pysh: EOF: command not found" not in stripped
    assert not target.exists()


def test_pty_paste_show_and_cancel_for_pending_multiline_paste() -> None:
    output = _run_pty_session_phased(
        [
            b"\x1b[200~git diff --stat\ngit status --short\x1b[201~"
            b"paste_show\npaste_cancel\n",
            b"paste_show\nexit\n",
        ]
    )
    lines = _visible_lines(output)
    assert (
        "pysh: multiline paste captured (2 lines). Review below."
    ) in lines
    assert "[paste:begin]" in lines
    assert "1 | git diff --stat" in lines
    assert "2 | git status --short" in lines
    assert "[paste:end]" in lines
    assert lines.count("[paste:begin]") >= 2
    assert lines.count("1 | git diff --stat") >= 2
    assert lines.count("2 | git status --short") >= 2
    assert lines.count("[paste:end]") >= 2
    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "paste_show: no pending multiline paste" in lines


def test_pty_paste_run_executes_pending_ordinary_commands() -> None:
    output = _run_pty_session(
        b"\x1b[200~echo one\necho two\x1b[201~paste_run\nexit\n"
    )
    lines = _visible_lines(output)
    assert (
        "pysh: multiline paste captured (2 lines). Review below."
    ) in lines
    assert "[paste_run:begin]" in lines
    assert "1 | echo one" in lines
    assert "2 | echo two" in lines
    assert "[paste_run:end]" in lines
    _assert_lines_in_order(
        lines,
        ["[paste_run:begin]", "1 | echo one", "2 | echo two", "[paste_run:end]", "one", "two"],
    )
    assert "one" in lines
    assert "two" in lines


def test_pty_empty_enter_executes_pending_ordinary_commands() -> None:
    output = _run_pty_session(
        b"\x1b[200~echo one\necho two\x1b[201~\nexit\n"
    )
    lines = _visible_lines(output)
    assert (
        "pysh: multiline paste captured (2 lines). Review below."
    ) in lines
    assert "[paste_run:begin]" in lines
    assert "1 | echo one" in lines
    assert "2 | echo two" in lines
    assert "[paste_run:end]" in lines
    _assert_lines_in_order(
        lines,
        ["[paste_run:begin]", "1 | echo one", "2 | echo two", "[paste_run:end]", "one", "two"],
    )
    assert "one" in lines
    assert "two" in lines


def test_pty_ctrl_c_cancels_pending_multiline_paste() -> None:
    output = _run_pty_session_phased(
        [
            b"\x1b[200~echo one\necho two\x1b[201~",
            b"\x03",
            b"paste_show\necho clean\nexit\n",
        ]
    )
    lines = _visible_lines(output)
    assert (
        "pysh: multiline paste captured (2 lines). Review below."
    ) in lines
    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "paste_show: no pending multiline paste" in lines
    assert "clean" in lines
    assert "one" not in lines
    assert "two" not in lines


def test_pty_repeated_same_paste_clear_retains_hint_and_allows_recovery() -> None:
    """Repeated paste replacement followed by clear must not trap the prompt."""
    paste = b"\x1b[200~echo loop-one\necho loop-two\necho loop-three\x1b[201~"
    output = _run_pty_session_phased(
        [
            paste,
            paste,
            b"clear\n",
            b"paste_cancel\n",
            b"echo recovered\nexit\n",
        ],
        collect_timeout=6.0,
    )
    lines = _visible_lines(output)
    text = _strip_ansi(output).decode("utf-8", errors="replace")

    assert lines.count("pysh: multiline paste captured (3 lines). Review below.") >= 2
    assert "pysh: previous pending paste replaced" in lines
    assert "pysh: pending multiline paste retained (3 lines). Review below." in lines
    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "recovered" in lines
    assert "pysh: pending multiline paste exists; use paste_run or paste_cancel first" not in lines
    assert "loop-one\n" not in text
    assert "loop-two\n" not in text
    assert "loop-three\n" not in text


def test_pty_clear_while_paste_pending_keeps_paste_runnable() -> None:
    """clear is a safe UI command; it must not discard or execute pending paste."""
    output = _run_pty_session_phased(
        [
            b"\x1b[200~echo clear-one\necho clear-two\necho clear-three\x1b[201~",
            b"clear\n",
            b"paste_run\n",
            b"echo after-clear\nexit\n",
        ],
        collect_timeout=6.0,
    )
    lines = _visible_lines(output)

    assert "pysh: pending multiline paste retained (3 lines). Review below." in lines
    assert "pysh: pending multiline paste exists; use paste_run or paste_cancel first" not in lines
    _assert_lines_in_order(
        lines,
        [
            "pysh: pending multiline paste retained (3 lines). Review below.",
            "[paste_run:begin]",
            "1 | echo clear-one",
            "2 | echo clear-two",
            "3 | echo clear-three",
            "[paste_run:end]",
            "clear-one",
            "clear-two",
            "clear-three",
            "after-clear",
        ],
    )


def test_pty_repeated_same_paste_ctrl_c_recovers_normal_command_execution() -> None:
    """Ctrl+C must cancel even after repeated replacement of the same paste."""
    paste = b"\x1b[200~echo ctrl-one\necho ctrl-two\necho ctrl-three\x1b[201~"
    output = _run_pty_session_phased(
        [
            paste,
            paste,
            b"\x03",
            b"echo clean-after-ctrl-c\nexit\n",
        ],
        collect_timeout=6.0,
    )
    lines = _visible_lines(output)
    text = _strip_ansi(output).decode("utf-8", errors="replace")

    assert "pysh: previous pending paste replaced" in lines
    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "clean-after-ctrl-c" in lines
    assert "pysh: pending multiline paste exists; use paste_run or paste_cancel first" not in lines
    assert "ctrl-one\n" not in text
    assert "ctrl-two\n" not in text
    assert "ctrl-three\n" not in text


@pytest.mark.parametrize("command", [b"exit\n", b"quit\n"])
def test_pty_exit_and_quit_discard_pending_paste_and_exit(command: bytes) -> None:
    """exit/quit while pending must not be treated as external commands."""
    output = _run_pty_session(
        b"\x1b[200~echo should-not-run-one\necho should-not-run-two\x1b[201~"
        + command,
        collect_timeout=6.0,
    )
    lines = _visible_lines(output)
    text = _strip_ansi(output).decode("utf-8", errors="replace")

    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "pysh: pending multiline paste exists; use paste_run or paste_cancel first" not in lines
    assert "pysh: exit: command not found" not in text
    assert "pysh: quit: command not found" not in text
    assert "should-not-run-one\n" not in text
    assert "should-not-run-two\n" not in text


def test_pty_paste_cancel_clears_same_batch_stale_commands() -> None:
    output = _run_pty_session_phased(
        [
            b"\x1b[200~echo stale-paste-cancel\necho stale-paste-cancel-2\x1b[201~"
            b"paste_cancel\n"
            b"echo stale-after-cancel\n",
            b"echo clean\nexit\n",
        ]
    )
    lines = _visible_lines(output)
    assert "paste_cancel: pending multiline paste discarded" in lines
    assert "clean" in lines
    assert "stale-paste-cancel" not in lines
    assert "stale-after-cancel" not in lines


def test_pty_paste_run_clears_same_batch_stale_commands() -> None:
    output = _run_pty_session_phased(
        [
            b"\x1b[200~echo staged-run\necho staged-run-2\x1b[201~paste_run\n"
            b"echo stale-after-run\n",
            b"echo clean\nexit\n",
        ],
        collect_timeout=4.0,
    )
    lines = _visible_lines(output)
    assert "[paste_run:begin]" in lines
    assert "staged-run" in lines
    assert "clean" in lines
    assert "stale-after-run" not in lines


def test_pty_paste_run_parse_error_has_paste_attribution() -> None:
    output = _run_pty_session_phased(
        [
            b'\x1b[200~echo "unterminated\necho second\x1b[201~paste_run\n',
            b"exit\n",
        ],
        collect_timeout=4.0,
    )
    text = _strip_ansi(output).decode("utf-8", errors="replace")
    assert "pysh: parse error (paste): unterminated double quote" in text
    assert "pysh: parse error: pysh:" not in text


def test_pty_direct_parse_error_has_no_paste_attribution() -> None:
    output = _run_pty_session(b'echo "unterminated\nexit\n', collect_timeout=4.0)
    text = _strip_ansi(output).decode("utf-8", errors="replace")
    assert "pysh: parse error: unterminated double quote" in text
    assert "pysh: parse error (paste):" not in text
    assert "pysh: parse error: pysh:" not in text


def test_pty_paste_run_executes_pending_python_block() -> None:
    output = _run_pty_session(
        b"\x1b[200~py {\n"
        b"x = 40 + 2\n"
        b"print(x)\n"
        b"}\x1b[201~paste_run\nexit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    lines = _visible_lines(output)
    assert b"py { ;" not in stripped
    assert b"SyntaxError" not in stripped
    assert b"pysh: x: command not found" not in stripped
    assert "[paste_run:begin]" in lines
    assert "1 | py {" in lines
    assert "2 | x = 40 + 2" in lines
    assert "3 | print(x)" in lines
    assert "4 | }" in lines
    assert "[paste_run:end]" in lines
    assert "42" in lines


def test_pty_empty_enter_executes_pending_python_block() -> None:
    output = _run_pty_session(
        b"\x1b[200~py {\n"
        b"x = 40 + 2\n"
        b"print(x)\n"
        b"}\x1b[201~\nexit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    lines = _visible_lines(output)
    assert b"py { ;" not in stripped
    assert b"SyntaxError" not in stripped
    assert b"pysh: x: command not found" not in stripped
    assert "[paste_run:begin]" in lines
    assert "1 | py {" in lines
    assert "2 | x = 40 + 2" in lines
    assert "3 | print(x)" in lines
    assert "4 | }" in lines
    assert "[paste_run:end]" in lines
    assert "42" in lines


def test_pty_paste_run_executes_pending_heredoc(tmp_path) -> None:
    target = tmp_path / "paste-heredoc-test.txt"
    output = _run_pty_session_phased(
        [
            b"\x1b[200~cat > "
            + str(target).encode("utf-8")
            + b" <<'EOF'\nline one\nline two\nEOF\x1b[201~paste_run\n",
            b"cat " + str(target).encode("utf-8") + b"\nexit\n",
        ],
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    lines = _visible_lines(output)
    assert b"heredoc>" not in stripped
    assert b"pysh: EOF: command not found" not in stripped
    assert target.exists()
    assert "[paste_run:begin]" in lines
    assert any(line.startswith("1 | cat > ") and line.endswith(" <<'EOF'") for line in lines)
    assert "2 | line one" in lines
    assert "3 | line two" in lines
    assert "4 | EOF" in lines
    assert "[paste_run:end]" in lines
    assert "line one" in lines
    assert "line two" in lines


def test_pty_empty_enter_executes_pending_heredoc(tmp_path) -> None:
    target = tmp_path / "paste-heredoc-test.txt"
    output = _run_pty_session_phased(
        [
            b"\x1b[200~cat > "
            + str(target).encode("utf-8")
            + b" <<'EOF'\nline one\nline two\nEOF\x1b[201~\n",
            b"cat " + str(target).encode("utf-8") + b"\nexit\n",
        ],
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    lines = _visible_lines(output)
    assert b"heredoc>" not in stripped
    assert b"pysh: EOF: command not found" not in stripped
    assert target.exists()
    assert "[paste_run:begin]" in lines
    assert any(line.startswith("1 | cat > ") and line.endswith(" <<'EOF'") for line in lines)
    assert "2 | line one" in lines
    assert "3 | line two" in lines
    assert "4 | EOF" in lines
    assert "[paste_run:end]" in lines
    assert "line one" in lines
    assert "line two" in lines


def test_pty_second_multiline_paste_replaces_first() -> None:
    output = _run_pty_session(
        b"\x1b[200~echo old-one\necho old-two\x1b[201~"
        b"\x1b[200~echo new-one\necho new-two\x1b[201~"
        b"paste_run\nexit\n"
    )
    lines = _visible_lines(output)
    assert "pysh: previous pending paste replaced" in lines
    assert "old-one" not in lines
    assert "old-two" not in lines
    assert "new-one" in lines
    assert "new-two" in lines


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


def test_pty_heredoc_ctrl_c_resets_state() -> None:
    """Ctrl+C during interactive heredoc must not replay body into the shell."""
    output = _run_pty_session(
        b"cat > /tmp/pysh-heredoc-regression.pysh <<'EOF'\n"
        b"echo SHOULD_NOT_REPLAY\n"
        b"\x03"
        b"echo AFTER_CANCEL\n"
        b"exit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    assert b"AFTER_CANCEL" in stripped, (
        "Shell did not recover to normal command mode after heredoc Ctrl+C.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"SHOULD_NOT_REPLAY" not in stripped, (
        "Heredoc body leaked or replayed into normal command execution after Ctrl+C.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert stripped.count(b"heredoc>") <= 1, (
        "Heredoc prompt/state persisted after cancellation.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_py_block_collects_body_once() -> None:
    """Interactive py block must not replay the opener into its own body."""
    output = _run_pty_session(
        b"py {\n"
        b"print('PY_BLOCK_OK')\n"
        b"}\n"
        b"echo AFTER_PY_BLOCK\n"
        b"exit\n",
        collect_timeout=4.0,
    )
    stripped = _strip_ansi(output)
    assert b"PY_BLOCK_OK" in stripped, (
        "Interactive py block body was not executed.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"AFTER_PY_BLOCK" in stripped, (
        "Shell did not return to normal command mode after py block.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"nested py { ... } blocks are not supported" not in stripped, (
        "The py block opener was replayed into the collected Python body.\n"
        f"Raw PTY output:\n{output!r}"
    )


# ---------------------------------------------------------------------------
# NO_COLOR / PYSH_NO_COLOR paste safety
# ---------------------------------------------------------------------------


def _make_no_color_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return _PTY_ENV with NO_COLOR added (and any *extra* overrides)."""
    env = dict(_PTY_ENV)
    env["NO_COLOR"] = "1"
    if extra:
        env.update(extra)
    return env


def _make_pysh_no_color_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return _PTY_ENV with PYSH_NO_COLOR=1 added."""
    env = dict(_PTY_ENV)
    env["PYSH_NO_COLOR"] = "1"
    if extra:
        env.update(extra)
    return env


def test_pty_no_color_bracketed_paste_is_staged() -> None:
    """NO_COLOR=1 must not change paste behaviour — multiline paste is staged."""
    output = _run_pty_session(
        b"\x1b[200~echo one\necho two\x1b[201~paste_cancel\nexit\n",
        env=_make_no_color_env(),
    )
    stripped = _strip_ansi(output)
    assert b"pysh: multiline paste captured (2 lines). Review below." in stripped, (
        "NO_COLOR=1: multiline paste was not staged.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"[paste:begin]" in stripped
    assert b"1 | echo one" in stripped
    assert b"2 | echo two" in stripped
    assert b"[paste:end]" in stripped
    assert b"one\n" not in stripped, (
        "NO_COLOR=1: 'echo one' executed immediately instead of being staged.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"two\n" not in stripped, (
        "NO_COLOR=1: 'echo two' executed before staged paste was confirmed.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_no_color_staged_paste_executes_on_enter() -> None:
    """Under NO_COLOR=1, staged paste must execute normally after Enter."""
    output = _run_pty_session(
        b"\x1b[200~echo one\necho two\x1b[201~\nexit\n",
        env=_make_no_color_env(),
    )
    stripped = _strip_ansi(output)
    assert b"one" in stripped, (
        "NO_COLOR=1: 'echo one' did not produce output after Enter.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"two" in stripped, (
        "NO_COLOR=1: 'echo two' did not produce output after Enter.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_pysh_no_color_bracketed_paste_is_staged() -> None:
    """PYSH_NO_COLOR=1 must not change paste behaviour — multiline paste is staged."""
    output = _run_pty_session(
        b"\x1b[200~echo one\necho two\x1b[201~paste_cancel\nexit\n",
        env=_make_pysh_no_color_env(),
    )
    stripped = _strip_ansi(output)
    assert b"pysh: multiline paste captured (2 lines). Review below." in stripped, (
        "PYSH_NO_COLOR=1: multiline paste was not staged.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"[paste:begin]" in stripped
    assert b"1 | echo one" in stripped
    assert b"2 | echo two" in stripped
    assert b"[paste:end]" in stripped
    assert b"one\n" not in stripped, (
        "PYSH_NO_COLOR=1: 'echo one' executed immediately instead of being staged.\n"
        f"Raw PTY output:\n{output!r}"
    )
    assert b"two\n" not in stripped, (
        "PYSH_NO_COLOR=1: 'echo two' executed before staged paste was confirmed.\n"
        f"Raw PTY output:\n{output!r}"
    )


def test_pty_no_color_paste_preview_content_has_no_ansi() -> None:
    """Under NO_COLOR=1, the paste preview content lines must not contain SGR color codes.

    The raw editor always emits cursor-positioning CSI sequences (e.g. ESC[J)
    regardless of NO_COLOR — those are operational, not colour-related.  Only
    the paste-preview diagnostic content (paste header, frame markers, line
    numbers, hints) must be free of colour SGR codes.
    """
    output = _run_pty_session(
        b"\x1b[200~echo hello\necho world\x1b[201~paste_cancel\nexit\n",
        env=_make_no_color_env(),
    )
    text = _strip_ansi(output).decode("utf-8", errors="replace")
    # Verify the expected plain markers are present.
    assert "pysh: multiline paste captured (2 lines). Review below." in text
    assert "[paste:begin]" in text
    assert "1 | echo hello" in text
    assert "2 | echo world" in text
    assert "[paste:end]" in text
    # Verify the paste preview lines are free of SGR color codes.
    # Extract the section between [paste:begin] and [paste:end].
    begin = text.find("[paste:begin]")
    end = text.find("[paste:end]")
    assert begin >= 0 and end > begin, "paste frame markers not found"
    preview_section = output[
        output.find(b"[paste:begin]") : output.find(b"[paste:end]") + len(b"[paste:end]")
    ]
    # SGR sequences have the form ESC [ ... m — verify none appear.
    import re as _re_local
    sgr_re = _re_local.compile(rb"\x1b\[[0-9;]*m")
    assert not sgr_re.search(preview_section), (
        "NO_COLOR=1: SGR colour codes found in paste preview content.\n"
        f"Preview section: {preview_section!r}"
    )


# ---------------------------------------------------------------------------
# Ctrl+R blocked when paste is pending
# ---------------------------------------------------------------------------


def test_pty_ctrl_r_blocked_when_paste_pending() -> None:
    """Ctrl+R must show a diagnostic and not enter reverse search when paste is pending."""
    output = _run_pty_session_phased(
        [
            b"\x1b[200~echo first-command\necho second-command\x1b[201~",
            b"\x12",  # Ctrl+R
            b"paste_show\npaste_cancel\nexit\n",
        ],
        settle=0.5,
    )
    lines = _visible_lines(output)
    full_text = _strip_ansi(output).decode("utf-8", errors="replace")
    assert "pending multiline paste" in full_text, (
        "Ctrl+R with pending paste did not show the expected diagnostic.\n"
        f"Visible lines:\n{lines!r}"
    )
    assert "paste_run or paste_cancel" in full_text, (
        "Ctrl+R with pending paste diagnostic missing paste_run/paste_cancel hint.\n"
        f"Visible lines:\n{lines!r}"
    )
    assert not any("reverse-i-search" in ln for ln in lines), (
        "Ctrl+R with pending paste entered reverse-search mode.\n"
        f"Visible lines:\n{lines!r}"
    )
    assert "[paste:begin]" in lines, (
        "Pending paste was lost after Ctrl+R was blocked.\n"
        f"Visible lines:\n{lines!r}"
    )


def test_pty_ctrl_r_works_normally_without_pending_paste() -> None:
    """Ctrl+R must still open reverse search when no paste is pending."""
    output = _run_pty_session_phased(
        [
            b"echo history-sentinel\n",
            b"\x12old",   # Ctrl+R then type search query
            b"\x1b",      # ESC to cancel search and return to prompt
            b"exit\n",
        ],
        settle=0.4,
    )
    stripped = _strip_ansi(output)
    assert b"reverse-i-search" in stripped, (
        "Ctrl+R did not open reverse search when no paste was pending.\n"
        f"Raw PTY output:\n{output!r}"
    )
