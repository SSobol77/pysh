<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/architecture.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Architecture Contracts

This document is the architecture contract for PySH 0.6.x, established by
GitHub Issue #3. It describes package responsibilities, dependency direction,
the contract protocol layer, boundary rules, known violations, and shim
lifecycle policy.

**Relation to other documents:**
- [source-tree.md](source-tree.md) — post-Issue #2 source tree: packages, modules, dependency diagram.
- [error-exit-code-contract.md](error-exit-code-contract.md) — Issue #5: canonical exit codes, PyShError taxonomy, $? propagation, boundary function.
- [parser-expansion-contract.md](parser-expansion-contract.md) — Issue #8: parser modules, expansion order, multiline grammar, unsupported syntax ownership.
- [signal-handling.md](signal-handling.md) — Issue #6: signal-handling architecture, terminal restoration guarantees, exit-code mapping.
- [security-trust-model.md](security-trust-model.md) — Issue #7: security and trust model, execution surfaces table, static import policy, sensitive input boundary.
- [job-control-contract.md](job-control-contract.md) — Issue #11: job-control model, process-group ownership, `jobs`/`fg`/`bg` builtins, SIGTSTP handling, background job reaping.
- [path-expansion-contract.md](path-expansion-contract.md) — Issue #9: native glob and path expansion, tilde expansion, dotfile policy, quoting contract.
- [ISSUE-2-refactor-source-tree.md](ISSUE-2-refactor-source-tree.md) — Issue #2 scope (relocation only).
- [ISSUE-3-architecture-contracts.md](ISSUE-3-architecture-contracts.md) — Issue #3 spec (this implementation).
- GitHub Issue #19 — shim lifecycle and removal.

---

## Enforcement status

| Gate | Status |
| ---- | ------ |
| No import cycles | **Hard gate** — `tests/test_architecture_import_boundaries.py::test_no_import_cycles` |
| contracts isolation | **Hard gate** — `tests/test_architecture_import_boundaries.py::test_contracts_isolation` |
| `__init__.py` side-effect policy | **Hard gate** — `tests/test_architecture_import_boundaries.py::test_init_files_are_side_effect_minimal` |
| Cross-domain ratchet | **Ratcheted** — `tests/test_architecture_import_boundaries.py::test_cross_domain_ratchet` |
| Public API snapshot | **Hard gate** — `tests/test_public_api_snapshot.py` |
| Cold-import budget | **Hard gate** — `tests/test_import_time_budget.py` |

**No-cycles** and **contracts isolation** are unconditional hard gates.
The cross-domain ratchet documents current violations and blocks new ones.
It is not a full layer-boundary enforcement; that belongs to Issue #3's successors.

---

## Package responsibilities

