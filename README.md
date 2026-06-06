<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: README.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

<p align="center">
  <img src="https://raw.githubusercontent.com/SSobol77/pysh/main/docs/img/pysh-icon-512.png" alt="PySH logo" width="160"/>
</p>

<h1 align="center">PySH</h1>

<p align="center">
  <strong>PySH — fast, Python-first universal interactive shell for Debian and Unix-like systems.</strong>
</p>

<p align="center">
  <a href="https://github.com/SSobol77/pysh/actions/workflows/ci.yml">
    <img src="https://github.com/SSobol77/pysh/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"/>
  </a>
  <a href="https://pypi.org/project/pysh-shell/">
    <img src="https://img.shields.io/pypi/v/pysh-shell?label=PyPI&logo=pypi&logoColor=white" alt="PyPI version"/>
  </a>
  <a href="https://pypi.org/project/pysh-shell/">
    <img src="https://img.shields.io/pypi/pyversions/pysh-shell?label=Python&logo=python&logoColor=white" alt="Supported Python versions"/>
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

**PySH — fast, Python-first universal interactive shell for Debian and Unix-like systems.**

PySH is a small, dependency-free interactive shell written in pure Python.
It is packaged as a regular PyPI distribution (`pysh-shell`), installs a
single console command (`pysh`), and is designed to feel familiar to anyone
used to a Bourne-style shell while remaining hackable from Python.

Current release: **PySH 0.8.0**. PySH targets **Python 3.13+** and is
validated primarily on **Debian 13** and Unix-like systems.

---

## Features

- Interactive REPL with persistent history (`~/.pysh_history`).
- Bash-like reverse incremental search bound to **Ctrl+R** in the raw editor
  and through GNU readline when that fallback editor is active.
- Welcome banner and two-line configurable prompt with user, host, CWD, Git,
  tool version, virtualenv, and last-status segments.
- Robust quote-aware parser:
  - Splits chains on `;`, `&&`, `||` only outside of quotes.
  - Splits pipelines on `|` only outside of quotes.
- Pipelines with correctly managed file-descriptor handover.
- Redirection: `<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`.
- Native glob and path expansion for documented unquoted path words.
- Here-documents and here-strings for command input.
- Job control foundation with background execution, `jobs`, `fg`, and `bg`.
- **Command substitution**: `$(command)` and `` `command` ``. Quote-aware:
  evaluated inside double quotes, suppressed inside single quotes.
  Bounded by a 5-second timeout by default.
- Local variables (`NAME=value`) and exported environment variables
  (`export NAME=value`) with `$NAME` / `${NAME}` expansion.
- Aliases with sane defaults; `alias` and **`unalias`** builtins.
- **Migration layer for zsh/bash/sh**: `source_zsh <file>` preserves the
  existing alias importer, `source_zsh_profile <file>` and
  `source_sh_aliases <file>` statically import simple aliases, exports and
  assignments without executing profile code, `migrate <file>` produces
  Python-first script migration guidance, `run_script <file> [args...]`
  delegates shebang scripts to their real interpreter, and `compat_check
  <file>` reports migration risk before execution.
- **Zsh Transition Layer** for explicit delegation: `zsh <command>` delegates
  to real zsh when installed, and `zsh_fallback` can be enabled for
  controlled fallback experiments.
- **Python-native runtime bridge**: `py <code>` executes one-line Python code
  in a persistent per-session runtime context.
- **Python automation blocks**: `py { ... }` runs a multiline Python block in
  the same persistent runtime context as the one-line `py` form.
- **PySH-native script mode**: `pysh script.pysh [args...]` and
  `python -m pysh script.pysh [args...]` execute explicit local PySH scripts
  with `$0`, `$1`, `$#`, `$@`, heredocs, glob expansion and `py { ... }`
  blocks. PySH scripts are not POSIX sh scripts.
- **Observability and diagnostics**: `--debug` and `--trace` emit structured,
  redacted stderr diagnostics without changing command stdout.
- **Debian/system profile helpers**: `sys_info`, `env_audit`, `path_audit`,
  `which_all`, `apt_check`, `apt_search` — non-mutating, never call `sudo`.
