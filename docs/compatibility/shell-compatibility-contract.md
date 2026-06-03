<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/shell-compatibility-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Shell Compatibility Contract

This document defines the governing contract for all PySH compatibility
claims. It is the authoritative reference for how PySH relates to POSIX sh,
zsh, bash, and other shell environments.

---

## Foundational statements

1. **PySH is Python-first.** The primary execution model is Python-native: pure
   Python runtime, Python stdlib only (plus declared runtime deps), Python
   configuration, Python extension points.

2. **PySH does not claim full zsh compatibility.** The zsh transition layer
   provides static alias/profile import and explicit delegation to real zsh.
   It is a migration bridge, not a compatibility boundary.

3. **PySH does not claim full bash compatibility.** Bash/sh profile import is
   static and limited. Bash grammar features are not implemented by PySH
   natively.

4. **PySH does not claim POSIX `/bin/sh` replacement status.** PySH must not
   be symlinked as `/bin/sh`. System scripts that rely on POSIX sh semantics
   must continue to use a real POSIX-compliant shell.

5. **PySH supports only documented shell constructs.** Behavior not documented
   in the feature matrix, builtins reference, or operators reference is not
   guaranteed and must not be relied upon.

6. **External shell delegation must be explicit.** PySH never silently
   delegates a command to an external shell without the user's explicit
   instruction (`zsh <cmd>`, `run_script <file>`, or `zsh_fallback on`).

7. **Foreign profile execution must be opt-in.** Static import (`source_zsh`,
   `source_zsh_profile`, `source_sh_aliases`) reads files as text. It does not
   execute shell code. Any future mechanism for executing foreign shell code
   must require explicit user opt-in.

8. **Safe static import is not the same as sourcing.** Importing aliases and
   exports from `~/.zshrc` statically is categorically different from running
   `source ~/.zshrc`. PySH documentation must not conflate these.

9. **Compatibility claims require a documented matrix and backing tests.**
   Claims without evidence in [feature-matrix.md](feature-matrix.md) and
   [validation-matrix.md](validation-matrix.md) are not valid claims.

10. **Negative cases must be documented.** For every construct that PySH does
    not support, the correct user behavior (use real zsh/bash, or wait for the
    relevant issue) must be documented.

---

## Contract categories

Every PySH feature or shell construct falls into exactly one category:

| Category | Definition | User expectation |
| -------- | ---------- | ---------------- |
| **Native** | Implemented by the PySH runtime directly. Behavior is defined by PySH, not by a foreign shell. | Works out of the box. Bugs are PySH bugs. |
| **Transition** | Statically imported or analyzed by PySH without executing foreign shell code. Examples: `source_zsh`, `compat_check`. | Safe to use. Unsupported constructs are skipped and counted, not silently broken. |
| **Delegated** | Forwarded explicitly to a real external shell or tool by user request. Examples: `zsh <cmd>`, `run_script`, `zsh_fallback`. | Requires the external tool to be installed. Behavior is the external tool's behavior. PySH is a pass-through. |
| **Planned** | On the roadmap with an assigned owner issue. Not currently implemented. | Not available in current release. Owner issue defines the implementation milestone. |
| **Unsupported** | Not implemented and not planned in the current roadmap horizon. | Must not be used; will not work. Use a real shell for these constructs. |
| **Forbidden by default** | Not executed or imported by default for safety reasons. Requires explicit user opt-in if available at all. | Opt-in only. Default behavior is safe rejection. |

---

## Scope boundaries

### Native scope (PySH 0.5.x)

PySH implements the following natively:

- Sequential chains (`;`), conditional chains (`&&`, `||`).
- Pipelines (`|`) with correctly closed file descriptors.
- Input/output redirection (`<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`).
- Command substitution (`$(...)`, `` `...` ``) with 5-second timeout.
- Single and double quoting with correct expansion semantics.
- Backslash escapes (outside and inside double quotes per POSIX).
- Variable assignment (`NAME=value`) and expansion (`$NAME`, `${NAME}`).
- Exported environment variables (`export NAME=value`).
- Temporary environment assignment for external commands (`NAME=value cmd`).
- Shell comments (`#` outside quotes).
- All documented builtins (see `docs/user/builtins.md`).
- Aliases (definition, expansion, `unalias`).
- Directory stack (`pushd`, `popd`, `dirs`).
- History (persistent, `~/.pysh_history`, Ctrl+R when readline available).
- Tab completion (aliases, builtins, filesystem paths).
- Python execution (`py`, `py { ... }`, `#py` interactive mode).
- Startup files (`~/.pyshrc`, `~/.pyshrc.d/*.pysh` plugins).
- Multiline paste (bracketed paste, compact paste replay).
- Raw-mode line editor with live syntax highlighting and autosuggestion.

