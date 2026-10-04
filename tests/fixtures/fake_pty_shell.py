# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fake_pty_shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository-owned FAKE interactive shell for the PTY-harness unit tests.

Selected by file name (``bash``/``zsh``/``fish``, or ``<shell>_<variant>``). It prints
the prompt from ``PS1``, then implements just ``fixture-echo``, ``export`` and ``exit``
so the controlled-PTY harness can be exercised, including failure modes, without a real
Bash, Zsh or Fish. Variants: ``hang`` (never reads), ``flood`` (endless output),
``hostile`` (prints the hostile-startup marker), ``orphan`` (leaves a background
descendant in its session and exits).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time


def expand(word: str) -> str:
    for name, value in sorted(os.environ.items(), key=lambda item: -len(item[0])):
        word = word.replace(f"${name}", value)
    return word


def main(argv: list[str]) -> int:
    _kind, _, variant = os.path.basename(argv[0]).partition("_")
    prompt = os.environ.get("PS1", "PTY> ")
    if variant == "hostile":
        print("HOSTILE-STARTUP-FILE-EXECUTED:fake", flush=True)
    if variant == "orphan":
        subprocess.Popen(  # noqa: S603 - test fixture spawning its own helper
            [sys.executable, os.environ["FAKE_CHILD"], "heartbeat", os.environ["FAKE_BEAT"]],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    if variant == "orphan":  # report ready only once the descendant is demonstrably running
        deadline = time.monotonic() + 20
        while not os.path.exists(os.environ["FAKE_BEAT"]) and time.monotonic() < deadline:
            time.sleep(0.01)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    if variant == "hang":
        time.sleep(600)
    if variant == "flood":
        while True:
            sys.stdout.write("x" * 4096)
            sys.stdout.flush()
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        words = shlex.split(line)
        if not words:
            pass
        elif words[0] == "fixture-echo":
            print(" ".join(expand(w) for w in words[1:]))
        elif words[0] == "export":
            name, _, value = words[1].partition("=")
            os.environ[name] = value
        elif words[0] == "exit":
            return int(words[1]) if len(words) > 1 else 0
        else:
            print(f"fake: {words[0]}: command not found")
        sys.stdout.write(prompt)
        sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
