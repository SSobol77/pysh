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

<a id="PYSH-MIG-EVIDENCE"></a>

## Evidence record

A future release evidence record contains: PySH commit/version, platform,
case ID, legacy profile, legacy tool version, PySH observation, legacy
observation, classification, and contract anchors. Its identity never
includes `HOME`, absolute personal paths, the environment, secrets, or a
timestamp.
