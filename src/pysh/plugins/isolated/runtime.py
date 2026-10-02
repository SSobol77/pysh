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
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from pysh.plugins.isolated.broker import BrokerResult, CommandHandler, PrivilegedRequestBroker
from pysh.plugins.isolated.capabilities import Capability, CapabilityGrant, format_capability
from pysh.plugins.isolated.errors import (
    FrameTooLargeError,
    LifecycleError,
    ProtocolError,
    ResourcePolicyError,
)
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.launcher import (
    EXIT_APPLY_FAILED,
    EXIT_POLICY_REJECTED,
    build_launcher_argv,
)
from pysh.plugins.isolated.manifest import IsolatedPluginManifest
from pysh.plugins.isolated.protocol import (
    HANDSHAKE_GRANT,
    HANDSHAKE_HELLO,
    HANDSHAKE_READY,
    LIFECYCLE_SHUTDOWN,
    LIFECYCLE_SHUTDOWN_ACK,
    MAX_FRAME_BYTES,
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
from pysh.plugins.isolated.resources import (
    DEFAULT_RESOURCE_PROFILES,
    IsolatedResourceLimits,
    ProcessLimitMode,
    ResourceBudget,
    ResourceEnforcementPlan,
    ResourceProfile,
    ResourceViolation,
    plan_enforcement,
    resolve_resource_budget,
)
from pysh.plugins.isolated.supervisor import (
    DEFAULT_CONCURRENCY_GOVERNOR,
    ConcurrencyGovernor,
    ConcurrencyPermit,
    WallClockWatchdog,
)

__all__ = [
    "BASELINE_CHILD_ENVIRONMENT",
    "EventSink",
    "IsolatedPluginRuntime",
    "IsolatedPluginState",
    "IsolatedResourceLimits",
]

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
        resource_limits: ResourceBudget | None = None,
        resource_catalog: Mapping[str, ResourceProfile] = DEFAULT_RESOURCE_PROFILES,
        process_limit_mode: ProcessLimitMode = ProcessLimitMode.DEFERRED,
        concurrency_governor: ConcurrencyGovernor = DEFAULT_CONCURRENCY_GOVERNOR,
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
        # ``resource_limits`` is an optional override that may only LOWER the
        # resolved profile budget. There is no ungoverned path: every runtime
        # resolves an effective budget (manifest class, else the default class).
        self._resource_limits = resource_limits if resource_limits is not None else ResourceBudget()
        self._resource_catalog = resource_catalog
        self._process_limit_mode = process_limit_mode
        self._governor = concurrency_governor
        self._enforcement: ResourceEnforcementPlan | None = None
        self._broker = PrivilegedRequestBroker(
            self.grant,
            environment=broker_environment,
            commands=command_handlers,
            event_sink=event_sink,
        )
        self._state = IsolatedPluginState.NEW
        self._process: subprocess.Popen[bytes] | None = None
        self._working_directory: tempfile.TemporaryDirectory[str] | None = None
        # Supervision state. ``_lock`` guards only short claim/flag transitions;
        # ``_term_lock`` serializes process-group termination; ``_finalize_lock``
        # makes cleanup idempotent across the caller and watchdog threads.
        self._lock = threading.Lock()
        self._term_lock = threading.Lock()
        self._finalize_lock = threading.Lock()
        self._busy = 0
        self._closing = False
        self._finalized = False
        self._group_released = False
        self._violation: ResourceViolation | None = None
        self._permit: ConcurrencyPermit | None = None
        self._watchdog: WallClockWatchdog | None = None

    @property
    def state(self) -> IsolatedPluginState:
        """Return the current parent-observed lifecycle state."""
        return self._state

    @property
    def process_id(self) -> int | None:
        """Return the child PID while a process object exists."""
        return self._process.pid if self._process is not None else None

    @property
    def enforcement(self) -> ResourceEnforcementPlan | None:
        """Return the active enforcement plan, or ``None`` when ungoverned."""
        return self._enforcement

    @property
    def working_directory(self) -> Path | None:
        """Return the dedicated temporary cwd while it is active."""
        if self._working_directory is None:
            return None
        return Path(self._working_directory.name)

    def start(self) -> None:
        """Resolve the budget, take a permit, spawn via the launcher, and handshake.

        The total wall-clock deadline starts at ``time.monotonic()`` taken
        immediately before the spawn call, so launcher and handshake time
        count against the budget. It is never reset afterwards.
        """
        if self._state is not IsolatedPluginState.NEW:
            raise LifecycleError("isolated plugin can only be started once")
        # Policy first: any failure here leaves no permit, no cwd, no process.
        try:
            effective = resolve_resource_budget(
                self.manifest.resource_class,
                self._resource_limits,
                catalog=self._resource_catalog,
            )
            plan = plan_enforcement(
                effective, self._resource_limits, process_mode=self._process_limit_mode
            )
            argv = build_launcher_argv(plan.os_limits, self.manifest.entrypoint)
        except ResourcePolicyError as exc:
            raise LifecycleError(f"resource policy rejected: {exc}") from exc
        self._enforcement = plan
        try:
            self._permit = self._governor.acquire(self.manifest.name, effective.concurrency)  # type: ignore[arg-type]
        except ResourcePolicyError as exc:
            self._emit_resource_violation(
                ResourceViolation.CONCURRENCY, effective.concurrency, "permit"
            )
            raise LifecycleError("isolated-plugin resource limit exceeded: concurrency") from exc

        with self._operation():
            try:
                self._working_directory = tempfile.TemporaryDirectory(prefix="pysh-isolated-")
                deadline = time.monotonic() + float(effective.wall_clock_seconds)  # type: ignore[arg-type]
                self._process = subprocess.Popen(  # noqa: S603 - validated explicit argv
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=self._working_directory.name,
                    env=dict(BASELINE_CHILD_ENVIRONMENT),
                    close_fds=True,
                    start_new_session=True,
                )
                self._watchdog = WallClockWatchdog(deadline, self._on_deadline)
                self._watchdog.start()
                self._state = IsolatedPluginState.HANDSHAKING
                self._emit(
                    IsolatedPluginEventKind.SPAWN,
                    requested=self.grant.requested,
                    granted=self.grant.granted,
                )
                hello = self._read(self._handshake_timeout)
                self._validate_hello(hello)
                self._emit(
                    IsolatedPluginEventKind.GRANTED,
                    requested=self.grant.requested,
                    granted=self.grant.granted,
                )
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
                violation = self._violation
                refusal = None if violation is not None else self._launcher_refusal()
                self._fail("handshake_failed")
                if violation is not None:
                    raise _violation_error(violation) from exc
                if refusal is not None:
                    raise LifecycleError(refusal) from exc
                if isinstance(exc, LifecycleError):
                    raise
                raise LifecycleError("isolated-plugin handshake failed") from exc
            except BaseException:
                self._finalize(IsolatedPluginState.FAILED)
                raise

    def serve_once(self, *, timeout: float | None = None) -> BrokerResult:
        """Serve exactly one child request and return its sanitized broker result."""
        if self._state is not IsolatedPluginState.RUNNING:
            violation = self._violation
            if violation is not None:  # a watchdog stopped it between calls: say why
                raise _violation_error(violation)
            raise LifecycleError("isolated plugin is not running")
        effective_timeout = (
            self._request_timeout if timeout is None else _positive_timeout(timeout, "timeout")
        )
        with self._operation():
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
                violation = self._violation
                self._fail("request_failed")
                if violation is not None:
                    raise _violation_error(violation) from exc
                if isinstance(exc, LifecycleError):
                    raise
                raise LifecycleError("isolated-plugin request failed") from exc
            except BaseException:
                self._finalize(IsolatedPluginState.FAILED)
                raise

    def shutdown(self) -> bool:
        """Request graceful shutdown, then terminate/kill on any timeout or violation.

        Shutdown claims the runtime before the watchdog can: once shutdown has
        begun, a deadline expiry is ignored and shutdown's own bounded
        terminate/kill governs. If a violation was claimed first, shutdown only
        completes that containment and returns ``False``.
        """
        with self._lock:
            if self._state is IsolatedPluginState.NEW:
                self._state = IsolatedPluginState.STOPPED
                return True
            if self._state in {IsolatedPluginState.STOPPED, IsolatedPluginState.FAILED}:
                return self._state is IsolatedPluginState.STOPPED
            violated = self._violation is not None
            if not violated:
                self._closing = True
        if violated:
            self._finalize(IsolatedPluginState.FAILED)
            return False
        graceful = False
        with self._operation():
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
                else:
                    with self._term_lock:  # reaped leader: never signal its group again
                        self._group_released = True
                self._finalize(IsolatedPluginState.STOPPED)
                self._emit(
                    IsolatedPluginEventKind.STOPPED, reason_code=None if graceful else "forced"
                )
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

    def _launcher_refusal(self) -> str | None:
        """Classify a launcher exit (policy rejected / cannot apply) after a failed start."""
        process = self._process
        if self._enforcement is None or process is None:
            return None
        try:
            returncode = process.wait(timeout=self._shutdown_timeout)
        except subprocess.TimeoutExpired:
            return None
        if returncode == EXIT_POLICY_REJECTED:
            return "resource launcher rejected the policy before plugin exec"
        if returncode == EXIT_APPLY_FAILED:
            return "resource launcher could not apply limits or exec the plugin"
        return None

    @property
    def _message_limit(self) -> int:
        return self._enforcement.message_bytes if self._enforcement else MAX_FRAME_BYTES

    def _read(self, timeout: float) -> IPCMessage:
        process = self._require_process()
        if process.stdout is None:
            raise LifecycleError("isolated-plugin stdout pipe is unavailable")
        try:
            return read_message(
                process.stdout.fileno(), timeout=timeout, max_bytes=self._message_limit
            )
        except FrameTooLargeError:
            self._record_message_violation()
            raise

    def _write(self, message: IPCMessage, *, timeout: float) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise LifecycleError("isolated-plugin stdin pipe is unavailable")
        try:
            write_message(
                process.stdin.fileno(), message, timeout=timeout, max_bytes=self._message_limit
            )
        except FrameTooLargeError:
            self._record_message_violation()
            raise

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise LifecycleError("isolated-plugin process is unavailable")
        return self._process

    @contextmanager
    def _operation(self) -> Iterator[None]:
        """Mark a caller operation in flight; finish a pending violation on exit."""
        with self._lock:
            self._busy += 1
        try:
            yield
        finally:
            with self._lock:
                self._busy -= 1
                pending = (
                    self._busy == 0 and self._violation is not None and not self._finalized
                )
            if pending:
                self._finalize(IsolatedPluginState.FAILED)

    def _fail(self, reason_code: str) -> None:
        # A claimed resource violation is the single reported cause; no
        # contradictory generic FAILURE is emitted for it.
        if self._violation is None:
            self._emit(IsolatedPluginEventKind.FAILURE, reason_code=reason_code)
        self._finalize(IsolatedPluginState.FAILED)

    def _claim_violation(self, kind: ResourceViolation) -> bool:
        """Atomically become the one reported cause; first claimant wins."""
        with self._lock:
            if self._violation is not None or self._closing or self._finalized:
                return False
            self._violation = kind
            return True

    def _emit_resource_violation(
        self, kind: ResourceViolation, configured_limit: int | None, enforcement: str
    ) -> None:
        """Emit one bounded RESOURCE event; observational, so ``Exception`` is contained."""
        try:
            self._emit(
                IsolatedPluginEventKind.RESOURCE_VIOLATION,
                reason_code=f"{kind.value}_exceeded",
                resource=kind.value,
                configured_limit=configured_limit,
                enforcement=enforcement,
            )
        except Exception:  # noqa: BLE001, S110 - diagnostics must not change containment
            pass

    def _record_message_violation(self) -> None:
        if self._claim_violation(ResourceViolation.MESSAGE_SIZE):
            self._emit_resource_violation(
                ResourceViolation.MESSAGE_SIZE, self._message_limit, "ipc_bound"
            )

    def _on_deadline(self) -> None:
        """Watchdog expiry: claim, report, then contain via the owned process group."""
        process = self._process
        if process is None or process.poll() is not None:
            return  # the child already exited; nothing is consuming the budget
        if not self._claim_violation(ResourceViolation.WALL_CLOCK):
            return  # shutdown or another violation won the race
        try:
            assert self._enforcement is not None
            self._emit_resource_violation(
                ResourceViolation.WALL_CLOCK,
                self._enforcement.effective.wall_clock_seconds,
                "watchdog",
            )
        finally:
            self._terminate_process()
            with self._lock:
                idle = self._busy == 0
            if idle:
                self._finalize(IsolatedPluginState.FAILED)

    def _finalize(self, final_state: IsolatedPluginState) -> None:
        """Idempotently contain, release, and settle the runtime in ``final_state``."""
        watchdog = self._watchdog
        if watchdog is not None:
            watchdog.cancel()  # outside every lock: its callback may need them
        with self._finalize_lock:
            if self._finalized:
                return
            self._terminate_process()
            self._cleanup_handles()
            if self._permit is not None:
                self._permit.release()
                self._permit = None
            self._state = final_state
            self._finalized = True

    def _terminate_process(self) -> None:
        """SIGTERM the owned group, wait a bounded grace, SIGKILL, then reap.

        Only the child's own session/process group (``pid == pgid`` because of
        ``start_new_session=True``) is ever signalled, and never again once the
        sequence has completed, so a recycled PID cannot be hit.
        """
        with self._term_lock:
            process = self._process
            if process is None or self._group_released:
                return
            _signal_group(process.pid, signal.SIGTERM)
            try:
                if process.poll() is None:
                    process.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                pass
            _signal_group(process.pid, signal.SIGKILL)
            if process.poll() is None:
                try:
                    process.wait(timeout=self._shutdown_timeout)
                except subprocess.TimeoutExpired:
                    pass
            self._group_released = True

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
        resource: str | None = None,
        configured_limit: int | None = None,
        enforcement: str | None = None,
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
                resource=resource,
                configured_limit=configured_limit,
                enforcement=enforcement,
            )
        )


def _capability_labels(capabilities: frozenset[Capability]) -> list[str]:
    return sorted(format_capability(capability) for capability in capabilities)


def _signal_group(process_group: int, signum: signal.Signals) -> None:
    """Signal only the isolated child's own process group; absence is not an error."""
    try:
        os.killpg(process_group, signum)
    except OSError:
        pass


def _violation_error(violation: ResourceViolation) -> LifecycleError:
    return LifecycleError(f"isolated-plugin resource limit exceeded: {violation.value}")


def _positive_timeout(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a positive number")
    return float(value)
