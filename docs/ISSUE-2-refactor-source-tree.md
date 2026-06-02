# ISSUE #2 - Refactor Source Tree by Pure Relocation

## Summary

Reorganize the flat `src/pysh/` layout into package-oriented internal modules
without changing observable behavior. This issue is a mechanical relocation
phase only.

The invariant is strict: a moved file remains the same implementation. Content
diffs in moved files are limited to import path fixups required by relocation.
No subsystem is redesigned in this issue.

## Allowed Scope

ISSUE #2 may do only the following:

- move existing modules with `git mv`,
- perform 1:1 file relocation,
- update imports required by the new paths,
- update tests only where imports refer to moved modules,
- add narrow re-export shims only where old import paths are actually needed,
- keep public CLI behavior unchanged,
- keep `pysh`, `python -m pysh`, `pysh --version`, `uv run pysh`, and
  `pysh -c ...` behavior unchanged.

## Forbidden Scope

ISSUE #2 must not add or change:

- runtime behavior,
- shell features,
- parser decomposition,
- command execution semantics,
- error/exit-code model,
- contracts layer,
- protocol layer,
- import-boundary tests,
- test-tree architecture suite,
- empty placeholder packages,
- TODO-only modules,
- broad compatibility layers,
- new subsystem design.

The following belong to ISSUE #3, not ISSUE #2: `contracts/protocols.py`, import-linter, architectural fitness functions, no-cycles gate, layers ratchet, public API snapshot, import-time budget, docs/architecture.md, architecture test suite.

Parser decomposition belongs to ISSUE #8. Error/exit-code semantics belong to
ISSUE #5. Signal architecture belongs to ISSUE #6. Job control and process
groups belong to ISSUE #11. Script execution belongs to ISSUE #14.

## Target Structure

The target structure is relocation-only. Every listed target maps to an existing
file or existing directory. Packages may be created only when they immediately
contain moved files.

```text
src/pysh/
├── __init__.py
├── __main__.py
├── cli.py
├── shell.py                    # optional narrow re-export shim
├── script_runner.py            # unchanged; script mode is ISSUE #14
│
├── core/
│   ├── __init__.py
│   └── shell.py
│
├── parsing/
│   ├── __init__.py
│   ├── parser.py
│   └── redirection.py
│
├── editor/
│   ├── __init__.py
│   ├── completion.py
│   ├── highlight.py
│   ├── history.py
│   └── lineedit/
│       └── existing line editor modules moved as-is
│
├── prompt/
│   ├── __init__.py
│   ├── colors.py
│   └── system_profile.py
│
├── python_layer/
│   ├── __init__.py
│   ├── mode.py
│   ├── runtime.py
│   ├── render.py
│   └── highlighting.py
│
├── config/
│   ├── __init__.py
│   ├── api.py
│   ├── rc.py
│   └── plugins.py
│
├── compat/
│   ├── __init__.py
│   ├── zsh_aliases.py
│   ├── zsh_bridge.py
│   ├── mc.py
│   └── profile_importer.py
│
├── services/
│   ├── __init__.py
│   ├── pyinit.py
│   └── service.py
│
├── security/
│   ├── __init__.py
│   └── secure_runner.py
│
└── diagnostics/
    ├── __init__.py
    ├── system_info.py
    └── command_plan.py
```

Placement decisions:

- `core/shell.py` owns the `PyShell` runtime.
- `cli.py` owns entrypoint orchestration.
- Top-level `shell.py`, if retained, is only a narrow import shim.
- Top-level `shell.py` must not become a second implementation.
- Command-line highlighting moves to `editor/highlight.py`.
- Python highlighting moves to `python_layer/highlighting.py`.
- Config relocation uses `config/api.py`, `config/rc.py`, and
  `config/plugins.py`; do not introduce unclear `rc` / `pyshrc` duplication.

## Migration Map

Pure `git mv` map. The migration map must be exhaustive against
`git ls-files src/pysh` when the implementation issue is executed.

