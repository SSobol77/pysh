<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/bash-scope.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# bash Scope

This document defines PySH's relationship to bash. PySH's native feature set
shares some surface area with bash (both implement common shell constructs),
but PySH is not bash and does not claim bash compatibility.

---

## Governing statements

1. **PySH is not bash.** PySH does not implement the bash grammar, bash
   builtins, bash arrays, bash parameter expansion forms, or the bash
   interactive feature set (readline key bindings, bash completion, etc.).

2. **Bash/sh alias and profile import is static and limited.** `source_sh_aliases`
   reads `.bash_aliases`, `.profile`, and simple POSIX-style alias/export files
   as text and extracts static entries. It does not execute bash code.

3. **Bash scripts are delegated only through explicit shebang/script runner
   behavior.** `run_script <file>` detects a `#!/bin/bash` shebang and
   delegates to the real bash interpreter via an argv list. PySH does not
   parse or execute bash script syntax natively.

4. **No broad bash compatibility claim is made.** PySH shares basic shell
   constructs with bash (simple commands, pipes, redirection, quoting), but
   this shared surface is POSIX-common ground, not a bash compatibility
   statement.

5. **Foreign bash profile execution must be opt-in if ever added.** Currently
   there is no mechanism to execute bash profiles. Any future mechanism requires
   explicit user action. (Issue #7.)

---

## bash scope table

| bash area | Current PySH status | Handling | Owner issue |
| --------- | ------------------- | -------- | ----------- |
| Simple commands and PATH lookup | Supported | Native — same semantics | — |
| Pipeline, sequence, conditional operators | Supported | Native | — |
| Input/output redirection (`<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`) | Supported | Native | — |
| Single/double quoting | Supported | Native — POSIX semantics | — |
| `$VAR` and `${VAR}` expansion | Supported (simple forms) | Native | — |
| `export NAME=value` | Supported | Native | — |
| `alias`, `unalias` | Supported | Native | — |
| Simple alias/export import from `.bash_aliases` | Supported | Transition — `source_sh_aliases` | — |
| Simple alias/export import from `.profile` | Supported | Transition — `source_sh_aliases` | — |
| `#!/bin/bash` script delegation | Supported | Delegated — `run_script` | #14 |
| bash arrays (`arr=(a b c)`, `${arr[@]}`) | Not supported | Unsupported | — |
| bash associative arrays (`declare -A`) | Not supported | Unsupported | — |
| bash arithmetic (`$(( expr ))`, `(( expr ))`, `let`) | Not supported | Unsupported; Issue #8 adds deterministic diagnostics only | — |
| bash parameter expansion flags | Not supported | Unsupported; simple `$NAME`, `${NAME}` and `$?` only | — |
| bash functions | Not supported | Unsupported | — |
| `declare`, `typeset`, `local` builtins | Not supported | Unsupported | — |
| `read` builtin | Not supported | Unsupported | — |
| `printf` builtin | Not supported | Unsupported (use Python `print`) | — |
| bash `[[ ... ]]` conditional | Not supported | Unsupported | — |
| bash `case` / `select` | Not supported | Unsupported | — |
| bash globbing (`*`, `?`, `[...]`, `**`) | Supported for documented native path expansion | Native | #9 |
| bash extended glob (`extglob`) | Not supported | Unsupported | — |
| bash brace expansion (`{a,b,c}`, `{1..5}`) | Not supported | Unsupported | — |
| bash process substitution (`<(cmd)`) | Not supported | Unsupported | — |
| bash here-strings (`<<<`) | Supported for documented native policy | Native | #10 |
| bash heredocs (`<< DELIM`) | Supported for documented native policy | Native | #10 |
| bash `set -e`, `set -x`, `set -u` | Not supported | Unsupported in PySH Script Mode v1 | #14 |
| bash job control (`&`, `jobs`, `bg`, `fg`) | Not supported | Planned | #11 |
| bash traps (`trap`) | Not supported | Not on current roadmap | — |
| bash `source` / `.` with bash semantics | Not supported | `source` runs PySH rc-interpreter only | — |
| bash readline integration | Partial | Native raw-editor Ctrl+R; readline fallback when active | — |
| bash-compatible `PS1`, `PS2` prompt vars | Not supported | PySH has its own prompt configuration | — |
| Full bash interactive session | Not supported | Use real bash | — |
| `.bashrc` / `.bash_profile` execution | Not supported | Forbidden by default | #7 |

---

## Overlap and distinction

PySH shares these constructs with bash because they are POSIX-common:

- Simple command execution, PATH lookup.
- Pipelines, sequences, conditional operators.
- Redirection syntax (`<`, `>`, `>>`, `2>`, `2>>`).
- Single and double quoting.
- `$VAR` expansion (simple forms).
- `export`.

This shared surface does NOT constitute "bash compatibility." PySH implements
these constructs natively with its own semantics. Where PySH and bash differ
(e.g., in edge cases of quoting, expansion, or redirection), PySH's documented
behavior is authoritative for PySH.

---

## Migration path for bash users

1. **Import stable aliases**: use `source_sh_aliases ~/.bash_aliases` to import
   simple aliases and exports from bash alias files.
2. **Check your `.bashrc`**: use `compat_check ~/.bashrc` to see which entries
   can be imported and which must be migrated manually.
3. **Delegate bash scripts**: use `run_script <file>` for scripts with
   `#!/bin/bash` shebangs.
4. **Move automation to Python**: complex bash scripts can be rewritten as
   `py { ... }` blocks or standalone Python scripts.

---

## Validation

bash scope claims are validated by:

1. `tests/test_profile_importer.py` — static import of bash alias files,
   skip counting for bash-specific constructs.
2. `tests/test_script_runner.py` — bash shebang detection and delegation.
3. `tests/test_parser.py`, `tests/test_redirection.py` — POSIX-common grammar.

See [validation-matrix.md](validation-matrix.md) for the full validation plan.
