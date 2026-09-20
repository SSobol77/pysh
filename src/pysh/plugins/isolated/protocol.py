# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/protocol.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Bounded, versioned, length-prefixed JSON IPC for isolated plugins."""
from __future__ import annotations

import json
import math
import os
import selectors
import struct
import time
from dataclasses import dataclass
from typing import cast

from pysh.plugins.isolated.errors import (
    FrameTooLargeError,
    LifecycleTimeoutError,
    ProtocolError,
)

IPC_PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 256 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096
MAX_STRING_BYTES = 64 * 1024
MAX_REQUEST_ID_BYTES = 128

_FRAME_HEADER = struct.Struct("!I")
_REQUIRED_FIELDS = frozenset({"protocol_version", "message_type", "request_id", "payload"})

HANDSHAKE_HELLO = "handshake.hello"
HANDSHAKE_GRANT = "handshake.grant"
HANDSHAKE_READY = "handshake.ready"
REQUEST_ENVIRONMENT = "request.environment"
REQUEST_FILESYSTEM_READ = "request.filesystem.read"
REQUEST_FILESYSTEM_WRITE = "request.filesystem.write"
REQUEST_COMMAND = "request.command"
REQUEST_NETWORK_CONNECT = "request.network.connect"
RESPONSE_OK = "response.ok"
RESPONSE_ERROR = "response.error"
LIFECYCLE_SHUTDOWN = "lifecycle.shutdown"
LIFECYCLE_SHUTDOWN_ACK = "lifecycle.shutdown_ack"

KNOWN_MESSAGE_TYPES: frozenset[str] = frozenset({
    HANDSHAKE_HELLO,
    HANDSHAKE_GRANT,
    HANDSHAKE_READY,
    REQUEST_ENVIRONMENT,
    REQUEST_FILESYSTEM_READ,
    REQUEST_FILESYSTEM_WRITE,
    REQUEST_COMMAND,
    REQUEST_NETWORK_CONNECT,
    RESPONSE_OK,
    RESPONSE_ERROR,
    LIFECYCLE_SHUTDOWN,
    LIFECYCLE_SHUTDOWN_ACK,
})

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class IPCMessage:
    """One validated isolated-plugin wire message."""

    message_type: str
    request_id: str
    payload: dict[str, JsonValue]
    protocol_version: int = IPC_PROTOCOL_VERSION