| Package | Responsibility | Owns | Must not own |
| ------- | -------------- | ---- | ------------ |
| `pysh` | Package identity and version metadata | `__version__`, `__author__`, `LICENSE_NAME` | Runtime logic |
| `pysh.__main__` | `python -m pysh` execution shim | Module-level `main()` dispatch | Argument parsing, shell logic |
| `pysh.cli` | Console script entry point | Argument parsing, `--version`, `-c`, interactive start | Shell execution, builtin dispatch |
| `pysh.core` | Main shell runtime (fan-in hub) | `PyShell`: REPL loop, all builtin implementations, pipeline and redirection execution; `errors.py`: canonical exit codes; `signals.py`: signal helpers; `jobs.py`: job table, POSIX job-control helpers, process-group model | Parser primitives, editor rendering, config loading (delegates to leaves) |
| `pysh.parsing` | Quote-aware text parsing, expansion, and path glob helpers | Parser AST values, parse errors, lexical scanning, chain/pipeline/paste splitting, multiline continuation, heredoc collection, variable/command substitution helpers, redirection parsing, tilde expansion, glob/path expansion (`tokenize_and_glob_expand`, `expand_tilde`, `expand_path_word`), no-match policy, dotfile policy | Shell state, command dispatch, editor rendering |
| `pysh.editor` | Interactive line editor (coordinator) | `Completer`, `HistoryManager`, `colors_enabled`, `paint` | Shell state, prompt rendering |
| `pysh.editor.lineedit` | Raw-mode terminal line editing engine | `RawLineReader`, `LineBuffer`, `LineHighlighter`, `AutoSuggester`, `KeyDecoder`, Completion Engine v1 | Higher-level shell concepts, history persistence |
| `pysh.prompt` | Prompt segment rendering | `colorize`, `color_to_hex`, `parse_color`, Debian profile helpers | Shell state, RC parsing |
| `pysh.python_layer` | Python command execution layer | `PythonRuntime`, `py` builtin, `#py` interactive mode, Python syntax highlighting | Shell builtins outside the Python layer, config loading |
| `pysh.config` | Configuration and startup | RC file execution, mini rc-interpreter, plugin loader, `ConfigAPI` | Runtime command dispatch, builtin logic |
| `pysh.compat` | Transition and compatibility helpers | Zsh bridge, alias/profile importers, MC detection | Core shell execution |
| `pysh.services` | Service management | `svc` builtin client, PID-file control, PyInit metadata parser | Shell REPL |
| `pysh.security` | Security-sensitive execution | `SecureRunner` PTY bridge, ring indicator | General command dispatch |
| `pysh.diagnostics` | Advisory diagnostics | `plan` classifier, opt-in trace model, redaction policy | Policy enforcement, runtime execution |
| `pysh.contracts` | Architecture protocol layer | Protocol definitions for boundary surfaces | Any runtime logic; implementation package imports |
| `pysh.shell` | Compatibility shim (scheduled removal) | Re-export of `PyShell` from `pysh.core.shell` | Any new logic |
| `pysh.script_runner` | Script mode runner | `ScriptRunner`, shebang detection, interpreter delegation, native logical-line execution | Interactive REPL state |

---

## Dependency direction

```text
pysh.__main__
    ↓
pysh.cli
    ↓
pysh.core.shell   ← fan-in hub: imports from all leaf packages
    ├── pysh.parsing
    ├── pysh.editor
    │   └── pysh.editor.lineedit
    ├── pysh.prompt
    ├── pysh.python_layer
    ├── pysh.config
    ├── pysh.compat
    ├── pysh.services
    ├── pysh.security
    ├── pysh.diagnostics
    └── pysh.script_runner

pysh.contracts   ← no runtime imports; stdlib only
```

`pysh.core` is the intended single fan-in point. All other packages are
imported by core rather than importing core. No circular dependencies exist.

---

## CLI entrypoint ownership

| Entrypoint | Owner | Mechanism |
| ---------- | ----- | --------- |
| `pysh` command | `pysh.cli:main` | `[project.scripts]` in `pyproject.toml` |
| `python -m pysh` | `pysh.__main__` → `pysh.cli:main` | `__main__.py` calls `cli.main()` |

Both paths converge on `pysh.cli.main`, which constructs `pysh.core.shell.PyShell`.

---

## Public Python API surface

The `pysh` package exposes a deliberately minimal public API:

```python
pysh.__version__   # str — package version
pysh.__author__    # str — package author
pysh.LICENSE_NAME  # str — SPDX licence identifier
```

These are the only symbols in `pysh.__all__`. Internal packages
(`pysh.core`, `pysh.editor`, …) are not part of the public API.

The extension-point surface for config authors and plugin authors is
`pysh.contracts`:

```python
pysh.contracts.ShellStateView
pysh.contracts.AliasRegistryView
pysh.contracts.CommandResolverView
pysh.contracts.EnvironmentView
pysh.contracts.ConfigView
pysh.contracts.PluginRegistrar
pysh.contracts.CompatibilityBridge
```

Any change to `pysh.__all__` or `pysh.contracts.__all__` must be reflected
in `tests/test_public_api_snapshot.py` and documented here.

---

## Contract layer (`pysh.contracts`)

`pysh.contracts` contains `typing.Protocol` definitions that describe the
read-only or action surfaces that cross package boundaries.

**Rules (enforced by `test_contracts_isolation`):**
- Imports only from the Python standard library.
- Must not import from `pysh.core`, `pysh.parsing`, `pysh.editor`,
  `pysh.prompt`, `pysh.python_layer`, `pysh.config`, `pysh.compat`,
  `pysh.services`, `pysh.security`, or `pysh.diagnostics`.
