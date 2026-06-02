<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/zsh-scope.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# zsh Scope

This document defines PySH's relationship to zsh. For the full transition-layer
workflow, see [docs/migration/zsh-compatibility.md](../migration/zsh-compatibility.md).

---

## Governing statements

1. **PySH is not a zsh clone.** PySH does not implement the zsh grammar,
   expansion model, module system, or completion framework.

2. **PySH has a zsh transition layer.** The transition layer provides safe
   static import of aliases and profile entries, a static compatibility
   checker, and explicit delegation to real zsh when needed.

3. **Static alias/profile import is not execution.** `source_zsh`,
   `source_zsh_profile`, and `source_sh_aliases` read files as text and
   extract safe, simple alias/export/assignment entries. They do not execute
   shell code, run plugin managers, evaluate `eval` expressions, or call
   external commands.

4. **`zsh <command>` is explicit delegation to real `zsh -lc`.** The user
   types the `zsh` prefix deliberately. PySH does not silently wrap commands
   in zsh.

5. **Fallback mode is explicit and off by default.** `zsh_fallback on` must
   be intentionally enabled. It is a migration aid, not a compatibility
   guarantee.

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
| `zsh COMMAND` (explicit delegation) | Supported | Delegated — `zsh -lc <command>` | — |
| `run_script` (shebang zsh scripts) | Supported | Delegated — real `zsh` via argv | #14 |
| `zsh_fallback on` | Supported | Delegated — off by default | — |
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
- Delegates specific commands to real zsh on demand.

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
3. **Delegate what remains**: use `zsh <cmd>` for commands that need real zsh.
4. **Move stable automation to Python**: use `py { ... }` for scripts.
5. **Enable fallback only during active migration**: `zsh_fallback on` is a
   temporary crutch, not a goal state.

See [docs/migration/zsh-compatibility.md](../migration/zsh-compatibility.md)
for the full workflow.

---

## Validation

zsh scope claims are validated by:

1. `tests/test_profile_importer.py` — static import behavior, skipped construct
   counts, malformed line reporting.
2. `tests/test_zsh_bridge.py` — explicit `zsh -lc` delegation, 127 on missing zsh.
3. `tests/test_zsh_transition.py` — fallback mode enable/disable/env var.
4. CI with real zsh installed (`ubuntu-latest` in GitHub Actions) for delegation tests.

See [validation-matrix.md](validation-matrix.md) for the full validation plan.
