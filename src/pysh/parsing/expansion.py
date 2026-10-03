# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/parsing/expansion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Variable and command-substitution expansion helpers."""
from __future__ import annotations

import hmac
import os
import re
import secrets
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS = 5.0

_VAR_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_POSITIONAL_BRACED_RE = re.compile(r"[0-9]+|[?@#*]")
_UNSUPPORTED_PARAMETER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?::-|:=|:\?|#|%|/).+|^#[A-Za-z_][A-Za-z0-9_]*$"
)


def expand_variables(
    text: str,
    local_vars: dict[str, str],
    env_vars: dict[str, str] | None = None,
    *,
    special_vars: dict[str, str] | None = None,
) -> str:
    """Expand simple variable and special-parameter references in ``text``."""
    if env_vars is None:
        env_vars = dict(os.environ)
    _special = special_vars or {}

    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            out.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_double = not in_double
            out.append(c)
            i += 1
            continue
        if c == "$" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "?":
                out.append(_special.get("?", "0"))
                i += 2
                continue
            if nxt in "@#*":
                out.append(_special.get(nxt, ""))
                i += 2
                continue
            if nxt.isdigit():
                out.append(_special.get(nxt, ""))
                i += 2
                continue
            if nxt == "{":
                end = text.find("}", i + 2)
                if end == -1:
                    out.append(c)
                    i += 1
                    continue
                name = text[i + 2 : end]
                if _POSITIONAL_BRACED_RE.fullmatch(name):
                    out.append(_special.get(name, "0" if name == "?" else ""))
                    i = end + 1
                    continue
                if not _VAR_NAME_RE.fullmatch(name):
                    out.append(text[i : end + 1])
                    i = end + 1
                    continue
                value = local_vars.get(name)
                if value is None:
                    value = env_vars.get(name, "")
                out.append(value)
                i = end + 1
                continue
            m = _VAR_NAME_RE.match(text, i + 1)
            if m:
                name = m.group(0)
                value = local_vars.get(name)
                if value is None:
                    value = env_vars.get(name, "")
                out.append(value)
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


def is_unsupported_parameter_expansion(expr: str) -> bool:
    """Return True when braced parameter content is recognized but unsupported."""
    return bool(_UNSUPPORTED_PARAMETER_RE.fullmatch(expr))


#: INTERNAL transport (not public API, not a user feature): counts nested
#: substitution levels. It is DEPTH STATE ONLY and never changes job control.
SUBSTITUTION_DEPTH_ENV = "PYSH_SUBSTITUTION_DEPTH"
#: INTERNAL containment capability. A nested substitution process is told, by its
#: parent, that it runs inside a command-substitution execution domain (external
#: commands then stay in the domain's process group). The grant is an inherited
#: pipe that the parent filled with a random per-run token; this variable only
#: names it as ``<fd>:<token>``. Text in the environment alone grants nothing: the
#: descriptor must exist, be a FIFO and yield the matching token. It is consumed
#: once, at the first query, then closed and removed from the environment.
CAPABILITY_ENV = "PYSH_SUBSTITUTION_CAPABILITY"
_CAPABILITY_MAGIC = b"pysh-substitution-domain-v1:"
_CAPABILITY_RE = re.compile(r"([0-9]{1,6}):([0-9a-f]{32})\Z")
_containment: bool | None = None
#: Maximum nested substitution depth. Each level is a separate PySH process and
#: the text shrinks at every level, so this is only a deterministic backstop.
MAX_SUBSTITUTION_DEPTH = 32
_WAIT_POLL_START = 0.001
_WAIT_POLL_MAX = 0.02
#: Hard bounds on captured output. The capture is a pipe read by this process with
#: these exact limits, so the amount ever held (or written to disk) is bounded by
#: the limit plus one read chunk; the nested process simply blocks on a full pipe
#: while we read. Exceeding either bound is a controlled failure, never truncation.
MAX_SUBSTITUTION_STDOUT_BYTES = 4 * 1024 * 1024
MAX_SUBSTITUTION_STDERR_BYTES = 256 * 1024
_READ_CHUNK = 65536


@dataclass(frozen=True, slots=True)
class NestedResult:
    """Outcome of one nested PySH run (stderr is kept for diagnostics, never forwarded).

    ``timed_out`` and ``output_limited`` are explicit failure states: the text
    fields are empty in both, because a truncated or abandoned capture must never be
    mistaken for complete command output.
    """

    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: str | None = None  # "stdout" or "stderr" when that stream exceeded its bound


def _nested_environment(depth: int) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != CAPABILITY_ENV}
    env[SUBSTITUTION_DEPTH_ENV] = str(depth + 1)
    return env


def _current_depth() -> int:
    raw = os.environ.get(SUBSTITUTION_DEPTH_ENV, "0")
    return int(raw) if raw.isascii() and raw.isdigit() else 0


