<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/builtins.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

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

## `command`

Syntax:

```sh
command -v NAME
command -V NAME
command NAME [ARGS ...]
```

Purpose: provide POSIX-style command lookup and execution with alias
expansion suppressed for `NAME`.

Resolution order for `-v` and `-V` is:

1. PySH builtin
2. alias
3. external executable found in `PATH`

Examples:

```sh
command -v pysh
command -V cd
command ls -la
```

`command -v NAME` prints only the resolved identity.  For a PySH builtin this
is the builtin name; for an alias this is the alias definition; for an external
command this is the resolved executable path.  Missing names produce no stdout
and return 1.

`command -V NAME` prints a human-readable description such as
`cd is a PySH builtin`, `ll is an alias for 'ls -la'`, or
`python is /usr/bin/python`.  Missing names are reported to stderr as
`pysh: command: NAME: not found` and return 1.

`command NAME [ARGS ...]` executes `NAME` without expanding aliases for `NAME`.
PySH has no shell functions, so this mainly matters for aliases.  Builtins such
as `command cd /tmp` and `command export FOO=bar` still execute as builtins;
external commands execute normally.

Return behavior:

- `0` when `NAME` is resolved or the executed command succeeds.
- `1` when `command -v NAME` or `command -V NAME` cannot resolve `NAME`.
- The external command's exit status for `command NAME [ARGS ...]`.
- `2` for invalid builtin usage.

## `secure`

Syntax: `secure COMMAND [ARGS ...]`

Purpose: Run a command behind an explicit PTY bridge. This is opt-in per
invocation and is intended for commands that may temporarily disable terminal
echo for sensitive input. Normal commands such as `sudo`, `ssh`, `su`, and
`gpg` are not wrapped automatically.

Example:

```sh
secure sudo -v
```

Return behavior: returns the child command's exit status. Missing arguments
return 2. A command that cannot be executed returns a deterministic exec
failure status such as 127 for command-not-found.

Security boundary: `secure` forwards terminal bytes but does not store, log,
count, or expose password bytes. When the sensitive-input indicator is enabled,
it renders at most one fixed symbol while the child PTY has echo disabled. It
does not show one symbol per character, does not reveal password length, and
does not indicate password correctness.

## Diagnostic builtins

The diagnostic builtins are explicit and non-mutating. They print their
intentional reports to stdout and usage/runtime errors to stderr. Sensitive
environment values are redacted by name-based policy.

- `plan <command...>` previews classification, risk and execution route. It is
  not execution and does not run the planned command.
- `sys_info` prints read-only platform, Python, cwd, user, shell and PATH-count
  metadata.
- `env_audit` prints a redacted environment audit.
- `path_audit` reports PATH entries as `ok`, `missing`, `not_dir` or
  `duplicate`.
- `which_all NAME` lists executable matches in PATH order without executing
  them.
- `apt_check` runs read-only `apt list --upgradable`; it never uses `sudo`.
- `apt_search QUERY` runs read-only `apt search QUERY`; it never uses `sudo`.
- `compat_check FILE` reads a shell file as text and never sources startup
  files or executes shell code.

## `.`

Syntax: `. FILE`

Purpose: Alias for `source FILE`.

Example:

```sh
. ~/.pyshrc
```

Return behavior: same as `source`.

## `jobs`

Syntax: `jobs`

Purpose: List background and stopped jobs managed by the current shell.

Each line shows `[N]+ STATUS  command_text` where `N` is the job ID, `+`
marks the current job, and STATUS is one of `Running`, `Stopped`, or `Done`.

Return behavior: returns 0 always.  Done jobs are removed from the table
after being displayed.

## `fg`

Syntax: `fg [N | %N]`

Purpose: Bring a job to the foreground.  If no argument is given, the current
job (most recently used alive job) is brought forward.  `%N` is accepted as
an alias for `N`.

Examples:

```sh
fg
fg 2
fg %1
```

Return behavior: returns the job's exit status on normal exit, `130` if
interrupted by Ctrl+C, `148` if stopped again by Ctrl+Z, or `1` if the job
does not exist or there is no current job.

Limitations: requires a real TTY for full terminal handover.

## `bg`

Syntax: `bg [N | %N]`

Purpose: Resume a stopped job in the background.  If no argument is given,
the current job is resumed.

Examples:

```sh
bg
bg 2
```

