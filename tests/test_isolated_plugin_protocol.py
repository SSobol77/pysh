# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_isolated_plugin_protocol.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Bounded IPC protocol tests for isolated plugins (Issue #44)."""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from pysh.plugins.isolated.errors import (
    FrameTooLargeError,
    LifecycleTimeoutError,
    ProtocolError,
)
from pysh.plugins.isolated.protocol import (
    IPC_PROTOCOL_VERSION,
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    REQUEST_ENVIRONMENT,
    IPCMessage,
    decode_message,
    encode_message,
    read_message,
    write_message,
)


def _raw_frame(value: object) -> bytes:
    body = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(body)) + body


def _message_dict(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocol_version": IPC_PROTOCOL_VERSION,
        "message_type": REQUEST_ENVIRONMENT,
        "request_id": "request-1",
        "payload": {"name": "VISIBLE"},
    }
    value.update(overrides)
    return value


def test_protocol_round_trip_is_deterministic_utf8_json() -> None:
    message = IPCMessage(
        message_type=REQUEST_ENVIRONMENT,
        request_id="request-1",
        payload={"name": "UNICODE_Ł"},
    )

    encoded = encode_message(message)

    assert decode_message(encoded) == message
    assert encoded == encode_message(message)


@pytest.mark.parametrize(
    "frame",
    [
        b"\x00\x00",
        struct.pack("!I", 3) + b"{}",
        struct.pack("!I", 2) + b"{}trailing",
        struct.pack("!I", 1) + b"\xff",
        struct.pack("!I", 1) + b"{",
        _raw_frame([]),
        _raw_frame(_message_dict(payload=[])),
        _raw_frame(_message_dict(extra=True)),
        _raw_frame(_message_dict(message_type="unknown.message")),
        _raw_frame(_message_dict(protocol_version=999)),
    ],
)
def test_protocol_rejects_malformed_frames_and_schema(frame: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_message(frame)


def test_protocol_rejects_oversized_frame_before_body_allocation() -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, struct.pack("!I", MAX_FRAME_BYTES + 1))
        with pytest.raises(FrameTooLargeError):
            read_message(read_fd, timeout=0.2)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_protocol_rejects_excessive_json_nesting() -> None:
    payload: object = "leaf"
    for _ in range(MAX_JSON_DEPTH + 1):
        payload = [payload]
    frame = _raw_frame(_message_dict(payload={"nested": payload}))

    with pytest.raises(ProtocolError, match="deeply nested"):
        decode_message(frame)


def test_protocol_partial_frame_times_out_without_unbounded_wait() -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"\x00\x00")
        with pytest.raises(LifecycleTimeoutError):
            read_message(read_fd, timeout=0.05)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_protocol_write_to_full_pipe_times_out() -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.set_blocking(write_fd, False)
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        os.set_blocking(write_fd, True)

        with pytest.raises(LifecycleTimeoutError):
            write_message(
                write_fd,
                IPCMessage(
                    message_type=REQUEST_ENVIRONMENT,
                    request_id="blocked-write",
                    payload={"name": "VISIBLE"},
                ),
                timeout=0.05,
            )
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_isolated_runtime_contains_no_executable_object_deserialization() -> None:
    source_root = Path(__file__).parent.parent / "src" / "pysh" / "plugins" / "isolated"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source_root.glob("*.py"))
    )

    assert "import pickle" not in source
    assert "import marshal" not in source
    assert "pickle." not in source
    assert "marshal." not in source
    assert "eval(" not in source
    assert "exec(" not in source
