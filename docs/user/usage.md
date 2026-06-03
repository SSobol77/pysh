<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/usage.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
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
python -m pysh --version    # module entry point version check
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

## Aliases

```sh
alias ll='ls -lah'
alias gs="git status -sb"
alias
unalias gs
```

Aliases are expanded only for the first word of each pipeline stage.

## Builtins

| Builtin    | Description                                                |
| ---------- | ---------------------------------------------------------- |
| `cd`       | Change the current working directory.                      |
| `pwd`      | Print the current working directory.                       |
| `alias`    | Define or display aliases.                                 |
| `unalias`  | Remove one or more aliases.                                |
| `export`   | Define or display exported environment vars.               |
| `source`   | Execute commands from a file (also `.`).                   |
| `command`  | Resolve or execute a command with alias expansion suppressed. |
| `source_zsh` | Safely import simple aliases from a zsh-compatible file. |
| `source_zsh_profile` | Statically import simple zsh aliases, exports and vars. |
| `source_sh_aliases` | Statically import simple sh/bash aliases, exports and vars. |
| `run_script` | Run a script through its shebang interpreter or native PySH. |
| `compat_check` | Print a static migration report for a shell file.      |
| `zsh`      | Execute one command through real `zsh -lc`.                |
| `zsh_fallback` | Enable or disable optional zsh fallback mode.         |
| `py`       | Execute Python code in the persistent PySH runtime.        |
| `sys_info` | Print platform / Python / user / shell / PATH summary.     |
| `env_audit` | Print a redacted environment audit summary.               |
| `path_audit` | Report missing / duplicate / non-directory PATH entries. |
| `which_all` | Print every executable match for a command in PATH.       |
| `apt_check` | Debian `apt list --upgradable` helper (never uses sudo).  |
| `apt_search` | Debian `apt search <query>` helper (never uses sudo).    |
| `plan`     | Preview classification/execution of a command; advisory.   |
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
source_zsh_profile ~/.zshrc
source_sh_aliases ~/.bash_aliases
compat_check ~/scripts/maintenance.sh
run_script ~/scripts/maintenance.sh --dry-run
zsh 'source ~/.zshrc; my_old_alias'
zsh 'print -r -- hello'
```

`source_zsh <file>` statically imports supported simple aliases without
executing the file. Comments, blank lines and unsupported zsh constructs are
skipped. Malformed alias lines are reported on stderr and counted as skipped.

`source_zsh_profile <file>` extends static import to simple zsh-compatible
aliases, `export NAME=value` statements and local `NAME=value` assignments.
It is intended for incremental migration from files such as `~/.zshrc`; it
never executes profile code, functions, plugin loaders, `eval`, command
substitution or external commands.

`source_sh_aliases <file>` uses the same static parser for `.bash_aliases`,
`.profile` and simple POSIX-style alias/export files.

`compat_check <file>` reads a profile or script without executing it and
prints a concise migration report. Lines are classified as `supported`,
`delegated`, `skipped` or `risky`. Risky constructs produce exit status 2.

`run_script <file> [args...]` is an explicit script transition runner. A
script with a `zsh`, `bash` or `sh` shebang is delegated to the real
interpreter using an argv list. A script with no shebang is run line-by-line
through PySH's native execution engine where possible.

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

### Multiline Python automation blocks

```sh
py {
    import os
    print(len(os.environ.get("PATH", "").split(":")))
}
```

The opener line is exactly `py {`, the closer line is exactly `}`. Block
bodies share the persistent Python runtime with one-line `py` invocations.
See [python-runtime.md](../python/python-runtime.md).

## System profile helpers

```sh
sys_info
env_audit
path_audit
which_all python3
apt_check
apt_search vim
```

These helpers are non-mutating and never call `sudo`. See
[system-profile.md](../shell/system-profile.md).

## Command planning

```sh
plan ls -la
plan echo a && echo b
plan sudo apt update
```

`plan` prints a deterministic classification (`kind`, `execution`, `risk`,
`reason`) without executing the command. See
[command-planning.md](../shell/command-planning.md).

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

## Python Command Execution Layer

Type `#py` at the normal PySH prompt to enter an interactive Python session:

```text
> #py
PySH Python Command Execution Layer | GPL-3.0
Python <current runtime>
Type #help for commands. Ctrl+D or #exit to return to PySH.

>>> x = 10
>>> x * 5
50
>>> def double(v):
...     return v * 2
...
>>> double(21)
42
>>> #exit
```

Inside Python command mode, available directives are:

| Directive        | Purpose                                                     |
| ---------------- | ----------------------------------------------------------- |
| `#exit`          | Return to the normal PySH prompt.                          |
| `#help`          | Show directive help.                                        |
| `#open <file>`   | Load a Python source file into the buffer (file-backed mode). |
| `#save [file]`   | Save the source buffer; `#save` uses the active file.       |
| `#show [file]`   | Display buffer with line numbers, or print file like `cat`. |
| `#run`           | Execute the source buffer.                                  |
| `#clear`         | Clear the buffer; keep active file and runtime state.       |
| `#reset`         | Clear buffer, active file, and runtime state.               |
| `#edit`          | Display buffer with full syntax highlighting.               |
| `#insert <line>` | Insert Python source before a line number.                  |
| `#replace <line>`| Replace a line with new Python source.                      |
| `#delete <line>` | Delete a line (or range `<a>:<b>`).                        |

TAB inserts four spaces inside Python code. Inside `#open`, `#save`, and
`#show` path positions, TAB completes filesystem paths.

Ctrl+D exits (same as `#exit`). Ctrl+C cancels current input.

Python command mode uses **Pygments** syntax highlighting across all views:
interactive input, continuation input, prompts, `#show`, `#show file.py`,
`#edit`, and Python diagnostics are colored on capable terminals.

Color controls:

| Variable          | Effect                             |
| ----------------- | ---------------------------------- |
| `PYSH_COLOR=0`    | Disable all colors                 |
| `PYSH_COLOR=1`    | Enable (default for capable TTY)   |
| `PYSH_COLOR=always` | Force ANSI even on non-TTY       |
| `NO_COLOR`        | Disable colors; overrides all else |

Path expansion works for all file directives: `~/file.py`, `./file.py`,
`../file.py`, and absolute paths are all supported.

Only successfully executed input is appended to the source buffer. Failed input
(syntax errors, runtime exceptions) is never saved. Saved files contain clean
Python source with no prompts and no ANSI escape sequences.

See [python-command-execution-layer.md](../python/python-command-execution-layer.md)
for the complete specification.

## Comments

A `#` that follows whitespace (or starts the line) begins a comment.
Everything from that `#` to the end of the line is ignored:

```sh
ls #abc          # runs: ls
echo "#abc"      # prints: #abc  (quoted hash is literal)
echo foo#bar     # prints: foo#bar  (mid-token hash is literal)
```

## Tab completion

`Tab` completes builtins and aliases for the first word, and filesystem
paths for any word. Inaccessible directories are silently skipped.

## Limitations

- No job control (`&`, `bg`, `fg`, `jobs`, `Ctrl+Z`).
- No full POSIX shell grammar — only the constructs documented here.
- No full zsh compatibility. The zsh bridge is a transition layer and
  delegates to real zsh only when explicitly requested or fallback is enabled.
- No full POSIX script compatibility. `run_script` delegates legacy scripts
  to their real interpreter when a supported shebang is present.
- No glob expansion is performed by PySH itself.
- `svc start` / `svc restart` require a PyInit control interface to fully
  relaunch processes.