### Transition scope

PySH implements the following as static, non-executing import:

- `source_zsh <file>`: static import of `alias NAME=value` forms.
- `source_zsh_profile <file>`: static import of simple aliases, exports, and
  assignments from zsh-style profiles.
- `source_sh_aliases <file>`: same static model for bash/sh-oriented files.
- `compat_check <file>`: static classification into supported/delegated/skipped/risky.

### Delegated scope

PySH delegates the following explicitly:

- `zsh <command>`: executes `zsh -lc <command>` when zsh is installed.
- `run_script <file>`: delegates scripts with zsh/bash/sh shebangs to the real
  interpreter via an argv list.
- `zsh_fallback on`: enables optional delegation of unparseable commands to zsh.

### Out of scope (Unsupported / Planned)

The following are not natively implemented in PySH 0.5.x:

- Native glob expansion — planned in Issue #9.
- Heredocs — planned in Issue #10.
- Job control — planned in Issue #11.
- Shell functions.
- Shell arrays.
- Arithmetic expansion (`$((expr))`).
- Advanced parameter expansion (`${VAR:-default}`, `${#VAR}`, etc.).
- Traps (`trap SIGNAL ACTION`).
- Process substitution (`<(cmd)`, `>(cmd)`).
- Brace expansion (`{a,b,c}`).
- `case`, `select` statements.
- Full script-mode contract — planned in Issue #14.

See [unsupported-constructs.md](unsupported-constructs.md) for the complete
list and correct user action for each.

---

## Claim lifecycle

A compatibility claim progresses through this lifecycle:

```text
Planned (owner issue assigned)
    ↓
Implemented (code change in owner issue)
    ↓
Tested (test added in owner issue or dedicated test issue)
    ↓
Documented (feature matrix updated, validation matrix updated)
    ↓
Verified (CI gate green, compatibility doc updated)
    ↓
Claimed (claim is valid and can appear in public documentation)
```

A claim that skips testing or documentation is not valid and must be
corrected before publication.

---

## Forbidden documentation patterns

The following patterns are prohibited in PySH documentation unless they
immediately precede a clear negation or qualification:

| Forbidden pattern | Prohibited because |
| ----------------- | ------------------ |
| zsh compatibility claim | False without qualification; PySH has a zsh transition layer, not broad compatibility |
| POSIX compatibility claim | False; PySH does not implement the POSIX grammar or expansion model |
| `/bin/sh` replacement claim | False; PySH must not be symlinked as `/bin/sh` |
| interchangeable replacement claim for zsh/bash | False; PySH has a different grammar and different feature set |
| bash compatibility claim | False; bash features are largely unsupported natively |
| unqualified full-compatibility claim | Vague and likely false; always qualify with the specific construct |

Allowed forms (negated or qualified):

- "PySH is not a full zsh clone."
- "PySH does not claim POSIX `/bin/sh` replacement status."
- "PySH is not interchangeable with bash."
- "zsh-compatible alias file" (refers to file format, not PySH behavior).

---

## Issue ownership

| Domain | Owner issue |
| ------ | ----------- |
| Shell compatibility contract (this document) | Issue #4 |
| Error and exit-code semantics | Issue #5 |
| Signal handling | Issue #6 |
| Security and trust model | Issue #7 |
| Parser, expansion, multiline grammar | Issue #8 |
| Native glob/path expansion | Issue #9 |
| Heredocs | Issue #10 |
| Job control | Issue #11 |
| Completion | Issue #12 |
| Script mode full contract | Issue #14 |
| Python migration layer | Issue #15 |
| zsh transition hardening | Issue #16 |
| System shell integration | Issue #17 |
| FreeBSD validation | Issue #18 |
| Shim removal and packaging quality gate | Issue #19 |
