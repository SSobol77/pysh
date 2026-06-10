<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/configuration.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Configuration

This page describes PySH's current configuration behavior and the Issue #31
configuration strategy. Status labels are intentional:

- **Current behavior** means implemented in the current codebase.
- **Issue #31 planned behavior** means the target design for the next
  configuration-system implementation.
- **Future / out of scope** means intentionally not part of Issue #31.

## Configuration Model

### Current behavior

PySH currently supports four startup layers:

1. `${XDG_CONFIG_HOME}/pysh/config.toml` or `~/.config/pysh/config.toml` -
   declarative TOML data loaded without command execution.
2. `~/.config/pysh/conf.d/*.toml` - declarative TOML drop-ins loaded in
   deterministic lexical order.
3. `~/.pyshrc` - shell-syntax startup file interpreted by PySH.
4. `~/.pyshrc.d/*.pysh` - shell-syntax drop-ins loaded in deterministic
   lexicographic order.
5. `~/.pyshrc.py` - Python-native configuration through `ShellConfigAPI`.

PySH creates `~/.pyshrc.py` from a commented template on first interactive
launch only when the file does not already exist. Existing user configuration
is not overwritten.

### Current Issue #31 behavior

Issue #31 implements a two-layer primary configuration model:

1. Declarative TOML configuration:
   - `${XDG_CONFIG_HOME}/pysh/config.toml`
   - fallback: `~/.config/pysh/config.toml`
   - drop-ins: `~/.config/pysh/conf.d/*.toml`
2. Advanced Python configuration:
   - `~/.pyshrc.py`
   - `ShellConfigAPI`
   - startup hooks and programmable behavior

TOML is the primary safe declarative format. `.pyshrc.py` remains the advanced
programmable layer. Existing `.pyshrc`, `.pyshrc.d`, and `.pyshrc.py`
compatibility remains intact.

## Load Order

### Current behavior

Current interactive startup loads:

1. built-in defaults;
2. `~/.pyshrc`;
3. `~/.pyshrc.d/*.pysh` in lexical order;
4. `${XDG_CONFIG_HOME}/pysh/config.toml` or `~/.config/pysh/config.toml`;
5. `~/.config/pysh/conf.d/*.toml` in lexical order;
6. `~/.pyshrc.py`;
7. Python config startup hooks;
8. Plugin API startup hooks after plugin discovery.

Invalid legacy rc lines are reported and the remaining file continues where
possible. A broken Python config is reported on stderr and does not terminate
the shell.

Runtime session changes do not rewrite user files automatically.

## TOML Declarative Configuration

### Current behavior

The primary declarative file is:

```text
${XDG_CONFIG_HOME}/pysh/config.toml
```

If `XDG_CONFIG_HOME` is unset, PySH uses:

```text
~/.config/pysh/config.toml
```

Planned drop-ins:

```text
~/.config/pysh/conf.d/*.toml
```

Drop-ins load in lexical order. Later files override earlier declarative
values. Invalid TOML reports readable diagnostics and does not crash shell
startup.

Example:

```toml
# ~/.config/pysh/config.toml

[profile]
active = "developer"

[theme]
active = "default"

[prompt]
prompt_layout = "two_line"
show_git_branch = true
show_python_version = true
show_last_status = true

[editor]
line_editor = "auto"
autosuggest = true
syntax_highlight = true

[history]
max_length = 10000
dedup_mode = "consecutive"
ignore_space_prefix = true

[colors.prompt]
cwd = "yellow"
git = "green"
symbol = "white"

[colors.highlight]
builtin = "aqua"
alias = "fuchsia"
comment = "gray"
heredoc = "yellow"

[alias_packs]
enabled = ["git", "python"]

[aliases]
ll = "ls -la --color=auto -F"
gs = "git status --short"

[env]
EDITOR = "nano"
PAGER = "less"
```

TOML is data only. It does not execute commands, evaluate shell expressions,
evaluate Python expressions, expand variables, load plugins, or run startup
hooks.

## Plugin Configuration Files

### Current behavior

Each plugin may optionally have a dedicated TOML configuration file stored
next to the main config directory:

