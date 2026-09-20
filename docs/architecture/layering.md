<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/layering.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# PySH v1.0 Layering and Dependency Boundary Contract

This document is the normative human-readable architecture contract established
by Issue #46. The canonical machine-readable policy is
[`architecture.toml`](../../architecture.toml). If prose and machine policy
disagree, the mismatch is a defect: update both in the same reviewed change.

“Architecture freeze” means **boundary freeze, not implementation freeze**.
After v1.0, internal refactoring, performance optimization, bug fixes, and
implementation replacement remain allowed provided that ownership, public API,
dependency direction, and stable extension seams remain valid. Private helper
names and signatures are deliberately not frozen.

## Enforcement model

Every Python source module belongs to exactly one declared domain. All
cross-domain imports are denied unless the exact target domain appears in the
importer's `allowed_dependencies`, or the exact pair is one of the temporary
debt exceptions below. Permission is not inherited by child domains: permission
to import `pysh.plugins` does not permit importing `pysh.plugins.isolated`.

`tests/test_architecture_import_boundaries.py` parses all source with the
standard-library `ast` module. It imports no application modules and detects
direct imports, from-imports, relative imports, and imports inside functions.
It rejects unclassified modules and PySH import targets, forbidden direction,
internal consumption of `pysh.api`, contract/parser upward dependencies,
isolated-extension seam violations, stale exceptions, and cycles.

The ordinary `pytest -q` step in `.github/workflows/ci.yml` discovers this test
module. No duplicate CI job is required. The focused local command is:

```bash
uv run pytest -q tests/test_architecture_import_boundaries.py
```

## Canonical layer and ownership map

“Allowed consumers” below is the inverse of the ordinary allowed-dependency
graph. A domain may always import within itself. Any cross-domain dependency
not listed is forbidden, except for the five exact temporary exceptions.

