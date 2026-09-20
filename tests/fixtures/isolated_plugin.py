# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/isolated_plugin.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Deterministic broken/malicious isolated-plugin protocol fixture."""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from pathlib import Path

IPC_PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 256 * 1024
HANDSHAKE_HELLO = "handshake.hello"
HANDSHAKE_GRANT = "handshake.grant"
HANDSHAKE_READY = "handshake.ready"
REQUEST_ENVIRONMENT = "request.environment"
REQUEST_FILESYSTEM_READ = "request.filesystem.read"
REQUEST_FILESYSTEM_WRITE = "request.filesystem.write"
REQUEST_COMMAND = "request.command"
REQUEST_NETWORK_CONNECT = "request.network.connect"
LIFECYCLE_SHUTDOWN = "lifecycle.shutdown"
LIFECYCLE_SHUTDOWN_ACK = "lifecycle.shutdown_ack"


def _write_raw(value: object) -> None:
    body = json.dumps(value, separators=(",", ":")).encode("utf-8")
    os.write(sys.stdout.fileno(), struct.pack("!I", len(body)) + body)


def _write_oversized_header() -> None:
    os.write(sys.stdout.fileno(), struct.pack("!I", MAX_FRAME_BYTES + 1))


def _write_message(message_type: str, request_id: str, payload: dict[str, object]) -> None:
    _write_raw(
        {
            "protocol_version": IPC_PROTOCOL_VERSION,
            "message_type": message_type,
            "request_id": request_id,
            "payload": payload,
        }
    )


def _read_exact(size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = os.read(sys.stdin.fileno(), size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def _read_message() -> dict[str, object]:
    (size,) = struct.unpack("!I", _read_exact(4))
    if size > MAX_FRAME_BYTES:
        raise ValueError("parent frame exceeds fixture bound")
    value = json.loads(_read_exact(size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("parent message must be an object")
    return value


def _send_request(message_type: str, payload: dict[str, object]) -> None:
    _write_message(message_type, "request-1", payload)
    _read_message()


def _report(argv: list[str]) -> None:
    _send_request(REQUEST_COMMAND, {"name": "report", "argv": argv})


def main() -> int:
    name, version, mode, *arguments = sys.argv[1:]
    if mode == "hang_handshake":
        time.sleep(60)
        return 0
    if mode == "malformed_handshake":
        os.write(sys.stdout.fileno(), struct.pack("!I", 1) + b"{")
        return 0
    if mode == "oversized_handshake":
        _write_oversized_header()
        return 0
    if mode == "unknown_handshake":
        _write_raw(
            {
                "protocol_version": IPC_PROTOCOL_VERSION,
                "message_type": "unknown.message",
                "request_id": "hello",
                "payload": {},
            }
        )
        return 0
    if mode == "version_mismatch":
        _write_raw(
            {
                "protocol_version": IPC_PROTOCOL_VERSION + 1,
                "message_type": HANDSHAKE_HELLO,
                "request_id": "hello",
                "payload": {},
            }
        )
        return 0

    hello_name = "wrong-plugin" if mode == "identity_mismatch" else name
    _write_message(
        HANDSHAKE_HELLO,
        "hello",
        {
            "plugin_name": hello_name,
            "plugin_version": version,
            "protocol_version": IPC_PROTOCOL_VERSION,
        },
    )
    grant = _read_message()
    if grant.get("message_type") != HANDSHAKE_GRANT:
        return 20
    _write_message(HANDSHAKE_READY, "hello", {"plugin_name": name})

    if mode == "crash":
        os._exit(23)
    if mode == "hang_after_ready":
        time.sleep(60)
    elif mode == "malformed_running":
        os.write(sys.stdout.fileno(), struct.pack("!I", 1) + b"{")
    elif mode == "oversized_running":
        _write_oversized_header()
    elif mode == "unknown_running":
        _write_raw(
            {
                "protocol_version": IPC_PROTOCOL_VERSION,
                "message_type": "request.escalate",
                "request_id": "request-1",
                "payload": {},
            }
        )
    elif mode == "request_environment":
        _send_request(REQUEST_ENVIRONMENT, {"name": arguments[0]})
    elif mode == "request_read":
        _send_request(REQUEST_FILESYSTEM_READ, {"path": arguments[0]})
    elif mode == "request_write":
        _send_request(
            REQUEST_FILESYSTEM_WRITE,
            {"path": arguments[0], "data": arguments[1]},
        )
    elif mode == "request_network":
        _send_request(
            REQUEST_NETWORK_CONNECT,
            {"host": arguments[0], "port": int(arguments[1])},
        )
    elif mode == "environment_probe":
        _report([json.dumps(dict(os.environ), sort_keys=True)])
    elif mode == "cwd_probe":
        _report([os.getcwd()])
    elif mode == "fd_probe":
        try:
            os.fstat(int(arguments[0]))
        except OSError:
            state = "closed"
        else:
            state = "open"
        _report([state])
    elif mode == "direct_file_probe":
        try:
            Path(arguments[0]).read_bytes()
        except OSError:
            state = "denied"
        else:
            state = "accessible"
        _report([state])

    while True:
        message = _read_message()
        if message.get("message_type") != LIFECYCLE_SHUTDOWN:
            return 21
        if mode == "hang_shutdown":
            time.sleep(60)
        _write_message(
            LIFECYCLE_SHUTDOWN_ACK,
            str(message["request_id"]),
            {},
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