```text
${XDG_CONFIG_HOME}/pysh/plugins/<plugin-name>.toml
~/.config/pysh/plugins/<plugin-name>.toml  (fallback)
```

Plugin config files are discovered automatically.  A missing file is not an
error.  An invalid file produces diagnostics on startup and is skipped without
crashing the shell.

Example plugin config file:

```toml
# ~/.config/pysh/plugins/example.toml

[plugin]
name = "example"

[settings]
enabled_feature = true
mode = "safe"
max_items = 100

[colors]
status = "aqua"

[env]
# plugin-specific environment-like settings (not applied to the process
# environment unless the plugin code does so explicitly)
```

**Security rules for plugin TOML files:**

- Plugin TOML files are **data only**.
- They do **not** execute commands.
- They do **not** evaluate shell or Python expressions.
- They do **not** load or enable plugin code by themselves.
- They do **not** enable project-local plugins.
- They do **not** access the network.
- Invalid plugin TOML does not crash shell startup.
- Secret-like values (`TOKEN`, `SECRET`, `KEY`, etc.) are masked in diagnostics.

**Plugin activation remains separate from plugin configuration.**  A plugin
TOML file may configure a plugin, but it does not cause the plugin to load or
execute.  Plugins are enabled only through `shell.enable_plugin("name")` in
`~/.pyshrc.py`.

Plugin config files are read through the same non-executing TOML loader as the
main config.  Plugin settings are available to the plugin at runtime through
`shell.get_plugin_config("name")` or `ShellConfigAPI.get_plugin_config("name")`.

Plugin file stem names must be safe identifiers: lowercase letters, digits,
`_`, `-`, and `.`.  Uppercase names and path separators are rejected.

If `[plugin].name` is declared in the file, it must match the file stem.  A
mismatch is a diagnostic, not a crash.

Use `config_check --locations` to see all discovered plugin config files.

## Advanced `.pyshrc.py` Configuration

### Current behavior

`~/.pyshrc.py` is implemented. It defines an optional `configure(shell)`
function that receives a `ShellConfigAPI` instance:

```python
def configure(shell):
    shell.alias("ll", "ls -la --color=auto -F")
    shell.env("EDITOR", "nano")
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_color("cwd", "yellow")
    shell.set_editor_option("syntax_highlight", True)
    shell.set_highlight_color("builtin", "aqua")
```

The Python file is trusted user code. Exceptions are caught and reported so a
broken configuration does not terminate the shell session.

`.pyshrc.py` remains the advanced programmable layer and runs after TOML. It
may override TOML-applied settings through `ShellConfigAPI`.

Startup hooks belong only in `.pyshrc.py`, not TOML:

```python
def configure(shell):
    def banner():
        print("Welcome to PySH")

    shell.register_startup_hook(banner)
```

Hook APIs do not run during TOML parsing or validation-only checks.

## Legacy `.pyshrc` And `.pyshrc.d`

### Current behavior

`~/.pyshrc` and `~/.pyshrc.d/*.pysh` are implemented. They use PySH's
mini-interpreter and support ordinary commands, `alias`, `export`, `source`,
pipelines, redirection, command substitution, and the documented `if` / `for`
 / `while` forms.

Example:

```sh
export EDITOR="nano"
export PAGER="less"

alias ll="ls -la --color=auto -F"
alias gs="git status -sb"
```

Legacy files remain compatible. They are not the primary new configuration
format, but Issue #31 must not break existing users.

## Profiles

### Current behavior

Profiles define behavior and prompt layout. They do not define aliases.
Built-in profiles:

| Profile | Purpose |
| ------- | ------- |
| `default` | Current PySH default behavior. |
| `minimal` | Quiet prompt and minimal visual noise. |
| `developer` | Daily software engineering prompt and editor behavior. |
| `server` | Remote/server-oriented prompt with clear user/host state. |
| `presentation` | Clean demo-friendly prompt. |
| `plain` | No icons and low ANSI dependence. |

TOML:

```toml
[profile]
active = "developer"
```

Custom profiles are defined under `[profiles.NAME]`. See
[themes.md](themes.md) for profile and theme examples.

## Themes

### Current behavior

Themes define visual style only. They are independent from profiles. A profile
may reference a theme, but users must be able to combine any profile with any
theme.

