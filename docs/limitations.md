<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Limitations

PySH is a Python-first shell with a deliberately bounded compatibility
surface. The goal is reliable interactive use and safe migration, not full
emulation of POSIX sh, bash or zsh.

## POSIX shell compatibility

PySH is not a full POSIX shell. It implements the operators and builtins
documented in this repository, but it does not implement the complete POSIX
grammar, expansion model or script execution semantics.

## zsh compatibility

PySH is not a full zsh clone. The Zsh Transition Layer provides static alias
and profile import plus explicit delegation to real zsh. zsh-specific
features remain the responsibility of real zsh when delegated.

## Job control

PySH does not implement job control in 0.2.2:

- no background execution with `&`,
- no `jobs`,
- no `bg`,
- no `fg`,
- no `Ctrl+Z` job suspension management.

## Glob expansion

PySH does not perform native glob expansion for plain command execution.
Arguments such as `*.py` are passed as literal arguments unless a delegated
interpreter or external command performs its own expansion.

## Shell grammar

The native parser supports documented chains, pipelines, redirection,
command substitution, variable expansion and quote handling. It does not
support here-documents, process substitution, shell arrays, shell functions,
case statements, arithmetic expansion or brace expansion.

## Static zsh/sh import

`source_zsh`, `source_zsh_profile` and `source_sh_aliases` are static import
helpers. They do not execute files and intentionally skip unsupported
constructs including `eval`, command substitution, dynamic `source`, plugin
managers, arrays and shell functions.

## Script transition runner

`run_script` delegates shebang scripts to real `zsh`, `bash` or `sh` when
declared. A no-shebang script is executed line-by-line through PySH's native
engine where possible. That native path is not full POSIX script semantics.

## Fallback mode

`zsh_fallback on` may delegate commands PySH cannot parse or execute
natively. It is a migration aid and is off by default. It should not be used
as a claim that PySH is zsh-compatible.

## Python runtime

`py <code>` supports one-line Python execution in a persistent session
context. PySH 0.3.0 adds multiline `py { ... }` blocks that share the same
persistent context. Limitations:

- Nested `py { ... }` blocks are not supported.
- The opener must be a line whose stripped form is exactly `py {`.
- The closer must be a line whose stripped form is exactly `}`.
- Unterminated blocks in script mode return non-zero and do not execute
  any partial body.

## Debian/system profile helpers

`sys_info`, `env_audit`, `path_audit`, `which_all`, `apt_check` and
`apt_search` are non-mutating diagnostic helpers:

- `apt_check` and `apt_search` require `apt` to be installed; they return
  127 deterministically when `apt` is missing.
- These helpers never call `sudo` and never modify system state.
- Secret redaction in `env_audit` is name-based; values whose key does not
  match a sensitive token are not treated as secrets.

## Command planning

`plan <command...>` is advisory only:

- It classifies the command into a kind / execution / risk triple and
  prints a reason line.
- It never executes the planned command.
- It never modifies aliases, env vars, the working directory or files.
- The risk model is coarse; a `low` classification is not a security
  clearance.
- Policy enforcement based on `plan` output is intentionally planned for a
  later release.

## Service helper

The `svc` builtin uses PID files and optional PyInit control integration. It
is not a complete replacement for systemd or another production supervisor.