def encode_message(message: IPCMessage, *, max_bytes: int = MAX_FRAME_BYTES) -> bytes:
    """Validate and encode one message with a four-byte network-order length."""
    validated = validate_message({
        "protocol_version": message.protocol_version,
        "message_type": message.message_type,
        "request_id": message.request_id,
        "payload": message.payload,
    })
    try:
        body = json.dumps(
            {
                "protocol_version": validated.protocol_version,
                "message_type": validated.message_type,
                "request_id": validated.request_id,
                "payload": validated.payload,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("message payload is not valid bounded JSON") from exc
    if len(body) > max_bytes:
        raise FrameTooLargeError(f"IPC frame exceeds {max_bytes} bytes")
    return _FRAME_HEADER.pack(len(body)) + body


def decode_message(frame: bytes, *, max_bytes: int = MAX_FRAME_BYTES) -> IPCMessage:
    """Decode exactly one complete framed message and reject trailing bytes."""
    if len(frame) < _FRAME_HEADER.size:
        raise ProtocolError("IPC frame header is incomplete")
    (size,) = _FRAME_HEADER.unpack(frame[: _FRAME_HEADER.size])
    if size > max_bytes:
        raise FrameTooLargeError(f"IPC frame exceeds {max_bytes} bytes")
    if len(frame) != _FRAME_HEADER.size + size:
        raise ProtocolError("IPC frame length does not match its header")
    return _decode_body(frame[_FRAME_HEADER.size :])


def read_message(
    file_descriptor: int,
    *,
    timeout: float,
    max_bytes: int = MAX_FRAME_BYTES,
) -> IPCMessage:
    """Read one bounded frame from a descriptor before a monotonic deadline."""
    _validate_timeout(timeout)
    deadline = time.monotonic() + timeout
    header = _read_exact(file_descriptor, _FRAME_HEADER.size, deadline)
    (size,) = _FRAME_HEADER.unpack(header)
    if size > max_bytes:
        raise FrameTooLargeError(f"IPC frame exceeds {max_bytes} bytes")
    body = _read_exact(file_descriptor, size, deadline)
    return _decode_body(body)


def write_message(
    file_descriptor: int,
    message: IPCMessage,
    *,
    timeout: float = 2.0,
) -> None:
    """Write one validated frame without buffering or an unbounded pipe wait."""
    _validate_timeout(timeout)
    frame = encode_message(message)
    view = memoryview(frame)
    deadline = time.monotonic() + timeout
    try:
        was_blocking = os.get_blocking(file_descriptor)
        os.set_blocking(file_descriptor, False)
    except OSError as exc:
        raise ProtocolError("isolated-plugin IPC descriptor cannot be configured") from exc
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(file_descriptor, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise LifecycleTimeoutError("isolated-plugin IPC write timed out")
                try:
                    written = os.write(file_descriptor, view)
                except BlockingIOError:
                    continue
                except (BrokenPipeError, OSError) as exc:
                    raise ProtocolError("isolated-plugin IPC write failed") from exc
                if written <= 0:
                    raise ProtocolError("isolated-plugin IPC write made no progress")
                view = view[written:]
    finally:
        try:
            os.set_blocking(file_descriptor, was_blocking)
        except OSError:
            pass


def validate_message(value: object) -> IPCMessage:
    """Validate message schema, version, type, IDs, and bounded JSON shape."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProtocolError("IPC message must be a JSON object")
    if set(value) != _REQUIRED_FIELDS:
        raise ProtocolError("IPC message fields do not match the protocol schema")

    protocol_version = value["protocol_version"]
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int):
        raise ProtocolError("protocol_version must be an integer")
    if protocol_version != IPC_PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported IPC protocol version: {protocol_version}")

    message_type = value["message_type"]
    if not isinstance(message_type, str) or message_type not in KNOWN_MESSAGE_TYPES:
        raise ProtocolError("unknown IPC message type")
    request_id = value["request_id"]
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError("request_id must be a non-empty string")
    if len(request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES or "\x00" in request_id:
        raise ProtocolError("request_id is invalid or too long")

    payload = value["payload"]
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ProtocolError("payload must be a JSON object")
    _validate_json_value(payload)
    return IPCMessage(
        protocol_version=protocol_version,
        message_type=message_type,
        request_id=request_id,
        payload=cast(dict[str, JsonValue], payload),
    )


def _decode_body(body: bytes) -> IPCMessage:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError("IPC payload is not valid UTF-8") from exc
    try:
        value = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProtocolError("IPC payload is not valid JSON") from exc
    return validate_message(value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _validate_json_value(value: JsonValue) -> None:
    nodes = 0
    stack: list[tuple[JsonValue, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ProtocolError("IPC JSON structure contains too many values")
        if depth > MAX_JSON_DEPTH:
            raise ProtocolError("IPC JSON structure is too deeply nested")
        if current is None or isinstance(current, bool):
            continue
        if isinstance(current, int):
            if not -(2**63) <= current <= 2**63 - 1:
                raise ProtocolError("IPC JSON integer is outside the signed 64-bit range")
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise ProtocolError("IPC JSON number must be finite")
            continue
        if isinstance(current, str):
            if len(current.encode("utf-8")) > MAX_STRING_BYTES:
                raise ProtocolError("IPC JSON string exceeds the maximum length")
            continue
        if isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
            continue
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ProtocolError("IPC JSON object keys must be strings")
                if len(key.encode("utf-8")) > MAX_STRING_BYTES:
                    raise ProtocolError("IPC JSON key exceeds the maximum length")
                stack.append((item, depth + 1))
            continue
        raise ProtocolError("IPC payload contains an unsupported JSON value")


def _read_exact(file_descriptor: int, size: int, deadline: float) -> bytes:
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(file_descriptor, selectors.EVENT_READ)
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LifecycleTimeoutError("isolated-plugin IPC read timed out")
            if not selector.select(remaining):
                raise LifecycleTimeoutError("isolated-plugin IPC read timed out")
            try:
                chunk = os.read(file_descriptor, size - len(data))
            except OSError as exc:
                raise ProtocolError("isolated-plugin IPC read failed") from exc
            if not chunk:
                raise ProtocolError("isolated-plugin IPC closed unexpectedly")
            data.extend(chunk)
    return bytes(data)


def _validate_timeout(timeout: float) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
