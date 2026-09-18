<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/themes.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Themes And Profiles

This page documents the Issue #31 user-facing profiles, themes, and alias
packs.

- **Current behavior** means implemented now.
- **Issue #31 planned behavior** means planned configuration strategy.
- **Future / out of scope** means not part of Issue #31.

## Current Behavior

PySH currently supports visual customization through `~/.pyshrc.py`:

```python
def configure(shell):
    shell.set_prompt_color("cwd", "yellow")
    shell.set_prompt_color("git", "green")
    shell.set_highlight_color("builtin", "aqua")
    shell.set_highlight_color("alias", "fuchsia")
```

Named themes, named profiles, and alias packs are also available through
declarative TOML.

## Issue #31 Behavior

Issue #31 separates three concepts:

| Concept | Responsibility |
| ------- | -------------- |
| Profile | Behavior and prompt layout. |
| Theme | Visual style only. |
| Alias pack | Optional alias groups. |

Profiles, themes, and alias packs are independent. A user should be able to
combine any profile with any theme and then choose zero or more alias packs.

Top-level TOML:

```toml
[profile]
active = "developer"

[theme]
active = "default"

[alias_packs]
enabled = ["git", "python"]
```

## Built-In Profiles

Built-in profiles:

| Profile | Purpose |
| ------- | ------- |
| `default` | Current PySH default behavior. |
| `minimal` | Quiet prompt and minimal visual noise. |
| `developer` | Daily software engineering profile. |
| `server` | Remote/server-oriented profile with prominent host state. |
| `presentation` | Clean readable profile for demos. |
| `plain` | No icons and low ANSI dependence. |

Profiles should not define aliases. A profile may reference a theme.

Custom profile example:

```toml
[profiles.focus]
base = "minimal"
theme = "nord"
description = "Quiet profile for focused work"

[profiles.focus.prompt]
prompt_layout = "single"
show_git_branch = true
show_python_version = false
show_node_version = false
show_rust_version = false
show_command_duration = true

[profiles.focus.editor]
autosuggest = true
syntax_highlight = true
```

## Built-In Themes

Built-in themes:

```text
default
minimal
dark
light
catppuccin-mocha
catppuccin-latte
tokyo-night
nord
gruvbox-dark
solarized-dark
solarized-light
plain
```

Theme rules:

- no theme may require external dependencies;
- no theme may require a Nerd Font;
- icon-heavy behavior must be controlled separately from color themes;
- dark and light terminal themes must both be readable;
- failure and error colors must be visually distinct;
- no-color mode must remain understandable.

## Custom Themes

Custom themes are defined under `[themes.NAME]`:

```toml
[themes.my-dark]
base = "dark"
description = "Personal dark terminal palette"

[themes.my-dark.colors.prompt]
user = "aqua"
host = "yellow"
cwd = "lime"
git = "fuchsia"
symbol = "white"

[themes.my-dark.colors.highlight]
builtin = "aqua"
alias = "fuchsia"
command_valid = "lime"
command_invalid = "red"
comment = "gray"
heredoc = "yellow"
error = "red"
```

Validation rules:

- `base` is optional;
- unknown base theme is an error;
- unknown color key is an error;
- invalid color value is an error;
- built-in theme name collisions are rejected unless `override = true` is set.

## Alias Packs

Alias packs provide convenience aliases without coupling them to profiles or
themes. Built-in packs include `git`, `python`, `project`, and `files`.

Example:

```toml
[alias_packs]
enabled = ["git", "python", "files"]

[aliases]
serve = "python -m http.server"
gs = "git status --short"
```

Safe default rules:

- packs are opt-in;
- packs are additive;
- project-local packs are not auto-enabled;
- alias values are not executed during config load;
- destructive aliases such as `rm -rf` are not included by default.

## No-Color And Dumb Terminal Behavior

### Current behavior

PySH suppresses ANSI color output when `NO_COLOR` is set, when `PYSH_COLOR=0`,
when output is not a capable TTY, or when `TERM=dumb`.

Themes must preserve readable plain-text structure when color is disabled.
Theme selection must not affect command execution, bracketed paste behavior, or
line editor eligibility.

The `plain` theme avoids icons and minimizes ANSI dependence.

## Accessibility Rules

Theme defaults must:

- avoid dim-white and dark-blue SGR defaults for important text;
- avoid relying only on gray for warnings or errors;
- keep error and status colors visually distinct;
- provide a readable light-terminal and dark-terminal path;
- work without a Nerd Font requirement;
- keep prompt, diagnostics, paste preview, reverse search, and syntax
  highlighting distinguishable without color.

## Theme Preview

`config_theme preview NAME` renders sample prompt,
diagnostic, paste-preview, reverse-search, and syntax-highlight lines. Preview
must be non-executing and must not write configuration files.

## Relation To Issue #30 Syntax Highlighting

Issue #30 added semantic live-highlight roles such as `builtin`, `alias`,
`comment`, `heredoc`, `paste`, and `reverse_search`.

### Current behavior

These roles are configured through `.pyshrc.py`:

```python
def configure(shell):
    shell.set_highlight_color("builtin", "aqua")
    shell.set_highlight_color("comment", "gray")
```

Themes provide defaults for both prompt colors and syntax-highlight
colors:

```toml
[colors.highlight]
builtin = "aqua"
alias = "fuchsia"
comment = "gray"
heredoc = "yellow"
paste = "yellow"
reverse_search = "fuchsia"
```

Theme application must not change parsing or execution semantics.

## Future / Out Of Scope

Not part of Issue #31:

- a theme marketplace;
- browser or GUI theme editor;
- requiring patched fonts by default;
- automatic project-local theme activation;
- downloading themes from the network during shell startup;
- destructive alias packs enabled by default.
