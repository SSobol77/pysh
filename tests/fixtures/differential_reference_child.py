# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/differential_reference_child.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository-owned fake "external interpreter" for executor tests (Issue #54).

It is deterministic test equipment and is never a real Bash, Zsh or Fish. The
first argument selects a mode; the remaining arguments are mode data.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    mode, data = argv[1], argv[2:]
    if mode == "argv":
        print(json.dumps(data))
    elif mode == "env":
        print(json.dumps({name: os.environ.get(name) for name in data}))
    elif mode == "envkeys":
        print(json.dumps(sorted(os.environ)))
    elif mode == "cwd":
        print(os.getcwd())
    elif mode == "listdir":
        print(json.dumps(sorted(os.listdir("."))))
    elif mode == "readfile":
        print(open(data[0], encoding="utf-8").read(), end="")
    elif mode == "stdin":
        sys.stdout.buffer.write(sys.stdin.buffer.read())
    elif mode == "stdin-ignored":
        return 0
    elif mode == "out":
        sys.stdout.write(data[0])
    elif mode == "err":
        sys.stderr.write(data[0])
    elif mode == "both":
        sys.stdout.write("OUT\n")
        sys.stderr.write("ERR\n")
    elif mode == "status":
        return int(data[0])
    elif mode == "signal":
        number = int(data[0])
        signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)
    elif mode == "sleep":
        time.sleep(float(data[0]))
    elif mode == "ignore-term-sleep":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("ready", flush=True)
        time.sleep(float(data[0]))
    elif mode == "flood":
        remaining = int(data[0])
        while remaining > 0:
            block = min(remaining, 4096)
            sys.stdout.write("x" * block)
            sys.stdout.flush()
            remaining -= block
    elif mode == "heartbeat":
        while True:
            with open(data[0], "ab") as handle:
                handle.write(b".")
            time.sleep(0.02)
    elif mode in {"spawn", "spawn-exit"}:
        quiet = mode == "spawn-exit"
        child = subprocess.Popen(  # noqa: S603 - fixed interpreter and this fixture
            [sys.executable, os.path.abspath(__file__), "heartbeat", data[0]],
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
        print(child.pid, flush=True)
        if quiet:  # exit only once the background child is demonstrably running
            deadline = time.monotonic() + 10
            while not os.path.exists(data[0]) and time.monotonic() < deadline:
                time.sleep(0.01)
        else:
            time.sleep(60)
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
