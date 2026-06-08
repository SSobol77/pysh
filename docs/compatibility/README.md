<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/README.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Compatibility Documentation

This directory is the authoritative source for all PySH compatibility claims.

---

## Current compatibility status (PySH 0.8.2)

| Target | Claim | Status |
| ------ | ----- | ------ |
| POSIX `/bin/sh` | PySH is **not** a POSIX sh replacement | Confirmed — see [posix-sh-scope.md](posix-sh-scope.md) |
| zsh | PySH is **not** a zsh clone | Confirmed — see [zsh-scope.md](zsh-scope.md) |
| bash | PySH is **not** bash | Confirmed — see [bash-scope.md](bash-scope.md) |
| Interactive shell | PySH targets interactive use with documented constructs | Partial — see [feature-matrix.md](feature-matrix.md) |
| Script interpreter | PySH targets documented `.pysh` scripts with the Script Mode v1 contract | Supported — see [feature-matrix.md](feature-matrix.md) |

**Core principle:** all PySH compatibility claims are explicit, scoped, and
test-backed. Aspirational claims are not permitted in this documentation.

---

## Compatibility documents

| Document | Purpose |
| -------- | ------- |
| [shell-compatibility-contract.md](shell-compatibility-contract.md) | Contract language, categories, and governing rules |
| [feature-matrix.md](feature-matrix.md) | Per-feature matrix: status, category, evidence, owner issue |
| [posix-sh-scope.md](posix-sh-scope.md) | POSIX sh scope: what PySH supports, what it does not |
| [system-shell-integration-policy.md](system-shell-integration-policy.md) | Safe/unsafe system shell integration modes and `/bin/sh` provider prohibition |
| [zsh-scope.md](zsh-scope.md) | zsh scope: transition layer, static import, delegation |
| [bash-scope.md](bash-scope.md) | bash scope: static import, explicit delegation only |
| [unsupported-constructs.md](unsupported-constructs.md) | Complete list of unsupported shell constructs |
| [validation-matrix.md](validation-matrix.md) | How each compatibility claim is validated |

---

## Four behavior categories

Every PySH feature or shell construct falls into one of four runtime categories:

| Category | Meaning |
| -------- | ------- |
| **Native** | Implemented and executed by the PySH runtime directly |
| **Transition** | Statically imported or analyzed — no foreign shell code is executed |
| **Delegated** | Forwarded explicitly to an external shell or tool by user request |
| **Unsupported** | Not implemented; documented as absent; must not be assumed to work |

A fifth contract-level category also exists:

| Category | Meaning |
| -------- | ------- |
| **Planned** | On the roadmap with an owner issue; not yet implemented |

See [shell-compatibility-contract.md](shell-compatibility-contract.md) for the
complete category definitions and governing rules.

---

## Key distinctions

**Native behavior** vs **transition-layer behavior**

PySH's own parser, executor, and builtins are native. When PySH encounters
a construct it cannot handle natively, it does not silently delegate —
it reports an error or notifies the user.

**Transition-layer behavior** is always explicit. The `source_zsh`,
`source_zsh_profile`, and `source_sh_aliases` builtins read files as text
and extract static alias/export/assignment entries without executing any code.

**Explicit delegation** vs **implicit fallback**

`zsh <command>` is explicit: the user types the `zsh` prefix. The command
is forwarded to `zsh -lc <command>`.

Fallback mode (`zsh_fallback on`) is off by default and must be explicitly
enabled. When enabled, PySH may forward unparseable commands to zsh. This is
a migration aid, not a compatibility guarantee.

**Static profile import** is not the same as sourcing a profile.
`source_zsh_profile ~/.zshrc` extracts aliases, exports, and assignments
from the file. It does not load plugins, run `compinit`, evaluate `eval`
expressions, or execute shell functions. Unsupported constructs are skipped
and counted.

**System shell integration** is explicit and bounded. PySH may be launched as
`pysh` for interactive use or PySH-native scripts, but it must not replace the
operating-system `/bin/sh` provider. See
[system-shell-integration-policy.md](system-shell-integration-policy.md).

---

## Source-of-truth policy

- `docs/compatibility/` is the authoritative source for all compatibility claims.
- `docs/user/limitations.md` summarizes non-goals for users; links here for detail.
- `docs/migration/zsh-compatibility.md` documents the zsh transition layer; links here for scope.
- `docs/migration/migration.md` documents migration workflows; links here for contract.
- The root `README.md` and PyPI description must not assert compatibility claims beyond those documented here.
