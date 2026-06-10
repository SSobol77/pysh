<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/issues/66-powershell-launch-and-compatibility-layer.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PowerShell Launch and Compatibility Layer

**Track:** Platform Expansion · **Milestone:** post-1.0 candidate
**Status:** new · **Type:** feasibility-gated (blocked by a "go" decision in #65)
**Depends on:** #65 (go decision), #57 (platform tier contract), #36 (line editor)
**Related:** #67 (path/environment translation), #68 (VSCode integration)

## Product Statement

PySH remains a Python-first shell for Unix-like systems. On Windows, the
supported path today is WSL2 with full PySH semantics and, after
unification, the native ECLI workbench in preview mode with delegated
execution. A native Windows execution layer is subject to a feasibility
study (#65) and is not part of any 1.x compatibility promise. PySH does
not claim POSIX, Bash, or PowerShell compatibility on any platform.

## Goal

Define how PySH is *launched from* PowerShell and Windows Terminal — and
nothing more. "Compatibility layer" here means compatibility of the
launch experience, terminal capabilities, and diagnostics with the
Windows console environment. It does **not** mean PowerShell language
compatibility, cmdlet interop, or making PySH "Bash for Windows".

This entire issue is inert until #65 concludes with a **go** decision.
If #65 concludes no-go, this issue is closed as not-planned and the
documented Windows path remains WSL2 + VSCode (#68) plus the
preview-only ECLI workbench.

## Background

Windows users encounter PySH from a PowerShell prompt or a Windows
Terminal profile. Today the correct outcome of typing `pysh` on native
Windows is a clear, honest answer — not a degraded shell that silently
violates the #36 invariants. The feasibility study (#65) determines
whether a native execution layer behind that launch is ever built; this
issue specifies the launch boundary either way the engineering lands,
but is only worth implementing if native execution is approved.

## Scope

### 1. Launch experience

* `pysh` invoked from PowerShell or Windows Terminal starts the native
  PySH session defined by the #65-approved scope;
* a documented Windows Terminal profile fragment and PowerShell launch
  examples that are copy-paste safe;
* startup honors the #52 cold-start budget on the tier assigned by #57.

### 2. Terminal capability detection

* detect ConPTY / Windows Terminal capabilities at startup
  (bracketed paste, ANSI/VT processing, resize reporting);
* capability detection is deterministic and inspectable (a diagnostics
  command reports what was detected and why);
* legacy `conhost` and capability-deficient consoles get an explicit,
  documented behavior: refuse with a clear `pysh: terminal: ...`
  diagnostic, or degrade along a *documented* ladder — never silent
  partial behavior.

### 3. Invariant preservation at the boundary

* paste never auto-executes, on ConPTY exactly as on POSIX PTYs;
* Ctrl+C recovers the prompt; console control events map to the
  documented exit-code contract as scoped by #65;
* terminal state restore on every exit path, using the Windows-native
  restore semantics defined in #65;
* no PowerShell syntax acceptance, no cmdlet passthrough, no profile
  (`$PROFILE`) evaluation — PySH semantics are the same on every
  platform it runs on.

### 4. Honest failure on unsupported configurations

* when the environment cannot support the invariants, PySH must say so
  and point to the supported path (WSL2 + #68) instead of limping;
* the refusal path is itself tested behavior, not an afterthought.

## Non-Goals

* No PowerShell language, alias, cmdlet, or object-pipeline
  compatibility, and no POSIX or Bash compatibility claims.
* No execution-layer design beyond what #65 approved; this issue does
  not expand the native scope.
* No path/environment translation logic (that is #67).
* No duplication of the unification track: the ECLI bridge, unified
  launcher, monorepo, shared contracts, preview-only boundary, terminal
  ownership, and the `wb` launcher remain in #60–#64.
* No changes to the canonical packaging names.
* Nothing in this issue enters a 1.x compatibility promise.

## Automated Testing Requirements

(Apply only if implemented, i.e., after a #65 go decision.)

* capability detection matrix tests (Windows Terminal, ConPTY, legacy
  console stub);
* refusal-path tests: unsupported console produces the documented
  diagnostic and exit code, with no terminal-state damage;
* bracketed-paste no-auto-execute regression on ConPTY;
* Ctrl+C prompt-recovery and exit-code tests under the #65 mapping;
* launch smoke tests wired into whatever CI tier #57 assigns Windows.

## Manual Validation Requirements

On Windows 11 with Windows Terminal and with PowerShell 7+: launch,
paste (small, multiline, control-sequence payloads), Ctrl+C, exit/quit,
resize during editing, and the documented refusal path on a legacy
console.

## Definition of Done

* #65 gate respected: either implemented per the go scope, or closed as
  not-planned with the WSL2 path documented as the Windows answer.
* Launch from PowerShell / Windows Terminal behaves deterministically;
  unsupported environments refuse with clear diagnostics.
* No PowerShell/POSIX/Bash compatibility claim appears in code, docs,
  or diagnostics.
* Docs include copy-paste-safe launch instructions and the explicit
  product statement above.
