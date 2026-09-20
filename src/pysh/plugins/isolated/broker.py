# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/broker.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Parent-owned capability broker for isolated-plugin privileged requests."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pysh.plugins.isolated.capabilities import (
    Capability,
    CapabilityGrant,
    CommandCapability,
    EnvironmentCapability,
    FilesystemAccess,
    FilesystemCapability,
    NetworkCapability,
    format_capability,
)
from pysh.plugins.isolated.errors import CapabilityDeniedError, ProtocolError
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.protocol import (
    REQUEST_COMMAND,
    REQUEST_ENVIRONMENT,
    REQUEST_FILESYSTEM_READ,
    REQUEST_FILESYSTEM_WRITE,
    REQUEST_NETWORK_CONNECT,
    IPCMessage,
    JsonValue,
)
from pysh.plugins.names import validate_command_name

MAX_BROKER_FILE_BYTES = 256 * 1024
MAX_COMMAND_ARGUMENTS = 128
MAX_COMMAND_ARGUMENT_BYTES = 4096

type CommandHandler = Callable[[list[str]], int]
type EventSink = Callable[[IsolatedPluginEvent], None]


@dataclass(frozen=True, slots=True)
class BrokerResult:
    """Sanitized response produced for one broker request."""

    ok: bool
    payload: dict[str, JsonValue]
    error_code: str | None = None


