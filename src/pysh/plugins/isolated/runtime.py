# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/runtime.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Portable subprocess lifecycle for capability-brokered isolated plugins."""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from pysh.plugins.isolated.broker import BrokerResult, CommandHandler, PrivilegedRequestBroker
from pysh.plugins.isolated.capabilities import Capability, CapabilityGrant, format_capability
from pysh.plugins.isolated.errors import LifecycleError, ProtocolError
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.manifest import IsolatedPluginManifest
from pysh.plugins.isolated.protocol import (
    HANDSHAKE_GRANT,
    HANDSHAKE_HELLO,
    HANDSHAKE_READY,
    LIFECYCLE_SHUTDOWN,
    LIFECYCLE_SHUTDOWN_ACK,
    REQUEST_COMMAND,
    REQUEST_ENVIRONMENT,
    REQUEST_FILESYSTEM_READ,
    REQUEST_FILESYSTEM_WRITE,
    REQUEST_NETWORK_CONNECT,
    RESPONSE_ERROR,
    RESPONSE_OK,
    IPCMessage,
    JsonValue,
    read_message,
    write_message,
)

BASELINE_CHILD_ENVIRONMENT: Mapping[str, str] = MappingProxyType(
    {
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
)
_BROKER_REQUEST_TYPES = frozenset({
    REQUEST_ENVIRONMENT,
    REQUEST_FILESYSTEM_READ,
    REQUEST_FILESYSTEM_WRITE,
    REQUEST_COMMAND,
    REQUEST_NETWORK_CONNECT,
})

type EventSink = Callable[[IsolatedPluginEvent], None]


class IsolatedPluginState(StrEnum):
    """Parent-observed lifecycle state for one isolated child."""

    NEW = "new"
    HANDSHAKING = "handshaking"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IsolatedResourceLimits:
    """Fail-closed Issue #53 integration seam; enforcement is not implemented here."""

    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    wall_clock_seconds: int | None = None
    file_descriptors: int | None = None
    processes: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.cpu_seconds,
            self.memory_bytes,
            self.wall_clock_seconds,
            self.file_descriptors,
            self.processes,
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError("resource limits must be positive integers or None")

    @property
    def configured(self) -> bool:
        """Return whether any Issue #53 limit was requested."""
        return any(
            value is not None
            for value in (
                self.cpu_seconds,
                self.memory_bytes,
                self.wall_clock_seconds,
                self.file_descriptors,
                self.processes,
            )
        )


class IsolatedPluginRuntime:
    """Spawn, authenticate, serve, and contain one isolated-plugin child."""

    def __init__(
        self,
        manifest: IsolatedPluginManifest,
        *,
        granted_capabilities: frozenset[Capability] = frozenset(),
        broker_environment: Mapping[str, str] | None = None,
        command_handlers: Mapping[str, CommandHandler] | None = None,
        event_sink: EventSink | None = None,
        handshake_timeout: float = 2.0,
        request_timeout: float = 2.0,
        shutdown_timeout: float = 1.0,
        resource_limits: IsolatedResourceLimits | None = None,
    ) -> None:
        self.manifest = manifest
        self.grant = CapabilityGrant.create(
            manifest.name,
            manifest.requested_capabilities,
            granted_capabilities,
        )
        self._event_sink = event_sink
        self._handshake_timeout = _positive_timeout(handshake_timeout, "handshake_timeout")
        self._request_timeout = _positive_timeout(request_timeout, "request_timeout")
        self._shutdown_timeout = _positive_timeout(shutdown_timeout, "shutdown_timeout")
        self._resource_limits = resource_limits or IsolatedResourceLimits()
        self._broker = PrivilegedRequestBroker(
            self.grant,
            environment=broker_environment,
            commands=command_handlers,
            event_sink=event_sink,
        )
        self._state = IsolatedPluginState.NEW
        self._process: subprocess.Popen[bytes] | None = None
        self._working_directory: tempfile.TemporaryDirectory[str] | None = None

    @property
    def state(self) -> IsolatedPluginState:
        """Return the current parent-observed lifecycle state."""
        return self._state

    @property
    def process_id(self) -> int | None:
        """Return the child PID while a process object exists."""
        return self._process.pid if self._process is not None else None

    @property
    def working_directory(self) -> Path | None:
        """Return the dedicated temporary cwd while it is active."""
        if self._working_directory is None:
            return None
        return Path(self._working_directory.name)

    def start(self) -> None:
        """Spawn the child and complete the identity/capability handshake."""
        if self._state is not IsolatedPluginState.NEW:
            raise LifecycleError("isolated plugin can only be started once")
        if self._resource_limits.configured:
            raise LifecycleError("resource-limit enforcement requires the Issue #53 launcher")

        self._working_directory = tempfile.TemporaryDirectory(prefix="pysh-isolated-")
        try:
            self._process = subprocess.Popen(  # noqa: S603 - validated explicit argv
                list(self.manifest.entrypoint),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self._working_directory.name,
                env=dict(BASELINE_CHILD_ENVIRONMENT),
                close_fds=True,
                start_new_session=True,
            )
            self._state = IsolatedPluginState.HANDSHAKING
            self._emit(
                IsolatedPluginEventKind.SPAWN,
                requested=self.grant.requested,
                granted=self.grant.granted,
            )
            hello = self._read(self._handshake_timeout)
            self._validate_hello(hello)
            self._write(
                IPCMessage(
                    message_type=HANDSHAKE_GRANT,
                    request_id=hello.request_id,
                    payload={
                        "plugin_name": self.manifest.name,
                        "requested_capabilities": _capability_labels(self.grant.requested),
                        "granted_capabilities": _capability_labels(self.grant.granted),
                    },
                ),
                timeout=self._handshake_timeout,
            )
            ready = self._read(self._handshake_timeout)
            self._validate_ready(ready, hello.request_id)
            self._state = IsolatedPluginState.RUNNING
            self._emit(IsolatedPluginEventKind.HANDSHAKE)
            self._emit(IsolatedPluginEventKind.RUNNING)
        except Exception as exc:
            self._fail("handshake_failed")
            if isinstance(exc, LifecycleError):
                raise
            raise LifecycleError("isolated-plugin handshake failed") from exc

    def serve_once(self, *, timeout: float | None = None) -> BrokerResult:
        """Serve exactly one child request and return its sanitized broker result."""
        if self._state is not IsolatedPluginState.RUNNING:
            raise LifecycleError("isolated plugin is not running")
        effective_timeout = (
            self._request_timeout if timeout is None else _positive_timeout(timeout, "timeout")
        )
        try:
            request = self._read(effective_timeout)
            if request.message_type not in _BROKER_REQUEST_TYPES:
                raise ProtocolError("unexpected message while isolated plugin is running")
            result = self._broker.dispatch(request)
            if result.ok:
                response = IPCMessage(
                    message_type=RESPONSE_OK,
                    request_id=request.request_id,
                    payload=result.payload,
                )
            else:
                response = IPCMessage(
                    message_type=RESPONSE_ERROR,
                    request_id=request.request_id,
                    payload={"code": result.error_code or "request_failed"},
                )
            self._write(response, timeout=effective_timeout)
            return result
        except Exception as exc:
            self._fail("request_failed")
            if isinstance(exc, LifecycleError):
                raise
            raise LifecycleError("isolated-plugin request failed") from exc

    def shutdown(self) -> bool:
        """Request graceful shutdown, then terminate/kill on any timeout or violation."""
        if self._state is IsolatedPluginState.NEW:
            self._state = IsolatedPluginState.STOPPED
            return True
        if self._state in {IsolatedPluginState.STOPPED, IsolatedPluginState.FAILED}:
            return self._state is IsolatedPluginState.STOPPED
        graceful = False
        try:
            request_id = "shutdown"
            self._write(
                IPCMessage(
                    message_type=LIFECYCLE_SHUTDOWN,
                    request_id=request_id,
                    payload={},
                ),
                timeout=self._shutdown_timeout,
            )
            response = self._read(self._shutdown_timeout)
            if (
                response.message_type != LIFECYCLE_SHUTDOWN_ACK
                or response.request_id != request_id
                or response.payload
            ):
                raise ProtocolError("invalid isolated-plugin shutdown acknowledgement")
            self._close_stdin()
            process = self._require_process()
            returncode = process.wait(timeout=self._shutdown_timeout)
            graceful = returncode == 0
        except Exception:  # noqa: BLE001 - shutdown must never escape into shell teardown
            self._emit(IsolatedPluginEventKind.FAILURE, reason_code="shutdown_failed")
        finally:
            if not graceful:
                self._terminate_process()
            self._cleanup_handles()
            self._state = IsolatedPluginState.STOPPED
            self._emit(IsolatedPluginEventKind.STOPPED, reason_code=None if graceful else "forced")
        return graceful

    def close(self) -> None:
        """Contain and release the child without propagating teardown failures."""
        self.shutdown()

    def __enter__(self) -> IsolatedPluginRuntime:
        self.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _validate_hello(self, message: IPCMessage) -> None:
        if message.message_type != HANDSHAKE_HELLO:
            raise ProtocolError("child sent a request before handshake completion")
        expected: dict[str, JsonValue] = {
            "plugin_name": self.manifest.name,
            "plugin_version": self.manifest.plugin_version,
            "protocol_version": self.manifest.protocol_version,
        }
        if message.payload != expected:
            raise ProtocolError("isolated-plugin handshake identity mismatch")

    def _validate_ready(self, message: IPCMessage, request_id: str) -> None:
        if (
            message.message_type != HANDSHAKE_READY
            or message.request_id != request_id
            or message.payload != {"plugin_name": self.manifest.name}
        ):
            raise ProtocolError("isolated-plugin ready acknowledgement is invalid")

    def _read(self, timeout: float) -> IPCMessage:
        process = self._require_process()
        if process.stdout is None:
            raise LifecycleError("isolated-plugin stdout pipe is unavailable")
        return read_message(process.stdout.fileno(), timeout=timeout)

    def _write(self, message: IPCMessage, *, timeout: float) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise LifecycleError("isolated-plugin stdin pipe is unavailable")
        write_message(process.stdin.fileno(), message, timeout=timeout)

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise LifecycleError("isolated-plugin process is unavailable")
        return self._process

    def _fail(self, reason_code: str) -> None:
        self._emit(IsolatedPluginEventKind.FAILURE, reason_code=reason_code)
        self._terminate_process()
        self._cleanup_handles()
        self._state = IsolatedPluginState.FAILED

    def _terminate_process(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            if process.poll() is None:
                process.wait(timeout=self._shutdown_timeout)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                pass

    def _close_stdin(self) -> None:
        process = self._process
        if process is not None and process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass

    def _cleanup_handles(self) -> None:
        process = self._process
        if process is not None:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if self._working_directory is not None:
            self._working_directory.cleanup()
            self._working_directory = None

    def _emit(
        self,
        kind: IsolatedPluginEventKind,
        *,
        requested: frozenset[Capability] = frozenset(),
        granted: frozenset[Capability] = frozenset(),
        reason_code: str | None = None,
    ) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            IsolatedPluginEvent(
                kind=kind,
                plugin_name=self.manifest.name,
                requested_capabilities=tuple(_capability_labels(requested)),
                granted_capabilities=tuple(_capability_labels(granted)),
                reason_code=reason_code,
            )
        )


def _capability_labels(capabilities: frozenset[Capability]) -> list[str]:
    return sorted(format_capability(capability) for capability in capabilities)


def _positive_timeout(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a positive number")
    return float(value)