- **Command planning**: `plan <command...>` previews how PySH would classify
  and execute a command without running it.
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
- **Python-native `~/.pyshrc.py`**: auto-generated production template on first
  interactive launch; never overwrites an existing file.
- **stdlib raw-mode line editor**: character-by-character editing with live
  syntax highlighting and fish-style autosuggestions.
- **Python command-mode syntax highlighting**: Pygments is installed by
  default and colors interactive `#py` input, continuation prompts, `#show`,
  `#edit`, and Python diagnostics on capable terminals.
- **Configurable prompt colors**: per-segment VGA and truecolor support via
  Python-native `~/.pyshrc.py`.
- **Configurable terminal cursor color**: OSC 12/112 support, disabled by
  default, opt-in via `~/.pyshrc.py`.
- **Explicit `secure <cmd>` PTY runner**: opt-in PTY bridge for commands that
  disable echo; never auto-wraps `sudo`/`ssh`.
- **Fixed-size ring indicator**: keypress feedback inside `secure <cmd>`;
  constant slot count never reveals password length.
- **Shell-style comments**: unquoted `#` after whitespace begins a comment;
  quoted and mid-token `#` remain literal.
- PySH-native tab completion for builtins, aliases, PATH commands, paths,
  variables and jobs.
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

### Quick start

```sh
pysh
pysh --version
pysh -c "echo hi"
pysh script.pysh arg1 arg2
# ~/.pyshrc.py is created automatically on first launch
ls #abc           # comment stripped; ls runs without #abc argument
echo "#abc"       # quoted hash preserved: prints #abc
secure sudo -v    # explicit PTY runner for sensitive prompts
alias ll='ls -lah'
source_zsh_profile ~/.zshrc
source_sh_aliases ~/.bash_aliases
compat_check ~/scripts/maintenance.sh
run_script ~/scripts/maintenance.sh --dry-run
py import platform; print(platform.platform())
```

### Development install

```bash
# Recommended: uv-based dev workflow
uv sync
uv run pytest -q
uv run ruff check src tests
scripts/check_release_quality.sh

# Classic venv alternative
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
pysh script.pysh arg1 arg2     # run a PySH-native script file
```

---

## Documentation

