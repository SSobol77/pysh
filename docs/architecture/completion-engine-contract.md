<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/completion-engine-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Completion Engine Contract (Issue #12)

This document defines Completion Engine v1 for PySH 0.5.x.

## Scope

Issue #12 implements PySH-native, non-executing TAB completion for builtin and
alias command names, executable command names found in `PATH`, filesystem
paths, directory-only contexts, variable names after `$` or `${`, and job IDs
after `fg` and `bg` when the current shell has jobs.

## Non-goals

Completion Engine v1 does not implement programmable bash, zsh, or fish
completion. It does not source foreign completion scripts, execute commands,
query the network, implement observability/trace CLI (#13), full script mode
(#14), zsh transition hardening (#16), or system shell integration (#17).

## Architecture

The pure engine lives in `pysh.editor.lineedit.completion`:

- `CompletionContext` describes cursor, token, quote, variable, command and
  job context.
- `CompletionCandidate` carries insertion text, display text and kind.
- `CompletionKind` classifies builtin, command, path, directory, variable and
  job candidates.
- `CompletionOptions` passes immutable snapshots of builtins, aliases,
  variables, PATH, cwd and job IDs.
- `CompletionResult` carries candidates plus replacement boundaries.
- `CompletionEngine` generates candidates without mutating shell state.

`pysh.editor.completion.Completer` is the interactive adapter for readline and
the raw line editor. The shell passes aliases, local variables and job IDs via
callbacks. The canonical builtin-name set is data-only in
`pysh.contracts.builtins`; completion does not import `pysh.core.shell`.

## Candidate Policy

Builtin and alias candidates are offered at command position. External command
candidates are read from `PATH` directories, deduplicated, sorted, and filtered
to executable regular files. No command is run.

Path candidates list local directory entries only. Directories include a
trailing `/`; hidden entries are shown only when the typed prefix starts with
`.`. `~` and `~/` are expanded for lookup but preserved in the inserted
candidate. Completion does not glob-expand.

After `cd` and `pushd`, only directory candidates are returned. Redirection
targets use file/path completion.

Variable completion returns names only: `$HO` can complete to `$HOME`, and
`${HO` to `${HOME}`. Values are never displayed or inserted.

Job completion after `fg` or `bg` returns job IDs supplied by the current shell
job table. Without a provider, no job candidates are returned.

## Quote And Escape Policy

Completion context is quote-aware:

- single quotes suppress variable completion;
- double quotes allow variable completion and path insertion inside the quote;
- unquoted path candidates escape spaces and shell metacharacters with
  backslashes;
- quoted path candidates do not double-escape spaces;
- existing opening quotes are preserved.

## Line Editor Behavior

TAB on a single candidate inserts it. Non-directory candidates append a space;
directories do not. TAB on multiple candidates displays a deterministic list
using candidate display text, resets raw-editor row tracking, and redraws the
prompt on the next editor cycle. Paste handling does not trigger completion.

## Safety

Completion is fail-closed. Missing, unreadable or permission-denied
directories return no candidates. Completion performs no subprocess calls, no
shell startup-file execution, no foreign completion-script sourcing, no network
access and no shell-state mutation.

## Validation Matrix

| Claim | Evidence |
| ----- | -------- |
| Context parsing is command/argument/redirection/quote aware | `tests/test_completion_engine.py` |
| Builtins use one canonical source | `tests/test_completion.py` |
| PATH command completion is executable-only and deduplicated | `tests/test_completion_engine.py` |
| Path completion handles hidden files, `~`, spaces and quotes | `tests/test_completion_engine.py` |
| Directory-only completion after `cd` | `tests/test_completion_engine.py` |
| Variable completion returns names only | `tests/test_completion_engine.py` |
| Job completion uses supplied job IDs | `tests/test_completion_engine.py` |
| Raw line editor completion remains deterministic | `tests/test_lineedit_completion.py`, `tests/test_lineedit_reader_pty.py` |

## Issue Relations

| Issue | Relation |
| ----- | -------- |
| #8 | Parser-aware quote/token context without executing expansions |
| #9 | Shares tilde and hidden-file policy, but does not glob-expand |
| #11 | Job IDs are completion candidates for `fg`/`bg` |
| #13 | Completion remains non-executing; observability trace is opt-in and does not expose variable values |
| #14 | Full script mode remains out of scope |
| #16 | zsh transition hardening remains out of scope |
| #17 | System shell integration remains out of scope |
