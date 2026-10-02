# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/resource_probe.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Bounded isolated-plugin probe reporting the resource limits it actually runs under."""
from __future__ import annotations

import errno
import json
import os
import resource
import struct
import sys

PROTOCOL = 1
_LIMITS = {
    "cpu": "RLIMIT_CPU",
    "as": "RLIMIT_AS",
    "vmem": "RLIMIT_VMEM",
    "nofile": "RLIMIT_NOFILE",
    "nproc": "RLIMIT_NPROC",
}


def _send(message_type: str, request_id: str, payload: dict[str, object]) -> None:
    body = json.dumps(
        {
            "protocol_version": PROTOCOL,
            "message_type": message_type,
            "request_id": request_id,
            "payload": payload,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    os.write(sys.stdout.fileno(), struct.pack("!I", len(body)) + body)


def _read() -> dict[str, object]:
    def exact(size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = os.read(sys.stdin.fileno(), size - len(data))
            if not chunk:
                raise EOFError
            data.extend(chunk)
        return bytes(data)

    (size,) = struct.unpack("!I", exact(4))
    return json.loads(exact(size).decode("utf-8"))


def _report(value: object) -> None:
    _send("request.command", "request-1", {"name": "report", "argv": [json.dumps(value)]})
    _read()


def _rlimits() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for label, constant in _LIMITS.items():
        which = getattr(resource, constant, None)
        if which is not None:
            found[label] = list(resource.getrlimit(which))
    return found


def _open_until_limit() -> dict[str, object]:
    held: list[int] = []
    code = 0
    try:
        for _ in range(4096):
            held.append(os.open(os.devnull, os.O_RDONLY))
    except OSError as exc:
        code = exc.errno or 0
    opened = len(held)
    for descriptor in held:
        os.close(descriptor)
    return {"opened": opened, "errno": code, "emfile": errno.EMFILE}


def _fork_once() -> dict[str, object]:
    try:
        pid = os.fork()
    except OSError as exc:
        return {"forked": False, "errno": exc.errno, "eagain": errno.EAGAIN}
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return {"forked": True}


def _try_raise() -> dict[str, object]:
    results: dict[str, object] = {}
    for label in ("cpu", "nofile", "as"):
        which = getattr(resource, _LIMITS[label], None)
        if which is None:
            continue
        soft, hard = resource.getrlimit(which)
        try:
            resource.setrlimit(which, (soft, hard + 1))
        except (ValueError, OSError):
            results[label] = "denied"
        else:
            results[label] = "raised"
    return results


def _allocate(mebibytes: int) -> str:
    try:
        block = bytearray(mebibytes * 1024 * 1024)
    except MemoryError:
        return "memory_error"
    return f"ok:{len(block)}"


def main() -> int:
    name, version, mode, *arguments = sys.argv[1:]
    _send("handshake.hello", "hello", {
        "plugin_name": name, "plugin_version": version, "protocol_version": PROTOCOL,
    })
    _read()
    _send("handshake.ready", "hello", {"plugin_name": name})
    if mode == "rlimits":
        _report(_rlimits())
    elif mode == "open_fds":
        _report(_open_until_limit())
    elif mode == "raise_limits":
        _report(_try_raise())
    elif mode == "alloc":
        _report(_allocate(int(arguments[0])))
    elif mode == "spin":
        while True:
            pass
    elif mode == "fork":
        _report(_fork_once())
    elif mode == "big_request":
        # A schema-valid request whose frame is larger than a small message budget.
        _send("request.command", "request-1",
              {"name": "report", "argv": ["x" * int(arguments[0])]})
        _read()
    elif mode == "request_environment":
        _send("request.environment", "request-1", {"name": arguments[0]})
        _read()
    while True:
        message = _read()
        if message.get("message_type") != "lifecycle.shutdown":
            return 21
        _send("lifecycle.shutdown_ack", str(message["request_id"]), {})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