| Domain | Layer / classification | Owner responsibility | Allowed dependencies | Allowed consumers | Prohibited responsibility / extension status |
| ------ | ---------------------- | -------------------- | -------------------- | ----------------- | --------------------------------------------- |
| `pysh` | Package/public API; stable public | Package identity and metadata | None | `python_layer`, `core`, `cli` | No runtime orchestration; root metadata only |
| `pysh.api` | Package/public API; stable public | Canonical Python facade and `ShellSession` lifecycle | `contracts`, `config`, `core` | External callers only | No CLI/UI logic, service locator, or isolated runtime objects; canonical Python API |
| `pysh.contracts` | Contracts; compatibility public | Dependency-light protocols and shared immutable contract data | None | `api`, `parsing`, `editor`, `python_layer`, `plugins`, `core` | No implementation imports, initialization, I/O, config loading, subprocess, or network activity; supported compatibility path |
| `pysh.parsing` | Syntax/parsing; internal | Parser, syntax, expansion, heredoc, and redirection primitives | `contracts` | `script_runner`, `diagnostics`, `editor`, `core`, `cli` | No runtime, UI, prompt, config, plugin, diagnostics, security, Python runtime, or script-runner dependency; shared low-level leaf |
| `pysh.script_runner` | Script runner; internal | Native script sequencing and explicit interpreter delegation | `parsing` | `core` | No interactive REPL ownership; no extension seam |
| `pysh.diagnostics` | Diagnostics; internal | Advisory planning, tracing, and redaction implementation | `parsing` | `core`, `cli` | No command execution, policy enforcement, or reverse dependency into runtime; schemas remain internal pending Issue #50 |
| `pysh.editor` | Interactive editor; internal | Editing, completion integration, history, and highlighting | `contracts`, `parsing` | `core` | No shell state, runtime dispatch, config, prompt, or extension ownership; no stable extension seam |
| `pysh.prompt` | Interactive presentation; internal | Prompt colors, terminal presentation, and system-profile rendering | None | `core` | No shell state or config parsing; no stable extension seam |
| `pysh.python_layer` | Python execution; internal | Persistent Python execution and Python command mode | `pysh`, `contracts` | `core` | No general shell dispatch or configuration ownership; no stable extension seam |
| `pysh.config` | Configuration; internal | Startup policy, configuration parsing, validation, and application | None | `api`, `core`, `cli` | No runtime command dispatch; documented configuration schema is the external contract |
| `pysh.compat` | Compatibility; internal | Static profile import and explicit foreign-shell bridges | None | `core` | No core execution or implicit broad compatibility layer; no stable extension seam |
| `pysh.services` | Services; internal | Service client and PyInit metadata implementation | None | `core` | No REPL or command-dispatch ownership; no stable extension seam |
| `pysh.security` | Security; internal | Security policy and explicit sensitive-input PTY runner | None | `core` | No general UI/runtime dumping ground; preserves the Issue #43 boundary |
| `pysh.plugins` | Plugins; compatibility public | Trusted in-process Plugin API 1.0, registry, loader, manager, and core integration boundary | `contracts` | `plugins.isolated`, `core` | No isolated process lifecycle or sandbox claim; trusted Plugin API 1.0 is versioned |
| `pysh.plugins.isolated` | Isolated plugin boundary; internal | Issue #44 manifest, IPC, broker, capabilities, and isolated subprocess lifecycle | `plugins` | None | No trusted-plugin discovery or core/runtime ownership; manifest and IPC are external contracts, Python objects are internal |
| `pysh.migration` | Migration analysis; internal | Static migration analysis and reporting | None | `core` | No execution or compatibility bridge; no stable extension seam |
| `pysh.core` | Runtime composition; internal | Application composition, shell state, dispatch, jobs, and execution | `pysh`, `compat`, `config`, `contracts`, `diagnostics`, `editor`, `migration`, `parsing`, `plugins`, `prompt`, `python_layer`, `script_runner`, `security`, `services` | `api`, `cli`, `shell` | Not a low-level leaf and not public embedding API; no isolated-plugin implementation dependency |
| `pysh.cli` | CLI entrypoints; internal Python module | Console parsing and top-level error/status conversion | `pysh`, `config`, `core`, `diagnostics`, `parsing` | `__main__` | No shell implementation ownership; documented CLI behavior is external, module objects are internal |
| `pysh.shell` | Package/public API; compatibility public | Deprecated `PyShell` compatibility import | `core` | Legacy external callers only | No new API; removal not before 1.2.0 |
| `pysh.__main__` | Module entrypoint; internal Python module | `python -m pysh` dispatch | `cli` | Python launcher only | No argument parsing or runtime logic; documented CLI entrypoint |

## Core terminology and direction

`pysh.core` is formally an **application/runtime composition layer**, not a
low-level “core” library. Its observed role is to assemble parsing, editor,
prompt, configuration, plugins, diagnostics, security, services, migration,
and script execution into `PyShell`. Therefore its fan-in dependencies are
intentional. The direction remains one-way: leaf and feature domains must not
import `pysh.core`; only `pysh.api`, `pysh.cli`, and the deprecated
`pysh.shell` compatibility path may consume it.

This classification resolves the naming ambiguity without moving runtime code
merely to make the package name appear lower-level.

## Boundary-specific invariants

### Stable facade

- Internal implementation domains must never import `pysh.api` for logic.
- `pysh.api` may eagerly re-export stable `pysh.contracts` objects.
- `ShellSession` may lazily construct `pysh.config` and `pysh.core` state.
- `pysh.api` is not an internal service locator and exposes no isolated-plugin
  implementation objects.
- The literal symbol and signature snapshots from Issue #45 remain independent
  expected values; the public/internal classification is shared through
  `architecture.toml`.

### Contracts and parsing

- `pysh.contracts` is stdlib-only and may import only within its own domain.
- It performs no runtime initialization, terminal I/O, config loading,
  subprocess execution, or network activity.
- `pysh.parsing` is a shared low-level leaf and may depend only on contracts.
- Small syntax predicates shared with higher layers belong in contracts or a
  separately reviewed low-level seam, never in a reverse dependency.

### Diagnostics and security

- Diagnostics remains advisory: it consumes parsing but cannot execute through
  core or become a reverse path to runtime state.
