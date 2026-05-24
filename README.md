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

# PySH

**Python-first interactive shell for Debian and Unix-like systems.**

PySH is a small, dependency-free interactive shell written in pure Python.
It is packaged as a regular PyPI distribution (`pysh-shell`), installs a
single console command (`pysh`), and is designed to feel familiar to anyone
used to a Bourne-style shell while remaining hackable from Python.

The 0.1.1 release targets **Python 3.13+** and is validated on **Debian 13**.

---

## Features

- Interactive REPL with command history (`~/.pysh_history`).
- Welcome banner, configurable prompt with user and CWD (`~` collapsed).
- Robust quote-aware parser:
  - Splits chains on `;`, `&&`, `||` only outside of quotes.
  - Splits pipelines on `|` only outside of quotes.
- Pipelines with correctly managed file-descriptor handover.
- Redirection: `<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`.
- Local variables (`NAME=value`) and exported environment variables
  (`export NAME=value`) with `$NAME` / `${NAME}` expansion.
- Aliases with sane defaults and user overrides via `alias`.
- Startup file `~/.pyshrc` (and the `source` builtin) for persistent
  customisation.
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
```

---

## Builtins

Implemented directly inside the shell (no subprocess spawned):

| Builtin   | Description                                      |
| --------- | ------------------------------------------------ |
| `cd`      | Change the current working directory.            |
| `pwd`     | Print the current working directory.             |
| `alias`   | Define or display aliases.                       |
| `export`  | Define or display exported environment vars.     |
| `source`  | Execute commands from a file (also `.`).         |
| `exit`    | Exit the shell with an optional status code.     |
| `quit`    | Same as `exit`.                                  |

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
echo "🐍 PySH v1.0 | Python 3.13.5"
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

## Variables

```sh
NAME=world           # local shell variable
export GREETING=hi   # exported environment variable
echo "$GREETING, $NAME"
```

Local variables shadow environment variables when expanded. Single quotes
suppress expansion; double quotes do not.

---

## `~/.pyshrc`

If `~/.pyshrc` exists at startup, PySH executes it line by line through the
normal command path. Blank lines and lines starting with `#` are ignored.
You can also re-source it at any time:

```sh
source ~/.pyshrc
```

### Example `~/.pyshrc`

```sh
export EDITOR="nano"
export PAGER="less"
export LANG="pl_PL.UTF-8"
export PYTHONDONTWRITEBYTECODE="1"

alias ll="ls -la --color=auto -F"
alias ls="ls --color=auto -F"
alias grep="grep --color=auto"
alias rm="rm -i"
alias cp="cp -i"
alias mv="mv -i"
alias df="df -h"
alias free="free -h"
alias python="python3.13"
alias pip="pip3.13"

echo "🐍 PySH 0.1.1 | Python 3.13+"
echo "🐧 Debian ready"
echo "💡 Supported: && || ; | > >> < 2> 2>> &> &>> source alias export cd"
```

A failing line is reported on stderr and the next line is still executed.

---

## Tab completion

`Tab` completes aliases and builtins for the first word, and filesystem
paths for any word. Inaccessible directories are silently skipped.

---

## Testing and quality gates

```bash
pytest -q
ruff check src tests
python -m build
twine check dist/*
```

The project ships with unit tests for the parser, the redirection module,
the rc loader and the shell itself.

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