TOML:

```toml
[theme]
active = "default"
```

See [themes.md](themes.md) for built-in themes, custom theme syntax,
accessibility rules, no-color behavior, and relation to Issue #30 syntax
highlighting.

## Alias Packs

### Current behavior

Alias packs define named groups of simple aliases. Built-in packs
include `git`, `python`, `project`, and `files`.

TOML:

```toml
[alias_packs]
enabled = ["git", "python", "files"]
```

Rules:

- packs are additive;
- alias values are strings only;
- aliases are not executed during config load;
- unknown pack names are validation errors;
- no destructive aliases are enabled by default;
- project-local alias packs are not auto-enabled.

## Prompt Configuration

### Current behavior

Prompt options are configured through `ShellConfigAPI`:

```python
def configure(shell):
    shell.set_prompt_option("prompt_layout", "two_line")
    shell.set_prompt_option("show_git_branch", True)
    shell.set_prompt_option("show_last_status", True)
    shell.set_prompt_color("cwd", "yellow")
    shell.set_prompt_color("git", "green")
```

`prompt_layout` accepts `single` or `two_line`. `cwd_style` accepts `full`,
`home`, or `basename`. Prompt color names use the existing PySH color parser.

### Current behavior

TOML provides the declarative prompt layer while `.pyshrc.py` remains the
advanced override layer:

```toml
[prompt]
prompt_layout = "two_line"
show_user = true
show_host = true
show_cwd = true
show_git_branch = true
show_last_status = true

[colors.prompt]
user = "lime"
host = "aqua"
cwd = "yellow"
git = "green"
symbol = "white"
```

## Syntax-Highlight Color Configuration

### Current behavior

Issue #30 live-input highlight colors are configured in `~/.pyshrc.py`:

```python
def configure(shell):
    shell.set_highlight_color("builtin", "aqua")
    shell.set_highlight_color("alias", "fuchsia")
    shell.set_highlight_color("comment", "gray")
    shell.set_highlight_color("heredoc", "yellow")
```

See [syntax-highlighting.md](syntax-highlighting.md).

### Current behavior

TOML exposes the same semantic roles declaratively:

```toml
[colors.highlight]
builtin = "aqua"
alias = "fuchsia"
command_valid = "lime"
command_invalid = "red"
string = "green"
operator = "yellow"
option = "aqua"
variable = "fuchsia"
path = "aqua"
comment = "gray"
heredoc = "yellow"
error = "red"
continuation = "yellow"
paste = "yellow"
reverse_search = "fuchsia"
```

Invalid roles and invalid color values must be validation errors.

## Completion Configuration

### Current behavior

Completion is configured by shell state. It uses builtins, aliases, local
variables, environment variable names, job IDs, plugins, local paths, and safe
`PATH` lookup. TOML supports the same declarative completion options.

TOML:

```toml
[completion]
enabled = true
case_sensitive = false
show_hidden = false
menu = "compact"
```

Completion configuration must not source bash, zsh, or fish completion scripts.

## History Configuration

### Current behavior

History is stored as JSONL at `~/.pysh_history` by default. Options are
configured through `ShellConfigAPI`:

```python
def configure(shell):
    shell.set_history_option("max_length", 10000)
    shell.set_history_option("dedup_mode", "consecutive")
    shell.set_history_option("ignore_space_prefix", True)
    shell.set_history_option("ignore_patterns", ["password", "secret", "token", "api_key"])
```

### Current behavior

TOML:

```toml
[history]
max_length = 10000
dedup_mode = "consecutive"
ignore_space_prefix = true
ignore_patterns = ["password", "secret", "token", "api_key"]
```

Diagnostics must not print sensitive history filter values in a way that leaks
secrets.

## Environment Configuration

### Current behavior

Environment variables can be configured with `export` in rc files or
`shell.env()` in `.pyshrc.py`:

```python
def configure(shell):
    shell.env("EDITOR", "nano")
    shell.env("PAGER", "less")
```

### Current behavior

TOML:

```toml
[env]
EDITOR = "nano"
PAGER = "less"
```

Keys must be valid environment variable names and values must be strings.
TOML environment values must not perform shell expansion, command
substitution, or Python evaluation. Diagnostics must mask likely secret values.