- Security owns explicit policy and sensitive-input execution. It cannot absorb
  unrelated UI/runtime responsibilities. Its current prompt dependency is
  temporary debt, not a general permission.
- Issue #50 alone may establish versioned diagnostic or audit schemas; Issue
  #46 does not freeze those internal schemas.

## Trusted and isolated plugin seams

The single owner of the **core-to-extension integration boundary** is
`pysh.plugins`: `pysh.core` consumes its manager and Plugin API 1.0 records.
Trusted in-process plugins are executable trusted Python and are not sandboxed.

`pysh.plugins.isolated` separately owns the **process-isolation boundary**:
manifest parsing, bounded IPC, capability broker, launch hygiene, and lifecycle.
It may reuse exact validation/identity helpers owned by `pysh.plugins`. The
reverse dependency is forbidden: neither `pysh.core` nor other implementation
domains may casually import broker, capability, or runtime internals. A future
orchestration adapter must be assigned an explicit policy edge rather than
reaching across this seam.

The trusted Plugin API version, isolated manifest version, and isolated IPC
version are independent external protocols. Python classes inside
`pysh.plugins.isolated` remain internal. This preserves Issues #43, #44, and
#45 without redesigning their runtime or public contracts.

## Actual import graph at the Issue #46 freeze

This graph is generated conceptually from the same AST domain resolution used
by the gate; arrows mean “imports”. It records the audited source state, not an
aspirational diagram:

```text
pysh.__main__ -> pysh.cli
pysh.api -> pysh.config, pysh.contracts, pysh.core
pysh.cli -> pysh, pysh.config, pysh.core, pysh.diagnostics, pysh.parsing
pysh.config -> pysh.editor, pysh.prompt, pysh.python_layer
pysh.core -> pysh, pysh.compat, pysh.config, pysh.contracts,
             pysh.diagnostics, pysh.editor, pysh.migration, pysh.parsing,
             pysh.plugins, pysh.prompt, pysh.python_layer,
             pysh.script_runner, pysh.security, pysh.services
pysh.diagnostics -> pysh.parsing
pysh.editor -> pysh.contracts, pysh.parsing
pysh.parsing -> pysh.contracts
pysh.plugins -> pysh.contracts
pysh.plugins.isolated -> pysh.plugins
pysh.python_layer -> pysh, pysh.contracts, pysh.editor
pysh.script_runner -> pysh.parsing
pysh.security -> pysh.prompt
pysh.shell -> pysh.core
```

All absent cross-domain edges are forbidden by default. This includes, in
particular, implementation-to-`pysh.api`, parsing-to-runtime/UI/config, any
contracts-to-implementation edge, diagnostics-to-core, core-to-isolated-plugin
internals, and new reverse-layer shortcuts.

## Exact temporary debt exceptions

Exceptions are exact domain pairs in `architecture.toml`; wildcard and prefix
exceptions are invalid. The gate fails if a new violation appears or a listed
edge disappears without its obsolete exception being removed.

| Importer | Imported domain | Retained reason | Cleanup owner |
| -------- | --------------- | --------------- | ------------- |
| `pysh.config` | `pysh.editor` | Configuration defaults and validation consume editor history, width, and highlight-role data | Issue #19 |
| `pysh.config` | `pysh.prompt` | Configuration validation consumes prompt color parsing and conversion helpers | Issue #19 |
| `pysh.config` | `pysh.python_layer` | The rc logical-line adapter consumes Python-block coalescing helpers via a deferred import | Issue #14 |
| `pysh.python_layer` | `pysh.editor` | Interactive Python mode reuses the terminal editor engine and rendering adapter | Issue #12 |
| `pysh.security` | `pysh.prompt` | The sensitive-input runner reuses prompt color parsing and rendering helpers | Issue #19 |

No existing violation was removed and no new exception was introduced by the
Issue #46 freeze. Removing a real edge requires removing its exception and
updating this table in the same change.

## Change procedure

An intentional architecture change must update `architecture.toml`, this
document, focused positive and negative tests, and any affected public or
extension contract documentation together. Adding an exception requires an
exact edge, concrete rationale, and owning cleanup issue. Passing tests by
broadening a domain or wildcard is prohibited.
