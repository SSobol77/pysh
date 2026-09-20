<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/api-stability.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Public API Stability, SemVer, and Deprecation Policy

This is the normative external-compatibility contract established by Issue
#45. It defines the surface prepared for PySH 1.0.0 while the package version
remains sourced from `pyproject.toml` and `pysh.__version__`. The guarantees
described as post-1.0 rules take effect with the 1.0.0 release.

Importability does not imply stability. Only surfaces classified below as
stable public, compatibility public, or a versioned external protocol carry a
compatibility guarantee.

## Public and internal inventory

| Surface | Classification | Contract |
| ------- | -------------- | -------- |
| `pysh.__version__`, `pysh.__author__`, `pysh.LICENSE_NAME` | `STABLE_PUBLIC` | Root metadata; the root `__all__` remains metadata-only |
| `pysh.api` | `STABLE_PUBLIC` | Canonical Python API for new external code and the future Plugin SDK |
| `pysh.contracts` | `COMPATIBILITY_PUBLIC` | Supported existing import path for the same contract objects re-exported by `pysh.api`; not deprecated |
| `pysh.plugins.PLUGIN_API_VERSION`, `pysh.plugins.check_api_compatibility` | `COMPATIBILITY_PUBLIC` | Supported trusted-plugin version helpers |
| `pysh.shell.PyShell` | `COMPATIBILITY_PUBLIC` | Deprecated legacy import; warning on symbol access; removal not before 1.2.0 |
| `pysh` CLI and `python -m pysh` | `STABLE_PUBLIC` | User-facing command contract, separate from Python embedding |
| Trusted Plugin API 1.0 registration callbacks | `VERSIONED_EXTERNAL_PROTOCOL` | In-process trusted-code protocol negotiated with `PLUGIN_API_VERSION` |
| Isolated-plugin TOML manifest version 1 | `VERSIONED_EXTERNAL_PROTOCOL` | Data format, independent of package and Plugin API versions |
| Isolated-plugin IPC protocol version 1 | `VERSIONED_EXTERNAL_PROTOCOL` | Wire format, independently negotiated and validated |
| Documented configuration keys and schema | `STABLE_PUBLIC` | User configuration compatibility follows package SemVer |
| Diagnostics/audit event schemas | `INTERNAL` | No serialized stability guarantee until Issue #50 explicitly versions one |
| `pysh.core.*`, `pysh.editor.*`, `pysh.config.*` | `INTERNAL` | Implementation modules, even though Python permits direct imports |
| Parsing and diagnostics implementation modules | `INTERNAL` | No public guarantee unless a symbol is deliberately promoted to `pysh.api` |
| `pysh.plugins.isolated.*` Python objects | `INTERNAL` | Runtime implementation; only manifest and IPC data contracts are external |

Issue #46 owns structural enforcement of the internal dependency partition.
Issue #45 does not mass-rename modules or make every currently importable name
public.

## Canonical `pysh.api`

The exact stable symbol set is:

```python
from pysh.api import (
    PLUGIN_API_VERSION,
    AliasRegistryView,
    CommandResolverView,
    CompatibilityBridge,
    ConfigView,
    EnvironmentView,
    PluginHooks,
    PluginMeta,
    PluginRegistrar,
    ShellSession,
    ShellStateView,
)
```

`pysh.api.__all__`, callable signatures, public method signatures, defaults,
parameter kinds, and public annotations are frozen by
`tests/test_public_api_snapshot.py`. The protocol types are the same objects as
their existing `pysh.contracts` counterparts. New external code should import
them from `pysh.api`; `pysh.contracts` remains supported and is not silently
deprecated.

`pysh.core.shell.PyShell` is deliberately absent. Its constructor and methods
expose implementation dependencies and are not a stable external contract.

## Embedding contract

`ShellSession` is the supported non-interactive embedding boundary:

```python
from pysh.api import ShellSession

with ShellSession() as session:
    status = session.execute("echo embedded")
    script_status = session.run_script("automation.pysh", ("arg1",))
```

Contract:

- construction takes no ambient CLI arguments and mutates neither `sys.argv`
  nor global CLI parser state;
- the internal runtime is created lazily on first execution;
- user rc files, Python configuration, declarative configuration, plugin
  discovery, and startup hooks are never loaded implicitly;
- `execute(command)` executes one PySH command and returns an integer status;
- `run_script(path, args=())` executes the file as native PySH input and does
  not delegate a foreign-shell shebang;
- `exit`, `quit`, and embedded `SystemExit` return a status and close the
  session without exiting the host process;
- `close()` is idempotent; operations after close raise `RuntimeError`;
- context-manager exit always closes the session;
- the facade performs no implicit network access and does not start the
  interactive REPL or require a TTY.

Executed commands retain normal shell authority. They can intentionally
change process-visible current-directory/environment state, access files, and
start subprocesses. Closing a session does not roll back command effects or
terminate processes independently created by an executed command. Embedding is
an invocation boundary, not a security sandbox. Issue #43 and #44 security
contracts remain unchanged.

The console entry point remains `pysh.cli:main`, but CLI emulation is not the
embedding API. Embedders must not mutate `sys.argv` and call `main()` as a
substitute for `ShellSession`.

