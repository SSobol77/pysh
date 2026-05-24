<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
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

`source_zsh` supports simple `alias NAME=VALUE` lines, ignores comments and
blank lines, skips unsupported zsh constructs, and reports malformed alias
lines deterministically.

`source_zsh_profile` and `source_sh_aliases` use the 0.2.2 static profile
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

The prompt is rendered as `<icon> <user>:<cwd>$ ` where `<cwd>` is
collapsed to `~` when inside your home directory. The icon is the snake
emoji on UTF-8 terminals and `$` otherwise.

The welcome banner and diagnostics use ANSI colors when:

- stdout is a TTY,
- `NO_COLOR` is not set,
- `TERM` is set and is not `dumb`.

The input line is intentionally left uncolored so editing remains stable
across terminals.

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

echo "PySH 0.3.0 | Python 3.13+"
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
