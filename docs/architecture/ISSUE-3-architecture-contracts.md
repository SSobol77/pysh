<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/ISSUE-3-architecture-contracts.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# ISSUE #3 - Add Architecture Contracts and Import-Boundary Enforcement

## Summary

Add the architecture contract layer and machine-checkable import boundaries that
were intentionally excluded from ISSUE #2. This issue makes the relocated tree
enforceable without changing shell command behavior.

ISSUE #3 is the owner of contracts, import graph policy, public API snapshots,
cold-start/import-time budget, architecture documentation, and shim lifecycle
refinement.

## Depends On

- ISSUE #2: Refactor source tree by pure relocation.

## Scope

ISSUE #3 owns:

- `pysh/contracts/` or an equivalent protocol layer,
- `contracts/protocols.py`,
- protocol definitions for editor, prompt, completion, command execution,
  compatibility bridges, configuration, and plugin surfaces,
- import-boundary enforcement,
- import-linter or pytest import-graph test,
- no-cycles gate,
- layered dependency ratchet,
- public API snapshot test,
- import-time/cold-start budget test,
- `docs/architecture/architecture.md`,
- known layering violations table,
- shim lifecycle/removal policy refinement,
- minimal side-effect-free `__init__.py` policy.

## Non-Goals

ISSUE #3 does not implement new shell behavior:

- no parser feature changes,
- no parser decomposition beyond what is required to type against protocols,
- no command execution semantic changes,
- no job-control feature work,
- no script-mode feature work,
- no compatibility claims beyond documenting boundaries.

If a boundary violation requires behavior or decomposition to fix, record it in
the known violations table and assign it to the appropriate later issue.

## Contract Layer

Create `pysh/contracts/` or an equivalent protocol layer after relocation has
established final package paths.

`contracts/protocols.py` should contain structural interfaces only. It must not
import implementation modules from `pysh.core`, `pysh.editor`, `pysh.prompt`,
`pysh.compat`, or other runtime packages.

Protocol candidates:

- shell state view consumed by prompt and editor,
- command resolver view consumed by completion,
- alias registry view,
- environment/config view,
- plugin registration interface,
- compatibility bridge interface where needed.

Do not speculatively model the entire runtime. Add protocols only where they
remove real cross-layer coupling or define a public extension boundary.

## Import-Boundary Enforcement

Use either import-linter or a pytest import-graph test. The enforcement must
cover:

- no import cycles across PySH packages,
- no editor/prompt/completion/compat imports of core internals except through
  contracts,
- no heavy side-effect imports from package `__init__.py`,
- no accidental dependency from contracts into implementation packages.

An import-linter configuration may look like:

```ini
[importlinter]
root_package = pysh

[importlinter:contract:no-cycles]
name = No import cycles between pysh packages
type = independence
modules =
    pysh.core
    pysh.parsing
    pysh.editor
    pysh.prompt
    pysh.python_layer
    pysh.config
    pysh.compat
    pysh.services
    pysh.security
    pysh.diagnostics
    pysh.contracts

[importlinter:contract:layers]
name = Layered dependency direction
type = layers
layers =
    pysh.cli
    pysh.core
    pysh.parsing | pysh.editor | pysh.prompt | pysh.config | pysh.compat | pysh.services | pysh.security | pysh.diagnostics
    pysh.contracts
```

If pytest import-graph enforcement is used instead, it must provide equivalent
evidence and deterministic failure messages.

## Layer Ratchet and Known Violations

The no-cycles gate is a hard gate.

The layer rule is a ratchet:

- known violations are listed explicitly,
- each known violation names the importing module, imported module, reason, and
  cleanup issue,
- new violations fail CI,
- the violations list may shrink but must not grow without architectural review.

Required table format in `docs/architecture/architecture.md`:

| Importing module | Imported module | Reason retained | Cleanup issue |
| --- | --- | --- | --- |

Cleanup issue references must use the final issue sequence:

- parser/expansion cleanup: ISSUE #8,
- error/exit-code cleanup: ISSUE #5,
- signal and PTY cleanup: ISSUE #6 or ISSUE #11,
- script-mode cleanup: ISSUE #14,
- packaging/shim removal: ISSUE #19.

## Public API Snapshot

Add a snapshot test for the supported Python import surface. The test must make
intentional API drift visible in review.

The snapshot covers the public `pysh` API intended for config authors, plugin
authors, and documented extension points. It must not bless internal runtime
modules as public API by accident.

Example policy:

```python
import pysh

EXPECTED_PUBLIC_API = set(pysh.__all__)


def test_public_api_surface_is_stable() -> None:
    assert set(pysh.__all__) == EXPECTED_PUBLIC_API
```

The final implementation should avoid self-referential snapshots; this example
documents intent, not the exact test body.

## Import-Time and Cold-Start Budget

Add a test that measures cold import of `pysh` in a subprocess. The budget must
be based on a measured baseline with documented headroom.

The test guards the shell invariant that imports and package initializers do not
perform terminal I/O, config reads, git probing, heavy module loading, or other
startup-cost side effects.

## Minimal `__init__.py` Policy

Package `__init__.py` files must be minimal and side-effect free:

- no terminal I/O,
- no filesystem probing unless explicitly part of public version metadata,
- no config loading,
- no git probing,
- no subprocess execution,
- no broad eager imports.

Any re-export from `__init__.py` must be justified as public API or a narrow
compatibility shim.

## `docs/architecture/architecture.md`

Create `docs/architecture/architecture.md` with:

1. package responsibilities,
2. dependency direction,
3. contract layer purpose,
4. CLI entrypoint ownership,
5. public Python API surface,
6. parser/execution/editor boundaries,
7. compatibility-layer boundaries,
8. Python command-execution layer boundaries,
9. minimal `__init__.py` policy,
10. known layering violations table,
11. shim lifecycle and removal policy.

## Shim Lifecycle Refinement

ISSUE #2 may create narrow re-export shims. ISSUE #3 refines their policy:

- every shim has an owner,
- every shim has a removal milestone,
- default removal milestone is ISSUE #19,
- any shorter milestone is documented in the shim and in `docs/architecture/architecture.md`,
- no shim contains behavior,
- no permanent broad compatibility layer is permitted.

## Acceptance Criteria

ISSUE #3 is complete only when:

1. Contract/protocol layer exists or an equivalent interface layer is documented.
2. Editor, prompt, completion, and compat depend on protocols/interfaces where
   they cross runtime boundaries.
3. Import-boundary enforcement runs in tests or CI.
4. No-cycles gate is active.
5. Layer ratchet is active with known violations documented.
6. Public API snapshot test exists.
7. Import-time/cold-start budget test exists.
8. `docs/architecture/architecture.md` exists and matches the actual tree.
9. `__init__.py` files are minimal and side-effect free.
10. Shim lifecycle/removal policy references ISSUE #19 or a narrower documented
    milestone.

## Required Validation

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
```

Additional architecture gates:

```sh
# exact command depends on whether import-linter or pytest import graph is used
uv run lint-imports
```

Required test evidence:

- import-boundary test,
- no-cycles gate,
- layer ratchet,
- public API snapshot test,
- import-time/cold-start budget test.