def _consume_capability() -> bool:
    """Validate and consume the containment capability inherited from a parent runner.

    The variable is always removed from this process's environment, so
    descendants cannot inherit a stale claim. The descriptor must be a FIFO that
    yields the matching token; it is closed only when it is the genuine
    capability. An unrelated descriptor named by a forged variable is never
    closed (a bounded prefix may be read from it, which only a deliberate forger
    who hands over a descriptor can cause).
    """
    raw = os.environ.pop(CAPABILITY_ENV, None)
    match = _CAPABILITY_RE.fullmatch(raw) if raw is not None else None
    if match is None:
        return False
    fd = int(match.group(1))
    expected = _CAPABILITY_MAGIC + match.group(2).encode("ascii")
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return False
        if not select.select([fd], [], [], 0)[0]:
            return False
        data = os.read(fd, len(expected) + 1)
    except (OSError, ValueError):
        return False
    if not hmac.compare_digest(data, expected):
        return False
    os.close(fd)
    return True


def in_substitution_domain() -> bool:
    """Return True when a parent substitution runner granted this process containment.

    Evaluated once per process (the capability is consumed); the depth variable
    plays no part.
    """
    global _containment
    if _containment is None:
        _containment = _consume_capability()
    return _containment


def _has_exited(process: subprocess.Popen[bytes]) -> bool:
    """Whether the leader has exited, WITHOUT reaping it.

    The zombie leader keeps the process-group id reserved until the whole group has
    been swept, so the id cannot be recycled for an unrelated process in between.
    """
    if hasattr(os, "waitid"):
        return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    return process.poll() is not None  # fallback: reaps early (tiny id-reuse window)


def _pump_until_exit(
    process: subprocess.Popen[bytes],
    deadline: float,
    buffers: dict[str, bytearray],
    limits: dict[str, int],
) -> str:
    """Read both streams until the leader exits. Returns ``exited``, ``timeout`` or the
    name of the stream that exceeded its bound. Never waits for EOF: a straggler that
    still holds a write end cannot block us."""
    assert process.stdout is not None and process.stderr is not None
    streams = {"stdout": process.stdout, "stderr": process.stderr}
    selector = selectors.DefaultSelector()
    for name, stream in streams.items():
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    pause = _WAIT_POLL_START
    try:
        while True:
            for key, _events in selector.select(pause):
                name = key.data
                try:
                    chunk = os.read(key.fd, _READ_CHUNK)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[name].extend(chunk)
                if len(buffers[name]) > limits[name]:
                    return name
            if _has_exited(process):
                return "exited"
            if time.monotonic() >= deadline:
                return "timeout"
            pause = min(pause * 2, _WAIT_POLL_MAX)
    finally:
        selector.close()


def _drain_after_exit(
    process: subprocess.Popen[bytes], buffers: dict[str, bytearray], limits: dict[str, int]
) -> str | None:
    """After the group is swept, read what is already in the pipes (non-blocking, bounded).

    Returns the name of a stream that exceeded its bound, else ``None``.
    """
    assert process.stdout is not None and process.stderr is not None
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        while True:
            try:
                chunk = os.read(stream.fileno(), _READ_CHUNK)
            except BlockingIOError:
                break
            if not chunk:
                break
            buffers[name].extend(chunk)
            if len(buffers[name]) > limits[name]:
                return name
    return None


