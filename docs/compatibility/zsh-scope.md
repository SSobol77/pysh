<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/zsh-scope.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# zsh Scope

This document defines PySH's relationship to zsh. For the full transition-layer
workflow, see [Zsh compatibility guide](../migration/zsh-compatibility.md).

---

## Governing statements

1. **PySH is not a zsh clone.** PySH does not implement the zsh grammar,
   expansion model, module system, or completion framework.

2. **PySH has zsh migration helpers.** They provide safe static import of
   aliases and profile entries and a static compatibility checker. PySH does
   not run zsh on the user's behalf.

3. **Static alias/profile import is not execution.** `source_zsh`,
   `source_zsh_profile`, and `source_sh_aliases` read files as text and
   extract safe, simple alias/export/assignment entries. They do not execute
   shell code, run plugin managers, evaluate `eval` expressions, or call
   external commands.

4. **There is no `zsh` builtin.** `zsh` is an ordinary program name: if a
   `zsh` executable is on PATH it runs like any other external command, with
   exactly the arguments the user typed. PySH adds no flags (such as `-lc`) and
   no semantics, and never wraps commands in zsh.

5. **There is no automatic fallback.** The former `zsh_fallback` builtin and
   `PYSH_ZSH_FALLBACK` variable were removed before PySH 1.0; PySH never
   retries a command through zsh on its own.

6. **Unsupported zsh constructs must be diagnosed, not silently misinterpreted.**
   `compat_check <file>` classifies zsh constructs as supported, delegated,
   skipped, or risky. PySH does not silently discard unsupported constructs
   or produce wrong behavior from them.

---

## zsh scope table

| zsh area | Current PySH status | Handling | Owner issue |
| -------- | ------------------- | -------- | ----------- |
| Simple aliases (`alias NAME=value`) | Supported | Transition — `source_zsh` / `source_zsh_profile` | — |
| Exports (`export NAME=value`) | Supported | Transition — `source_zsh_profile` | — |
| Simple assignments (`NAME=value`) | Supported | Transition — `source_zsh_profile` | — |
| `autoload -Uz compinit` and `compinit` | Skipped | Transition — counted as skipped | — |
| zsh plugin managers (`oh-my-zsh`, `zinit`) | Skipped | Transition — counted as skipped | — |
| `eval "$(cmd)"` forms | Skipped (risky) | `compat_check` flags as risky | — |
| zsh functions (`function f() { ... }`) | Skipped | Transition — counted as skipped | — |
| zsh arrays (`arr=(a b c)`) | Not imported | Transition — counted as skipped | — |
| zsh associative arrays | Not imported | Transition — counted as skipped | — |
| zsh extended globbing (`**`, `*(om)`) | Not supported | Unsupported | — |
| zsh parameter expansion flags | Not supported | Unsupported | — |
| zsh arithmetic forms | Not supported | Unsupported | — |
| zsh themes and prompt expansion | Not supported | Unsupported | — |
| zsh key binding (`bindkey`) | Not supported | Unsupported | — |
| zsh options (`setopt`, `unsetopt`) | Not imported | Transition — counted as skipped | — |
| `zsh COMMAND` | No builtin | Ordinary external program, if installed | #54 |
| `run_script` (shebang zsh scripts) | Supported | Delegated — real `zsh` via argv | #14 |
| `zsh_fallback`, `PYSH_ZSH_FALLBACK` | Removed before 1.0 | No automatic fallback exists | #54 |
| `compat_check FILE` (static report) | Supported | Transition — static analysis only | — |
| zsh-compatible alias file format | Supported (static import) | Transition | — |
| Full zsh interactive session | Not supported | Use real zsh | — |
| `.zshrc` sourcing with execution | Not supported | Forbidden by default | #7 |
| zsh completion system | Not supported | Unsupported | #12 |
| zsh history sharing | Not supported | Unsupported | — |
| zsh module (`zmodload`) | Not supported | Unsupported | — |

---

## What the transition layer covers

The transition layer is designed for users moving from zsh to PySH gradually.
It is not a compatibility layer — it does not make PySH behave like zsh.

**What it does:**
- Imports simple aliases from zsh-compatible alias files.
- Imports simple aliases, exports, and assignments from zsh profile files.
- Classifies zsh scripts as supported/delegated/skipped/risky without executing them.

**What it does not do:**
- Execute `~/.zshrc` or any zsh profile code.
- Load zsh plugins or modules.
- Evaluate `eval`, command substitution, or function definitions from profiles.
- Provide zsh-compatible completion.
- Replace any zsh behavior for the user.

---

## Migration path

The recommended migration path for zsh users:

1. **Inventory**: use `compat_check ~/.zshrc` to see what is safe, what needs
   manual migration, and what to keep in real zsh.
2. **Import safe entries**: use `source_zsh_profile ~/.zshrc` to import
   supported aliases and exports into PySH.
3. **Keep what remains in real zsh**: run it as a normal program (or in a
   script with a `#!/bin/zsh` shebang through `run_script`) for commands that
   need real zsh behavior.
4. **Move stable automation to Python**: use `py { ... }` for scripts.
5. **Do not rely on fallback**: PySH has none; commands PySH cannot run
   report a diagnostic.

See [Zsh compatibility guide](../migration/zsh-compatibility.md)
for the full workflow.

---

## Validation

zsh scope claims are validated by:

1. `tests/test_profile_importer.py` — static import behavior, skipped construct
   counts, malformed line reporting.
2. `tests/test_no_production_zsh_bridge.py` — no `zsh` builtin or bridge; `zsh` is an ordinary program.
3. `tests/test_zsh_transition.py` and `tests/test_no_automatic_legacy_fallback.py` — diagnostics and no automatic fallback.
4. Zsh/Bash/Fish comparison evidence belongs to the test/CI differential laboratory (`tests/differential`), not the runtime.

See [validation-matrix.md](validation-matrix.md) for the full validation plan.
