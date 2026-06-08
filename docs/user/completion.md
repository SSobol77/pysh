<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/completion.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Completion

PySH Completion Engine 2.0 provides deterministic TAB completion for daily
interactive use. Completion is stdlib-only, local, and non-executing.

## What Completes

At command position, PySH completes:

- builtins;
- aliases;
- executable commands discovered from `PATH`;
- local paths.

In argument position, PySH completes paths by default. After `cd` and `pushd`,
only directories are completed. After `fg` and `bg`, job IDs are completed when
jobs are available.

Environment variables complete as `$VAR` and `${VAR}`. Values are never shown.

Python command mode completes symbols from the active Python Command Execution
Layer namespace when completion is safe. If no Python-symbol candidate is
available, TAB inserts four spaces for Python indentation.

## Repeated TAB

TAB behavior is deterministic:

1. One candidate inserts immediately.
2. Multiple candidates with a longer common prefix insert that prefix.
3. Pressing TAB again displays a labeled candidate menu.
4. Typing any non-TAB key resets the repeated-TAB state.

Candidate menus are displayed above a clean prompt redraw and do not modify the
current input buffer.

## Path Rules

Directories append `/`. Hidden entries are offered only when the typed path
component begins with `.`. Paths with spaces are escaped in unquoted input and
preserved in quoted input. Unicode path names are supported.

If there are no matches, PySH leaves the input buffer unchanged.

## Safety

Completion never executes candidate commands, never reads Bash/Zsh/Fish
completion scripts, never performs network calls, and never imports arbitrary
user modules. Python dotted completion avoids property and `__getattr__`
side effects.
