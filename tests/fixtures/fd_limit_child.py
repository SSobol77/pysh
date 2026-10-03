# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fd_limit_child.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Run a pipeline in a child whose soft RLIMIT_NOFILE leaves exactly one free descriptor.

Only this child's soft limit changes (the hard limit and the parent are untouched);
the soft limit is restored afterwards to prove the shell still works.
"""
from __future__ import annotations

import json
import resource
import sys

from pysh.config.startup import NO_RC_STARTUP_POLICY
from pysh.core.shell import PyShell
from tests.fuzz_support import fdprobe


def main() -> int:
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    before = sorted(fdprobe.open_fds())
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(before) + 2, hard))  # one free fd
    try:
        status = shell.execute(sys.argv[1])
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    after = sorted(fdprobe.open_fds())
    health = shell.execute(sys.argv[2])
    sys.stdout.flush()
    print(json.dumps({"status": status, "before": before, "after": after, "health": health}),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
