<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/limitations.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Limitations

PySH is a Python-first shell with a deliberately bounded compatibility
surface. The goal is reliable interactive use and safe migration, not full
emulation of POSIX sh, bash or zsh.

> **Full compatibility contract**: see the
> [compatibility documentation](../compatibility/README.md) for the complete
> per-feature matrix, scope tables, unsupported-construct list, and validation
> plan. This page summarizes the most important non-goals.

## POSIX shell compatibility

PySH is not a full POSIX shell. It implements the operators and builtins
documented in this repository, but it does not implement the complete POSIX
grammar, expansion model or script execution semantics.

See the [POSIX sh scope document](../compatibility/posix-sh-scope.md)
for the complete POSIX sh scope table and prohibition on `/bin/sh` use.

## zsh compatibility

PySH is not a full zsh clone. The Zsh Transition Layer provides static alias
and profile import plus explicit delegation to real zsh. zsh-specific
features remain the responsibility of real zsh when delegated.

See the [zsh scope document](../compatibility/zsh-scope.md) for the
complete zsh scope table.

## Security model

PySH is not sandboxed and does not provide privilege separation or capability
confinement.  Key security properties:

- Foreign shell profiles (`.zshrc`, `.bashrc`) are **not** executed automatically.
  `source_zsh`, `source_zsh_profile`, and `source_sh_aliases` parse files as plain
  text and import only safe static constructs.
- `zsh_fallback` is **off by default**. Delegation to zsh requires explicit opt-in.
- Normal external commands inherit the terminal. PySH does not observe password
  bytes for `sudo`, `ssh`, `su`, or `gpg`.
- The `secure <cmd>` PTY bridge is opt-in and non-default.
- `py`, `py { ... }`, and `#py` execute Python in-process with full OS access.
  They are not sandboxed.

Full documentation: [Security and Trust Model](../architecture/security-trust-model.md).

## Signal handling

PySH implements deterministic signal handling for three execution contexts:

- **Line editor**: Ctrl+C cancels the current input line, restores terminal
  state, and sets `$?` to 130. The shell does not exit.
- **External command**: Ctrl+C interrupts the foreground child. PySH sets
  `$?` to 130. Signal-killed children (SIGTERM etc.) map to `128 + signum`.
- **Python (`py` builtin)**: `KeyboardInterrupt` maps to exit status 130
  without printing a traceback.

SIGTERM received by PySH outside a child command causes clean process
termination via OS default disposition. Terminal state is restored by
`atexit` handlers where possible.

See the [Signal-Handling Architecture](../architecture/signal-handling.md)
document for the full signal contract.

## Job control

PySH does not implement job control:

- no background execution with `&`,
- no `jobs`,
- no `bg`,
- no `fg`,
- no `Ctrl+Z` (SIGTSTP) job suspension.

Ctrl+Z at an interactive prompt may suspend the PySH process using the OS
default `SIGTSTP` disposition. This is safe but provides no job-control
features. Full job control is planned for Issue #11.

## Glob expansion

PySH performs native glob expansion for unquoted arguments (Issue #9):

- `*.py` expands to matching `.py` files in the current directory.
- `?` matches a single character; `[abc]` matches a character class.
- `**/*.py` expands recursively across subdirectories.
- `~` and `~/path` are expanded via tilde expansion.
- No-match default: if a pattern matches nothing, the literal pattern is passed.
- `*` does NOT match names beginning with `.`; use `.*` to match dotfiles.
- Single-quoted and double-quoted patterns remain literal.
- Backslash-escaped metacharacters (`\*`, `\?`) remain literal.

Brace patterns such as `{a,b}` are passed literally; PySH does not perform
brace expansion.

## Shell grammar

The native parser supports documented chains, pipelines, redirection,
here-documents, here-strings, command substitution, `$NAME`, `${NAME}`, `$?`,
quote handling and backslash-newline continuation. It does not support process
substitution, shell arrays, shell functions, case statements, arithmetic
expansion or advanced parameter expansion.

Parser-owned unsupported constructs such as `$((expr))`, `(( expr ))` and
`let` return a parse diagnostic with status 2. Heredoc parse errors such as a
missing delimiter word or missing terminator also return status 2.

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
as a broad zsh compatibility claim.

## Python runtime

`py <code>` supports one-line Python execution in a persistent session
context. PySH includes multiline `py { ... }` blocks that share the same
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
