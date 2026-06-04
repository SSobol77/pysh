<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/configuration.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Configuration

PySH loads two layers of startup files on every interactive launch:

1. `~/.pyshrc` — your personal startup file.
2. `~/.pyshrc.d/*.pysh` — plugin snippets, loaded in deterministic
   **lexicographic order** after `~/.pyshrc`.

Both layers go through the same mini-interpreter, so they support the same
syntax: ordinary commands, `alias`, `export`, `source`, pipelines,
redirection, command substitution, and the `if` / `for` / `while`
constructs documented below.

A failing line is reported on stderr and the next line is still executed.
A broken plugin does not prevent later plugins from loading.

## Python-native configuration: ~/.pyshrc.py

PySH supports a Python-native configuration file at `~/.pyshrc.py`. On the
first interactive launch, PySH creates this file automatically from a
production-quality commented template — if and only if the file does not already
exist. **An existing `~/.pyshrc.py` is never overwritten.**

The file is loaded last, after `~/.pyshrc` and after all plugins in
`~/.pyshrc.d/`, so Python-native settings have the final word over the
shell-syntax startup layers.

The generated template documents every configurable option inline with
comments. Open it to see the current options:

```sh
${EDITOR:-nano} ~/.pyshrc.py
```

The file exports a single `configure(shell)` function. PySH calls it once
with the live shell instance:

```python
def configure(shell):
    # Prompt segments
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_last_status", True)
    shell.set_prompt_option("cwd_style", "home")

    # Per-segment prompt colors (named colors or #RRGGBB)
    shell.set_prompt_color("cwd", "cyan")
    shell.set_prompt_color("git", "#888888")

    # Terminal cursor color (disabled by default)
    shell.set_cursor_color_enabled(True)
    shell.set_cursor_color("#FFA500")

    # Line editor behavior
    shell.set_editor_option("autosuggest", True)
    shell.set_editor_option("syntax_highlight", True)

    # Aliases
    shell.register_alias("ll", "ls --color=auto -laF")
```

The `configure` function is optional; an empty file or a file that defines no
`configure` function is silently ignored without error.

## Terminal Color Overrides

PySH enables ANSI colors by default on capable TTYs and disables them for
`TERM=dumb`, non-TTY output, and `NO_COLOR`.

- `NO_COLOR`: disable ANSI color output.
- `PYSH_COLOR=0`: disable PySH ANSI color output.
- `PYSH_COLOR=1`: enable colors when the terminal is capable.
- `PYSH_COLOR=always`: force ANSI output, useful for terminal smoke tests.

## Aliases

```sh
alias ll="ls -la --color=auto -F"
alias gs="git status -sb"

# Remove an alias:
unalias ll
```

Aliases are expanded on the first word of each pipeline stage only.

Simple zsh-compatible alias files can be imported without executing them:

```sh
source_zsh ~/.zsh_aliases
source_zsh_profile ~/.zshrc
source_sh_aliases ~/.bash_aliases
```

## Completion

Completion Engine v1 is configured by current PySH state rather than foreign
shell startup files. It uses PySH aliases, builtins, local variables,
environment variable names, job IDs and local filesystem/PATH state.

PySH does not source bash, zsh or fish completion scripts and does not support
programmable shell completion hooks.

`source_zsh` supports simple `alias NAME=VALUE` lines, ignores comments and
blank lines, skips unsupported zsh constructs, and reports malformed alias
lines deterministically.

`source_zsh_profile` and `source_sh_aliases` use the current static profile
importer. They support simple aliases, `export NAME=value` statements and
local `NAME=value` assignments. They read files as text and never execute
profile code, command substitution, shell functions, plugin loaders or
external commands.

## Exports and local variables

```sh
NAME=world           # local shell variable
export EDITOR="nano" # exported environment variable
echo "$EDITOR - $NAME"
```

Local variables shadow environment variables in `$NAME` / `${NAME}`
expansion. Single quotes suppress expansion; double quotes do not.

## Prompt

The default prompt uses two lines: an informational line followed by a command
line prompt. With no opt-in segments enabled it renders as:

```text
<icon> <user>:<cwd>
>
```

`<cwd>` is the absolute current directory by default. The icon is the snake
emoji on UTF-8 terminals and `$` otherwise.

Python-native configuration can opt into additional prompt segments:

```python
def configure(shell):
    shell.set_prompt_option("show_host", True)
    shell.set_prompt_option("show_virtualenv", True)
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_git_dirty", True)
    shell.set_prompt_option("show_python_version", True)
    shell.set_prompt_option("show_uv_version", True)
    shell.set_prompt_option("show_ruff_version", True)
    shell.set_prompt_option("show_last_status", True)
    shell.set_prompt_option("cwd_style", "home")
    shell.set_prompt_option("prompt_layout", "single")
```

`cwd_style` accepts `full`, `home`, or `basename`. `prompt_layout` accepts
`two_line` (default) or `single`. Git prompt metadata is read from `.git` files
only; PySH does not invoke `git` while rendering prompts. uv and Ruff versions
are detected with bounded subprocess calls and cached per shell instance.