- Performs no runtime initialisation, terminal I/O, config loading,
  git probing, or subprocess calls.
- `__init__.py` re-exports the protocol names; no logic beyond re-export.
- `builtins.py` contains canonical builtin-name data only.

**Why protocols, not abstract base classes:**
Protocol (structural subtyping) allows existing classes to satisfy the
interface without modification, which is safer for a ratcheted refactor
where full boundary enforcement is deferred.

**`@runtime_checkable` policy:**
Added only to protocols where `isinstance` checks are genuinely useful.
Currently: `AliasRegistryView` (compat helpers) and `EnvironmentView`
(completion). Properties are not reliable targets for runtime isinstance
checks.

---

## Parser / execution / editor boundaries

```text
pysh.parsing  ──►  provides: ast, errors, lexer, grammar, expansion, heredoc,
                             multiline,
                             split_chain, split_pipeline, split_paste_commands,
                             RedirectionSpec, parse_redirections,
                             path_expansion, tokenize_and_glob_expand,
                             expand_tilde, expand_path_word
                   consumed by: core, editor.lineedit, diagnostics, script_runner
                   must not: import from core, editor, prompt, python_layer

pysh.editor   ──►  provides: Completer, HistoryManager, ANSI helpers, RawLineReader
                   consumed by: core, python_layer
                   must not: import from core, config, prompt, python_layer
                   may consume: pysh.parsing shared-leaf helpers for paste splitting

pysh.core     ──►  imports from: all leaf packages (fan-in)
                   must not: be imported by any leaf package
```

---

## Compatibility-layer boundaries

```text
pysh.compat   ──►  provides: ZshBridge, zsh/sh alias importers, MC detection
                   consumed by: core
                   must not: import from core, python_layer, config
                   current state: clean (no known violations)
```

The compat layer is a **transition** layer, not a permanent broad compatibility
layer. `zsh_fallback` and `run_script` delegation are explicit operations, not
transparent wrappers. No new broad compatibility layers are permitted.

---

## Python command-execution layer boundaries

```text
pysh.python_layer  ──►  provides: PythonRuntime, #py mode, syntax highlighting
                         consumed by: core (py builtin, #py REPL)
                         current violations:
                           python_layer → pysh.editor (Issue #12 cleanup remains)
                         must not: import from core, config, compat, services
```

The Python layer intentionally reaches into `pysh.editor.lineedit` to drive
the `#py` interactive REPL (reader, buffer, highlighting, autosuggestion).
Completion Engine v1 is isolated, but the broader Python-mode editor import
cleanup remains tracked separately.

---

## Minimal `__init__.py` policy

Package `__init__.py` files must be minimal and side-effect free:

| Rule | Enforcement |
| ---- | ----------- |
| No terminal I/O | `test_init_files_are_side_effect_minimal` |
| No `subprocess` import | `test_init_files_are_side_effect_minimal` |
| No `threading` / `asyncio` import | `test_init_files_are_side_effect_minimal` |
| No `curses` / `readline` import | `test_init_files_are_side_effect_minimal` |
| No `pygments` import | `test_init_files_are_side_effect_minimal` |
| No config loading | architectural convention |
| No git probing | architectural convention |
| No broad eager imports from runtime packages | architectural convention |

Re-exports from `__init__.py` are permitted only for public API or narrow
compatibility shims.

---

## Known layering violations

The following cross-domain boundary imports exist in the current codebase.
Each is documented here and in
`tests/test_architecture_import_boundaries.py::KNOWN_VIOLATIONS`.
New violations fail the ratchet test automatically.

