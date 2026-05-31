<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/roadmap.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Roadmap

This document lists planned and possible future work for PySH. Items are
subject to change based on project priorities and user feedback.

## v0.5.0 (current)

- Python Command Execution Layer (`#py` interactive mode).
- Shell-style comments (`#` at token boundary).
- Python-native `~/.pyshrc.py` auto-generation.
- Raw-mode line editor with syntax highlighting and autosuggestions.
- Configurable prompt colors and terminal cursor color.
- Explicit `secure <cmd>` PTY runner with fixed-size ring indicator.
- `uv`-based dev workflow.

## Planned future work

### Python Command Execution Layer

- Python symbol completion on TAB inside `#py` mode.
- Syntax highlighting in the Python prompt.
- Source buffer line editing directives (`#insert`, `#delete`, `#replace`).
- Optional session persistence across `#reset` / `#exit` cycles.
- Integration with the `py` builtin runtime as an opt-in.

### Shell features

- Job control (`&`, `bg`, `fg`, `jobs`, `Ctrl+Z`).
- Glob expansion (`*`, `?`, `[...]`) native to PySH.
- `~user` home directory expansion.
- Here-documents and here-strings.
- Shell functions (`function_name() { ... }`).
- Arithmetic expansion `$((...))`.
- Associative arrays.

### Editor

- Bracketed paste polish.
- Configurable key bindings.
- Multi-line editing for long commands.

### Configuration

- Typed `~/.pyshrc.py` API for all shell settings in one place.
- Plugin registry with versioned interfaces.

### Platform

- macOS testing and validation.
- FreeBSD testing and validation.

### Tooling

- Automated release CI from `publish.yml` through GitHub Trusted Publishing.
- Debian and RPM package publishing in CI.