| Current file | Target | Operation |
| --- | --- | --- |
| `src/pysh/shell.py` | `src/pysh/core/shell.py` | move + optional shim |
| `src/pysh/parser.py` | `src/pysh/parsing/parser.py` | move |
| `src/pysh/redirection.py` | `src/pysh/parsing/redirection.py` | move |
| `src/pysh/lineedit/*` | `src/pysh/editor/lineedit/*` | move |
| `src/pysh/completion.py` | `src/pysh/editor/completion.py` | move |
| `src/pysh/highlighting.py` | `src/pysh/editor/highlight.py` | move |
| `src/pysh/history.py` | `src/pysh/editor/history.py` | move |
| `src/pysh/colors.py` | `src/pysh/prompt/colors.py` | move |
| `src/pysh/system_profile.py` | `src/pysh/prompt/system_profile.py` | move |
| `src/pysh/python_mode.py` | `src/pysh/python_layer/mode.py` | move |
| `src/pysh/python_runtime.py` | `src/pysh/python_layer/runtime.py` | move |
| `src/pysh/python_terminal_render.py` | `src/pysh/python_layer/render.py` | move |
| `src/pysh/python_highlight.py` | `src/pysh/python_layer/highlighting.py` | move |
| `src/pysh/config_api.py` | `src/pysh/config/api.py` | move |
| `src/pysh/rc.py` | `src/pysh/config/rc.py` | move |
| `src/pysh/plugins.py` | `src/pysh/config/plugins.py` | move |
| `src/pysh/zsh_aliases.py` | `src/pysh/compat/zsh_aliases.py` | move |
| `src/pysh/zsh_bridge.py` | `src/pysh/compat/zsh_bridge.py` | move |
| `src/pysh/mc_compat.py` | `src/pysh/compat/mc.py` | move |
| `src/pysh/profile_importer.py` | `src/pysh/compat/profile_importer.py` | move |
| `src/pysh/pyinit.py` | `src/pysh/services/pyinit.py` | move |
| `src/pysh/service.py` | `src/pysh/services/service.py` | move |
| `src/pysh/secure_runner.py` | `src/pysh/security/secure_runner.py` | move |
| `src/pysh/system_info.py` | `src/pysh/diagnostics/system_info.py` | move |
| `src/pysh/command_plan.py` | `src/pysh/diagnostics/command_plan.py` | move |
| `src/pysh/script_runner.py` | `src/pysh/script_runner.py` | unchanged; ISSUE #14 |

`src/pysh/completion.py` and `src/pysh/lineedit/completion.py` are distinct
modules and must not be collapsed. The top-level completion driver moves to
`editor/completion.py`; raw-line editor helpers remain under
`editor/lineedit/`.

## Shim Policy for ISSUE #2

Shims are allowed only when an old import path is actually needed by tests,
documentation, or known external users.

A shim is a re-export only:

```python
from pysh.core.shell import PyShell
```

Rules:

- no duplicate implementation,
- no behavioral logic,
- no side effects beyond the re-export itself,
- no wildcard compatibility namespace,
- no shim for purely internal paths when all callers are updated in the same
  relocation,
- every retained shim documents its removal milestone as ISSUE #19 unless the
  implementation PR chooses a narrower milestone.

Deprecation warnings are optional and must not break normal imports or CLI
startup. If a warning would create noise for supported use, omit it and rely on
the documented ISSUE #19 removal milestone.

## Mechanical Review Rules

ISSUE #2 must be reviewable as a relocation:

- commits use `git mv`,
- moved file content diffs are limited to import path edits,
- no logic is copied,
- no symbol has two implementations,
- new package `__init__.py` files are minimal and side-effect free,
- no package directory exists unless it contains moved files,
- tests are adjusted only for import paths,
- CLI behavior is compared before and after relocation.

Recommended commit structure:

```text
refactor(src): move modules into internal packages via git mv
refactor(src): update imports after relocation
chore(compat): add required narrow re-export shims
test(src): update test imports after relocation
```

Do not add architecture tests or import graph gates in these commits. Those are
ISSUE #3.

## Out of Scope and Reassignment

| Removed from ISSUE #2 | Correct issue |
| --- | --- |
| Architecture contract layer and gates | ISSUE #3 |
| parser decomposition into expansion/command-chain/assignments modules | ISSUE #8 |
| `core/errors.py` or exception-to-exit-code model | ISSUE #5 |
| PTY/job-control redesign | ISSUE #6 and ISSUE #11 |
| `security/pty_runner.py` | ISSUE #11 if job-control related; ISSUE #7 if trust-boundary related |
| script execution semantics / `script_runner.py` redesign | ISSUE #14 |
| packaging release gate | ISSUE #19 |

## Acceptance Criteria

ISSUE #2 is complete only when:

1. Source tree is reorganized through the migration map or an explicitly
   reviewed extension to it.
2. `git diff --find-renames` shows relocations rather than rewrites.
3. Moved file content diffs are limited to import edits.
4. Public CLI behavior is unchanged.
5. Existing tests pass.
6. No contracts layer or architecture gate has been introduced.
7. No parser, error-model, script-mode, PTY, job-control, security, or
   observability subsystem has been decomposed or redesigned.
8. Any shim is a narrow re-export with ISSUE #19 removal milestone.

## Required Validation

Behavior-neutral validation only:

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
uv run pysh -c 'echo hello'
```

Manual review checks:

```sh
git diff --find-renames
git diff --stat
```

Packaging builds are not required for ISSUE #2 unless the relocation affects
packaging metadata. Packaging and release quality is ISSUE #19.
