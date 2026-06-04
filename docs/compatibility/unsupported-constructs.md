<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/unsupported-constructs.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Unsupported Constructs

This document lists shell constructs that are not yet implemented natively in
PySH 0.5.x, their current behavior when attempted, and the required user
action.

Constructs marked **Planned** have an owner issue and will be implemented.
Constructs marked **Unsupported** are not on the current roadmap.
Entries that were historically unsupported may remain listed with their
implemented status when a roadmap issue closes the gap.

Issue #8 added parser foundation and deterministic diagnostics for selected
unsupported constructs. It did not implement arithmetic expansion, advanced
parameter expansion, fd duplication, nested command substitution, pipefail,
ANSI C quoting, or full script loop semantics.

---

## Summary

| Construct | Category | Owner issue |
| --------- | -------- | ----------- |
| Shell functions | Unsupported | — |
| Shell arrays | Unsupported | — |
| Arithmetic expansion `$((expr))` | Unsupported | — |
| Advanced parameter expansion | Unsupported | — |
| `fd` duplication `2>&1` | Unsupported | — |
| Nested command substitution | Unsupported | — |
| Native glob expansion | Supported (Issue #9) | #9 |
| Job-control extensions (`wait`, `disown`) | Unsupported | #11 |
| Process substitution `<(cmd)` | Unsupported | — |
| Brace expansion `{a,b,c}` | Unsupported | — |
| `case` / `select` statements | Unsupported | — |
| Programmable shell completion scripts | Unsupported | — |
| Traps | Unsupported | — |
| `test` / `[` / `[[` builtins | Unsupported | — |
| `read` builtin | Unsupported | — |
| `printf` builtin | Unsupported | — |
| `declare` / `typeset` / `local` | Unsupported | — |
| `pipefail` semantics | Unsupported | — |
| ANSI C quoting `$'...'` | Unsupported | — |
| Full for/while/until in scripts | Unsupported | — |
| POSIX `set -e`, `set -x`, `set -u` | Unsupported | #14 |
| `/bin/sh` provider | Unsupported | #17 |

---

## Detailed entries

### Shell functions

| Field | Value |
| ----- | ----- |
| Construct | `function f() { ... }` / `f() { ... }` |
| Current behavior | PySH does not parse function definitions. Lines that define functions are not executed as functions and will produce an error or be misinterpreted. |
| Required user action | Define automation in Python using `py { ... }` blocks or standalone `.py` files. |
| Owner issue | Not on current roadmap |

### Shell arrays

| Field | Value |
| ----- | ----- |
| Construct | `arr=(a b c)`, `${arr[@]}`, `${arr[0]}`, `declare -a`, `declare -A` |
| Current behavior | Not supported. Array syntax is not parsed. |
| Required user action | Use Python lists via `py { ... }`: `py arr = ["a", "b", "c"]` |
| Owner issue | Not on current roadmap |

### Arithmetic expansion

| Field | Value |
| ----- | ----- |
| Construct | `$((expr))`, `(( expr ))`, `let NAME=expr` |
| Current behavior | Not supported. Parser-owned diagnostic; returns exit status 2. |
| Required user action | Use Python arithmetic via `py`: `py result = 2 + 3` |
| Owner issue | — |

### Advanced parameter expansion

| Field | Value |
| ----- | ----- |
| Construct | `${VAR:-default}`, `${VAR:=default}`, `${VAR:?err}`, `${#VAR}`, `${VAR#pat}`, `${VAR%pat}`, `${VAR/old/new}` |
| Current behavior | Only `$VAR`, `${VAR}` and `$?` simple forms are supported. Advanced expansion forms are not expanded and remain literal. |
| Required user action | Use Python string operations via `py { ... }` |
| Owner issue | — |

### File descriptor duplication

| Field | Value |
| ----- | ----- |
| Construct | `2>&1`, `1>&2`, `N>&M` |
| Current behavior | Not supported. `2>&1` is not recognized as fd duplication. |
| Required user action | Use `&>` or `&>>` for combined stdout+stderr, or delegate to a real shell. |
| Owner issue | — |

### Nested command substitution

| Field | Value |
| ----- | ----- |
| Construct | `$(cmd1 $(cmd2))` |
| Current behavior | Not fully supported. Outer substitution is recognized; inner may not parse correctly. |
| Required user action | Use sequential `py` invocations or intermediate variables. |
| Owner issue | — |

### Native glob expansion

Implemented in Issue #9.

| Field | Value |
| ----- | ----- |
| Construct | `*.py`, `file?.txt`, `dir/[abc]*`, `**/*.md` |
| Current behavior | Supported. PySH expands unquoted glob patterns before passing arguments to commands. Quoted patterns (`"*.py"`, `'*.py'`) remain literal. No-match returns the literal pattern. |
| Owner issue | Issue #9 (implemented) |

### Job control

| Field | Value |
| ----- | ----- |
| Construct | `cmd &`, `jobs`, `bg %N`, `fg %N`, `Ctrl+Z` |
| Current behavior | Supported by the Issue #11 job-control model. Full Ctrl+Z behavior requires a real TTY. |
| Required user action | Use documented `cmd &`, `jobs`, `fg` and `bg`; `wait` and `disown` remain unsupported. |
| Owner issue | Issue #11 (implemented core model) |

### Process substitution

| Field | Value |
| ----- | ----- |
| Construct | `<(cmd)`, `>(cmd)` |
| Current behavior | Not supported. |
| Required user action | Use named pipes (`mkfifo`) or temporary files, or delegate via `zsh <cmd>`. |
| Owner issue | Not on current roadmap |

### Brace expansion

| Field | Value |
| ----- | ----- |
| Construct | `{a,b,c}`, `{1..5}`, `prefix{a,b}suffix` |
| Current behavior | Braces are passed literally. `{a,b,c}` is not expanded to `a b c`. |
| Required user action | List values explicitly, or use Python iteration via `py { ... }`. |
| Owner issue | Not on current roadmap |

### `case` and `select` statements

| Field | Value |
| ----- | ----- |
| Construct | `case VAR in pattern) ... ;; esac`, `select NAME in ...` |
| Current behavior | Not supported as native shell constructs. |
| Required user action | Use `if`/`elif` chains, or Python `match`/`if` statements via `py { ... }`. |
| Owner issue | Not on current roadmap |

### Traps

| Field | Value |
| ----- | ----- |
| Construct | `trap 'cmd' SIGNAL`, `trap '' SIGNAL`, `trap 'cmd' EXIT` |
| Current behavior | Not supported. |
| Required user action | Handle signals in Python via `py { import signal; signal.signal(...) }` |
| Owner issue | Not on current roadmap |

### `test` / `[` / `[[` builtins

| Field | Value |
| ----- | ----- |
| Construct | `test -f file`, `[ -d dir ]`, `[[ "$VAR" == "val" ]]` |
| Current behavior | Not implemented as native builtins. |
| Required user action | Use Python conditionals: `py { if not Path("file").exists(): ... }` |
| Owner issue | Not on current roadmap |

### `read` builtin

| Field | Value |
| ----- | ----- |
| Construct | `read VAR` (read input into variable) |
| Current behavior | Not supported. |
| Required user action | Use Python: `py { var = input("prompt: ") }` |
| Owner issue | Not on current roadmap |

### `printf` builtin

| Field | Value |
| ----- | ----- |
| Construct | `printf "%s\n" value` |
| Current behavior | `printf` is not a PySH builtin. Delegates to external `printf` if installed. |
| Required user action | Use `echo` or Python `print` via `py`. |
| Owner issue | Not on current roadmap |

### `declare` / `typeset` / `local`

| Field | Value |
| ----- | ----- |
| Construct | `declare -i`, `typeset NAME`, `local NAME` |
| Current behavior | Not supported as builtins. |
| Required user action | Use normal shell variables or Python via `py`. |
| Owner issue | Not on current roadmap |

### `pipefail` semantics

| Field | Value |
| ----- | ----- |
| Construct | `set -o pipefail` (exit on any pipeline failure) |
| Current behavior | PySH returns the exit status of the last pipeline stage. |
| Required user action | Check intermediate exit status manually. |
| Owner issue | — |

### ANSI C quoting

| Field | Value |
| ----- | ----- |
| Construct | `$'string with \n \t \x41'` |
| Current behavior | Not supported. `$'...'` is not parsed as ANSI C quoting. |
| Required user action | Use Python string escapes via `py`. |
| Owner issue | — |

### Full `for`/`while`/`until` in scripts

| Field | Value |
| ----- | ----- |
| Construct | Shell loop constructs in scripts (beyond the mini rc-interpreter) |
| Current behavior | The mini rc-interpreter supports `for`/`while`/`if` in `~/.pyshrc` and `.pysh` plugins. Full loop semantics in arbitrary scripts are not implemented. |
| Required user action | Use Python loops via `py { ... }` or `run_script` to delegate to a real shell. |
| Owner issue | — |

### `set` options (`-e`, `-x`, `-u`)

| Field | Value |
| ----- | ----- |
| Construct | `set -e` (exit on error), `set -x` (trace), `set -u` (unset var error) |
| Current behavior | Not supported. |
| Required user action | Wait for Issue #14 (script mode). |
| Owner issue | Issue #14 |

### `/bin/sh` provider

| Field | Value |
| ----- | ----- |
| Construct | Symlinking PySH as `/bin/sh` |
| Current behavior | **Hard prohibition.** PySH must not be used as `/bin/sh`. System scripts and maintenance tools rely on POSIX sh semantics that PySH does not implement. |
| Required user action | Keep a real POSIX sh (`/bin/dash`, `/bin/bash --posix`, etc.) as `/bin/sh`. |
| Owner issue | Issue #17 |