| Importing package | Imported package | Reason retained | Cleanup issue |
| ----------------- | ---------------- | --------------- | ------------- |
| `pysh.config` | `pysh.editor` | `config.api` uses `_display_width` from `editor.lineedit.buffer` for prompt width calculation | Issue #19 |
| `pysh.config` | `pysh.prompt` | `config.api` uses `color_to_hex`, `parse_color` from `prompt.colors` | Issue #19 |
| `pysh.config` | `pysh.python_layer` | `config.rc` uses `is_block_opener`, `iter_logical_lines` (deferred local import) for `py { ... }` block coalescing | Issue #14 |
| `pysh.python_layer` | `pysh.editor` | `python_layer.mode` uses `editor.lineedit` (reader, buffer, highlight, autosuggest) for `#py` REPL; `python_layer.highlighting` uses `editor.highlight` | Issue #12 |
| `pysh.security` | `pysh.prompt` | `security.secure_runner` uses `colorize`, `parse_color` from `prompt.colors` for indicator rendering | Issue #19 |

**Total known violations: 5.**

To resolve a violation: remove the cross-package import (refactor or extract
to contracts), remove the entry from `KNOWN_VIOLATIONS` in the test file,
and update this table.

---

## Shim lifecycle and removal policy

Issue #2 created the following compatibility shims:

| Shim module | Re-exports | Removal milestone | Notes |
| ----------- | ---------- | ----------------- | ----- |
| `pysh.shell` | `PyShell` from `pysh.core.shell` | Issue #19 | Created to avoid breaking any pre-Issue-#2 import of `pysh.shell.PyShell` |

**Policy (Issue #3):**
- Every shim has a single owner (the issue that created it).
- Every shim has a documented removal milestone.
- Default removal milestone is Issue #19.
- No shim may contain logic — re-exports only.
- No permanent broad compatibility layer is permitted.
- When a shim's removal milestone is reached, the shim file is deleted
  and any remaining callers of the old import path are updated.

---

## Cold-start import budget

`tests/test_import_time_budget.py` enforces that a bare `import pysh` in a
clean subprocess completes within **2.0 seconds** (conservative CI budget).

Typical measured values:
- Subprocess creation overhead: 50–150 ms
- `pysh.__init__` import time: < 5 ms
- `pysh.contracts` import time: < 10 ms

Failure of the budget test indicates that a package initializer is performing
heavy work (heavy module loading, terminal I/O, config reads, git probing, or
subprocess calls) that should be deferred to first use.

---

## Relation to other issues

| Issue | Role |
| ----- | ---- |
| Issue #2 | Source tree relocation (pure move, no behavior changes). Created the subpackage layout that contracts enforce. |
| Issue #3 | This document. Contract layer, boundary tests, ratchet, public API snapshot, cold-start budget. |
| Issue #6 | Signal-handling architecture: deterministic SIGINT/SIGTERM exit-code behavior, explicit SIGTSTP/job-control non-support, `returncode_to_exit_status()`, terminal restoration guarantees. Does not resolve the `pysh.security → pysh.prompt` violation (deferred to Issue #19). |
| Issue #7 | Security and trust model: execution surfaces, static import policy, sensitive input boundary, trust levels, diagnostics non-mutation. See [security-trust-model.md](security-trust-model.md). |
| Issue #8 | Parser/expansion/multiline foundation: decomposes parser modules, defines unsupported syntax ownership, and classifies `pysh.parsing` as a shared leaf consumed by editor, diagnostics and script runner. |
| Issue #9 | Native path and glob expansion: `tokenize_and_glob_expand`, tilde expansion, dotfile policy, no-match policy. See [path-expansion-contract.md](path-expansion-contract.md). |
| Issue #13 | Observability and diagnostics: opt-in `--debug`/`--trace`, stderr-only trace output, redaction policy, and formalized diagnostic builtins. See [observability-diagnostics-contract.md](observability-diagnostics-contract.md). |
| Issue #14 | Script Mode v1: direct PySH-native script invocation, shebang header handling, positional parameters and script exit-code policy. See [script-mode-contract.md](script-mode-contract.md). |
| Issue #10 | Here-documents and here-strings: stdin inline-data parser model, body collection, delimiter expansion policy, and redirection precedence. See [heredoc-contract.md](heredoc-contract.md). |
| Issue #12 | Completion Engine v1. See [completion-engine-contract.md](completion-engine-contract.md). |
| Issue #14 | Script/config mode cleanup: resolves `pysh.config → pysh.python_layer` and finalizes native script-mode contracts. |
| Issue #19 | Shim removal: removes `pysh.shell` compatibility shim after all callers are updated. |
