<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/repository-structure.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Repository Structure

This document maps the PySH repository using repository-relative paths. These
paths are authoritative for development, review, documentation, and AI-assisted
maintenance. When a file header contains `File: ...`, that value is the
canonical repository-relative path for the file.

## Tree Overview

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── docs/
│   ├── architecture/
│   ├── compatibility/
│   ├── development/
│   ├── img/
│   ├── migration/
│   ├── python/
│   ├── shell/
│   └── user/
├── packaging/
│   ├── debian/
│   ├── rpm/
│   └── wrappers/
├── scripts/
├── src/
│   └── pysh/
│       ├── compat/
│       ├── config/
│       ├── contracts/
│       ├── core/
│       ├── diagnostics/
│       ├── editor/
│       │   └── lineedit/
│       ├── migration/
│       ├── parsing/
│       ├── prompt/
│       ├── python_layer/
│       ├── security/
│       └── services/
└── tests/
```

## Major Directories

| Path | Purpose |
| ---- | ------- |
| `.github/` | GitHub issue templates and workflows. Release, publish, CI, and packaging automation live here. |
| `docs/` | Canonical project documentation. Public docs must not depend on private agent instruction files. |
| `docs/architecture/` | Architecture contracts, trust model, parser and execution contracts, roadmap, and issue-backed design records. |
| `docs/compatibility/` | Explicit shell compatibility scope, feature matrices, validation policy, and non-goals for POSIX, bash, zsh, and xonsh comparisons. |
| `docs/development/` | Contributor-facing development, packaging, release, completion-engine, and repository-structure documentation. |
| `docs/user/` | End-user guides for installation, usage, completion, builtins, operators, configuration, limitations, and Midnight Commander behavior. |
| `scripts/` | Shell-script orchestration for release quality, package builds, artifact validation, and header checks. Packaging orchestration belongs here. |
| `src/` | Python source tree for the installable package. |
| `src/pysh/` | Import package root and top-level CLI/module entry points. |
| `src/pysh/core/` | Shell runtime core: main shell state, jobs, signal normalization, and runtime errors. |
| `src/pysh/editor/` | Interactive editor adapters, history, highlighting, and completion integration. |
| `src/pysh/editor/lineedit/` | Raw-mode line editor implementation, pure completion engine, key handling, buffer logic, highlighting, and autosuggestion. |
| `src/pysh/python_layer/` | Python command mode, persistent runtime, highlighting, and display rendering. |
| `tests/` | Deterministic pytest suite covering parser, runtime, docs, packaging contracts, completion, line editing, services, and compatibility behavior. |

## Files with Similar Names

The repository intentionally contains files with similar names because user
documentation, architecture contracts, implementation modules, and tests are
separate evidence layers. Always use the full repository-relative path.

| Path | Distinction |
| ---- | ----------- |
| `src/pysh/editor/completion.py` | Shell-facing completion adapter. It converts shell state into pure completion options and integrates with readline/raw-mode callers. |
| `src/pysh/editor/lineedit/completion.py` | Pure completion engine for raw-mode line editing. It is non-executing and owns candidate classification, ranking, path completion, cache behavior, and completion result structure. |
| `docs/user/completion.md` | User-facing explanation of TAB completion behavior and operational limitations. |
| `docs/development/completion-engine.md` | Contributor-facing implementation notes and manual validation guidance for Completion Engine 2.0. |
| `docs/architecture/completion-engine-contract.md` | Normative architecture contract for completion semantics, invariants, and compatibility expectations. |
| `tests/test_completion_engine.py` | Tests for the pure completion engine and deterministic candidate behavior. |
| `tests/test_lineedit_completion.py` | Tests for line editor completion interaction and raw-mode completion application. |
| `tests/test_python_mode.py` | Tests for Python command mode behavior, not general shell command execution. |
| `tests/test_pty_integration.py` | Pseudo-terminal integration tests for interactive shell behavior. |

## AI Agent Guidance

AI agents and automation helpers must treat repository-relative paths as part
of the interface contract:

- Always quote repository-relative paths in plans, reports, patches, and review
  comments.
- Never refer only to a basename when multiple files share similar names.
- Inspect the file header before editing and verify the `File:` value matches
  the intended repository-relative path.
- Do not guess file purpose from filename alone; confirm it from the header,
  imports, tests, and nearby documentation.
- Preserve source-controlled documentation and code ownership boundaries.
