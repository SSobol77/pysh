<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/syntax-highlighting.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Syntax Highlighting

PySH can colorize editable interactive input when the raw-mode line editor is
active. Highlighting is presentation only: it never changes the command buffer,
never expands variables, never evaluates Python expressions, and never executes
commands while classifying input.

## Highlighted Input

The live line editor highlights these shell input roles:

| Role | Meaning |
| ---- | ------- |
| `builtin` | PySH builtin command in command position. |
| `alias` | Alias name in command position. Builtins take precedence. |
| `command_valid` | External command found by safe `PATH` lookup. |
| `command_invalid` | Command-position token not known as builtin, alias, or external command. |
| `string` | Single-quoted or double-quoted string. |
| `operator` | Shell operators and redirections such as `|`, `&&`, `>`, `<<`, and `<<-`. |
| `option` | Non-command tokens beginning with `-`. |
| `variable` | Shell variable references such as `$HOME`, `${HOME}`, `$?`, and `$1`. |
| `path` | Path-like tokens containing `/` or beginning with `~` or `.`. |
| `comment` | Comments beginning with `#` outside quotes at a token boundary. |
| `heredoc` | Here-document delimiter token following `<<` or `<<-`. |
| `error` | Visual role reserved for malformed input feedback. |
| `continuation` | Visual role for multiline continuation state. |
| `paste` | Visual role for staged paste state. |
| `reverse_search` | Visual role for reverse-search state. |

PySH does not implement a full Bash, Zsh, or Fish highlighter. It does not
perform command substitution, glob expansion, variable expansion, shell
evaluation, Python evaluation, plugin execution, network access, or unbounded
filesystem scanning during highlighting.

## Visual States

Staged multiline paste is displayed as a framed preview block with line numbers
and explicit actions. The payload can be syntax-highlighted, but it is not
executed until the user explicitly presses Enter or runs `paste_run`.

Reverse search (`Ctrl+R`) uses a separate one-line display that distinguishes
the search label, current match, and query. If a multiline paste is pending,
reverse search is blocked and PySH prints a pending-paste diagnostic instead.

Multiline Python blocks and heredoc bodies use continuation prompts such as
`py> ` and `heredoc> `. These prompts are state markers only; completion,
autosuggest, and syntax highlighting are disabled while collecting continuation
body lines.

## Color Configuration

Configure live-input colors in `~/.pyshrc.py`:

```python
def configure(shell):
    shell.set_highlight_color("builtin", "aqua")
    shell.set_highlight_color("alias", "fuchsia")
    shell.set_highlight_color("comment", "gray")
    shell.set_highlight_color("heredoc", "yellow")
```

`set_highlight_color(role, color)` validates both arguments. Unknown roles are
rejected. Invalid colors are rejected using the same parser as prompt colors.
Supported named colors include `black`, `silver`, `gray`, `white`, `maroon`,
`red`, `purple`, `fuchsia`, `green`, `lime`, `olive`, `orange`, `yellow`,
`navy`, `blue`, `teal`, and `aqua`. `#RRGGBB` values are also accepted.

Disable live input highlighting while keeping the raw editor:

```python
def configure(shell):
    shell.set_editor_option("syntax_highlight", False)
```

Force the classic input path:

```python
def configure(shell):
    shell.set_editor_option("line_editor", "readline")
```

## No-Color and Dumb Terminal Behavior

PySH suppresses ANSI color output when `NO_COLOR` is set, when `PYSH_COLOR=0`,
when `TERM=dumb`, or when output is not a capable TTY. The input remains plain
text. Paste previews, reverse-search labels, and continuation prompts keep
plain-text markers so the state is still understandable without color.

`PYSH_COLOR=always` may be used for terminal smoke tests, but `NO_COLOR` still
wins.

## Accessibility Notes

Default roles avoid dim-white and dark-blue SGR sequences because they are
unreadable on common dark terminal themes. Important states use text markers as
well as color. Users who need a higher-contrast palette should configure roles
with `set_highlight_color()`.

## Manual Validation Checklist

Run these checks in a capable terminal:

```sh
uv run pysh
echo "$HOME" # comment
cat <<EOF
payload
EOF
```

Also validate:

- builtin, alias, external, and unknown command colors are distinct;
- `#` inside quotes is not highlighted as a comment;
- staged multiline paste shows a preview and waits for explicit execution;
- `Ctrl+R` displays reverse-search query and match separately;
- `TERM=dumb uv run pysh` remains readable without ANSI color;
- `NO_COLOR=1 uv run pysh` remains readable without ANSI color;
- Unicode input and long lines do not corrupt cursor placement.
