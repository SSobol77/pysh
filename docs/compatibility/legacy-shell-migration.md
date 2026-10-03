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

The only remaining production hand-off to an external shell is explicit shebang
delegation by `run_script` (see
[shell-compatibility-contract.md](shell-compatibility-contract.md)); it is the
script's own request and is not a semantic authority. PySH has no automatic
fallback and no dedicated `zsh` builtin (see below).

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

A legacy profile is **test metadata**, not a dependency. It is specific to one
shell on one Tier-1 platform (`bash-debian13-amd64`, `zsh-freebsd14.4-amd64`,
...) and records `profile_id`, `legacy_shell`, `platform`, `executable` (absolute
path), `startup_policy`, `version` (the executable's first `--version` line),
`package_version` (the OS package version) and `version_status`. Exact versions
are `pending` until established from the controlled Tier-1 CI environments and
reviewed into the file (the six Tier-1 profiles have now been pinned, see
below); the developer workstation's shell is never an authority.

<a id="PYSH-MIG-DIVERGENCE-REGISTRY"></a>

## Divergence registry

Each verified intentional divergence adds one `<a id="PYSH-MIG-DIV-...">`
anchor and section here, plus one metadata case. No intended divergence is
registered: the reviewed Tier-1 baseline (see below) produced no difference that
needed an `INTENDED_DIVERGENCE`, and speculative mappings are not recorded. A
real divergence still requires a `PYSH-MIG-DIV-*` anchor and guidance.

<a id="PYSH-MIG-BOUNDARIES"></a>

## Legacy execution boundaries

`tests/differential/legacy-boundaries-v1.json` classifies every place where
PySH production code can hand work to Bash, Zsh, Fish or a POSIX `sh`, in
exactly one category:

| Category | Meaning |
| --- | --- |
| `PYSH_NATIVE` | Normal PySH behavior, including static analysis that executes nothing. |
| `EXPLICIT_MIGRATION_BRIDGE` | A dedicated production bridge to another shell. None exists; the category must stay empty. |
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

### No production migration bridge

PySH has no dedicated `zsh` builtin and no `ZshBridge` (removed in Issue #54,
Slice 2.7). `zsh` is an ordinary program name: if an executable named `zsh` is
on `PATH` it runs through generic external-command execution with exactly the
arguments the user typed. PySH injects no flags (such as `-lc`) and no
semantics, and never defines language behavior from it. Migration comparison
against Bash, Zsh or Fish belongs to the test/CI differential laboratory
(`tests/differential`), not to the shell runtime.

<a id="PYSH-MIG-AUTOMATIC-FALLBACK"></a>

### Automatic legacy fallback: removed

Decision (Issue #54, Slices 2.6 and 2.7): automatic fallback from PySH language execution
to Bash, Zsh or Fish is not part of the PySH 1.0 architecture, and it has been
removed. Testable facts:

- The `zsh_fallback` builtin does not exist: `zsh_fallback on` is an unknown command
  with the ordinary status 127.
- `PYSH_ZSH_FALLBACK` has no meaning. It may be set like any unrelated
  variable and changes no execution behavior (environment, local assignment and
  `export` are all inert).
- A path-expansion error, an unresolved external command (alone or in a
  pipeline) and a process-creation `FileNotFoundError` produce the ordinary PySH
  diagnostic and status; nothing is retried through zsh.
- The `zsh <cmd>` builtin does not exist either. Explicit legacy shebang
  execution through `run_script` remains interoperability requested by the
  script itself; it is not a fallback and does not define PySH semantics.
- No external legacy shell is required for ordinary PySH operation.
- The boundary inventory's automatic-fallback category must stay empty, and the
  AST drift guard rejects reintroduced fallback machinery.

Command substitution (`$(...)` and backticks) is **PySH-native** and no longer
a legacy boundary: the default runner evaluates the nested command in an
isolated nested PySH execution (no user startup configuration, all descendants
contained in one process group and terminated with it), never `/bin/sh`.
(Before Issue #54 Slice 2.5 it ran `/bin/sh -c`.)

Containment limit (known, not hidden): containment covers descendants that stay
in the substitution's execution domain and process group. A descendant that
deliberately leaves it with its own `setsid()` or `setpgid()` (for example a
daemon) escapes portable POSIX process-group containment and is not terminated.
No Linux-only mechanism (`/proc`, cgroups, subreaper, process-name scanning) is
used.

<a id="PYSH-MIG-LAB"></a>

## Legacy-shell differential laboratory

Bash, Zsh and Fish are used **only** as reference equipment in dedicated CI jobs
and tests; they are installed there as test packages, never by PySH, and no
runtime or package dependency exists (the Debian and RPM metadata and
`pyproject.toml` are unchanged). The laboratory lives in `tests/differential`,
and `scripts/run_legacy_shell_differential.py` is its entry point.

- **Where it runs.** Two Tier-1 jobs, `legacy-shell differential evidence
  (debian-13, ...)` and `(freebsd-14.4, ...)`, in `.github/workflows/ci.yml`.
  Both require all three shells; a missing shell fails the job. Locally, the
  real-shell tests are skipped unless `PYSH_LEGACY_LAB` is set.
- **PySH stays normative.** For each selected #48 command case PySH runs first
  under `--no-rc` and is checked against its #48 `pysh_expected`. A violation is
  a `REGRESSION` that no reference result can excuse (the reference is not even
  run). Only then is the reference observation compared, on the dimensions the
  case declares, and classified `MATCH`, `INTENDED_DIVERGENCE` or `REGRESSION`
  by the oracle above. Legacy output is never an oracle.
- **Selection.** `tests/differential/reference-cases-v1.json` selects a small set
  of existing #48 cases with explicit shell applicability and compared
  dimensions. It copies no expectation. Reviewed accepted states live in
  `migration-v1.json`.
- **Controlled execution and user-startup isolation.** The reference runs
  through the executor with an explicit absolute executable, a private `HOME`
  containing hostile startup files, a private cwd, a fixture-only `PATH`, a fixed
  locale, a timeout and bounded output, with user startup files disabled. The
  executor is hermetic with respect to the environment and files it controls:
  it builds the environment from scratch, and a variable that names startup code
  (`BASH_ENV`, `ENV`, `SHELLOPTS`, `BASHOPTS`, `ZDOTDIR`, `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`) is rejected by the laboratory. The startup policies
  (`bash --noprofile --norc`, `zsh -f`, `fish --no-config`) are accepted only
  after a live self-test on the installed version: a positive control proves
  the hostile files (including Fish `config.fish` and `conf.d/*.fish`) are
  executed when isolation is off, the isolated run must not execute them, a
  hostile `BASH_ENV`/`ZDOTDIR`/`XDG_CONFIG_HOME` set in the host process must
  neither be inherited nor executed, and a deliberately forced hook proves the
  hook would otherwise run.
- **Platform-global Zsh startup is an explicit baseline limitation.** The
  guarantee is *user* startup isolation, not complete system startup isolation:
  Zsh reads the installation-wide `zshenv` before `-f` can suppress later startup
  files, and the laboratory does not edit it or require root. For every shell
  an empty isolated run must print nothing, and for Zsh the shell must also see
  the controlled `PATH`, `HOME` and no `ZDOTDIR`; otherwise the profile fails its
  isolation check instead of producing contaminated evidence. A clean probe does
  not prove the global file did not execute; it shows only that platform-global
  startup caused no observable contamination relevant to the observations.
- **Version drift fails CI.** A `pinned` profile whose executable version line or
  package version differs from the committed pin fails the job before any
  semantic result is interpreted, reporting the profile, platform, expected and
  actual values. A `pending` profile (no pin yet) is discovery only: the run
  prints a pin proposal and an unreviewed difference is reported, not accepted.
  Changing a pin or an accepted state requires an explicit reviewed change.
- **Evidence.** Each run writes `legacy-shell-differential-<platform>.json`
  (rewritten as the run progresses, so the version and pin information survives a
  later failure; canonical, sorted, no timestamps, `HOME`, user names, environment or absolute
  paths; fixture paths appear as `{{WORK}}`-style placeholders) and uploads it as
  a CI artifact.
- **Not part of it.** `run_script` shebang delegation is unrelated to the
  laboratory, and the laboratory never executes user scripts.

### Reviewed Tier-1 baseline

The initial discovery run (GitHub Actions run 37138273140, source commit
`15aae5f3f6e24919f53de0f3d73575276ff87e71`) was reviewed and its observations
pinned in `migration-v1.json`. Six platform-specific reference profiles are
`pinned`, each with the executable's first `--version` line and the OS package
version, compared as exact strings (no normalization of epochs, revisions or
build strings):

| Profile | Executable | `--version` | Package |
| --- | --- | --- | --- |
| `bash-debian13-amd64` | `/usr/bin/bash` | `GNU bash, version 5.2.37(1)-release (x86_64-pc-linux-gnu)` | `5.2.37-2+b10` |
| `zsh-debian13-amd64` | `/usr/bin/zsh` | `zsh 5.9 (x86_64-debian-linux-gnu)` | `5.9-8+b24` |
| `fish-debian13-amd64` | `/usr/bin/fish` | `fish, version 4.0.2` | `4.0.2-1` |
| `bash-freebsd14.4-amd64` | `/usr/local/bin/bash` | `GNU bash, version 5.3.20(0)-release (amd64-portbld-freebsd14.4)` | `5.3.20` |
| `zsh-freebsd14.4-amd64` | `/usr/local/bin/zsh` | `zsh 5.9.2 (amd64-portbld-freebsd14.4)` | `5.9.2` |
| `fish-freebsd14.4-amd64` | `/usr/local/bin/fish` | `fish, version 4.9.1` | `4.9.1_1` |

- These versions are test-reference pins only. They are not PySH dependencies,
  and no runtime or package dependency exists.
- Version drift is merge-blocking until it is reviewed: a package or executable
  version change fails the job before any semantic result is interpreted.
- All 84 applicable case/profile pairs (Bash 15 and Zsh 15 per platform, Fish 12
  per platform) matched on their compared dimensions, every startup-isolation
  check passed on both platforms, and no `REGRESSION` or undeclared difference
  was observed. Each pair is recorded in `migration-v1.json` as a reviewed
  `match` with no anchor and no guidance; no `INTENDED_DIVERGENCE` was needed by
  this initial corpus.
- The metadata declares only the reviewed classification. Observations stay
  generated CI evidence, and PySH #48 remains the only normative expectation:
  external shells still do not define PySH semantics.
- A pinned profile now requires exactly one reviewed mapping for every selected
  case that applies to its shell, with the same compared dimensions. Adding a
  selected case, pinning a profile or changing a dimension without updating the
  mappings fails a contract test before CI.
- The Zsh baseline is still the scoped one described above: it shows no
  observable contamination, and does not prove the global `zshenv` did not run.

Completion of Issue #54 additionally requires the same workflow to pass again
with the pinned profiles.

<a id="PYSH-MIG-PTY"></a>

### Controlled PTY migration evidence

Issue #54 also requires a few interactive migration cases, run only through a
controlled PTY harness. This evidence is **migration evidence only**: it never
makes a reference shell normative, and it does not claim interactive
compatibility. Only a small set of deterministic behaviors is compared.
Shell-specific line editing, key bindings, completion, history, prompt
decoration, themes and cursor positioning are out of scope.

- **Corpus.** `tests/differential/pty-cases-v1.json` holds PySH-owned PTY cases,
  each with a stable ID (`pty-...`), a documentation anchor below, the exact
  payload lines and exit status an interactive session must produce, and the
  shells it applies to. #48 defines no interactive behavior, so these cases have
  their own IDs and anchors and are kept visibly separate from the 84 command
  mappings in `migration-v1.json`, which are unchanged.
- **Harness.** `tests/differential/pty_lab.py` reuses the repository PTY helper
  (`scripts/pty_smoke.py`, extended with opt-in controls). The reference runs by
  explicit absolute path with a from-scratch environment, a private `HOME` with
  hostile startup files, the same user-startup-isolation flags as the command
  laboratory plus interactive flags, a fixed `PTY> ` prompt, a fixed 24x200
  window, `TERM=dumb`, at most 512 bytes of input, a 25-second wall-clock
  timeout and 64 KiB of captured output. The child is a session leader with the
  PTY as controlling terminal, and its whole process group is SIGKILLed before the
  leader is reaped on every exit path.
- **Normalization.** Exactly: ANSI/OSC escape sequences are removed, CRLF becomes
  LF, a carriage-return redraw keeps its final text, the configured `PTY> ` prompt
  is stripped from the start of a line, and only lines beginning with
  `PYSH-PTY:` then count as output. Prompts, echoed input and editor redraws never
  take part. Comparison is exact on the exit status and the payload lines.
- **Classification.** PySH runs first and must satisfy the case; a violation is a
  `REGRESSION` and the reference is not run. A reference that satisfies the case
  is a `MATCH` (no mapping is needed: the expectation is PySH-owned). A difference
  is an `INTENDED_DIVERGENCE` only when `pty-cases-v1.json` registers it with a
  `PYSH-MIG-DIV-*` anchor; otherwise it is unreviewed and fails CI. No PTY
  divergence is registered.
- **Evidence.** The same per-platform evidence file carries a `pty_records` list
  per profile, separate from `records`, with the platform, pinned profile and
  version, PTY case ID, normalized observations, classification and anchors.

<a id="PYSH-MIG-PTY-ROUNDTRIP"></a>
**`pty-prompt-roundtrip`** (Bash, Zsh, Fish): a prompt appears, one submitted
command prints its output, and end of input ends the session with status 0.

<a id="PYSH-MIG-PTY-SUBMISSION"></a>
**`pty-submission-order`** (Bash, Zsh, Fish): two commands submitted with Return
run once each, in order.

<a id="PYSH-MIG-PTY-QUOTING"></a>
**`pty-quoted-argument`** (Bash, Zsh, Fish): a double-quoted argument keeps its
inner whitespace.

<a id="PYSH-MIG-PTY-ENVIRONMENT"></a>
**`pty-exported-variable`** (Bash, Zsh): a variable exported at the prompt is
visible to a later command. Fish is not selected because its variable syntax
differs.

<a id="PYSH-MIG-PTY-EXIT"></a>
**`pty-explicit-exit-status`** (Bash, Zsh, Fish): `exit 7` ends the session with
status 7.

<a id="PYSH-MIG-PTY-EOF"></a>
**`pty-end-of-input-exits-cleanly`** (Bash, Zsh, Fish): Ctrl-D at an empty prompt
ends the session with status 0.

<a id="PYSH-MIG-EVIDENCE"></a>

## Evidence record

A future release evidence record contains: PySH commit/version, platform,
case ID, legacy profile, legacy tool version, PySH observation, legacy
observation, classification, and contract anchors. Its identity never
includes `HOME`, absolute personal paths, the environment, secrets, or a
timestamp.
