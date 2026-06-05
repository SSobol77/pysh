<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/migration/zsh-compatibility.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Zsh compatibility and migration

> **Compatibility scope**: this document describes the zsh transition layer
> workflow. For the authoritative zsh compatibility scope table, see the
> [zsh scope document](../compatibility/zsh-scope.md). For the
> complete feature matrix, see the
> [feature matrix](../compatibility/feature-matrix.md).

PySH includes the **Zsh Transition Layer** and a safe profile
import path. The design goal is migration, not full zsh emulation:

- PySH remains a Python-first shell with its own native execution engine.
- zsh compatibility is explicit, deterministic and testable.
- Static alias/profile import never executes arbitrary zsh files.
- Real zsh may be used as an optional bridge when it is installed.
- Native PySH builtins and native command errors are not hidden by default.

## Migrating from zsh to PySH

PySH is Python-first, not a zsh clone. Treat migration as a configuration and
workflow rewrite, not as an attempt to run `.zshrc` unchanged.

Canonical PySH configuration lives in:

```sh
~/.pyshrc
~/.pyshrc.d/*.pysh
~/.pyshrc.py
```

PySH never automatically sources `.zshrc`, `.zprofile`, zsh completion
scripts or zsh plugin manager files. The plain `source` builtin rejects
standard zsh startup/profile files (`.zshenv`, `.zprofile`, `.zshrc`,
`.zlogin`, `.zlogout`) with an explicit diagnostic; use
`source_zsh_profile ~/.zshrc` only when you want the safe static importer for
simple aliases, exports and local assignments.

Common zsh user expectations map to PySH as follows:

| zsh expectation | PySH migration path |
| --- | --- |
| simple aliases | `source_zsh <file>` or `alias NAME='command'` in `~/.pyshrc` |
| `export NAME=value` | supported in `~/.pyshrc`; Python-native code may use `os.environ` |
| `cd` | supported as a PySH builtin |
| history | persistent PySH history; reverse search remains PySH-native |
| command completion | PySH-native builtin, alias, command and path completion |
| prompt virtualenv/git visibility | PySH prompt renders its own environment and git metadata |
| legacy zsh-only command | explicit `zsh '<command>'` delegation when real zsh is installed |
| shell-script rewrite | `migrate <file>` for Python-first analysis and guidance |

Unsupported zsh-specific syntax is diagnosed where PySH can identify it
conservatively:

```sh
${(f)PATH}
${name:u}
array=(one two)
${array[1]}
*(.)
**/*(.)
*(N)
PROMPT='%F{red}%~%f'
autoload -Uz compinit
compinit
setopt autocd
unsetopt autocd
```

Example diagnostics:

```text
pysh: unsupported zsh syntax: ${( ... )}
hint: PySH does not evaluate zsh parameter expansion. Use Python mode or explicit Python expressions.

pysh: unsupported zsh config command: compinit
hint: PySH does not run zsh completion initialization. Use PySH-native completion.

pysh: unsupported zsh config command: setopt
hint: PySH does not apply zsh shell options. Use PySH-native configuration in ~/.pyshrc.
```

Replacement guidance:

- Move stable shell configuration into `~/.pyshrc` using PySH-supported
  aliases, exports, variables and documented control flow.
- Move zsh arrays, parameter modifiers and prompt logic into Python-native
  code where possible.
- Replace zsh completion initialization with PySH-native completion.
- Use `source_zsh_profile` for static extraction from old profile files; it
  reads text and never executes plugin managers, command substitution or
  dynamic `source` lines.
- Use explicit `zsh '<command>'` only as a temporary bridge for commands that
  truly require zsh semantics.

## Safe alias import

Use `source_zsh <file>` to import simple zsh-compatible aliases into the
current PySH alias table:

```sh
source_zsh ~/.zsh_aliases
```

Supported forms:

```sh
alias ll='ls -lah'
alias gs="git status -sb"
alias update='sudo apt update && sudo apt upgrade'
alias grep=grep
```

Rules:

- Blank lines and comments are ignored.
- Unsupported zsh constructs are skipped.
- Malformed alias lines are reported on stderr with file and line number.
- The file is read as text and is never executed as code.
- Existing PySH aliases can be overridden by imported aliases.

The command prints a concise summary:

```text
imported=N skipped=M file=/home/user/.zsh_aliases
```

Missing or unreadable files return non-zero.

## Safe zsh profile import

Use `source_zsh_profile <file>` to import safe, static parts of a zsh-style
profile without executing it:

```sh
source_zsh_profile ~/.zshrc
```

Supported forms:

```sh
alias ll='ls -lah'
alias gs="git status -sb"
export EDITOR=nano
export PAGER="less"
PYSH_MODE=transition
```

Supported static syntax is intentionally narrow:

- aliases: `alias NAME=value`, `alias NAME="value"`, `alias NAME='value'`;
- exports: `export NAME=value`, `export NAME="value"`, `export NAME='value'`;
- assignments: `NAME=value`, `NAME="value"`, `NAME='value'`.

The importer ignores comments and blank lines, imports simple aliases,
exports and local assignments, and deterministically skips unsupported zsh
constructs, including:

```sh
autoload -Uz compinit
compinit
eval "$(starship init zsh)"
function foo() { echo hi; }
plugins=(git docker)
source "$HOME/.oh-my-zsh/oh-my-zsh.sh"
```

The profile is read as text only. PySH does not evaluate command
substitution, execute shell functions, run plugin managers or invoke external
commands during import.

The command prints:

```text
aliases=N exports=N vars=N skipped=M file=/home/user/.zshrc
```

For bash/sh-oriented files, use `source_sh_aliases <file>`; it uses the same
static model but is documented for `.bash_aliases`, `.profile` and simple
POSIX-style alias/export files.

## CI behavior

The GitHub Actions CI workflow installs zsh before running tests so the
transition-layer tests cover real zsh delegation on `ubuntu-latest`. Local
tests that require zsh skip cleanly when zsh is not installed.

## Static compatibility check

Use `compat_check <file>` before importing or running legacy shell content:

```sh
compat_check ~/scripts/maintenance.sh
```

The checker does not execute the file. It classifies lines as `supported`,
`delegated`, `skipped` or `risky` and flags common migration hazards such as
`eval`, command substitution, shell functions and `source` statements. It
returns 0 when no risky constructs are found, 2 when risky constructs are
present, and 1 for file read errors.

## Explicit zsh delegation

Use `zsh <command>` when an old command needs real zsh behavior:

```sh
zsh 'echo $ZSH_VERSION'
zsh 'source ~/.zshrc; my_old_alias'
zsh 'print -r -- hello'
```

PySH executes the command as:

```sh
zsh -lc '<command>'
```

stdout and stderr are forwarded to the PySH user. The builtin returns the
underlying zsh exit code. If zsh is unavailable, PySH returns 127 and prints:

```text
pysh: zsh: command not found
```

## Optional fallback mode

Fallback is off by default. Enable it only when intentionally testing a
migration path:

```sh
zsh_fallback on
zsh_fallback off
PYSH_ZSH_FALLBACK=1
```

When fallback is enabled, PySH may delegate a command it cannot parse or
execute natively to real zsh through the bridge. PySH does not delegate
builtins it already handles, and it does not reinterpret successful native
commands.

Fallback is a compatibility aid, not a certification boundary. Production
configurations should keep the native command surface explicit and minimize
implicit delegation.