class PrivilegedRequestBroker:
    """Map known requests to exact parent-side capability checks."""

    def __init__(
        self,
        grant: CapabilityGrant,
        *,
        environment: Mapping[str, str] | None = None,
        commands: Mapping[str, CommandHandler] | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._grant = grant
        self._environment = environment if environment is not None else os.environ
        self._commands = dict(commands or {})
        self._event_sink = event_sink

    def dispatch(self, message: IPCMessage) -> BrokerResult:
        """Validate and execute one known privileged request without dynamic dispatch."""
        try:
            if message.message_type == REQUEST_ENVIRONMENT:
                return self._read_environment(message.payload)
            if message.message_type == REQUEST_FILESYSTEM_READ:
                return self._read_file(message.payload)
            if message.message_type == REQUEST_FILESYSTEM_WRITE:
                return self._write_file(message.payload)
            if message.message_type == REQUEST_COMMAND:
                return self._execute_command(message.payload)
            if message.message_type == REQUEST_NETWORK_CONNECT:
                return self._network_connect(message.payload)
            raise ProtocolError("message is not a broker request")
        except CapabilityDeniedError as exc:
            self._emit_denied(message.message_type, exc)
            return BrokerResult(ok=False, payload={}, error_code="capability_denied")
        except ProtocolError:
            return BrokerResult(ok=False, payload={}, error_code="invalid_request")
        except (OSError, UnicodeError):
            return BrokerResult(ok=False, payload={}, error_code="operation_failed")
        except Exception:  # noqa: BLE001 - parent command failures must be contained
            return BrokerResult(ok=False, payload={}, error_code="internal_error")

    def _read_environment(self, payload: dict[str, JsonValue]) -> BrokerResult:
        _require_payload_fields(payload, {"name"})
        name = payload["name"]
        if not isinstance(name, str):
            raise ProtocolError("environment name must be a string")
        capability = EnvironmentCapability(name=name)
        self._require_exact(capability)
        value = self._environment.get(name)
        return BrokerResult(ok=True, payload={"present": value is not None, "value": value})

    def _read_file(self, payload: dict[str, JsonValue]) -> BrokerResult:
        _require_payload_fields(payload, {"path"})
        target = _canonical_request_path(payload["path"], must_exist=True)
        self._require_filesystem(FilesystemAccess.READ, target)
        stat_result = target.stat()
        if not target.is_file() or stat_result.st_size > MAX_BROKER_FILE_BYTES:
            raise OSError("broker read target is not an allowed bounded regular file")
        data = target.read_text(encoding="utf-8")
        if len(data.encode("utf-8")) > MAX_BROKER_FILE_BYTES:
            raise OSError("broker read result exceeds its bound")
        return BrokerResult(ok=True, payload={"data": data})

    def _write_file(self, payload: dict[str, JsonValue]) -> BrokerResult:
        _require_payload_fields(payload, {"path", "data"})
        data = payload["data"]
        if not isinstance(data, str):
            raise ProtocolError("filesystem write data must be a string")
        encoded = data.encode("utf-8")
        if len(encoded) > MAX_BROKER_FILE_BYTES:
            raise ProtocolError("filesystem write exceeds its bound")
        target = _canonical_request_path(payload["path"], must_exist=False)
        self._require_filesystem(FilesystemAccess.WRITE, target)
        written = target.write_text(data, encoding="utf-8")
        return BrokerResult(ok=True, payload={"characters_written": written})

    def _execute_command(self, payload: dict[str, JsonValue]) -> BrokerResult:
        _require_payload_fields(payload, {"name", "argv"})
        raw_name = payload["name"]
        argv = payload["argv"]
        if not isinstance(raw_name, str) or not isinstance(argv, list):
            raise ProtocolError("command request has invalid field types")
        try:
            name = validate_command_name(raw_name)
        except Exception as exc:
            raise ProtocolError("command request has an invalid name") from exc
        if len(argv) > MAX_COMMAND_ARGUMENTS or not all(isinstance(item, str) for item in argv):
            raise ProtocolError("command argv is invalid or too large")
        typed_argv = cast(list[str], argv)
        if any(len(item.encode("utf-8")) > MAX_COMMAND_ARGUMENT_BYTES for item in typed_argv):
            raise ProtocolError("command argument exceeds its encoded bound")
        self._require_exact(CommandCapability(name=name))
        handler = self._commands.get(name)
        if handler is None:
            return BrokerResult(ok=False, payload={}, error_code="command_unavailable")
        status = handler(list(typed_argv))
        if isinstance(status, bool) or not isinstance(status, int):
            return BrokerResult(ok=False, payload={}, error_code="invalid_command_result")
        return BrokerResult(ok=True, payload={"status": status})

    def _network_connect(self, payload: dict[str, JsonValue]) -> BrokerResult:
        _require_payload_fields(payload, {"host", "port"})
        host = payload["host"]
        port = payload["port"]
        if not isinstance(host, str) or isinstance(port, bool) or not isinstance(port, int):
            raise ProtocolError("network request has invalid field types")
        self._require_exact(NetworkCapability(host=host.casefold(), port=port))
        # No raw network channel is part of protocol v1. A later narrow proxy
        # may implement this operation without exposing a socket or parent object.
        return BrokerResult(ok=False, payload={}, error_code="operation_unavailable")

    def _require_exact(self, capability: Capability) -> None:
        if not self._grant.allows(capability):
            raise CapabilityDeniedError(format_capability(capability))

    def _require_filesystem(self, access: FilesystemAccess, target: Path) -> None:
        for capability in self._grant.granted:
            if not isinstance(capability, FilesystemCapability) or capability.access is not access:
                continue
            if target == capability.root or target.is_relative_to(capability.root):
                return
        raise CapabilityDeniedError(f"fs.{access.value}")

    def _emit_denied(self, operation: str, error: CapabilityDeniedError) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            IsolatedPluginEvent(
                kind=IsolatedPluginEventKind.DENIED,
                plugin_name=self._grant.plugin_name,
                operation=operation,
                reason_code="capability_denied",
            )
        )
        _ = error


def _require_payload_fields(payload: dict[str, JsonValue], required: set[str]) -> None:
    if set(payload) != required:
        raise ProtocolError("broker request fields do not match the operation schema")


def _canonical_request_path(value: JsonValue, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ProtocolError("filesystem request path must be a non-empty string")
    path = Path(value)
    if not path.is_absolute():
        raise ProtocolError("filesystem request path must be absolute")
    try:
        return path.resolve(strict=must_exist)
    except OSError as exc:
        raise OSError("filesystem request path cannot be resolved") from exc
