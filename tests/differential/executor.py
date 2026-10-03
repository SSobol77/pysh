# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/executor.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Hermetic, test-only executor for future reference-shell observations (Issue #54).

External interpreters are test equipment: this module runs one explicitly
supplied executable with an explicit argv list and never a shell
(``shell=True`` is never used, and nothing is resolved through ``PATH``).

Each run builds its own environment from a tiny allowlist (the host
environment is never inherited), a private temporary ``HOME`` and working
directory, a hard wall-clock timeout enforced on the whole process group, and
bounded stdout/stderr capture. Result objects carry no timestamps, absolute
paths or environment dumps. It needs neither ``/proc`` nor a real shell.

Startup isolation flags for a particular legacy shell are *not* decided here:
callers pass them as ``argv_prefix`` once they are established from a
controlled reference environment.
"""
from __future__ import annotations

import contextlib
import enum
import errno
import os
import selectors
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.differential.model import Observation

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_OUTPUT_BYTES = 1 << 20
TERMINATE_GRACE_SECONDS = 1.0
READ_CHUNK = 65536
POLL_SECONDS = 0.02
LOCALE = "C.UTF-8"


class ExecutorError(RuntimeError):
    """Infrastructure failure: the run produced no observation."""


class ExecutableNotFoundError(ExecutorError):
    """The explicit executable does not exist or is not a regular file."""


class ExecutableNotRunnableError(ExecutorError):
    """The explicit executable cannot be executed (permission, format, OS refusal)."""


class Termination(enum.Enum):
    EXIT = "exit"
    SIGNAL = "signal"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Deterministic outcome of one hermetic run."""

    termination: Termination
    returncode: int | None  # exit code when termination is EXIT
    signal_number: int | None  # terminating signal when termination is SIGNAL
    stdout: str
    stderr: str
    truncated: bool  # captured output was cut at the bound (always with OUTPUT_LIMIT)

    @property
    def timed_out(self) -> bool:
        return self.termination is Termination.TIMEOUT

    @property
    def output_limit_exceeded(self) -> bool:
        return self.termination is Termination.OUTPUT_LIMIT

    def to_observation(self) -> Observation:
        """Convert a complete run to a Slice 1 observation.

        A signal death is reported as the conventional ``128 + signal`` status.
        A timeout or an output-limit run is not a valid observation.
        """
        if self.termination is Termination.EXIT:
            assert self.returncode is not None
            return Observation(self.returncode, self.stdout, self.stderr)
        if self.termination is Termination.SIGNAL:
            assert self.signal_number is not None
            return Observation(128 + self.signal_number, self.stdout, self.stderr)
        raise ExecutorError(f"no valid observation: run ended with {self.termination.value}")


def _validate_environment(extra: Mapping[str, str]) -> dict[str, str]:
    for key, value in extra.items():
        if not key or "=" in key or "\0" in key or "\0" in value:
            raise ExecutorError(f"invalid environment entry {key!r}")
    return dict(extra)


def _check_executable(executable: Path) -> None:
    if not executable.is_absolute():
        raise ExecutorError("the executable must be an absolute path (it is never searched on PATH)")
    if not executable.is_file():
        raise ExecutableNotFoundError(f"executable not found: {executable.name}")
    if not os.access(executable, os.X_OK):
        raise ExecutableNotRunnableError(f"executable is not runnable: {executable.name}")


