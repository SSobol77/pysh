<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Zsh compatibility

PySH 0.2.0 starts a **Zsh Transition Layer**. The design goal is migration,
not full zsh emulation:

- PySH remains a Python-first shell with its own native execution engine.
- zsh compatibility is explicit, deterministic and testable.
- Static alias import never executes arbitrary zsh files.
- Real zsh may be used as an optional bridge when it is installed.
- Native PySH builtins and native command errors are not hidden by default.

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
