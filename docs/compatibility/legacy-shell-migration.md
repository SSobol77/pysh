<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/legacy-shell-migration.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Legacy-Shell Migration Contract

This document is the PySH-owned contract for measuring migration **away from**
legacy shells (Bash, Zsh, Fish). It is the documentation anchor registry for
the Issue #54 migration metadata in `tests/differential/migration-v1.json`.

<a id="PYSH-MIG-POSITIONING"></a>

## Positioning

- PySH is a standalone, Python-native shell.
- PySH is intended to replace legacy shells for normal interactive and
  automation use.
- Bash, Zsh and Fish are **not** runtime dependencies, package dependencies,
  required workstation components, fallback runtimes, or semantic authorities.
- PySH does not promise Bash, Zsh or Fish emulation.
- Migration guidance prefers PySH-native constructs.

<a id="PYSH-MIG-AUTHORITY"></a>

## Authority

PySH semantics are defined by PySH:

1. [`docs/spec/pysh-language.md`](../spec/pysh-language.md) and
2. `tests/conformance/pysh-language-v1.json` (Issue #48).

The #48 corpus is the only normative language oracle. The migration layer is
metadata keyed by stable #48 case IDs; it never copies or overrides
`pysh_expected`. A legacy shell's behavior is descriptive evidence only. The
rule is always *PySH specification → PySH expected behavior*, never *Bash
behavior → PySH expected behavior*.

<a id="PYSH-MIG-NON-GOALS"></a>

## Non-goals

Issue #54 does **not** require, and PySH does not promise:

- POSIX-shell emulation;
- Bash, Zsh or Fish syntax compatibility;
- arbitrary legacy scripts running unchanged;
- preservation of historical quirks;
- installing legacy shells with PySH;
- runtime fallback to a legacy shell.

Intentional incompatibility is allowed. Unsupported legacy syntax is not
automatically a bug. An *undocumented* PySH regression is a bug.

Existing, explicit opt-in transition bridges (`zsh <cmd>`, `zsh_fallback`,
`run_script` on a foreign shebang; see
[shell-compatibility-contract.md](shell-compatibility-contract.md)) predate this
contract. Issue #54 adds none, treats none of them as a semantic authority, and
their long-term place is a separate architectural decision.

<a id="PYSH-MIG-OUTCOMES"></a>

## Outcome model

Every migration case answers four questions: can the behavior be used
unchanged; what PySH-native form replaces it; is the legacy construct
intentionally unsupported; is PySH violating its own documented behavior.

| Outcome | Meaning from PySH's perspective |
| --- | --- |
| `MATCH` | The legacy construct maps to equivalent observable PySH behavior on the dimensions that matter for that case. |
| `INTENDED_DIVERGENCE` | PySH intentionally differs or does not support the legacy behavior, anchored in a `PYSH-MIG-DIV-*` anchor of this document, with migration guidance. |
| `REGRESSION` | PySH violates its own #48 expectation, or violates an established documented migration contract (a declared `MATCH` that no longer holds). |

A difference from a legacy shell alone is **never** sufficient for
`REGRESSION`. `REGRESSION` is only ever an observed outcome; metadata may
declare only `match` or `intended_divergence`.

Deterministic rules, evaluated in order, on the compared dimensions only:

1. PySH does not satisfy its own #48 expectation → `REGRESSION`, whatever the
   legacy shell did.
2. The legacy observation satisfies the #48 expectation (same matcher
   semantics as the #48 runner):
   - declared `match` → `MATCH`;
   - declared `intended_divergence` → **stale divergence**, a contract failure.
3. The legacy observation differs:
   - declared `intended_divergence` with a resolving anchor and guidance →
     `INTENDED_DIVERGENCE`;
   - declared `match` → `REGRESSION` (the documented migration contract no
     longer holds).

Comparison dimensions are an explicit non-empty subset of `status`, `stdout`
and `stderr` per case. There is no fuzzy comparison.

<a id="PYSH-MIG-METADATA"></a>

## Metadata contract

`tests/differential/migration-v1.json` is versioned and closed
(`schema_version`, `legacy_profiles`, `cases`). A case has `case_id` (an
existing #48 ID), `legacy_profile`, `classification`, `compared_dimensions`,
`migration_anchor`, `guidance`, `rationale`. Unknown fields, unknown #48 IDs,
duplicate `(case_id, legacy_profile)` pairs, unknown classifications,
malformed dimensions, unresolvable or non-`PYSH-MIG-DIV-` anchors, and missing
guidance on a divergence all fail validation.

Guidance is one of: a PySH-native replacement (`legacy_construct` plus
`pysh_replacement`), or an intentional non-support (`legacy_construct` plus
`reason`). Changing a documented divergence requires changing this document
and the metadata in the same change.

A legacy profile (`profile_id`, `legacy_shell`, `version`, `version_status`,
`platform`) is **test metadata**, not a dependency. Exact versions are
`pending` until established from controlled Tier-1 reference environments; the
developer workstation's shell is never an authority.

<a id="PYSH-MIG-DIVERGENCE-REGISTRY"></a>

## Divergence registry

Each verified intentional divergence adds one `<a id="PYSH-MIG-DIV-...">`
anchor and section here, plus one metadata case. None are registered yet: no
legacy shell has been executed as evidence, and speculative mappings are not
recorded.

<a id="PYSH-MIG-BOUNDARIES"></a>

## Legacy execution boundaries

`tests/differential/legacy-boundaries-v1.json` classifies every place where
PySH production code can hand work to Bash, Zsh, Fish or a POSIX `sh`, in
exactly one category:

| Category | Meaning |
| --- | --- |
| `PYSH_NATIVE` | Normal PySH behavior, including static analysis that executes nothing. |
| `EXPLICIT_MIGRATION_BRIDGE` | The user explicitly asks for another interpreter (`zsh <cmd>`). |
| `EXPLICIT_SHEBANG_DELEGATION` | The script itself names an external interpreter in its shebang. |
| `AUTOMATIC_LEGACY_FALLBACK` | PySH hands work to a legacy shell without an explicit per-command request. |
| `BUILD_OR_TEST_TOOLING` | Shell use outside language semantics (for example the OS-package launcher). |
| `DOCUMENTATION_ONLY` | Mentions only. |

A boundary is never a product dependency and never a semantic authority. An
AST drift guard (`tests/test_legacy_boundary_contract.py`) fails when
production code gains a legacy-execution signal that is not inventoried. Its
limits are documented in `tests/differential/boundaries.py` (dynamically built
executables and non-Python files are invisible to it).

<a id="PYSH-MIG-SHEBANG"></a>

### Shebang delegation

A script whose own first line is `#!/bin/bash`, `#!/bin/sh` or `#!/bin/zsh`
(or the `env` form) is an explicit request by that script for an external
interpreter, honored only by the `run_script` builtin; direct `pysh FILE`
ignores the shebang. Delegating it is **not** a fallback from PySH language
semantics. The interpreter is optional and PySH must not depend on it: when it
is absent the failure is controlled (status 127), and PySH never silently
substitutes a different legacy shell.

<a id="PYSH-MIG-BRIDGE"></a>

### Migration bridge

`zsh <cmd>` is an explicit migration and interoperability request. It does not
define PySH language semantics and is not used internally as a fallback for
ordinary PySH execution. It is retained for now.

<a id="PYSH-MIG-AUTOMATIC-FALLBACK"></a>

### Automatic legacy fallback: decision record

Automatic fallback from PySH language execution to Bash, Zsh or Fish is **not**
part of the target PySH 1.0 architecture. Current behavior, recorded and not
changed by Issue #54:

- `zsh_fallback on`, `PYSH_ZSH_FALLBACK=1` in the environment, or assigning
  that variable arms a fallback that is off by default. While armed, a path
  expansion error, an unresolved external command in a pipeline, and a
  process-creation `FileNotFoundError` are handed to `zsh -lc`.

Command substitution (`$(...)` and backticks) is **PySH-native** and no longer
a legacy boundary: the default runner evaluates the nested command in an
isolated nested PySH execution (no user startup configuration, no zsh
fallback armed, all descendants contained in one process group and terminated
with it), never `/bin/sh`. (Before Issue #54 Slice 2.5 it ran `/bin/sh -c`.)
The zsh fallback above is **not** resolved by this change.

Containment limit (known, not hidden): containment covers descendants that stay
in the substitution's execution domain and process group. A descendant that
deliberately leaves it with its own `setsid()` or `setpgid()` (for example a
daemon) escapes portable POSIX process-group containment and is not terminated.
No Linux-only mechanism (`/proc`, cgroups, subreaper, process-name scanning) is
used.

The zsh fallback is migration-era technical debt. Before PySH 1.0 it needs one
explicit decision: (A) remove it, (B) deprecate then remove it, or (C) retain it only as
a clearly separated compatibility feature with no default enablement. No option
is chosen here.

<a id="PYSH-MIG-LAB"></a>

## Future isolated legacy laboratory (requirements only)

Not implemented. Any later legacy-shell process is external test equipment in
isolated differential CI, never PySH runtime machinery, and must run with:

- a controlled `HOME` and cwd, and a controlled environment;
- startup files disabled (`--noprofile --norc`, `-f`, `--no-config` style);
- a hard timeout, and no network dependency;
- test-owned input files only, never user scripts;
- deterministic stdout/stderr/status capture;
- no access to developer rc or configuration files.

Legacy shell input there is test data.

`tests/differential/executor.py` is the test-only foundation for that
laboratory: it runs an explicitly supplied executable and argv (never a shell,
never found through `PATH`) with an allowlisted environment, a private `HOME`
and working directory, a hard process-group timeout and bounded output. It is
exercised only with a repository-owned fake interpreter; startup flags for
real shells are supplied later as `argv_prefix` and are not defined yet.

<a id="PYSH-MIG-EVIDENCE"></a>

## Evidence record

A future release evidence record contains: PySH commit/version, platform,
case ID, legacy profile, legacy tool version, PySH observation, legacy
observation, classification, and contract anchors. Its identity never
includes `HOME`, absolute personal paths, the environment, secrets, or a
timestamp.
