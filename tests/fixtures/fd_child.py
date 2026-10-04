# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fd_child.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Child helper for descriptor tests: a bounded ``os.fstat`` scan, no /proc or /dev/fd."""
from __future__ import annotations

import errno
import json
import os
import sys

CAP = 4096


def open_fds() -> list[int]:
    try:
        import resource

        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        bound = CAP if soft == resource.RLIM_INFINITY else min(int(soft), CAP)
    except (ImportError, ValueError, OSError):
        raise SystemExit("probe unavailable") from None
    found: list[int] = []
    for fd in range(bound):
        try:
            os.fstat(fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
            continue
        found.append(fd)
    return found


if __name__ == "__main__":
    # Only stdout carries the report; stdin is never read.
    sys.stdout.write(json.dumps(open_fds()) + "\n")
