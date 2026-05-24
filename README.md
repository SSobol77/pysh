<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: README.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

<p align="center">
  <img src="https://raw.githubusercontent.com/SSobol77/pysh/main/docs/img/pysh-icon-512.png" alt="PySH logo" width="160"/>
</p>

<h1 align="center">PySH</h1>

<p align="center">
  <strong>Python-first interactive shell for Debian and Unix-like systems.</strong>
</p>

<p align="center">
  <a href="https://github.com/SSobol77/pysh/actions/workflows/ci.yml">
    <img src="https://github.com/SSobol77/pysh/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"/>
  </a>
  <a href="https://github.com/SSobol77/pysh/actions/workflows/publish.yml">
    <img src="https://github.com/SSobol77/pysh/actions/workflows/publish.yml/badge.svg?branch=main" alt="PyPI publish workflow"/>
  </a>
  <a href="https://pypi.org/project/pysh-shell/">
    <img src="https://img.shields.io/pypi/v/pysh-shell?label=PyPI&logo=pypi&logoColor=white" alt="PyPI version"/>
  </a>
  <a href="https://pypi.org/project/pysh-shell/">
    <img src="https://img.shields.io/pypi/pyversions/pysh-shell?label=Python&logo=python&logoColor=white" alt="Supported Python versions"/>
  </a>
  <a href="https://pypi.org/project/pysh-shell/">
    <img src="https://img.shields.io/pypi/dm/pysh-shell?label=PyPI%20downloads" alt="PyPI downloads"/>
  </a>
  <a href="https://github.com/SSobol77/pysh/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/SSobol77/pysh?label=License" alt="License"/>
  </a>
  <a href="https://github.com/SSobol77/pysh/releases">
    <img src="https://img.shields.io/github/v/release/SSobol77/pysh?label=Release&logo=github" alt="GitHub release"/>
  </a>
  <a href="https://github.com/SSobol77/pysh">
    <img src="https://img.shields.io/badge/platform-Debian%20%7C%20Unix--like-2f4f6f?logo=debian&logoColor=white" alt="Debian and Unix-like systems"/>
  </a>
  <a href="https://github.com/SSobol77/pysh">
    <img src="https://img.shields.io/badge/shell-Python--first-3776AB?logo=python&logoColor=white" alt="Python-first shell"/>
  </a>
</p>

---

**Python-first interactive shell for Debian and Unix-like systems.**

PySH is a small, dependency-free interactive shell written in pure Python.
It is packaged as a regular PyPI distribution (`pysh-shell`), installs a
single console command (`pysh`), and is designed to feel familiar to anyone
used to a Bourne-style shell while remaining hackable from Python.

The 0.1.3 release targets **Python 3.13+** and is validated on **Debian 13**.

---

## Features

- Interactive REPL with persistent history (`~/.pysh_history`).
- Bash-like reverse incremental search bound to **Ctrl+R** when GNU readline
  is available; degrades silently on other backends.
- Welcome banner and configurable prompt with user and CWD (`~` collapsed).
- Robust quote-aware parser:
  - Splits chains on `;`, `&&`, `||` only outside of quotes.
  - Splits pipelines on `|` only outside of quotes.
- Pipelines with correctly managed file-descriptor handover.
- Redirection: `<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`.
- **Command substitution**: `$(command)` and `` `command` ``. Quote-aware:
  evaluated inside double quotes, suppressed inside single quotes.
  Bounded by a 5-second timeout by default.
- Local variables (`NAME=value`) and exported environment variables
  (`export NAME=value`) with `$NAME` / `${NAME}` expansion.
- Aliases with sane defaults; `alias` and **`unalias`** builtins.
- Startup file `~/.pyshrc` plus a **plugin directory** at `~/.pyshrc.d/`
  whose `*.pysh` files load in deterministic lexicographic order.
- **Mini rc-interpreter** for control flow inside `~/.pyshrc` and plugins:
  `if`/`else`/`fi`, `for`/`do`/`done`, `while`/`do`/`done` (with a hard
  iteration safety limit).
- **Directory stack**: `pushd`, `popd`, `dirs`.
- **`svc` builtin** for PyInit-style service control by PID file:
  `svc list`, `svc status`, `svc stop`, `svc restart`, `svc start`.
- **PyInit service metadata** parser with dependency tracking
  (`depends: [network]`).
- Safe ANSI color helpers that respect `NO_COLOR` and `TERM=dumb`, used for
  the banner and diagnostics. The input line itself is left untouched so
  editing remains stable.
- Basic tab completion for aliases, builtins, files and directories.
- Clean Ctrl+C (cancels current line, keeps the shell alive) and Ctrl+D
  (exits the shell).

---

## Installation

### From PyPI

```bash
pip install pysh-shell
```

Then start the shell with:

```bash
pysh
```

### Development install

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Running

```bash
pysh           # console entry point installed by the wheel
python -m pysh # equivalent module entry point
pysh --version # print version and exit
pysh -c "echo hi; echo there"  # run one command line and exit
```

---

## Documentation

Full documentation lives under [`docs/`](docs/):

