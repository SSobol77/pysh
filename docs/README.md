<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/README.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Documentation

This directory is the **single source of truth** for all PySH project documentation.
GitHub Wiki may mirror selected pages in the future; it is not an independent second
source of truth. All canonical documentation lives here under `docs/`.

---

## Current project status

| Attribute            | Value                                             |
| -------------------- | ------------------------------------------------- |
| Version              | 0.8.2 current release                           |
| Language             | Pure Python (stdlib only, no external deps)       |
| Primary target       | Debian 13, Python 3.13+                           |
| Shell type           | Python-first interactive shell and script runner  |
| POSIX `/bin/sh`      | Not a replacement                                 |
| Zsh compatibility    | Transition layer only — not a zsh clone           |
| Compatibility claims | Matrix- and test-backed only; no aspirational claims |

---

## Documentation tree

```text
docs/
├── README.md                          ← this file (documentation index)
├── user/                              ← end-user guides
│   ├── installation.md
│   ├── usage.md
│   ├── builtins.md
│   ├── operators.md
│   ├── configuration.md
│   ├── limitations.md
│   └── midnight-commander.md
├── shell/                             ← shell behavior documentation
│   ├── command-planning.md
│   ├── multiline-paste.md
│   ├── security-sensitive-input.md
│   └── system-profile.md
├── python/                            ← Python execution layer
│   ├── python-runtime.md
│   └── python-command-execution-layer.md
├── compatibility/                     ← compatibility contracts and scope (Issue #4)
│   ├── README.md
│   ├── shell-compatibility-contract.md
│   ├── feature-matrix.md
│   ├── posix-sh-scope.md
│   ├── zsh-scope.md
│   ├── bash-scope.md
│   ├── unsupported-constructs.md
│   └── validation-matrix.md
├── migration/                         ← transition and compatibility guides
│   ├── migration.md
│   └── zsh-compatibility.md
├── architecture/                      ← architecture decisions and roadmap
│   ├── architecture.md
│   ├── error-exit-code-contract.md
│   ├── completion-engine-contract.md
│   ├── heredoc-contract.md
│   ├── observability-diagnostics-contract.md
│   ├── parser-expansion-contract.md
│   ├── signal-handling.md
│   ├── security-trust-model.md
│   ├── script-mode-contract.md
│   ├── path-expansion-contract.md
│   ├── source-tree.md
│   ├── roadmap.md
│   ├── pysh-issue-backlog.md
│   ├── documentation-policy.md
│   ├── ISSUE-2-refactor-source-tree.md
│   └── ISSUE-3-architecture-contracts.md
├── development/                       ← contributor and release guides
│   ├── development.md
│   ├── release.md
│   └── packaging.md
└── img/                               ← project images and icons
```

---

## User guide

Documentation for people who install and use PySH day to day.

| Document | Description |
| -------- | ----------- |
| [installation.md](user/installation.md) | Installing from PyPI; development install; running |
| [usage.md](user/usage.md) | Invocation, operators, pipelines, redirection, substitution, variables |
| [builtins.md](user/builtins.md) | Every builtin: syntax, examples, exit codes, limitations |
| [operators.md](user/operators.md) | Chain, pipeline, redirection, substitution, quoting semantics |
| [configuration.md](user/configuration.md) | `~/.pyshrc`, plugin directory `~/.pyshrc.d/`, aliases, prompt |
| [limitations.md](user/limitations.md) | Explicit non-goals and compatibility boundaries |
| [midnight-commander.md](user/midnight-commander.md) | MC integration policy and the `mc` builtin |

---

## Shell behavior

Internal shell feature documentation.

| Document | Description |
| -------- | ----------- |
| [command-planning.md](shell/command-planning.md) | `plan <cmd>` advisory classifier |
| [multiline-paste.md](shell/multiline-paste.md) | Multiline paste handling and replay queue |
| [security-sensitive-input.md](shell/security-sensitive-input.md) | Password/passphrase security boundary; `secure <cmd>` PTY runner |
| [system-profile.md](shell/system-profile.md) | `sys_info`, `env_audit`, `path_audit`, `which_all`, `apt_check`, `apt_search` |

---

## Python layer

Documentation for PySH's Python execution and runtime bridge.

| Document | Description |
| -------- | ----------- |
| [python-runtime.md](python/python-runtime.md) | `py` builtin: persistent per-session Python runtime context |
| [python-command-execution-layer.md](python/python-command-execution-layer.md) | `#py` interactive mode: REPL, source buffer, file directives, highlighting |

---

## Migration

Guides for users transitioning from zsh, bash, or sh.

| Document | Description |
| -------- | ----------- |
| [migration.md](migration/migration.md) | Static profile import, script transition runner, compatibility reporting |
| [zsh-compatibility.md](migration/zsh-compatibility.md) | Transition bridge, safe profile import, explicit zsh delegation, fallback mode |

---

## Compatibility