def _decode(data: bytearray) -> str:
    return bytes(data).decode("utf-8", errors="replace")


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL the substitution's process group (the nested PySH is its leader)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _run_nested(
    command: str,
    timeout: float,
    *,
    max_stdout: int | None = None,
    max_stderr: int | None = None,
) -> NestedResult:
    """Run ``command`` as PySH source in an isolated nested PySH and capture its output.

    The nested process is PySH itself (never ``/bin/sh`` or another legacy
    shell): it parses and executes ``command`` with PySH's own grammar, reads no
    user startup configuration (``--no-rc``), and is started with ``-P`` so a
    ``pysh`` package in the working directory is never imported in place of the
    installed one. A fresh process is used because in-process nesting cannot
    isolate the working directory, exported environment, file descriptors and
    signal state, nor enforce the timeout. It inherits the exported environment
    and working directory and reads no stdin.

    Resource bounds: stdout and stderr are captured through pipes that this
    function reads with hard limits (``MAX_SUBSTITUTION_STDOUT_BYTES`` and
    ``MAX_SUBSTITUTION_STDERR_BYTES``). Because the reader enforces the limit
    while the child writes, a runaway producer is blocked by the pipe and killed
    as soon as it crosses a limit (overshoot is at most one read chunk), instead of
    growing a capture until the timeout. No pipe EOF is awaited, so a straggler
    holding a write end cannot hang the substitution.

    Containment: the outermost nested PySH is a session and process-group leader
    and holds a containment capability (see ``CAPABILITY_ENV``), so it keeps every
    external command and pipeline stage, and deeper nested PySH processes, in
    that one group. Whatever way the substitution ends (completion, timeout,
    output limit, cancellation, error) the group is SIGKILLed before its leader is
    reaped. Known limit: a descendant that deliberately leaves the group
    (``setsid`` or ``setpgid`` by itself, for example a daemon) escapes portable
    POSIX process groups and is not contained.
    """
    limits = {
        "stdout": MAX_SUBSTITUTION_STDOUT_BYTES if max_stdout is None else max_stdout,
        "stderr": MAX_SUBSTITUTION_STDERR_BYTES if max_stderr is None else max_stderr,
    }
    depth = _current_depth()
    # Inside a domain the group already exists: stay in it and let the outermost
    # runner sweep it; only the direct child is killed here.
    nested_level = in_substitution_domain()
    process: subprocess.Popen[bytes] | None = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    argv = [sys.executable, "-P", "-m", "pysh", "--no-rc", "-c", command]
    token = secrets.token_hex(16)
    env = _nested_environment(depth)
    cap_read, cap_write = os.pipe()
    try:
        os.write(cap_write, _CAPABILITY_MAGIC + token.encode("ascii"))
        os.close(cap_write)
        cap_write = -1
        env[CAPABILITY_ENV] = f"{cap_read}:{token}"
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and PySH module, no shell
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                pass_fds=(cap_read,),
                start_new_session=not nested_level,
            )
            state = _pump_until_exit(process, time.monotonic() + timeout, buffers, limits)
            if state == "exited":
                # Sweep stragglers first so they cannot keep writing, then take what is buffered.
                _kill_group(process)
                state = _drain_after_exit(process, buffers, limits) or "exited"
        finally:
            if process is not None:
                if nested_level:
                    process.kill()
                else:
                    _kill_group(process)
                process.wait()
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
    finally:
        os.close(cap_read)
        if cap_write != -1:
            os.close(cap_write)
    if state == "timeout":
        return NestedResult("", "", timed_out=True)  # nothing captured is read or decoded
    if state in ("stdout", "stderr"):
        return NestedResult("", "", output_limited=state)
    return NestedResult(_decode(buffers["stdout"]), _decode(buffers["stderr"]))


def _default_runner(command: str, timeout: float) -> str:
    """Substitution text for ``command``: nested PySH stdout without trailing newlines.

    Nested stderr and exit status are not propagated (unchanged since the former
    backend). Timeouts, launch failures and the depth bound emit a ``pysh:``
    diagnostic and substitute an empty string.
    """
    if _current_depth() >= MAX_SUBSTITUTION_DEPTH:
        print(
            f"pysh: substitution: nesting deeper than {MAX_SUBSTITUTION_DEPTH} levels",
            file=sys.stderr,
        )
        return ""
    try:
        result = _run_nested(command, timeout)
    except OSError as exc:
        print(f"pysh: substitution error: {exc}", file=sys.stderr)
        return ""
    if result.timed_out:
        print(f"pysh: substitution timed out: {command}", file=sys.stderr)
        return ""
    if result.output_limited is not None:
        limit = (
            MAX_SUBSTITUTION_STDOUT_BYTES
            if result.output_limited == "stdout"
            else MAX_SUBSTITUTION_STDERR_BYTES
        )
        print(
            f"pysh: substitution: {result.output_limited} exceeded {limit} bytes; "
            "the substitution is empty",
            file=sys.stderr,
        )
        return ""
    return result.stdout.rstrip("\n")


def expand_command_substitution(
    text: str,
    *,
    runner: Callable[[str, float], str] | None = None,
    timeout: float = DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS,
) -> str:
    """Expand ``$(command)`` and ``` `command` ``` substitutions in ``text``."""
    run = runner if runner is not None else _default_runner
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            out.append(c)
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_double = not in_double
            out.append(c)
            i += 1
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "(":
            end = _find_matching_paren(text, i + 1)
            if end == -1:
                out.append(c)
                i += 1
                continue
            command = text[i + 2 : end]
            out.append(run(command, timeout))
            i = end + 1
            continue
        if c == "`":
            end = text.find("`", i + 1)
            if end == -1:
                out.append(c)
                i += 1
                continue
            command = text[i + 1 : end]
            out.append(run(command, timeout))
            i = end + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_matching_paren(text: str, open_idx: int) -> int:
    """Return the index of the ``)`` matching ``text[open_idx] == '('``."""
    depth = 0
    in_single = False
    in_double = False
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "'":
            in_single = True
        elif c == '"':
            in_double = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1
