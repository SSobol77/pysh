<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Builtins

PySH builtins are dispatched by the shell process. State-changing builtins
modify the current shell directly; transition builtins such as `zsh` and
`run_script` may explicitly delegate to real interpreters as documented.

Unless stated otherwise, builtins return 0 on success, 1 on general runtime
error and 2 on usage error.

## `cd`

Syntax: `cd [directory]`

Purpose: Change the current working directory. With no argument, changes to
the current user's home directory.

Examples:

```sh
cd /var/log
cd
```

Return behavior: returns 0 when the directory change succeeds, 1 when the
target cannot be entered.

Limitations: PySH does not implement `cd -` in this release.

## `pwd`

Syntax: `pwd`

Purpose: Print the current working directory.

Example:

```sh
pwd
```

Return behavior: returns 0.

## `alias`

Syntax: `alias [NAME=VALUE ...]`

Purpose: Define or display aliases. With no arguments, prints all aliases.
Aliases are expanded only for the first word of each pipeline stage.

Examples:

```sh
alias
alias ll='ls -lah'
alias gs="git status -sb"
```

Return behavior: returns 0 when aliases are displayed or updated. Returns 1
when a requested alias name is not found.

Limitations: PySH supports simple aliases, not zsh global aliases or
parameterized shell functions.

## `unalias`

Syntax: `unalias NAME [NAME ...]`

Purpose: Remove aliases from the current shell session.

Example:

```sh
unalias ll
```

Return behavior: returns 0 when all requested aliases are removed, 1 when
one or more names do not exist, and 2 when no name is supplied.

## `export`

Syntax: `export [NAME[=VALUE] ...]`

Purpose: Display exported variables or add/update environment variables.
`export NAME=value` also updates PySH local variables so `$NAME` expansion
sees the same value.

Examples:

```sh
export EDITOR=nano
export PAGER="less"
export PATH="$HOME/bin:$PATH"
export
```

Return behavior: returns 0 for supported export forms.

Limitations: complex shell export syntax such as `export -f` is not
implemented.

## `source`

Syntax: `source FILE`

Purpose: Execute commands from a PySH rc-style file.

Example:

```sh
source ~/.pyshrc
```

Return behavior: returns the rc loader status. Missing arguments return 2.

Limitations: `source` executes the file through PySH's rc interpreter. Do not
use it for arbitrary zsh/bash profile migration; use `source_zsh_profile` or
`source_sh_aliases` for static import.

## `.`

Syntax: `. FILE`

Purpose: Alias for `source FILE`.

Example:

```sh
. ~/.pyshrc
```

Return behavior: same as `source`.

## `pushd`

Syntax: `pushd DIRECTORY`

Purpose: Push the current directory onto PySH's directory stack and change to
`DIRECTORY`.

Example:

```sh
pushd /tmp
```

Return behavior: returns 0 on success, 1 when the target is invalid or cannot
be entered, and 2 when no directory is supplied.

## `popd`

Syntax: `popd`

Purpose: Pop the most recent entry from the directory stack and change to it.

Example:

```sh
popd
```

Return behavior: returns 0 on success and 1 when the stack is empty or the
directory change fails.

## `dirs`

Syntax: `dirs`

Purpose: Print the current directory followed by the directory stack.

Example:

```sh
dirs
```

Return behavior: returns 0.

## `svc`

Syntax: `svc {list|status|start|stop|restart} [name]`

Purpose: Query or signal PyInit-style services using PID files under
`/run/pyinit`.

Examples:

```sh
svc list
svc status network
svc stop worker
svc restart worker
svc start worker
```

Return behavior: returns 0 for successful operations, 1 for service runtime
errors and 2 for invalid usage or unknown actions.

Limitations: `svc start` and full restart require a PyInit control interface.
PySH never calls `sudo`.

## `exit`

Syntax: `exit [status]`

Purpose: Leave the interactive shell.

Example:

```sh
exit 0
```

Return behavior: terminates the shell with the supplied numeric status or 0.
Non-numeric status reports an error and exits with status 2.

