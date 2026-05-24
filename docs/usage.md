<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Usage

PySH is an interactive Bourne-style shell with a small, predictable feature
set. This page documents the day-to-day surface used at the command line.

## Invocation

```bash
pysh                        # interactive REPL via the console entry point
python -m pysh              # equivalent module entry point
pysh -c "echo hi"           # run a single command line and exit
pysh --version              # print version and exit
pysh -V                     # short form
```

`Ctrl+C` cancels the line being typed and keeps the shell alive.
`Ctrl+D` exits the shell. When GNU readline is available, **Ctrl+R**
opens Bash-like reverse incremental search.

## Operators

| Operator         | Meaning                                                  |
| ---------------- | -------------------------------------------------------- |
| `cmd1 ; cmd2`    | Run `cmd1`, then unconditionally run `cmd2`.             |
| `cmd1 && cmd2`   | Run `cmd2` only if `cmd1` exits with status 0.           |
| `cmd1 \|\| cmd2` | Run `cmd2` only if `cmd1` exits with non-zero status.    |
| `cmd1 \| cmd2`   | Pipe `cmd1`'s stdout into `cmd2`'s stdin.                |

Operators inside single or double quotes are treated as literal text.

```sh
echo "Test | pipe & semicolon; && ok"
python3.13 -c "import subprocess; print('ok')"
```

## Pipelines

PySH connects each pipeline stage with a real OS pipe and closes the
parent's duplicate handles after the child is spawned, so neither side
deadlocks.

```sh
ls -la | head -3
apt list --upgradable 2>/dev/null | grep -c "/"
```

## Redirection

| Syntax      | Effect                                  |
| ----------- | --------------------------------------- |
| `< file`    | Read stdin from `file`.                 |
| `> file`    | Write stdout to `file` (truncate).      |
| `>> file`   | Write stdout to `file` (append).        |
| `2> file`   | Write stderr to `file` (truncate).      |
| `2>> file`  | Write stderr to `file` (append).        |
| `&> file`   | Write stdout + stderr to `file`.        |
| `&>> file`  | Append stdout + stderr to `file`.       |

```sh
ls -la 2>/dev/null | head -3
echo "hello" > out.txt
echo "again" >> out.txt
```

## Command substitution

Both POSIX forms are supported:

```sh
echo "Kernel: `uname -r`"
echo "Date: $(date '+%Y-%m-%d')"
echo 'No substitution: $(date)'
```

- `$(...)` and `` `...` `` are both supported.
- Substitutions inside double quotes are evaluated.
- Substitutions inside single quotes are kept literally.
- Each substitution has a 5-second timeout by default. Timeouts and
  failures expand to an empty string; the shell stays usable.

## Variables

```sh
NAME=world           # local shell variable
export GREETING=hi   # exported environment variable
echo "$GREETING, $NAME"
```

Local variables shadow environment variables when expanded. Single quotes
suppress expansion; double quotes do not.

## Builtins

| Builtin    | Description                                                |
| ---------- | ---------------------------------------------------------- |
| `cd`       | Change the current working directory.                      |
| `pwd`      | Print the current working directory.                       |
| `alias`    | Define or display aliases.                                 |
| `unalias`  | Remove one or more aliases.                                |
| `export`   | Define or display exported environment vars.               |
| `source`   | Execute commands from a file (also `.`).                   |
| `source_zsh` | Safely import simple aliases from a zsh-compatible file. |
| `zsh`      | Execute one command through real `zsh -lc`.                |
| `zsh_fallback` | Enable or disable optional zsh fallback mode.         |
| `py`       | Execute Python code in the persistent PySH runtime.        |
| `pushd`    | Push CWD onto the directory stack and `cd` to a path.      |
| `popd`     | Pop the directory stack and `cd` to the popped entry.      |
| `dirs`     | Print the current directory followed by the stack.         |
| `svc`      | Query and signal PyInit services (see below).              |
| `exit`     | Exit the shell with an optional status code.               |
| `quit`     | Same as `exit`.                                            |

## Zsh transition commands

PySH is Python-first, not a full zsh clone. The zsh compatibility bridge is
for transition and controlled delegation.

```sh
source_zsh ~/.zsh_aliases
zsh 'source ~/.zshrc; my_old_alias'
zsh 'print -r -- hello'
```

`source_zsh <file>` statically imports supported simple aliases without
executing the file. Comments, blank lines and unsupported zsh constructs are
skipped. Malformed alias lines are reported on stderr and counted as skipped.

`zsh <command>` runs the command through `zsh -lc <command>` when zsh is
installed. If zsh is unavailable, it returns 127 and reports
`pysh: zsh: command not found`.

Fallback is off by default:

```sh
zsh_fallback on
zsh_fallback off
PYSH_ZSH_FALLBACK=1
```

When enabled, fallback may delegate commands PySH cannot parse or execute
natively. PySH builtins are not delegated.

## Python runtime

`py <code>` executes one-line Python code in a persistent runtime context for
the current shell session:

```sh
py print("hello from python")
py import platform; print(platform.platform())
py from pathlib import Path; print(Path(".").resolve())
py x = 10
py print(x)
```

Imports and variables persist between `py` invocations. Exceptions are
printed to stderr and return non-zero without terminating the shell.

## Directory stack

```sh
pushd /tmp
pushd /var/log
dirs
popd
popd
```

Popping an empty stack produces a deterministic error and non-zero exit
status.

## svc / PyInit services

```sh
svc list
svc status <name>
svc start <name>
svc stop <name>
svc restart <name>
```

- `svc list`, `svc status`, `svc stop` use PID files under
  `/run/pyinit/*.pid`.
- `svc restart` sends `SIGTERM` and reports that supervision is required to
  actually relaunch the process unless a PyInit control interface is
  registered.
- `svc start` requires a PyInit control interface. Without one it fails
  deterministically rather than pretending to work.

PySH never calls `sudo`. Run PySH under an account that already has the
required permissions to control system-wide services.

## Tab completion

`Tab` completes builtins and aliases for the first word, and filesystem
paths for any word. Inaccessible directories are silently skipped.

## Limitations

- No job control (`&`, `bg`, `fg`, `jobs`, `Ctrl+Z`).
- No full POSIX shell grammar — only the constructs documented here.
- No full zsh compatibility. The zsh bridge is a transition layer and
  delegates to real zsh only when explicitly requested or fallback is enabled.
- No glob expansion is performed by PySH itself.
- `svc start` / `svc restart` require a PyInit control interface to fully
  relaunch processes.