- [Installation](docs/installation.md) — installing from PyPI and dev install.
- [Usage](docs/usage.md) — invocation, operators, pipelines, redirection,
  command substitution, variables, builtins.
- [Configuration](docs/configuration.md) — `~/.pyshrc`, plugins under
  `~/.pyshrc.d/`, aliases, exports, prompt behavior.
- [Development](docs/development.md) — running the test suite, linting,
  building artifacts, repository layout.
- [Release process](docs/release.md) — how PySH 0.1.3 ships via GitHub
  Actions and PyPI Trusted Publishing.

---

## Builtins

Implemented directly inside the shell (no subprocess spawned):

| Builtin    | Description                                              |
| ---------- | -------------------------------------------------------- |
| `cd`       | Change the current working directory.                    |
| `pwd`      | Print the current working directory.                     |
| `alias`    | Define or display aliases.                               |
| `unalias`  | Remove one or more aliases.                              |
| `export`   | Define or display exported environment vars.             |
| `source`   | Execute commands from a file (also `.`).                 |
| `pushd`    | Push CWD onto the directory stack and `cd` to a path.    |
| `popd`     | Pop the directory stack and `cd` to the popped entry.    |
| `dirs`     | Print the current directory followed by the stack.       |
| `svc`      | Query / signal PyInit services. See [svc / PyInit](#svc--pyinit). |
| `exit`     | Exit the shell with an optional status code.             |
| `quit`     | Same as `exit`.                                          |

---

## Operators

| Operator         | Meaning                                                |
| ---------------- | ------------------------------------------------------ |
| `cmd1 ; cmd2`    | Run `cmd1`, then unconditionally run `cmd2`.           |
| `cmd1 && cmd2`   | Run `cmd2` only if `cmd1` exits with status 0.         |
| `cmd1 \|\| cmd2` | Run `cmd2` only if `cmd1` exits with non-zero status.  |
| `cmd1 \| cmd2`   | Pipe `cmd1`'s stdout into `cmd2`'s stdin.              |

Operators inside single or double quotes are treated as literal text.

```sh
echo "🐍 PySH v0.1.3 | Python 3.13.5"
echo "Test | pipe & semicolon; && ok"
python3.13 -c "import subprocess; print('ok')"
```

---

## Redirection

| Syntax       | Effect                                  |
| ------------ | --------------------------------------- |
| `< file`     | Read stdin from `file`.                 |
| `> file`     | Write stdout to `file` (truncate).      |
| `>> file`    | Write stdout to `file` (append).        |
| `2> file`    | Write stderr to `file` (truncate).      |
| `2>> file`   | Write stderr to `file` (append).        |
| `&> file`    | Write stdout + stderr to `file`.        |
| `&>> file`   | Append stdout + stderr to `file`.       |

```sh
ls -la 2>/dev/null | head -3
python3.13 -c "import sys; print('err', file=sys.stderr)" 2> err.log
echo "hello" > out.txt
echo "again" >> out.txt
```

Redirection operators inside quotes are kept as literal characters.

---

## Pipelines

PySH connects each stage with a real OS pipe and closes the parent's
duplicate handles after the child is spawned, so neither side deadlocks.

```sh
ls -la | head -3
apt list --upgradable 2>/dev/null | grep -c "/"
```

---

## Command substitution

```sh
echo "Kernel: `uname -r`"
echo "Date: $(date '+%Y-%m-%d')"
echo 'No substitution: $(date)'
```

- `$(...)` and `` `...` `` are both supported.
- Quotes are honoured: substitutions inside single quotes are kept
  literally; substitutions inside double quotes are evaluated.
- Each substitution runs with a 5-second timeout by default. On timeout or
  failure the substitution expands to an empty string and the shell
  remains usable.

---

## Variables

```sh
NAME=world           # local shell variable
export GREETING=hi   # exported environment variable
echo "$GREETING, $NAME"
```

Local variables shadow environment variables when expanded. Single quotes
suppress expansion; double quotes do not.

---

## `~/.pyshrc` and `~/.pyshrc.d/`

At startup PySH first executes `~/.pyshrc` (if present), then every file in
`~/.pyshrc.d/` whose name ends with `.pysh`. Plugins are loaded in
deterministic lexicographic order so prefix numbering (`10-…`, `20-…`)
gives predictable layering.

You can also re-source any file at any time:

```sh
source ~/.pyshrc
```

A failing line is reported on stderr and the next line is still executed.
A broken plugin does not prevent later plugins from loading.

### Example `~/.pyshrc`

```sh
export EDITOR="nano"
export PAGER="less"
export LANG="pl_PL.UTF-8"
export PYTHONDONTWRITEBYTECODE="1"

alias rm="rm -i"
alias cp="cp -i"
alias mv="mv -i"
alias python="python3.13"
alias pip="pip3.13"

if [ -d /opt/local/bin ]; then
    export PATH="/opt/local/bin:$PATH"
fi

for dir in ~/bin ~/.local/bin; do
    if [ -d "$dir" ]; then
        export PATH="$dir:$PATH"
    fi
done

echo "🐍 PySH 0.1.3 | Python 3.13+"
echo "💡 Operators: && || ; | > >> < 2> 2>> &> &>>  + \$() and backticks"
```

### Example plugin `~/.pyshrc.d/10-aliases.pysh`

```sh
# Loaded after ~/.pyshrc, in lexicographic order.
alias gs="git status -sb"
alias gd="git diff"
alias gl="git log --oneline --decorate"

if [ -f ~/.work_aliases ]; then
    source ~/.work_aliases
fi
```

### Mini rc-interpreter cheat sheet

| Construct                                  | Notes                                |
| ------------------------------------------ | ------------------------------------ |
| `if [ <cond> ]; then ... fi`               | `else` block optional                |
| `for VAR in a b c; do ... done`            | Iterates literal words               |
| `while [ <cond> ]; do ... done`            | Bounded by a safety iteration limit  |

The canonical else keyword is `else`. The form `else:` is accepted as a
compatibility alias.

Supported test operators:

| Test                  | Meaning                              |
| --------------------- | ------------------------------------ |
| `[ -f path ]`         | path exists and is a regular file    |
| `[ -d path ]`         | path exists and is a directory       |
| `[ -e path ]`         | path exists                          |
| `[ -z "$VAR" ]`       | `$VAR` is empty                      |
| `[ -n "$VAR" ]`       | `$VAR` is non-empty                  |
| `[ "$A" = "$B" ]`     | string equality                      |
| `[ "$A" == "$B" ]`    | string equality (alias)              |
| `[ "$A" != "$B" ]`    | string inequality                    |
| `[ ! -f path ]` etc.  | negate any of the above              |

---

## Directory stack

```sh
pushd /tmp
pushd /var/log
dirs
popd
popd
```

`pushd path` pushes the current directory onto the stack and changes to
`path`. `popd` returns to the most-recently-pushed directory. `dirs` prints
the current directory followed by the stack contents. Popping an empty
stack produces a deterministic error and a non-zero exit status.

---

## svc / PyInit

PySH ships a small service client used by the `svc` builtin. It is
deliberately PID-file based so it can be useful on systems that do not run
a full supervisor, but it is also designed to plug into PyInit when a
control interface is present.

```
svc list
svc status <name>
svc start <name>
svc stop <name>
svc restart <name>
```

- `svc list` walks `/run/pyinit/*.pid` and prints each service as
  `name\tactive|dead\tpid=N`.
- `svc status <name>` checks the PID file at
  `/run/pyinit/<name>.pid`.
- `svc stop <name>` reads the PID file and sends `SIGTERM`.
- `svc restart <name>` sends `SIGTERM`. Without a registered PyInit control
  interface it then reports that restart requires supervision.
- `svc start <name>` requires a PyInit control interface. Without one it
  fails deterministically rather than pretending to work.

PySH never calls `sudo`. To control system-wide PyInit services, run PySH
under an account that already has permission.

### PyInit service metadata

PyInit-style service files live in `~/.config/pyinit/services/` (or a path
chosen by your integration). PySH ships a strict metadata parser:

```
# ~/.config/pyinit/services/example.service
name: example
command: python3.13 -m http.server 8080
depends: [network]
```

Recognised fields:

- `name`     — required, identifier
- `command`  — required, the launch command line
- `depends`  — optional list of dependency names; accepts `[a, b]` or
  comma-separated form

Invalid metadata (unknown syntax, malformed dependencies, missing fields)
produces a deterministic `ServiceMetadataError` rather than silently
dropping content. This is metadata support for PyInit integration, **not**
a complete replacement for systemd.

---

## Tab completion

`Tab` completes aliases and builtins for the first word, and filesystem
paths for any word. Inaccessible directories are silently skipped.

---

## Limitations

- No job control (`&`, `bg`, `fg`, `jobs`, `Ctrl+Z` job suspension).
- No full POSIX shell grammar — only the constructs documented above.
- No glob expansion is performed by PySH itself; external commands still
  receive globs through their own expansion logic when run via a system
  shell, but plain pipelines do not expand `*` / `?` in arguments.
- `svc start` and `svc restart` to actually re-launch a process require a
  PyInit control interface; without one they return a deterministic error.

---

## Testing and quality gates

```bash
pytest -q
ruff check src tests
python -m build
twine check dist/*
```

The project ships unit tests for the parser, the redirection module, the
rc loader and mini-interpreter, command substitution, the history manager,
the highlighting helpers, the plugin loader, directory stack, `unalias`,
the `svc` builtin and the PyInit metadata parser.

---

## Publishing

This repository is configured for **PyPI Trusted Publishing** via GitHub
Actions. See [`.github/workflows/publish.yml`](.github/workflows/publish.yml) —
it uses `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` and
the `pypi` environment. Tagging a release on GitHub publishes the build.

Do **not** publish from a developer machine; let the workflow do it.

---

## Target platform

- Primary target: **Debian 13** with **Python 3.13+**.
- Should work on any POSIX system with a working `subprocess` and
  `readline`, but only Debian 13 is regularly validated.

---

## License

PySH is distributed under the **GNU General Public License v3.0 or later**
(`GPL-3.0-or-later`). See [`LICENSE`](LICENSE) for the full text.