def _wait_exited(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """Wait for exit WITHOUT reaping, so the process group id stays reserved."""
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        if hasattr(os, "waitid"):
            if os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return True
        elif process.poll() is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def _signal_group(pgid: int, number: int) -> None:
    try:
        os.killpg(pgid, number)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM, bounded grace, then SIGKILL for the whole process group."""
    _signal_group(process.pid, signal.SIGTERM)
    if not _wait_exited(process, TERMINATE_GRACE_SECONDS):
        _signal_group(process.pid, signal.SIGKILL)
        _wait_exited(process, TERMINATE_GRACE_SECONDS)


def _pump(
    process: subprocess.Popen[bytes], stdin: bytes, deadline: float, limit: int
) -> tuple[str, bytearray, bytearray]:
    """Feed stdin and drain both streams. Returns (``eof``|``timeout``|``output_limit``, out, err)."""
    selector = selectors.DefaultSelector()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    assert process.stdout is not None and process.stderr is not None and process.stdin is not None
    pending = memoryview(stdin)
    if pending:
        os.set_blocking(process.stdin.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    else:
        process.stdin.close()
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        selector.register(stream, selectors.EVENT_READ, name)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout", buffers["stdout"], buffers["stderr"]
            for key, _events in selector.select(min(remaining, 0.1)):
                if key.data == "stdin":
                    try:
                        written = os.write(key.fd, pending[:READ_CHUNK])
                    except BlockingIOError:
                        continue
                    except OSError as error:
                        if error.errno != errno.EPIPE:
                            raise
                        written = len(pending)
                    pending = pending[written:]
                    if not pending:
                        selector.unregister(key.fileobj)
                        process.stdin.close()
                    continue
                chunk = os.read(key.fd, READ_CHUNK)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[key.data]
                buffer.extend(chunk)
                if len(buffer) > limit:
                    del buffer[limit:]
                    return "output_limit", buffers["stdout"], buffers["stderr"]
    finally:
        selector.close()
    return "eof", buffers["stdout"], buffers["stderr"]


def _decode(data: bytearray) -> str:
    return bytes(data).decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class HermeticTree:
    """The private directories of one hermetic run (all under a removed-on-exit root)."""

    root: Path
    home: Path
    work: Path
    bin: Path
    tmp: Path


@contextlib.contextmanager
def hermetic_tree() -> Iterator[HermeticTree]:
    """Create an empty private tree; it is removed on exit."""
    with tempfile.TemporaryDirectory(prefix="pysh-differential-") as root_name:
        root = Path(root_name)
        home, work, empty_bin, tmp = (root / n for n in ("home", "work", "bin", "tmp"))
        for directory in (home, work, empty_bin, tmp):
            directory.mkdir()
        yield HermeticTree(root, home, work, empty_bin, tmp)


def _write_files(base: Path, files: Mapping[str, bytes], what: str) -> None:
    for name, content in files.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ExecutorError(f"{what} escapes its directory: {name!r}")
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def run_hermetic(
    executable: str | os.PathLike[str],
    args: Sequence[str] = (),
    *,
    argv_prefix: Sequence[str] = (),
    stdin: bytes = b"",
    environment: Mapping[str, str] | None = None,
    input_files: Mapping[str, bytes] | None = None,
    home_files: Mapping[str, bytes] | None = None,
    tree: HermeticTree | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> ExecutionResult:
    """Run ``executable`` ``argv_prefix`` ``args`` once, hermetically.

    ``environment`` entries are added to the minimal base environment
    (``HOME``, ``PATH``, ``TMPDIR``, ``LANG``, ``LC_ALL``). ``input_files`` are
    test-owned files created in the private working directory and ``home_files``
    in the private ``HOME`` (for example hostile startup files) before the run.
    A caller-built ``tree`` (see :func:`hermetic_tree`) is used as is and is not
    removed, so several runs can share prepared fixtures. Raises
    :class:`ExecutorError` subclasses for infrastructure failures.
    """
    if tree is None:
        with hermetic_tree() as private:
            return run_hermetic(
                executable, args, argv_prefix=argv_prefix, stdin=stdin,
                environment=environment, input_files=input_files, home_files=home_files,
                tree=private, timeout=timeout, max_output_bytes=max_output_bytes,
            )
    if timeout <= 0 or max_output_bytes <= 0:
        raise ExecutorError("timeout and max_output_bytes must be positive")
    path = Path(executable)
    _check_executable(path)
    extra = _validate_environment(environment or {})
    argv = [str(path), *argv_prefix, *args]
    if any("\0" in item for item in argv):
        raise ExecutorError("argv entries may not contain NUL")

    _write_files(tree.work, input_files or {}, "input file")
    _write_files(tree.home, home_files or {}, "home file")
    env = {
        "HOME": str(tree.home),
        "PATH": str(tree.bin),
        "TMPDIR": str(tree.tmp),
        "LANG": LOCALE,
        "LC_ALL": LOCALE,
        **extra,
    }
    try:
        process = subprocess.Popen(  # noqa: S603 - explicit executable and argv, no shell
            argv,
            cwd=tree.work,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # own process group: timeout cleanup reaches grandchildren
            close_fds=True,
            shell=False,
        )
    except FileNotFoundError as error:
        raise ExecutableNotFoundError(f"executable not found: {path.name}") from error
    except OSError as error:
        raise ExecutableNotRunnableError(
            f"cannot execute {path.name}: {errno.errorcode.get(error.errno or 0, 'OSError')}"
        ) from error

    deadline = time.monotonic() + timeout
    # From here on this function owns the new session's process group until it has swept
    # it. The sweep is unconditional and happens BEFORE the leader is reaped (the zombie
    # leader keeps the group id reserved, so an unrelated recycled group is never hit):
    # the leader may already be gone while a background descendant is still alive.
    try:
        state, out, err = _pump(process, stdin, deadline, max_output_bytes)
        if state == "eof" and not _wait_exited(process, deadline - time.monotonic()):
            state = "timeout"
        if state != "eof":
            _terminate_group(process)
    finally:
        _signal_group(process.pid, signal.SIGKILL)  # every exit path, leader alive or not
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        returncode = process.wait()  # reap the leader last

    stdout, stderr = _decode(out), _decode(err)
    if state == "timeout":
        return ExecutionResult(Termination.TIMEOUT, None, None, stdout, stderr, False)
    if state == "output_limit":
        return ExecutionResult(Termination.OUTPUT_LIMIT, None, None, stdout, stderr, True)
    if returncode < 0:
        return ExecutionResult(Termination.SIGNAL, None, -returncode, stdout, stderr, False)
    return ExecutionResult(Termination.EXIT, returncode, None, stdout, stderr, False)
