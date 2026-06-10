<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/issues/67-cross-platform-path-and-environment-translation.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Cross-Platform Path and Environment Translation

**Track:** Platform Expansion · **Milestone:** post-1.0 candidate
**Status:** new · **Type:** specification + library (no shell runtime changes)
**Depends on:** #57 (platform tier contract); consumes the difference
catalog from #65 · **Related:** unification track #60–#64 (delegated
execution), #66, #68

## Product Statement

PySH remains a Python-first shell for Unix-like systems. On Windows, the
supported path today is WSL2 with full PySH semantics and, after
unification, the native ECLI workbench in preview mode with delegated
execution. A native Windows execution layer is subject to a feasibility
study (#65) and is not part of any 1.x compatibility promise. PySH does
not claim POSIX, Bash, or PowerShell compatibility on any platform.

## Goal

Specify deterministic, explicit, preview-visible translation of paths
and environment values between a Windows host and the POSIX environment
that actually executes commands (WSL2 today; remote execution after
unification). Translation is a service used at the delegation boundary —
it is never a hidden rewrite inside PySH command execution.

## Background

In the supported Windows model, authoring can happen on the Windows side
(VSCode, the future native ECLI workbench in preview mode) while
execution is delegated into WSL2 or a remote POSIX host. Anything that
crosses that boundary — file arguments, working directories,
environment variables — exists in two coordinate systems:
`C:\Users\dev\project` vs. `/mnt/c/Users/dev/project`, `%USERPROFILE%`
vs. `$HOME`, CRLF vs. LF, case-insensitive vs. case-sensitive names.

The unification track already fixes *where* execution happens
(`CommandPlan` is inert; only `ExecutorService` executes — #61/#62).
This issue fixes *what the data looks like* when a plan authored on
Windows is executed in a POSIX environment. It adds no execution
authority and does not modify the #60–#64 boundary.

## Scope

### 1. Path translation rules

* Windows → WSL2 path mapping (drive letters to `/mnt/<drive>/...`),
  consistent with `wslpath` observable behavior, including UNC paths
  (`\\wsl.localhost\...`) and their inverses;
* explicit failure for untranslatable paths (unmapped drives, reserved
  device names, paths that exist only on one side) — translation either
  succeeds deterministically or fails with a structured diagnostic;
  no silent guessing, no heuristic "best effort";
* case-sensitivity hazards are flagged, not papered over: a translation
  that would collide under case-insensitive semantics is reported;
* normalization rules (separators, trailing separators, `.`/`..`
  resolution) are written down and total — every input has exactly one
  documented outcome.

### 2. Environment translation rules

* an explicit allow-listed mapping table (e.g. `USERPROFILE` ↔ `HOME`,
  `TEMP` ↔ `TMPDIR`, `Path` ↔ `PATH`), with everything outside the
  table passed through untouched or dropped per documented policy —
  never transformed implicitly;
* variable-name casing policy across the boundary is explicit;
* `PATH`-like list values are translated entry-wise with the path rules
  from scope 1, with per-entry failure reporting;
* secrets and sensitive values are never logged by the translation
  layer (consistent with the #55 redaction schema).

### 3. Preview visibility

* every translation applied at a delegation boundary is visible in the
  plan preview: original value, translated value, and the rule that
  produced it;
* denied or failed translations are part of the preview, so the user
  sees what will *not* cross the boundary before anything executes;
* this is data presented through existing #61/#62 surfaces; this issue
  does not add new execution or preview authority.

### 4. Library shape

* a pure, side-effect-free module: no filesystem probing required for
  rule evaluation (existence checks, where needed, are explicit and
  separate from mapping logic);
* fully testable on any platform — Linux CI must exercise the complete
  rule table without a Windows host;
* versioned rule table so behavior changes are visible in diffs and
  release notes.

## Non-Goals

* No automatic line-ending conversion of file contents.
* No translation inside native PySH command execution on Unix-like
  systems — POSIX-to-POSIX execution is untouched.
* No duplication of #60–#64: `CommandPlan`, `ExecutorService`, the
  preview-only boundary, and delegated execution stay where they are
  specified; this issue only defines the data transformation they use.
* No native Windows execution semantics; if #65 concludes go, the
  native targets are added then — nothing here presumes that outcome.
* No POSIX, Bash, or PowerShell compatibility claims.

## Automated Testing Requirements

* property-style round-trip tests for every reversible mapping rule;
* exhaustive table tests: drive letters, UNC, relative paths, reserved
  names, unmapped drives, case-collision inputs, empty and degenerate
  inputs;
* environment mapping tests: allow-list hits, pass-through, drops,
  `PATH`-list entry-wise translation and partial failure;
* failure-path tests: every untranslatable input yields the documented
  structured diagnostic, never a guessed value;
* redaction test: sensitive values do not appear in diagnostics or logs;
* all of the above run on Linux CI with no Windows dependency.

## Manual Validation Requirements

On a Windows 11 + WSL2 (Debian) host: spot-check the rule table against
real `wslpath` output for representative paths (drive, UNC, unmapped
drive failure), and verify preview output shows original, translated,
and rule for each value.

## Definition of Done

* The rule table is specified, versioned, total, and documented.
* Translation is deterministic: same input, same output, every time;
  untranslatable input fails loudly with structured diagnostics.
* Every boundary translation is preview-visible before execution.
* Tests pass on Linux CI without a Windows host; manual WSL2 spot-check
  recorded.
* No change to PySH native execution paths and no new execution
  authority anywhere in the translation layer.
