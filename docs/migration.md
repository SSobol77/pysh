<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Migration

PySH 0.2.2 includes the professional migration layer for users moving from
zsh/bash/sh profiles and scripts. The layer is intentionally conservative:
PySH remains Python-first and does not claim full zsh or POSIX shell
compatibility.

## Migrating aliases from `~/.zsh_aliases`

If aliases are already isolated in a zsh-compatible alias file, keep using
the conservative alias-only importer:

```sh
source_zsh ~/.zsh_aliases
```

Supported alias examples:

```sh
alias ll='ls -lah'
alias gs="git status -sb"
```

This imports aliases only and never executes the file.

## Migrating simple `~/.zshrc` content

Use `source_zsh_profile <file>` for zsh-style profile files:

```sh
source_zsh_profile ~/.zshrc
```

This imports simple aliases, exports and local assignments while skipping
dynamic zsh constructs such as `autoload`, `compinit`, `eval`, shell
functions, arrays, plugin managers and dynamic `source` lines.

## Migrating `~/.bash_aliases` and `.profile`

Use `source_sh_aliases <file>` for `.bash_aliases`, `.profile` and simple
POSIX-style alias/export files:

```sh
source_sh_aliases ~/.bash_aliases
```

Supported static forms:

```sh
alias ll='ls -lah'
alias gs="git status -sb"
export EDITOR=nano
export PAGER="less"
PYSH_MODE=transition
```

Both commands read the file as text and never execute it. They do not
evaluate command substitution, run shell functions, start plugin managers,
process dynamic `source` statements or invoke external commands. Unsupported
constructs are skipped deterministically.

The import summary is:

```text
aliases=N exports=N vars=N skipped=M file=<path>
```

## Compatibility report

Use `compat_check <file>` before importing a profile or running a legacy
script:

```sh
compat_check ~/scripts/maintenance.sh
```

The checker is static. It does not execute the file. It classifies lines as:

| Action      | Meaning                                             |
| ----------- | --------------------------------------------------- |
| `supported` | Simple alias, export or local assignment.           |
| `delegated` | Shell grammar better run by a real interpreter.     |
| `skipped`   | Unsupported but not directly hazardous to inspect.  |
| `risky`     | Constructs requiring maintainer review before use.  |

Common risky patterns include `eval`, command substitution, shell functions
and `source` statements. The command returns 0 when no risky constructs are
found, 2 when risky constructs are present, and 1 for file read errors.

## Script transition runner

Use `run_script <file> [args...]` as an explicit bridge for legacy scripts:

```sh
run_script ~/scripts/maintenance.sh --dry-run
```

Scripts with these shebangs are delegated to the real interpreter using an
argv list:

```sh
#!/bin/zsh
#!/usr/bin/env zsh
#!/bin/bash
#!/usr/bin/env bash
#!/bin/sh
#!/usr/bin/env sh
```

If the required interpreter is missing, PySH returns 127 with a deterministic
error. Script arguments are passed as argv entries, not by string
interpolation.

Scripts without a shebang are executed line-by-line through PySH's native
engine where possible. Blank lines and comments are ignored. Execution stops
on the first non-zero status unless the line uses `&&` or `||` error-handling
operators.

## Python-first path

Migration should move stable automation toward Python where that improves
maintainability:

```sh
py import platform; print(platform.platform())
```

`py <code>` remains one-line persistent Python execution in 0.2.2. Multiline
Python blocks are planned for a future release.
