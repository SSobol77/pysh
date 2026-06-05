<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/posix-sh-scope.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# POSIX sh Scope

This document defines PySH's relationship to the POSIX shell standard
(IEEE Std 1003.1, Shell Command Language).

---

## Governing statements

1. **PySH is not a POSIX sh implementation.** PySH does not implement the
   complete POSIX shell grammar, parameter expansion model, or script execution
   semantics.

2. **PySH must not be symlinked as `/bin/sh`.** Doing so would break system
   scripts and maintenance tools that rely on POSIX sh semantics. This is a
   hard prohibition.

3. **PySH executes only its own documented native constructs.** POSIX shell
   scripts that use constructs beyond PySH's documented native surface will
   produce incorrect or absent behavior. This is not a bug in those scripts.

4. **POSIX shell scripts should not be assumed compatible.** Passing a POSIX sh
   script to PySH's native executor is not supported. Use `run_script` to
   delegate scripts with `#!/bin/sh` shebangs to the real `sh` interpreter.

5. **Script mode is PySH-native.** `.pysh` script semantics do not imply POSIX
   sh compatibility.

6. **System shell integration is explicit and bounded.** PySH may be launched
   as `pysh` for interactive use or PySH-native scripts, but it must not be
   installed or invoked as the system `/bin/sh` provider. See
   [system-shell-integration-policy.md](system-shell-integration-policy.md).

---

## POSIX sh scope table

| POSIX sh area | Current PySH status | Notes | Owner issue |
| ------------- | ------------------- | ----- | ----------- |
| Sequential execution (`;`) | Supported (native) | Documented in operators | — |
| Conditional AND (`&&`) | Supported (native) | Documented in operators | — |
| Conditional OR (`\|\|`) | Supported (native) | Documented in operators | — |
| Pipeline (`\|`) | Supported (native) | With correct fd handover | — |
| Input/output redirection | Supported (native) | `<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>` | — |
| Simple command execution | Supported (native) | External commands via PATH | — |
| Variable assignment (`NAME=val`) | Supported (native) | Local scope | — |
| Variable expansion (`$NAME`, `${NAME}`) | Supported (native) | Simple forms only | — |
| Export (`export NAME=val`) | Supported (native) | — | — |
| Quoting (single, double, backslash) | Supported (native) | Per-POSIX semantics | — |
| Command substitution (`$(...)`, backtick) | Supported (native) | 5-second timeout | — |
| Shell comments (`#`) | Supported (native) | — | — |
| `cd`, `pwd` builtins | Supported (native) | — | — |
| `exit` builtin | Supported (native) | — | — |
| Shell functions | **Not supported** | Not in PySH grammar | — |
| `case` statement | **Not supported** | — | — |
| `for` / `while` / `until` loops (in scripts) | **Not supported** (native) | Mini-interpreter in rc files only | — |
| `test` / `[` builtin | **Not supported** | Use Python in `py { ... }` | — |
| Arithmetic expansion (`$((expr))`) | **Not supported** | Deterministic parser diagnostic | — |
| Here-documents (`<< DELIM`) | Supported for documented native policy | Native | #10 |
| Native glob expansion (`*`, `?`, `[...]`) | Supported for documented native policy | Native | #9 |
| Parameter expansion (advanced forms) | **Not supported** | Simple forms only; advanced forms remain literal | — |
| `set -e`, `set -x`, `set -u` | **Not supported** | Unsupported in PySH Script Mode v1 | #14 |
| Traps (`trap`) | **Not supported** | Not on current roadmap | — |
| Job control (`&`, `jobs`, `bg`, `fg`) | Supported for documented native policy | Native | #11 |
| Process substitution (`<(cmd)`) | **Not supported** | Not planned | — |
| `/bin/sh` provider status | **Not supported** | Hard prohibition | #17 |
| System shell integration policy | Supported | Explicit policy and argv0 diagnostic | #17 |

---

## What to do instead

### For shell scripts

Use `run_script <file>` to delegate POSIX sh scripts to the real `sh`
interpreter. PySH passes the script path and arguments to the interpreter via
an argv list:

```sh
run_script ~/scripts/deploy.sh --dry-run
```

Scripts with `#!/bin/sh` shebangs are delegated automatically when invoked
through `run_script`.

### For system scripts / `/bin/sh` context

Do not route system scripts through PySH. System maintenance scripts, package
hooks, and init system scripts must continue to use a real POSIX sh
(`/bin/dash`, `/bin/bash --posix`, or another POSIX-compliant shell).

### For interactive use

PySH's documented native constructs cover the common interactive shell
workflow. Native PySH scripts do not change the delegation rule for real POSIX
scripts. For constructs that will never be native, use `zsh <cmd>` or
`run_script`.

---

## Validation

POSIX sh scope claims in this document are validated by:

1. Absence of POSIX-incompatible constructs from PySH's own test suite
   (tests do not assume behavior PySH doesn't implement).
2. `tests/test_script_runner.py` — shebang dispatch to real `sh`.
3. Negative test cases confirming that unsupported constructs produce
   deterministic errors rather than silent misinterpretation.

See [validation-matrix.md](validation-matrix.md) for the full validation plan.
