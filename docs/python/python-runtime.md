<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/python/python-runtime.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Python runtime

PySH provides a Python-native runtime bridge through the `py` builtin. This
is a first-class PySH feature: it runs Python code in the shell process using
the installed Python runtime and keeps state for the duration of one PySH
session.

## One-line use

```sh
py print("hello from python")
py import platform; print(platform.platform())
py from pathlib import Path; print(Path(".").resolve())
```

The one-line form accepts any Python statement that fits on a single line.

## Multiline Python automation blocks

PySH supports multiline Python automation blocks:

```sh
py {
    import os
    targets = [p for p in os.environ.get("PATH", "").split(":") if p]
    print(f"PATH entries: {len(targets)}")
}
```

- The opener is a line that, after stripping whitespace, is exactly `py {`.
- The closer is a line that, after stripping whitespace, is exactly `}`.
- The block body executes in the **same persistent Python runtime context**
  as one-line `py` invocations.
- Variables and imports flow in both directions between one-line and block
  forms.

In interactive mode, PySH displays the continuation prompt `py> ` until the
closing `}` line is entered. In script/source mode, the block is collected
before execution and unterminated blocks return non-zero.

## Persistent context

```sh
py x = 10
py {
    print(x + 1)
    y = "shared"
}
py print(y)
```

The context is per `PyShell` instance. Starting a new PySH process creates a
fresh Python runtime context.

## Failure behavior

```sh
py 1 / 0
py {
    raise RuntimeError("oops")
}
py print("shell still alive")
```

Exceptions are printed cleanly to stderr. The builtin returns non-zero and
the shell stays usable. `KeyboardInterrupt` is handled as normal Ctrl+C
behavior: it returns 130 and does not print a traceback. A `SyntaxError`
inside a block is reported and returns non-zero. An unterminated block in
script mode returns non-zero and does **not** execute any partial body.

## Scope and limitations

- Nested `py { ... }` blocks are not supported. A second `py {` opener while
  a block is open produces a deterministic error.
- Block bodies are dedented (common leading whitespace is removed) so that
  indented blocks inside scripts and plugins work without surprises.
- The runtime is intentionally per-session: there is no globally persisted
  Python state between PySH invocations.
- This is not a full Python REPL replacement: there is no `help()` prompt,
  no autocompletion of attribute names, and no debugger.
