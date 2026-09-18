<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/completion-engine.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Completion Engine Development

Completion Engine 2.0 is implemented in `pysh.editor.lineedit.completion`.
The module is pure: it depends on the Python standard library and data passed
through `CompletionOptions`. It must not import shell runtime internals.

## Architecture

`pysh.editor.completion.Completer` adapts shell state into immutable snapshots:
builtins, aliases, environment names, local variables, job IDs, and `PATH`.
Python command mode passes its active namespace through a separate callback.

The raw reader owns repeated-TAB state and candidate menu rendering. It tracks
the last buffer and completion result so repeated TAB can display candidates
without changing the buffer.

## Cache Contract

`_PathCache` caches the executable inventory for the full `PATH` string. It is
bounded, has TTL invalidation, and supports explicit `invalidate()`. Tests must
use an injected fake monotonic clock; do not use `time.sleep()`.

## Manual Validation Checklist

Debian 13:

- command completion from `PATH`;
- builtin completion;
- alias completion;
- path completion;
- directory completion;
- hidden file completion;
- paths with spaces;
- Unicode paths;
- environment variable completion;
- Python symbol completion;
- repeated TAB candidate display;
- virtualenv active;
- inside and outside Git repositories.

FreeBSD 14+:

- command completion from FreeBSD `PATH`;
- path completion;
- directory completion;
- environment variable completion;
- repeated TAB behavior;
- Python symbol completion;
- no dependency on GNU-specific behavior.

## Safety Review Points

- No completion path may execute a command.
- No completion path may perform network I/O.
- Python dotted completion must not trigger properties or `__getattr__`.
- Filesystem errors must degrade to no candidates.
- Candidate display must preserve the current input buffer.