## Semantic versioning

PySH package releases use `MAJOR.MINOR.PATCH`:

- `MAJOR`: incompatible changes to a stable package, Python, CLI, or
  configuration contract after 1.0;
- `MINOR`: backward-compatible features and additive public API changes;
- `PATCH`: backward-compatible fixes that do not add or break a promised
  interface.

A removal after the documented deprecation lifecycle normally occurs in a
minor release and is not itself a major-version change because affected users
received the guaranteed migration window. Removing or incompatibly changing a
stable API without that completed lifecycle requires a major version, except
for the security-emergency rule below.

Pre-1.0 releases may still make deliberate contract corrections, but every
such change must be explicit in review and release notes. The surface in this
document is the candidate frozen boundary for 1.0.0.

### Python API

After 1.0.0, removing a stable symbol, renaming or removing a parameter,
changing a parameter kind or contractual default, removing a stable method, or
introducing an incompatible annotation requires either a major release or a
completed deprecation lifecycle. Additions require a reviewed snapshot update.

### CLI

Documented option names, invocation forms, exit-code behavior, and explicitly
contractual stdout/stderr formats are compatibility surfaces. Incidental
wording, whitespace, colors, prompt presentation, and undocumented diagnostics
are not frozen unless a contract says otherwise. Breaking a documented CLI
contract follows package SemVer and deprecation policy where a transition is
practical.

### Configuration

Documented configuration keys, accepted value types, defaults when specified,
and schema validation behavior follow package SemVer. New optional keys are
minor-compatible. Removing or incompatibly redefining a documented key
requires deprecation or a major release. Executable configuration remains
trusted code under the security model; stability does not imply sandboxing.

## Independent version domains

| Domain | Current identifier | Compatibility authority | Change relationship |
| ------ | ------------------ | ----------------------- | ------------------- |
| PySH package | package SemVer from the version source files | Release and Python/CLI/config policy | Does not negotiate plugin or IPC compatibility |
| Python `pysh.api` | package SemVer | This document and API snapshot | Follows package SemVer; no separate numeric protocol version |
| Trusted Plugin API | `PLUGIN_API_VERSION == (1, 0)` | `check_api_compatibility` and Plugin API docs | Independent of package SemVer |
| Isolated manifest | `manifest_version = 1` | Manifest parser and isolated-plugin contract | Independent data-format version |
| Isolated IPC | `protocol_version = 1` | Handshake/protocol validator | Independent wire-protocol version |

Changing one domain does not automatically change another. Package SemVer is
not a substitute for Plugin API checks, manifest validation, or IPC protocol
negotiation. The manifest and IPC happen to use value `1`; that numerical
equality does not merge their contracts.

Future serialized diagnostics or audit schemas are not stable merely because
their Python objects exist. Issue #50 must name and version any such external
schema before it receives a compatibility guarantee.

## Deprecation lifecycle

For the 1.x line, a stable API deprecated in release `1.N` remains available
through at least `1.(N+1)`. Its earliest normal removal is `1.(N+2)`.

Every public deprecation requires:

1. documentation and an applicable changelog or release-note entry;
2. a concrete replacement and migration path;
3. a standard `DeprecationWarning`, never `FutureWarning`;
4. a deterministic message naming the deprecated path and replacement;
5. a `stacklevel` that identifies the external caller;
6. a snapshot or compatibility regression test;
7. an explicit removal-not-before release.

Python hides `DeprecationWarning` by default for normal end-user execution.
It remains machine-visible with standard warning controls such as
`python -Walways::DeprecationWarning`.

A critical security defect may require earlier removal. Such an exception must
be narrowly justified, documented in release notes and security guidance, and
provide the safest available migration. Convenience, cleanup, or maintenance
cost is not a security emergency.

### Concrete compatibility deprecation

`pysh.shell.PyShell` is the genuine legacy shim retained from the source-tree
relocation. Accessing the symbol emits:

```text
pysh.shell.PyShell is deprecated; use pysh.api.ShellSession for supported embedding. It will not be removed before PySH 1.2.0.
```

The deprecation is assigned to 1.0.0 and the shim remains available through at
least 1.1.x. Merely importing `pysh.shell` without accessing `PyShell` does not
warn. The replacement is the deliberately smaller embedding facade, not a
promise that every internal `PyShell` method will become public.

## Enforcement and release evidence

- `tests/test_public_api_snapshot.py` freezes public symbol sets, annotations,
  method signatures, defaults, and parameter kinds.
- `tests/test_stable_api.py` checks internal-type leakage, clean import,
  embedding lifecycle/status behavior, startup isolation, deprecation warning
  category/message/caller location, and independent version domains.
- `tests/test_import_time_budget.py` enforces cold imports for `pysh`,
  `pysh.contracts`, and `pysh.api`.
- Existing plugin and isolated-plugin suites protect Plugin API 1.0 and Issue
  #44 contracts.

Any intentional public change must update implementation, literal snapshot,
normative documentation, migration guidance, and release notes in the same
review. Issue #35 may cite these artifacts and validation results as release
readiness evidence after merge.
