<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: CHANGELOG.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Changelog

All notable changes to PySH are documented in this file.

## 0.6.0 - 2026-06-04

- Added the parser, expansion and multiline grammar foundation:
  - Quote-aware parser primitives now provide a stronger contract for command
    chains, pipelines, continuations, unsupported syntax and parse errors.
  - Expansion behavior is documented and tested for the supported PySH-native
    subset.
- Added native glob and path expansion:
  - Tilde, relative path and glob expansion are handled inside PySH without
    shell delegation.
  - Dotfile and no-match behavior are documented and test-backed.
- Added here-documents and here-strings for PySH command execution.
- Added job control and process-group handling:
  - Background execution, `jobs`, `fg` and `bg` are implemented for the
    documented POSIX job-control subset.
- Added Completion Engine v1:
  - Completion covers builtins, aliases, PATH commands, filesystem paths,
    variables and jobs.
- Added observability and diagnostics:
  - `--debug` and `--trace` emit structured stderr diagnostics.
  - Diagnostic output applies redaction for sensitive values.
- Added Script Mode v1:
  - `pysh script.pysh [args...]` and `python -m pysh script.pysh [args...]`
    execute explicit PySH-native scripts.
  - Script mode supports positional parameters, heredocs, glob expansion,
    Python blocks and deterministic exit-status behavior.
- Migrated project licensing metadata and headers to GPL-2.0-only.
- Reorganized architecture, compatibility, user and development documentation
  around explicit contracts and validation evidence.

### Compatibility boundary

- PySH remains PySH-native.
- PySH is not a POSIX `/bin/sh` replacement.
- PySH is not zsh-compatible or bash-compatible.
- Foreign-shell migration and delegation paths remain explicit and scoped.

## 0.5.0

- Added Python-native `~/.pyshrc.py` generation on first launch.
- Added production-commented `~/.pyshrc.py` template.
- Added full two-line prompt with tool/version segments.
- Added configurable prompt colors with VGA/truecolor support.
- Added configurable terminal cursor color.
- Added stdlib raw-mode line editor.
- Added live syntax highlighting.
- Added fish-style history autosuggestions.
- Added prefix-filtered TAB completion fixes.
- Added ANSI-safe cursor positioning for colored prompts.
- Added explicit `secure <cmd>` PTY runner.
- Added fixed-size sensitive-input ring indicator.
- Added shell-style comments with unquoted `#`.
- Added uv.lock/dev dependency workflow.
- Added header checker.
- Added Python Command Execution Layer (`#py`):
  - Interactive Python REPL with persistent runtime state.
  - IDLE-like multi-line block input with auto-indentation.
  - Blank Enter closes a complete block (CPython REPL semantics).
  - Syntax highlighting via Pygments across all Python mode views.
  - File-backed edit workspace: `#open`, `#save`, `#show`, `#run`, `#clear`,
    `#reset`, `#edit`, `#insert`, `#replace`, `#delete`.
  - Path expansion for `~`, relative, and absolute paths.
  - TAB completion for file directives; TAB inserts four spaces in code.
  - Safe source-buffer policy: only successfully executed input is saved.
  - Saved files contain clean Python source — no prompts, no ANSI escapes.
- Added `system_info` helper for compact startup banner (`System:` line).
- Updated startup banner: PySH version, Python version, GPL-2.0-only license tag,
  and system summary line.

### Known limitations

- `secure <cmd>` uses fork/PTY and emits pytest DeprecationWarning under
  threaded pytest.
- Bracketed paste is handled safely as byte stream; polish remains future work.
- TAB inside Python command mode inserts four spaces only (no symbol completion).
- Viewport bottom padding without scrollback pollution is deferred.
