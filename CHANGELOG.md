<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: CHANGELOG.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Changelog

All notable changes to PySH are documented in this file.

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
- Updated startup banner: PySH version, Python version, GPL-3.0 license tag,
  and system summary line.

### Known limitations

- `secure <cmd>` uses fork/PTY and emits pytest DeprecationWarning under
  threaded pytest.
- Bracketed paste is handled safely as byte stream; polish remains future work.
- TAB inside Python command mode inserts four spaces only (no symbol completion).
- Viewport bottom padding without scrollback pollution is deferred.