Shell compatibility contracts, scope definitions, and feature matrices (Issue #4).
All compatibility claims are explicit, scoped, and test-backed.

| Document | Description |
| -------- | ----------- |
| [compatibility/README.md](compatibility/README.md) | Compatibility overview: status, categories, source-of-truth policy |
| [shell-compatibility-contract.md](compatibility/shell-compatibility-contract.md) | Contract language, categories, governing rules, forbidden claim patterns |
| [feature-matrix.md](compatibility/feature-matrix.md) | Per-feature matrix: status, category, evidence, owner issue |
| [posix-sh-scope.md](compatibility/posix-sh-scope.md) | POSIX sh scope: what PySH supports, what it does not, `/bin/sh` prohibition |
| [system-shell-integration-policy.md](compatibility/system-shell-integration-policy.md) | System shell integration policy: safe modes, unsupported modes, `/bin/sh` provider prohibition |
| [zsh-scope.md](compatibility/zsh-scope.md) | zsh scope: transition layer, static import, explicit delegation |
| [bash-scope.md](compatibility/bash-scope.md) | bash scope: static import, shebang delegation, no broad compatibility claim |
| [unsupported-constructs.md](compatibility/unsupported-constructs.md) | Complete list of unsupported constructs with user actions and owner issues |
| [validation-matrix.md](compatibility/validation-matrix.md) | How each compatibility claim is validated; gap analysis |

---

## Architecture

Internal architecture decisions, issue tracking, and roadmap.

| Document | Description |
| -------- | ----------- |
| [architecture.md](architecture/architecture.md) | Architecture contracts (Issue #3): boundaries, protocols, ratchet, shim policy |
| [error-exit-code-contract.md](architecture/error-exit-code-contract.md) | Error and exit-code contract (Issue #5): ExitCode enum, PyShError taxonomy, $? propagation |
| [heredoc-contract.md](architecture/heredoc-contract.md) | Here-document and here-string stdin contract (Issue #10) |
| [observability-diagnostics-contract.md](architecture/observability-diagnostics-contract.md) | Observability and diagnostics contract (Issue #13): opt-in trace, stderr contract, redaction, diagnostic builtins |
| [parser-expansion-contract.md](architecture/parser-expansion-contract.md) | Parser, expansion and multiline grammar contract (Issue #8): modules, expansion order, unsupported syntax ownership |
| [signal-handling.md](architecture/signal-handling.md) | Signal-handling architecture (Issue #6): SIGINT/SIGTERM/SIGTSTP contract, exit-code mapping, terminal restoration |
| [security-trust-model.md](architecture/security-trust-model.md) | Security and trust model (Issue #7): trust boundaries, execution surfaces, static import policy, sensitive input boundary |
| [script-mode-contract.md](architecture/script-mode-contract.md) | Script Mode v1 contract (Issue #14): direct script invocation, positional parameters, shebang handling, exit status |
| [path-expansion-contract.md](architecture/path-expansion-contract.md) | Path and glob expansion contract (Issue #9): glob syntax, tilde, dotfile policy, quoting, no-match policy |
| [source-tree.md](architecture/source-tree.md) | Post-Issue #2 source tree: packages, modules, dependency direction |
| [roadmap.md](architecture/roadmap.md) | Feature roadmap and milestone planning |
| [pysh-issue-backlog.md](architecture/pysh-issue-backlog.md) | Issue backlog and linear architecture plan |
| [documentation-policy.md](architecture/documentation-policy.md) | Required documentation coverage for new features |
| [ISSUE-2-refactor-source-tree.md](architecture/ISSUE-2-refactor-source-tree.md) | Issue #2 design: relocating source into domain subpackages |
| [ISSUE-3-architecture-contracts.md](architecture/ISSUE-3-architecture-contracts.md) | Issue #3 spec: enforceable import-boundary contracts |

---

## Development and release

Documentation for contributors, maintainers, and the release process.

| Document | Description |
| -------- | ----------- |
| [development.md](development/development.md) | Test suite, linting, build commands, repository layout |
| [release.md](development/release.md) | Release checklist, tagging, PyPI Trusted Publishing via GitHub Actions |
| [packaging.md](development/packaging.md) | Canonical naming contract; PyPI / `.deb` / `.rpm` / `.pkg` artifact filenames and build scripts |

---

## GitHub Wiki mapping

The GitHub Wiki is **not** used as an independent documentation source.
If Wiki pages are created in the future, they will mirror or link to content
in this `docs/` tree. Content is authored here and synced to the Wiki; the
Wiki is never the authority.

Suggested future Wiki structure when mirroring is implemented:

| Wiki page | Source |
| --------- | ------ |
| `Home` | `docs/README.md` (this file) |
| `Installation` | `docs/user/installation.md` |
| `Builtins` | `docs/user/builtins.md` |
| `Configuration` | `docs/user/configuration.md` |
| `Migration` | `docs/migration/migration.md` |
| `Architecture` | `docs/architecture/source-tree.md` |

---

## Source-of-truth policy

1. `docs/` is the single source of truth for all project documentation.
2. The root `README.md` is a project introduction and links into `docs/`.
3. `docs/README.md` (this file) is the canonical documentation index.
4. GitHub Wiki, if used, may mirror selected pages from `docs/` but must
   never become an independent second source of truth.
5. Documentation must not be duplicated into divergent copies across the tree.
6. All compatibility and feature claims in documentation must be backed by
   tests or the current test matrix. Aspirational claims are not permitted.