## `quit`

Syntax: `quit [status]`

Purpose: Alias for `exit`.

Example:

```sh
quit
```

Return behavior: same as `exit`.

## `source_zsh`

Syntax: `source_zsh FILE`

Purpose: Preserve the existing transition behavior by statically importing
simple zsh-compatible aliases without executing the file.

Example:

```sh
source_zsh ~/.zsh_aliases
```

Return behavior: returns 0 after a readable file is parsed, 1 when the file
is missing or unreadable, and 2 when no file is supplied. Prints
`imported=N skipped=M file=<path>`.

Limitations: imports aliases only. Use `source_zsh_profile` for aliases,
exports and assignments.

## `source_zsh_profile`

Syntax: `source_zsh_profile FILE`

Purpose: Statically import safe zsh profile entries: simple aliases, simple
`export NAME=value` statements and simple local `NAME=value` assignments.

Example:

```sh
source_zsh_profile ~/.zshrc
```

Return behavior: returns 0 for readable files, 1 for read errors and 2 for
missing arguments. Prints `aliases=N exports=N vars=N skipped=M file=<path>`.

Limitations: never executes profile code. Skips command substitution,
functions, arrays, plugin managers, `eval`, dynamic `source` lines and other
unsupported constructs.

## `source_sh_aliases`

Syntax: `source_sh_aliases FILE`

Purpose: Statically import simple sh/bash alias, export and assignment files
such as `.bash_aliases` or `.profile`.

Example:

```sh
source_sh_aliases ~/.bash_aliases
```

Return behavior: same summary and status model as `source_zsh_profile`.

Limitations: this is a static importer, not a POSIX shell interpreter.

## `run_script`

Syntax: `run_script FILE [args...]`

Purpose: Run legacy scripts as an explicit transition action. Scripts with
`zsh`, `bash` or `sh` shebangs are delegated to the real interpreter. Scripts
without a shebang run line-by-line through PySH where possible.

Examples:

```sh
run_script ./legacy.zsh
run_script ./maintenance.sh --dry-run
run_script ./pysh-script
```

Return behavior: returns the delegated script exit code. Returns 127 when a
required interpreter is unavailable, 1 for file read errors and 2 for missing
arguments.

Limitations: no-shebang execution is PySH line execution, not full POSIX
script semantics.

## `compat_check`

Syntax: `compat_check FILE`

Purpose: Produce a static migration report without executing the file.

Example:

```sh
compat_check ~/scripts/maintenance.sh
```

Return behavior: returns 0 when no risky constructs are found, 2 when risky
constructs are present and 1 for file read errors.

Limitations: the checker is conservative. A `delegated` line may still need
manual review before production migration.

## `zsh`

Syntax: `zsh COMMAND...`

Purpose: Execute one command through real `zsh -lc` as an explicit
transition bridge.

Example:

```sh
zsh 'print -r -- $ZSH_VERSION'
```

Return behavior: returns zsh's exit code. Returns 127 if zsh is unavailable
and 2 when no command is supplied.

Limitations: this delegates to real zsh; it does not make PySH a zsh clone.

## `zsh_fallback`

Syntax: `zsh_fallback {on|off}`

Purpose: Enable or disable optional fallback delegation for commands PySH
cannot parse or execute natively.

Examples:

```sh
zsh_fallback on
zsh_fallback off
```

Return behavior: returns 0 for `on` or `off`, and 2 for invalid usage.

Limitations: fallback is off by default and should be treated as a migration
aid, not a compatibility guarantee.

## `py`

Syntax: `py PYTHON_CODE...`

Purpose: Execute one line of Python code in a persistent per-session runtime
context.

Examples:

```sh
py import platform; print(platform.platform())
py x = 10
py print(x)
```

Return behavior: returns 0 when Python execution succeeds and non-zero when
the Python code raises an exception. Exceptions are printed to stderr and do
not kill the shell.

Limitations: PySH 0.2.2 supports one-line Python execution only. Multiline
Python blocks are planned for a future release.
