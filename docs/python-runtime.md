<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Python runtime

PySH 0.2.0 adds a Python-native runtime bridge through the `py` builtin. This
is a first-class PySH feature: it runs Python code in the shell process using
the current Python 3.13+ runtime and keeps state for the duration of one PySH
session.

## Basic use

```sh
py print("hello from python")
py import platform; print(platform.platform())
py from pathlib import Path; print(Path(".").resolve())
```

The builtin accepts one line of Python code. Standard output and standard
error behave normally.

## Persistent context

Variables and imports persist across `py` invocations:

```sh
py x = 10
py print(x)

py import pathlib
py print(pathlib.Path(".").exists())
```

The context is per `PyShell` instance. Starting a new PySH process creates a
fresh Python runtime context.

## Failure behavior

Python exceptions are contained inside the builtin:

```sh
py 1 / 0
py print("shell still alive")
```

Exceptions are printed cleanly to stderr, the builtin returns non-zero, and
the shell remains usable. The `py` builtin does not terminate the process on
user-code exceptions.

## Scope

`py` is intentionally one-line execution in this release. It is suitable for
interactive inspection, Python-native shell automation and gradual movement
from shell snippets into Python. It is not a replacement for a full Python
REPL, debugger or long-running script supervisor.