## Startup Hooks Through `.pyshrc.py` Only

### Current behavior

User startup hooks belong only in `.pyshrc.py`. TOML must not define executable
hooks.

```python
def configure(shell):
    def after_startup():
        print("ready")

    shell.register_startup_hook(after_startup)
```

Hooks must not run during TOML parsing, TOML validation-only checks, syntax
highlighting, or documentation examples.

## Config Diagnostics

### Current behavior

Diagnostic builtins:

```text
config_check
config_reset
config_profile
config_theme
config_alias_pack
```

Expected diagnostic behavior:

- identify file path, section, key, and reason where practical;
- avoid printing secret values;
- report invalid TOML without crashing startup;
- show active config locations and effective values where safe.

## Config Reset

### Current behavior

`config_reset` resets runtime session state without overwriting user files.
Any future file-writing reset must require an explicit flag and must create a
backup first.

## Security Model

### Current behavior

`.pyshrc` and `.pyshrc.d/*.pysh` execute through PySH's rc interpreter.
`.pyshrc.py` is trusted Python user code. Static migration helpers read foreign
profile files as text and do not execute them.

TOML configuration must be non-executing:

- no shell command execution;
- no Python evaluation;
- no shell expression evaluation;
- no command substitution;
- no plugin execution;
- no project-local config auto-enable;
- no destructive aliases by default;
- no runtime dependency addition.

PySH uses Python 3.13 stdlib `tomllib` for reading TOML.

## Invalid Config Recovery

### Current behavior

Broken `.pyshrc.py` is caught and reported without terminating the shell.
Legacy rc parsing reports errors and continues where possible.

Invalid TOML must not crash PySH. The shell should fall back to defaults and
valid later layers where possible. Diagnostics should include:

- file path;
- section;
- key;
- safe value representation where appropriate;
- reason;
- valid values where practical.

Likely secret values must be redacted for names containing `TOKEN`, `SECRET`,
`PASSWORD`, `PASS`, `KEY`, `PRIVATE`, or `CREDENTIAL`.

## Migration From `.pyshrc.py`-Only Usage

### Current behavior

Users configure PySH behavior primarily through `.pyshrc.py` and legacy rc
files.

Users should move stable preferences into TOML and keep programmable behavior
in `.pyshrc.py`.

Example migration:

Current `.pyshrc.py`:

```python
def configure(shell):
    shell.set_prompt_option("show_git_branch", True)
    shell.set_editor_option("autosuggest", True)
    shell.set_highlight_color("builtin", "aqua")
    shell.alias("gs", "git status --short")
```

Planned TOML:

```toml
[prompt]
show_git_branch = true

[editor]
autosuggest = true

[colors.highlight]
builtin = "aqua"

[aliases]
gs = "git status --short"
```

Keep `.pyshrc.py` for logic that cannot be represented as declarative data.

## Future / Out Of Scope

These are not part of the current behavior and are not required for Issue #31
Part 1 documentation:

- browser or GUI configuration;
- theme marketplace;
- automatic project-local config enablement;
- writing TOML from every runtime setting;
- `config_check --fix`;
- destructive alias packs;
- requiring Nerd Fonts by default.

## Manual Validation Checklist

### Current behavior

```sh
uv run pysh -c "echo ok"
uv run pysh -c "exit"
uv run pysh -c "quit"
```

Manual checks:

- confirm `~/.pyshrc.py` is not overwritten when it already exists;
- confirm `shell.set_prompt_option()` errors are readable;
- confirm `shell.set_highlight_color()` rejects invalid roles and colors;
- confirm `NO_COLOR=1 uv run pysh` remains readable;
- confirm `TERM=dumb uv run pysh` falls back safely.

### Issue #31 planned behavior

After implementation, validate:

- `${XDG_CONFIG_HOME}/pysh/config.toml` load path;
- fallback `~/.config/pysh/config.toml` load path;
- lexical `conf.d/*.toml` override order;
- invalid TOML diagnostics;
- invalid profile/theme/alias-pack diagnostics;
- no execution from TOML values;
- `.pyshrc.py` overrides after TOML;
- user files are not overwritten;
- planned config diagnostic builtins do not print secret values.