The welcome banner and diagnostics use ANSI colors when:

- stdout is a TTY,
- `NO_COLOR` is not set,
- `TERM` is set and is not `dumb`.

Trace diagnostics are not configured from startup files. They are enabled only
by explicit CLI flags such as `pysh --debug -c "echo hi"` or
`pysh --trace -c "echo hi"`. Trace output goes to stderr and sensitive values
are redacted.

Script mode does not load extra startup files for each script. It executes the
explicit script path supplied on the command line and does not source
`.bashrc`, `.zshrc` or `.profile`.

When the stdlib raw-mode editor is active, PySH can colorize the editable input
line and show history autosuggestions. If the terminal is not capable, if
`TERM=dumb`, if `NO_COLOR` is set, or if `line_editor="readline"` is configured,
PySH falls back to the classic readline/input path without live input coloring.

## Cursor Color

Python-native configuration can request a terminal cursor color:

```python
def configure(shell):
    shell.set_cursor_color_enabled(True)
    shell.set_cursor_color("#FF9900")
```

Cursor color is disabled by default. When enabled, PySH emits OSC 12 after
`~/.pyshrc.py` is loaded and resets the cursor with OSC 112 on shell exit. The
control sequence is emitted only for interactive TTY output when `TERM` is set
and not `dumb`, and `NO_COLOR` is not set. Terminals that do not implement OSC
12 simply ignore the request.

`set_cursor_color()` accepts the same named colors and `#RRGGBB` values as
prompt colors. Named colors are stored as canonical uppercase hex; for example,
`orange` becomes `#FFA500`.

## `~/.pyshrc` example

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
```

Plugins may also contain multiline Python automation blocks. The block
opener `py {` starts a deterministic multiline collection that ends at the
next line containing `}`:

```sh
# ~/.pyshrc.d/30-py-banner.pysh
py {
    import platform
    print(f"# host={platform.node()} python={platform.python_version()}")
}
```

To opt into zsh fallback for one interactive session, set the variable or use
the builtin explicitly. Fallback is off unless configured:

```sh
PYSH_ZSH_FALLBACK=1
zsh_fallback on
```

This is a transition setting. It does not turn PySH into a zsh clone; it only
allows commands PySH cannot parse or execute natively to be delegated through
the zsh compatibility bridge.

## Midnight Commander

PySH wraps the `mc` command so Midnight Commander is launched with a policy that
matches MC's shell-specific subshell support.  MC does not generically support
arbitrary custom shells as concurrent subshells; `$SHELL=/path/to/pysh` alone is
not sufficient.

Configure the policy in `~/.pyshrc.py`:

```python
def configure(shell):
    shell.set_mc_integration("auto")
    shell.set_mc_warning_enabled(True)
```

Modes:

| Mode | Behavior |
|---|---|
| `auto` | Default.  Use safe no-subshell launch behavior when PySH is not a supported MC subshell. |
| `safe` | Always add `-u` / disable MC concurrent subshell for wrapped `mc`. |
| `subshell` | Pass wrapped `mc` through unchanged. |
| `off` | Disable PySH's wrapper policy. |

`mc -u` disables MC's concurrent subshell.  Explicit paths such as `/usr/bin/mc`
bypass the PySH builtin wrapper.  In `mc -u`, Ctrl+O only shows the previous
terminal screen; it is not a live interactive PySH prompt.

`auto` mode prints one explanatory warning per PySH session.  Suppress it with:

```python
def configure(shell):
    shell.set_mc_warning_enabled(False)
```

## Plugin directory: `~/.pyshrc.d/*.pysh`

Files in `~/.pyshrc.d/` are loaded **after** `~/.pyshrc`, in
lexicographic order. Use a numeric prefix to control layering:

```
~/.pyshrc.d/
├── 10-aliases.pysh
├── 20-exports.pysh
└── 90-overrides.pysh
```

Example `~/.pyshrc.d/10-aliases.pysh`:

```sh
alias gs="git status -sb"
alias gd="git diff"
alias gl="git log --oneline --decorate"

if [ -f ~/.work_aliases ]; then
    source ~/.work_aliases
fi
```

Rules:

- Only regular files whose name ends with `.pysh` are loaded.
- Directories and other suffixes are ignored.
- One broken plugin does not abort the loading loop; the error is reported
  and the next plugin still runs.

## Mini rc-interpreter

| Construct                                  | Notes                                |
| ------------------------------------------ | ------------------------------------ |
| `if [ <cond> ]; then ... fi`               | `else` block is optional             |
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

## PyInit service metadata

`~/.config/pyinit/services/*.service` files describe services that the
`svc` builtin can manage:

```
name: example
command: python3.13 -m http.server 8080
depends: [network]
```

Recognised fields:

- `name`     — required identifier.
- `command`  — required launch command line.
- `depends`  — optional list of dependency names; accepts `[a, b]` or
  comma-separated form.

This is metadata support for PyInit integration, **not** a complete
replacement for systemd.

## History

Persistent history is written to `~/.pysh_history`. Length is capped at
10,000 entries. When GNU readline is available, **Ctrl+R** opens
Bash-like reverse incremental search.