Return behavior: returns `0` on success, `1` if the job is not stopped or
does not exist.

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
without a supported foreign-shell shebang run through PySH's native script
engine.

Examples:

```sh
run_script ./legacy.zsh
run_script ./maintenance.sh --dry-run
run_script ./pysh-script
```

Return behavior: returns the delegated or native script exit code. Returns 127
when a required interpreter is unavailable, 1 for file read errors and 2 for
missing arguments.

Limitations: native execution is PySH Script Mode v1, not full POSIX script
semantics. POSIX `set -e`, `set -u` and `set -x` are not implemented.

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

Syntax: `py PYTHON_CODE...` or multiline block:

```sh
py {
    PYTHON_BODY
}
```

Purpose: Execute Python code in a persistent per-session runtime context.

Examples:

```sh
py import platform; print(platform.platform())
py x = 10
py print(x)

py {
    import math
    print(math.tau)
}
```

Return behavior: returns 0 when Python execution succeeds and non-zero when
the Python code raises an exception. Exceptions are printed to stderr and
do not kill the shell. An unterminated `py { ... }` block in a script
returns non-zero.

Limitations: nested `py { ... }` blocks are rejected. See
[python-runtime.md](../python/python-runtime.md) for full behavior.

## `sys_info`

Syntax: `sys_info`

Purpose: Print a concise, non-secret system summary (platform, Python,
executable, cwd, user, home, shell, PATH entry count).

Example:

```sh
sys_info
```

Return behavior: returns 0.

Limitations: only stdlib-derived fields are reported; no secret values are
printed.

## `env_audit`

Syntax: `env_audit`

Purpose: Print a redacted environment audit summary. Lists the total number
of variables, prints a curated whitelist of safe variables, and prints any
variable whose name contains a sensitive token as `<redacted>`.

Example:

```sh
env_audit
```

Return behavior: returns 0.

Limitations: redaction is name-based. A name that does not contain `KEY`,
`TOKEN`, `SECRET`, `PASSWORD`, `PASS`, `CREDENTIAL`, or `AUTH` is not
treated as a secret.

## `path_audit`

Syntax: `path_audit`

Purpose: Print per-entry status for every `$PATH` entry as
`<status>\t<entry>` where status is one of `ok`, `missing`, `not_dir`,
`duplicate`.

Example:

```sh
path_audit
```

Return behavior: returns 0 when every entry is `ok` with no duplicates;
returns 1 when any entry is `missing`, `not_dir`, or `duplicate`.

Limitations: does not verify per-entry file permissions or symlink targets
beyond `is_dir()`.

## `which_all`

Syntax: `which_all COMMAND`

Purpose: Print every executable match for `COMMAND` along `$PATH`.

Example:

```sh
which_all python3
```

Return behavior: returns 0 when at least one executable match exists, 1
when none exist, and 2 when the command argument is missing.

Limitations: matches files that are executable for the current user; does
not consult `$PATHEXT` or shell-builtin lookup.

## `apt_check`

Syntax: `apt_check`

Purpose: Probe available Debian package upgrades using `apt list
--upgradable`. Never calls `sudo` and never modifies system state.

Example:

```sh
apt_check
```

Return behavior: returns the apt exit code. Returns 127 with a
deterministic message when `apt` is not found.

Limitations: Debian-oriented helper; does not work on systems without
`apt`. Some apt versions warn that the CLI is not stable for scripts; the
warning is harmless and is forwarded as-is.

## `apt_search`

Syntax: `apt_search QUERY`

Purpose: Run `apt search QUERY` safely without `shell=True`. Never calls
`sudo`, never modifies system state.

Example:

```sh
apt_search vim
```

Return behavior: returns the apt exit code. Returns 127 when `apt` is not
found and 2 when the query argument is missing.

Limitations: same as `apt_check`.

## `plan`

Syntax: `plan COMMAND...`

Purpose: Preview how PySH would classify and execute `COMMAND` without
running it. Prints `original=`, `kind=`, `execution=`, `risk=` and `reason=`
lines.

Examples:

```sh
plan ls -la
plan echo a && echo b
plan sudo apt update
plan py print("x")
```

Return behavior: returns 0 for a successful plan and 2 when no command
argument is supplied.

Limitations: `plan` is advisory only. Policy enforcement is intentionally
planned for a future release. See
[command-planning.md](../shell/command-planning.md).
