<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/issues/68-vscode-terminal-integration.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# VSCode Terminal Integration

**Track:** Platform Expansion · **Milestone:** post-1.0 candidate
**Status:** new · **Type:** integration + documentation
**Depends on:** #36 (line editor invariants), #32 (shell integrations pack)
**Related:** #57 (platform tiers), #65–#67, unification track #60–#64

## Product Statement

PySH remains a Python-first shell for Unix-like systems. On Windows, the
supported path today is WSL2 with full PySH semantics and, after
unification, the native ECLI workbench in preview mode with delegated
execution. A native Windows execution layer is subject to a feasibility
study (#65) and is not part of any 1.x compatibility promise. PySH does
not claim POSIX, Bash, or PowerShell compatibility on any platform.

## Goal

Make PySH a first-class shell inside the VSCode integrated terminal on
Linux, FreeBSD, and — via the Remote - WSL extension — on Windows. This
is the *current supported Windows path*: VSCode on Windows, connected to
WSL2, running real PySH with full semantics. The issue covers terminal
profile setup, VSCode shell-integration support, and documentation; it
does not create an extension, an execution bridge, or any new execution
surface.

## Background

VSCode's integrated terminal is where many users will first meet PySH,
and on Windows it is the front door to the supported WSL2 path. VSCode
offers shell integration through documented escape sequences (OSC 633 /
OSC 133 prompt and command markers) that enable command decorations,
command navigation, exit-code indicators, and working-directory
tracking. Bash, zsh, and fish ship integration scripts; PySH currently
relies on whatever VSCode detects heuristically.

The #32 shell integrations pack already owns the pattern of explicit,
opt-in integration artifacts. This issue extends that pattern to VSCode.
The future native ECLI workbench on Windows (unification track, #60–#64)
is unaffected: it remains preview / author / diagnose first, with
delegated execution through WSL2 or remote execution, and is specified
entirely in that track.

## Scope

### 1. Terminal profile documentation

* documented, copy-paste-safe VSCode `terminal.integrated.profiles.*`
  entries for Linux and FreeBSD;
* the Windows path documented end-to-end: install WSL2 (Debian), install
  PySH inside WSL2, use the Remote - WSL extension or a WSL terminal
  profile so PySH runs with full semantics inside the POSIX environment;
* explicit statement that this WSL2 + VSCode route *is* the supported
  Windows path today, with the product statement above embedded in the
  user docs.

### 2. VSCode shell integration sequences

* opt-in emission of the VSCode shell-integration markers (OSC 633, with
  OSC 133 fallback semantics where applicable): prompt start/end,
  command start/end, exit code, and working directory;
* emission is explicit configuration (consistent with the #32 opt-in
  doctrine and the #31 config model) — never auto-detected magic that
  changes output behind the user's back;
* markers must not violate #36: no interference with redraw, bracketed
  paste, reverse search, or multiline state; diagnostics remain visually
  distinct from editable input;
* clean degradation: when not enabled, or in a non-VSCode terminal, zero
  integration bytes are emitted.

### 3. Interactive invariants inside VSCode

* verify the #36 contract holds in the VSCode terminal (xterm.js):
  paste never auto-executes, multiline paste is contained, Ctrl+C
  recovers the prompt, Ctrl+D exits cleanly, resize reflows correctly;
* differences between the VSCode terminal and a plain PTY are recorded
  as documented behavior or filed as upstream issues — not silently
  absorbed.

### 4. Documentation

* a user-facing "PySH in VSCode" page covering Linux, FreeBSD, and the
  Windows/WSL2 route, with every command and settings fragment
  copy-paste safe;
* troubleshooting section: shell-integration not detected, profile not
  appearing, WSL2 distro selection.

## Non-Goals

* No VSCode extension and no editor-side code in this issue.
* No native Windows PySH execution and no promise of it in v1.0.0; the
  native execution question belongs to #65/#66 exclusively.
* No duplication of #60–#64: the ECLI bridge, unified launcher,
  monorepo, shared contracts, preview-only boundary, terminal ownership,
  and the `wb` launcher remain in the unification track.
* No POSIX, Bash, or PowerShell compatibility claims, and no attempt to
  make PySH "Bash for Windows".
* No always-on integration output; everything is opt-in.

## Automated Testing Requirements

* marker emission tests: enabled vs. disabled, exact byte sequences,
  correct exit codes in OSC 633 payloads, working-directory updates;
* zero-emission regression test when integration is disabled or the
  terminal is not VSCode;
* PTY tests proving markers do not corrupt redraw, paste capture, or
  reverse search (extends the #36 suites);
* docs consistency tests for the settings fragments and commands shown
  in the user docs.

## Manual Validation Requirements

* VSCode on Debian 13: profile setup, command decorations, command
  navigation, exit-code indicators, paste, Ctrl+C/Ctrl+D, resize;
* VSCode on Windows 11 + Remote - WSL (Debian): the full documented
  Windows path, end-to-end, exactly as the docs describe it;
* FreeBSD 14+ where VSCode tooling permits, otherwise via remote SSH
  workflow, with the result recorded.

## Definition of Done

* Shell-integration markers are available opt-in, emit correct
  sequences, and provably do not violate any #36 invariant.
* The "PySH in VSCode" documentation exists; every example is
  copy-paste safe; the WSL2 route is documented as the supported
  Windows path and carries the product statement verbatim.
* Disabled-state emits nothing; regression-locked.
* Manual validation on Debian and on Windows 11 + WSL2 recorded.