Full documentation lives under the repository [`docs/`](https://github.com/SSobol77/pysh/tree/main/docs). See [`docs/README.md`](https://github.com/SSobol77/pysh/blob/main/docs/README.md) for the complete documentation index.

**User guide**

- [Installation](https://github.com/SSobol77/pysh/blob/main/docs/user/installation.md) — installing from PyPI and dev install.
- [Usage](https://github.com/SSobol77/pysh/blob/main/docs/user/usage.md) — invocation, operators, pipelines, redirection, command substitution, variables, builtins.
- [Builtins](https://github.com/SSobol77/pysh/blob/main/docs/user/builtins.md) — syntax, examples, return behavior and limitations for every builtin.
- [Operators](https://github.com/SSobol77/pysh/blob/main/docs/user/operators.md) — chains, pipelines, redirection, command substitution, quoting and parser limitations.
- [Configuration](https://github.com/SSobol77/pysh/blob/main/docs/user/configuration.md) — `~/.pyshrc`, plugins under `~/.pyshrc.d/`, aliases, exports, prompt behavior.
- [Limitations](https://github.com/SSobol77/pysh/blob/main/docs/user/limitations.md) — explicit non-goals and compatibility boundaries.

**Shell behavior**

- [System profile](https://github.com/SSobol77/pysh/blob/main/docs/shell/system-profile.md) — `sys_info`, `env_audit`, `path_audit`, `which_all`, `apt_check`, `apt_search`.
- [Command planning](https://github.com/SSobol77/pysh/blob/main/docs/shell/command-planning.md) — `plan <command...>`, the advisory classifier.
- [Sensitive input](https://github.com/SSobol77/pysh/blob/main/docs/shell/security-sensitive-input.md) — security boundary for password/passphrase prompts and the explicit `secure <cmd>` PTY runner.

**Python layer**

- [Python runtime](https://github.com/SSobol77/pysh/blob/main/docs/python/python-runtime.md) — persistent Python-native `py` execution context.
- [Python command execution layer](https://github.com/SSobol77/pysh/blob/main/docs/python/python-command-execution-layer.md) — interactive `#py` mode with full REPL, source buffer, and file directives.

**Migration**

- [Migration](https://github.com/SSobol77/pysh/blob/main/docs/migration/migration.md) — static profile import, script transition runner, and compatibility reporting.
- [Zsh compatibility](https://github.com/SSobol77/pysh/blob/main/docs/migration/zsh-compatibility.md) — transition bridge, safe profile import, explicit zsh delegation, optional fallback mode.

**Compatibility contracts**

- [Compatibility overview](https://github.com/SSobol77/pysh/blob/main/docs/compatibility/README.md) — PySH is not a `/bin/sh` replacement, not a zsh clone, not bash. All claims are test-backed.
- [Feature matrix](https://github.com/SSobol77/pysh/blob/main/docs/compatibility/feature-matrix.md) — per-feature status, category, evidence, and owner issue.
- [System shell integration policy](https://github.com/SSobol77/pysh/blob/main/docs/compatibility/system-shell-integration-policy.md) — safe use as `pysh`, unsupported `/bin/sh` provider mode, and system-script boundaries.
- [Unsupported constructs](https://github.com/SSobol77/pysh/blob/main/docs/compatibility/unsupported-constructs.md) — what PySH does not support and what to do instead.

**Development and release**

- [Development](https://github.com/SSobol77/pysh/blob/main/docs/development/development.md) — running the test suite, linting, building artifacts, repository layout.
- [Release process](https://github.com/SSobol77/pysh/blob/main/docs/development/release.md) — how PySH ships via GitHub Actions and PyPI Trusted Publishing.
- [Packaging](https://github.com/SSobol77/pysh/blob/main/docs/development/packaging.md) — PyPI / `.deb` / `.rpm` / `.pkg` artifact naming contract and build scripts.

---

## Sensitive Input

For normal external commands such as `sudo`, `ssh`, `su`, and `gpg`, PySH does
not intercept, read, count, store, log, or buffer password bytes. Those programs
continue to read secrets directly from the controlling terminal. A keypress
indicator for such prompts is therefore available only through the explicit
`secure <cmd>` PTY wrapper, not ordinary command execution.

See [Sensitive input security boundary](https://github.com/SSobol77/pysh/blob/main/docs/shell/security-sensitive-input.md).

---

## Builtins

Available shell builtins. Most run inside the shell process; transition
builtins such as `zsh` and `run_script` may delegate explicitly as
documented.

| Builtin    | Description                                              |
| ---------- | -------------------------------------------------------- |
| `cd`       | Change the current working directory.                    |
| `pwd`      | Print the current working directory.                     |
| `alias`    | Define or display aliases.                               |
| `unalias`  | Remove one or more aliases.                              |
| `export`   | Define or display exported environment vars.             |
| `source`   | Execute commands from a file (also `.`).                 |
| `command`  | Resolve or execute a command with alias expansion suppressed. |
| `secure`   | Explicit PTY runner for one command; never auto-wraps sudo/ssh/su/gpg. |
| `source_zsh` | Safely import simple aliases from a zsh-compatible file. |
| `source_zsh_profile` | Statically import simple zsh profile entries. |
| `source_sh_aliases` | Statically import simple sh/bash aliases and vars. |
| `run_script` | Run a script through a shebang interpreter or native PySH lines. |
| `paste_show` / `paste_run` / `paste_cancel` | Manage captured bracketed multiline paste. |
| `compat_check` | Produce a static migration report for a shell file. |
| `migrate`  | Produce Python-first shell-script migration guidance. |
| `zsh`      | Execute one command through real `zsh -lc`.              |
| `zsh_fallback` | Enable or disable explicit zsh fallback mode.       |
| `py`       | Execute Python code in the persistent PySH runtime.      |
| `sys_info` | Print platform / Python / user / shell / PATH summary.   |
| `env_audit` | Print a redacted environment audit summary.             |
| `path_audit` | Report missing / duplicate / non-directory PATH entries. |
| `which_all` | Print every executable match for a command in PATH.     |
| `apt_check` | Run `apt list --upgradable` (Debian helper, no sudo).   |
| `apt_search` | Run `apt search <query>` (Debian helper, no sudo).     |
| `mc`       | Launch external Midnight Commander using PySH MC integration policy. |
| `plan`     | Preview classification/execution of a command, advisory. |
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
echo "PySH current release | Python current runtime"
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

## Zsh Transition Layer

PySH is Python-first, not a full zsh clone. The zsh compatibility bridge is
for transition: it lets users move aliases and selected legacy commands into
PySH without pretending that every zsh grammar feature is native.
`.pyshrc` is the canonical PySH configuration file; `.zshrc` is not sourced
automatically and the plain `source` builtin rejects zsh startup/profile
files with guidance to use PySH-native configuration or the safe static
importer.

```sh
source_zsh ~/.zsh_aliases
source_zsh_profile ~/.zshrc
source_sh_aliases ~/.bash_aliases
compat_check ~/scripts/maintenance.sh
migrate ~/scripts/maintenance.sh
run_script ~/scripts/maintenance.sh --dry-run
zsh 'source ~/.zshrc; my_old_alias'
zsh 'print -r -- hello'
```

`source_zsh <file>` statically imports supported simple alias definitions
such as `alias ll='ls -lah'`, ignores comments and unsupported constructs,
and never executes the file as code. It prints `imported=N skipped=M
file=<path>` and reports malformed alias lines deterministically on stderr.

`source_zsh_profile <file>` and `source_sh_aliases <file>` use the current
static profile importer. They read files such as `~/.zshrc`, `.profile` and
`.bash_aliases` without executing them, import supported simple aliases,
exports and local assignments, and print `aliases=N exports=N vars=N
skipped=M file=<path>`.

`compat_check <file>` produces a static report with `supported`,
`delegated`, `skipped` and `risky` counts. Risky constructs such as `eval`,
command substitution, `source` and shell functions cause exit status 2.

`migrate <file>` or `migrate --text TEXT` produces a Python-first migration
report with `info`, `warning`, `unsafe` and `unsupported` findings. It detects
common shell-script patterns such as shebangs, assignments, exports,
pipelines, redirections, command substitution, simple conditionals, simple
loops, heredocs and unsafe `eval`/`exec` behavior. It is analysis only: it
does not execute, source, expand, or automatically convert analyzed shell
content.

`run_script <file> [args...]` is an explicit transition runner. Scripts with
`zsh`, `bash` or `sh` shebangs are delegated to the real interpreter through
an argv list; no-shebang scripts are executed line-by-line by PySH's native
engine where possible.

`zsh <command>` delegates explicitly to real `zsh -lc <command>`. If zsh is
not installed, it returns 127 with a deterministic error.

Fallback mode is off by default. It can be enabled only explicitly:

```sh
zsh_fallback on
zsh_fallback off
PYSH_ZSH_FALLBACK=1
```

When fallback is on, PySH may delegate commands it cannot parse or execute
natively to zsh. Builtins already handled by PySH stay native, and native
command failures are not hidden.

---

## Python Runtime

The `py` builtin executes one-line Python code in a persistent runtime context
owned by the current PySH session:

```sh
py print("hello from python")
py import platform; print(platform.platform())
py from pathlib import Path; print(Path(".").resolve())
```

Variables and imports persist across `py` invocations:

```sh
py x = 10
py print(x)
py import pathlib
py print(pathlib.Path(".").exists())
```

Exceptions are printed to stderr and return non-zero without terminating the
shell.

### Multiline Python automation blocks

```sh
py {
    import os
    targets = [p for p in os.environ.get("PATH", "").split(":") if p]
    print(f"PATH entries: {len(targets)}")
}
```

The opener line is exactly `py {`, the closer is a line that contains only
`}`. Block bodies execute in the same persistent runtime context as one-line
`py` invocations, so variables and imports flow in both directions.
Unterminated blocks return non-zero in script/source mode; nested
`py { ... }` blocks are rejected deterministically.

---

## System profile helpers

PySH includes a small, non-mutating Debian/system profile layer. None of
these helpers call `sudo` or modify system state.

```sh
sys_info                # platform, Python, user, shell, PATH count
env_audit               # safe env audit with secret redaction
path_audit              # report missing / duplicate / non-directory entries
which_all python3       # all executables for "python3" along PATH
apt_check               # apt list --upgradable
apt_search vim          # apt search vim
```

Variables whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASS`,
`CREDENTIAL`, or `AUTH` are replaced with `<redacted>` in `env_audit`. See
[docs/shell/system-profile.md](https://github.com/SSobol77/pysh/blob/main/docs/shell/system-profile.md).

---

## Command planning

`plan <command...>` previews how PySH would classify and execute a command
without running it. It is advisory only — there is no policy enforcement.

```sh
plan ls -la
plan echo a && echo b
plan sudo apt update
plan py print("x")
```

The output prints `original=`, `kind=`, `execution=`, `risk=` and `reason=`
fields. See
[docs/shell/command-planning.md](https://github.com/SSobol77/pysh/blob/main/docs/shell/command-planning.md).

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

echo "PySH current release | Python 3.13+"
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

`Tab` uses PySH-native Completion Engine v1. It completes builtins, aliases
and executable command names at command position; filesystem paths in argument
and redirection positions; directories after `cd` and `pushd`; variable names
after `$` and `${`; and job IDs after `fg` and `bg` when jobs exist.

Completion is non-executing and non-mutating. It does not source bash, zsh or
fish completion scripts and does not implement programmable shell completion.

Architecture contract:
[Completion Engine Contract](https://github.com/SSobol77/pysh/blob/main/docs/architecture/completion-engine-contract.md).

---

## Limitations

- No full POSIX shell grammar — only the constructs documented above.
- No system `/bin/sh` provider role. Keep the distribution `/bin/sh`
  unchanged and run PySH explicitly as `pysh`.
- Native glob expansion is supported for unquoted `*`, `?`, character classes
  and `**`; brace expansion remains unsupported.
- No full zsh compatibility. The zsh compatibility bridge is a transition
  layer with safe static alias import and explicit delegation to real zsh.
- `svc start` and `svc restart` to actually re-launch a process require a
  PyInit control interface; without one they return a deterministic error.
- Multiline `py { ... }` blocks do not support nested blocks; the opener
  must be exactly `py {` and the closer must be a line containing only `}`.
- Debian helpers (`apt_check`, `apt_search`) require `apt` to exist; they
  return 127 deterministically when it does not.
- `plan` is advisory only. Policy enforcement is intentionally out of scope
  for the current release.

---

## Testing and quality gates

```bash
bash scripts/check_headers.sh
uv run pytest -q
uv run ruff check src tests
python -m build
twine check dist/*
```

The project ships unit tests for the parser, the redirection module, the
rc loader and mini-interpreter, command substitution, the history manager,
the highlighting helpers, the plugin loader, directory stack, `unalias`,
the `svc` builtin, the PyInit metadata parser, the zsh transition layer and
the Python runtime bridge.

---

## Publishing

This repository is configured for **PyPI Trusted Publishing** via GitHub
Actions. See [`.github/workflows/publish.yml`](https://github.com/SSobol77/pysh/blob/main/.github/workflows/publish.yml) — it uses `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` and the `pypi` environment. Tagging a release on GitHub publishes the build.

Do **not** publish from a developer machine; let the workflow do it.

---

## Target platform

- Primary target: **Debian 13** with **Python 3.13+**.
- Should work on any POSIX system with a working `subprocess` and
  `readline`, but only Debian 13 is regularly validated.

---

## License

PySH is distributed under the **GNU General Public License version 2 only**
(`GPL-2.0-only`). See [`LICENSE`](https://github.com/SSobol77/pysh/blob/main/LICENSE) for the full text.
