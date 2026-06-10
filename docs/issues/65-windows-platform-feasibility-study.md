<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/issues/65-windows-platform-feasibility-study.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Windows Platform Feasibility Study

**Track:** Platform Expansion · **Milestone:** post-1.0 candidate
**Status:** new · **Type:** research / decision (no runtime code)
**Depends on:** #36 (line editor invariants), #57 (platform tier contract)
**Gates:** #66, and the native-execution portions of #67

## Product Statement

PySH remains a Python-first shell for Unix-like systems. On Windows, the
supported path today is WSL2 with full PySH semantics and, after
unification, the native ECLI workbench in preview mode with delegated
execution. A native Windows execution layer is subject to a feasibility
study (#65) and is not part of any 1.x compatibility promise. PySH does
not claim POSIX, Bash, or PowerShell compatibility on any platform.

## Goal

Decide, with evidence, whether a native `pysh.exe` running inside
PowerShell / Windows Terminal is worth the engineering cost — or whether
the WSL2 + VSCode path plus the preview-only ECLI workbench is the
permanent Windows story.

This issue produces a written go / no-go decision. It does not produce
runtime code, and no outcome of this study creates a 1.x compatibility
promise.

## Background

PySH's interactive invariants (#36) and platform tier contract (#57) are
specified against POSIX terminal semantics: termios, PTYs, signals
(`SIGINT`, `SIGTSTP`, `SIGCONT`, `SIGWINCH`), `fork`/`exec` argv
execution, and POSIX exit codes. Windows offers none of these natively;
it offers ConPTY, a different signal and console-event model,
`CreateProcess` with a single command-line string, and different path
and environment semantics.

The current supported Windows path is WSL2 (full PySH semantics inside a
Debian environment) accessed through Windows Terminal or the VSCode
integrated terminal (#68). The unification track (#60–#64) adds a native
ECLI workbench that can run on Windows in preview / author / diagnose
mode with delegated execution; that track is specified in
`ROADMAP-v1-2.md` and is **not** re-scoped here.

The open question is only whether a *native execution layer* — PySH
itself executing commands on Windows, outside WSL2 — is feasible without
weakening the determinism, terminal-state, and security invariants that
define the project.

## Scope

### 1. Terminal layer feasibility

Assess against the #36 invariants, each with a written verdict
(supported / supportable with bounded effort / not supportable):

* ConPTY capabilities vs. the raw-mode editor: bracketed paste, redraw,
  cursor addressing, resize notification (no `SIGWINCH`), wide-character
  and combining-mark rendering in Windows Terminal;
* terminal state save/restore semantics without termios — what
  "deterministic restore on every exit path" means on a Windows console;
* Ctrl+C / Ctrl+Break console events vs. the `SIGINT` recovery and exit
  code 130 contract;
* absence of `SIGTSTP`/`SIGCONT` (no job control) and what that removes
  from the UX contract;
* behavior in legacy `conhost`, and whether legacy consoles are declared
  out of scope.

### 2. Execution layer feasibility

* argv-list execution vs. `CreateProcess` single-string command lines:
  whether the "explicit argv, no `shell=True`" invariant survives
  Windows quoting rules (`cmd.exe` is out of the question; direct
  `CreateProcess` quoting must be deterministic and tested);
* exit code semantics: mapping the POSIX contract (`0/1/2/126/127/130`)
  onto Windows process exit codes, and which guarantees cannot be kept;
* `PATH` / `PATHEXT` resolution and the command-not-found (127) and
  permission-denied (126) distinctions;
* subprocess interruption and cleanup semantics without POSIX signals.

### 3. Filesystem and environment differences

Catalog (as input to #67, not solved here): path separators, drive
letters, UNC paths, case-insensitivity, reserved names, line endings,
environment variable casing, and home/config directory conventions
(`%APPDATA%` vs. `~/.config`).

### 4. Packaging and distribution

Sketch only — distribution channel (PyPI wheel vs. MSIX vs. scoop/winget),
Python 3.13+ availability on Windows, and how the packaging naming
contract (`pysh-shell` / `pysh`) extends without changes to the existing
canonical names.

### 5. Cost / risk assessment and decision

* engineering cost estimate per layer (terminal, execution, paths,
  packaging, CI);
* CI cost: a Windows lane for the differential/regression suites
  (#53/#59) and what tier (#57) Windows could honestly occupy;
* enumerate which PySH invariants would have to be weakened, scoped, or
  dropped on native Windows — any invariant weakening is a strong signal
  toward no-go;
* explicit comparison against the WSL2 baseline: what user-visible value
  native execution adds that WSL2 + VSCode (#68) and the preview-only
  ECLI workbench do not already deliver.

## Deliverables

* `docs/development/windows-feasibility.md` — the study, with one
  verdict per section above and exact evidence (prototype notes are
  allowed; prototype code is not merged);
* a go / no-go / defer recommendation with the conditions under which
  the decision should be revisited;
* if **go**: a proposed platform tier for Windows under #57 and a scoped
  issue list (starting with #66);
* if **no-go**: the documented permanent Windows story (WSL2 + #68 +
  preview-only ECLI workbench) and closure of #66 as not-planned.

## Non-Goals

* No runtime code, no merged prototypes, no Windows CI lane in this
  issue.
* No POSIX, Bash, or PowerShell compatibility claims on any platform.
* No re-scoping of the unification track (#60–#64); delegated execution
  and the preview-only boundary stay where they are specified.
* No changes to the v1.0.0 critical path (#36, #49–#59) or to the
  v1.1.0/v1.2.0 feature issues (#37–#48).
* No packaging-name changes; the canonical naming contract is untouched.

## Definition of Done

* The feasibility report exists with a verdict per scope section and a
  single go / no-go / defer recommendation.
* Every #36 invariant has an explicit Windows verdict; none is silently
  skipped.
* The decision states clearly that no 1.x compatibility promise is
  created either way.
* #66 is either unblocked (go) or closed as not-planned (no-go), and
  #67's scope is annotated with which translation targets are live.
