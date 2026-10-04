# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/diagnostics/audit.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Opt-in persistent audit log sink (Issue #50, slice 3).

:class:`AuditLogSink` owns the lifecycle of one explicit, user-selected
append-only JSON Lines file. It is only ever constructed when the user
passes ``--audit-log PATH``; nothing in this module touches the filesystem
at import time or when audit logging is not requested.

Invariants:

* Every persisted line is produced by the shared serializer
  :func:`pysh.diagnostics.jsonl.encode_jsonl_line`, i.e. it has already
  passed through :class:`~pysh.diagnostics.emitter.DiagnosticEmitter`
  (validate -> canonical redaction -> JSON) before any byte reaches the
  file descriptor.
* The file is opened with an explicit descriptor (``O_APPEND``,
  ``O_CREAT`` mode 0600, ``O_CLOEXEC``, ``O_NOFOLLOW`` where available).
  It is never truncated. The opened descriptor must be a regular file
  owned by the effective user with no group/other permission bits; an
  insecure pre-existing file is rejected rather than ``chmod``-ed.
* Command *diagnostic metadata* (trace events, already redacted) may be
  audited. Child stdout/stderr payloads and protected PTY input are never
  routed here: this sink only receives structured events.
* An open failure raises :class:`AuditLogError` so the caller can refuse to
  run. A later write failure is observational: the sink records the
  failure, disables itself, and never raises ``OSError`` to the caller.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Mapping

from pysh.diagnostics.emitter import DiagnosticEmitter
from pysh.diagnostics.jsonl import encode_jsonl_line
from pysh.diagnostics.redaction import RedactionPolicy
from pysh.diagnostics.schema import StructuredDiagnosticEvent

__all__ = ["AuditLogError", "AuditLogSink"]


class AuditLogError(Exception):
    """Raised when the audit log cannot be opened safely."""


def _open_flags() -> int:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    # Python already creates non-inheritable descriptors (PEP 446); the
    # explicit flag is kept where the platform provides it.
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    # Do not block opening a FIFO that has no reader (fstat then rejects it).
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOCTTY", 0)
    return flags


class AuditLogSink:
    """Append-only, redacting JSONL audit file sink.

    Use :meth:`open` to construct; call :meth:`close` (idempotent) when the
    session ends.
    """

    def __init__(self, fd: int, path: str, policy: RedactionPolicy | None = None) -> None:
        self._fd: int | None = fd
        self._path = path
        self._emitter = DiagnosticEmitter(policy)
        self._failed = False

    @classmethod
    def open(cls, path: str | os.PathLike[str], policy: RedactionPolicy | None = None) -> AuditLogSink:
        """Open *path* for appending, or raise :class:`AuditLogError`."""
        text = os.fspath(path)
        if not text or "\0" in text:
            raise AuditLogError("invalid audit log path")
        if not hasattr(os, "O_NOFOLLOW"):
            # Portable fallback: best-effort (racy) symlink detection.
            try:
                if stat.S_ISLNK(os.lstat(text).st_mode):
                    raise AuditLogError("audit log path is a symbolic link")
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise AuditLogError(f"cannot open audit log: {exc.strerror or 'error'}") from exc
        try:
            fd = os.open(text, _open_flags(), 0o600)
        except OSError as exc:
            if hasattr(os, "O_NOFOLLOW") and _is_symlink(text):
                raise AuditLogError("audit log path is a symbolic link") from exc
            raise AuditLogError(f"cannot open audit log: {exc.strerror or 'error'}") from exc
        try:
            _validate_descriptor(fd)
            if hasattr(os, "set_blocking"):
                os.set_blocking(fd, True)
        except (AuditLogError, OSError) as exc:
            os.close(fd)
            if isinstance(exc, AuditLogError):
                raise
            raise AuditLogError(f"cannot open audit log: {exc.strerror or 'error'}") from exc
        return cls(fd, text, policy)

    @property
    def path(self) -> str:
        """Return the audit file path this sink was opened with."""
        return self._path

    @property
    def failed(self) -> bool:
        """Return True once a terminal write failure disabled this sink."""
        return self._failed

    @property
    def closed(self) -> bool:
        """Return True when the descriptor has been released."""
        return self._fd is None

    def write_structured_event(
        self,
        event: StructuredDiagnosticEvent,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Redact, encode, and append *event*; contain filesystem failures.

        Schema/serialization errors (``TypeError``/``ValueError``) from a
        malformed event propagate to the caller's containment boundary
        without disabling the sink, because they say nothing about the
        file. An ``OSError`` while writing is terminal: the sink is marked
        failed, its descriptor is released, and no further writes (or
        retries) occur. No diagnostic is printed here.
        """
        if self._failed or self._fd is None:
            return
        data = encode_jsonl_line(self._emitter, event, env=env).encode("utf-8")
        try:
            view = memoryview(data)
            while view:
                written = os.write(self._fd, view)
                view = view[written:]
        except OSError:
            self._failed = True
            self.close()

    def close(self) -> None:
        """Release the descriptor. Safe to call more than once."""
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                self._failed = True


def _is_symlink(path: str) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _validate_descriptor(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise AuditLogError("audit log path is not a regular file")
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and info.st_uid != geteuid():
        raise AuditLogError("audit log file is not owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise AuditLogError(
            "audit log file permissions are too open (group/other access); "
            "refusing to use it"
        )
