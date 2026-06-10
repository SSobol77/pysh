<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/issues/31-user-configuration-profiles-and-themes.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Issue #31 — User Configuration Profiles and Themes

## Goal

Build a professional, safe, modern user configuration system for PySH.

The configuration system must make PySH feel polished and easy to personalize while preserving deterministic behavior, explicit user control, and strong validation.

PySH should provide the convenience users like in modern shells and prompt systems:

* works out of the box;
* readable declarative configuration;
* good defaults;
* named profiles;
* named themes;
* alias packs;
* safe validation;
* clear diagnostics;
* no hidden command execution;
* no fragile state mutation;
* no mandatory external dependency.

The primary user-facing configuration format for Issue #31 is **TOML**.

The advanced programmable configuration surface remains **Python-native `.pyshrc.py`** through `ShellConfigAPI`.

This creates a two-layer model:

```text
Declarative layer:
  ~/.config/pysh/config.toml

Advanced programmable layer:
  ~/.pyshrc.py
```

TOML is for safe, declarative user preferences.
Python config is for advanced programmable behavior such as hooks.

This issue must not remove existing configuration compatibility. Existing `.pyshrc`, `.pyshrc.py`, and current config API behavior must continue to work.

---

## Product Direction

PySH should be better than traditional shell configuration in three ways:

1. **Safer than arbitrary shell startup files**

   * declarative TOML must not execute code;
   * invalid config must not crash the shell;
   * diagnostics must be readable.

2. **More pleasant than scattered shell variables**

   * one primary user config file;
   * optional structured drop-in files;
   * clear schema;
   * clear defaults;
   * clear validation.

3. **More professional than theme-only systems**

   * profiles define behavior/layout;
   * themes define visual style;
   * alias packs define command convenience;
   * diagnostics explain what is active and why.

---

## Research-Informed Design Notes

Design input considered:

* Fish-style user friendliness:

  * works out of the box;
  * syntax highlighting and completions should need minimal setup;
  * configuration should be discoverable;
  * optional drop-in files help organization.

* Fish-style config UX:

  * terminal/browser configuration is useful, but not required for this issue;
  * PySH should first implement a reliable terminal-native and file-based system.

* Starship-style configuration:

  * a single TOML file is easy to read, version-control, copy, and share;
  * presets and named palettes make customization approachable;
  * prompt configuration should be practical, not noisy.

* Python ecosystem practice:

  * TOML is already familiar to Python developers through `pyproject.toml`;
  * Python 3.13 provides `tomllib` for reading TOML without adding dependencies.

Design decision:

```text
Use TOML for declarative configuration.
Keep .pyshrc.py for advanced programmable configuration.
Do not add runtime dependencies.
Do not implement GUI/web configuration in this issue.
```

---

## Configuration File Model

### Primary Config File

Primary declarative config:

```text
~/.config/pysh/config.toml
```

Respect `XDG_CONFIG_HOME`:

```text
${XDG_CONFIG_HOME}/pysh/config.toml
```

Fallback:

```text
~/.config/pysh/config.toml
```

### Optional Drop-In Directory

Optional declarative drop-ins:

```text
~/.config/pysh/conf.d/*.toml
```

Rules:

* files are loaded in deterministic lexical order;
* later files override earlier values;
* invalid drop-ins report diagnostics but must not crash the shell;
* drop-ins are declarative only;
* drop-ins must not execute code.

### Advanced Python Config

Advanced programmable config remains:

```text
~/.pyshrc.py
```

Rules:

* `.pyshrc.py` remains supported;
* it is loaded after TOML config;
* it may override TOML-applied values through `ShellConfigAPI`;
* startup hooks and advanced logic belong here, not in TOML;
* errors must be caught and reported without crashing the shell.

### Legacy Config

Existing legacy config remains supported:

```text
~/.pyshrc
~/.pyshrc.d/
```

Issue #31 must not remove or break legacy behavior.

---

## Configuration Load Order

Required load order:

```text
1. Built-in defaults
2. Built-in profile/theme/alias-pack definitions
3. ~/.config/pysh/config.toml
4. ~/.config/pysh/conf.d/*.toml in lexical order
5. ~/.pyshrc.py advanced overrides
6. runtime session changes
```

Rules:

* defaults must always produce a usable shell;
* invalid user TOML must not crash shell startup;
* invalid `.pyshrc.py` must not crash shell startup;
* diagnostics must identify the file, section, key, value, and reason where possible;
* runtime session changes do not automatically rewrite user files.

---

## Primary TOML Schema

Example:

```toml
# ~/.config/pysh/config.toml

[profile]
active = "developer"

[theme]
active = "catppuccin-mocha"

[prompt]
style = "two-line"
show_user = true
show_host = true
show_cwd = true
show_git = true
show_python = true
show_rust = true
show_node = true
show_status = true
show_duration = true

[editor]
line_editor = "raw"
autosuggest = true
syntax_highlight = true
safe_paste = true

[completion]
enabled = true
case_sensitive = false
show_hidden = false
menu = "compact"

[history]
enabled = true
path = "~/.local/share/pysh/history"
max_length = 10000
dedupe_mode = "consecutive"

[colors.prompt]
user = "aqua"
host = "yellow"
cwd = "lime"
git = "fuchsia"
symbol = "white"

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

[alias_packs]
enabled = ["git", "python", "files"]

[aliases]
ll = "ls -la"
gs = "git status --short"

[env]
EDITOR = "ecli"
PAGER = "less"

[features]
project_plugins = false
```

---

## Built-In Profiles

Profiles define behavior and prompt layout.

Profiles must not define aliases.
Profiles may reference a theme.

Minimum built-in profiles:

### `default`

Current PySH default behavior.

### `minimal`

Quiet prompt and minimal visual noise.

Recommended:

```text
single-line prompt
no language version segments
no command duration unless slow
syntax highlighting enabled
autosuggest enabled
completion enabled
```

### `developer`

Daily software engineering profile.

Recommended:

```text
two-line prompt
git segment enabled
Python/Rust/Node/npm/uv/ruff segments enabled where available
command duration enabled
syntax highlighting enabled
autosuggest enabled
completion enabled
history enabled
```

### `server`

Remote/server-oriented profile.

Recommended:

```text
hostname prominent
user/host visible
cwd visible
git optional
language versions reduced
minimal color intensity
clear failure status
safe paste enabled
```

### `presentation`

Clean, readable, demo-friendly profile.

Recommended:

```text
high-contrast prompt
minimal noisy segments
clear command status
no long version segment list
syntax highlighting enabled
```

### `plain`

No icons and safe plain text.

Recommended:

```text
no Nerd Font requirement
ASCII-compatible prompt
low ANSI dependence
works well in simple terminals
```

---

## Built-In Themes

Themes define visual style only.

Themes must be independent from profiles.

A profile may reference a theme, but users must be able to combine any profile with any theme.

Minimum built-in themes:

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

Theme requirements:

* no theme may require external dependencies;
* no theme may require a Nerd Font;
* icon-heavy behavior must be controlled separately from color themes;
* dark and light terminal themes must both be readable;
* defaults must avoid low-contrast gray for important text;
* failure/error colors must be visually distinct;
* no-color mode must remain understandable.

---

## User-Defined Themes

Users may define custom themes in TOML:

```toml
[themes.my-dark]
base = "dark"
description = "My personal dark theme"

[themes.my-dark.colors.prompt]
user = "aqua"
host = "yellow"
cwd = "lime"
git = "fuchsia"
symbol = "white"

[themes.my-dark.colors.highlight]
builtin = "aqua"
alias = "fuchsia"
comment = "gray"
error = "red"
```

Rules:

* `base` is optional;
* if `base` is set, missing keys inherit from the base theme;
* unknown base theme is a validation error;
* unknown color key is a validation error;
* invalid color value is a validation error;
* user themes override built-in themes by name only if explicitly allowed.

For Issue #31, user theme name collision with a built-in theme must be rejected unless an explicit `override = true` field is present.

---

## User-Defined Profiles

Users may define custom profiles in TOML:

```toml
[profiles.focus]
base = "minimal"
theme = "nord"
description = "Quiet profile for writing and focused work"

[profiles.focus.prompt]
style = "single-line"
show_git = true
show_python = false
show_node = false
show_rust = false
show_duration = true

[profiles.focus.editor]
autosuggest = true
syntax_highlight = true
safe_paste = true
```

Rules:

* `base` is optional;
* if `base` is set, missing keys inherit from the base profile;
* unknown base profile is a validation error;
* unknown prompt/editor/completion/history keys are validation errors;
* profiles must not include aliases;
* profiles may reference themes.

---

## Alias Packs

Alias packs define useful command alias groups.

Minimum built-in alias packs:

### `git`

```text
gs  = git status --short
gd  = git diff
gl  = git log --oneline --decorate --graph -20
ga  = git add
gc  = git commit
gp  = git push
gb  = git branch
gco = git checkout
```

### `python`

```text
py     = python
pyv    = python --version
pip    = python -m pip
pytest = uv run pytest
venv   = python -m venv .venv
```

### `project`

```text
lint = uv run ruff check src tests
test = uv run pytest -q
fmt  = uv run ruff format src tests
```

### `files`

```text
ll = ls -la
la = ls -A
lt = tree
md = mkdir -p
```

Do not include dangerous aliases such as `rd = rm -rf` by default.

If a destructive alias pack is ever added, it must be opt-in and clearly named.

Alias pack rules:

* packs are additive;
* loading a pack does not remove existing aliases;
* later aliases overwrite earlier aliases only with diagnostics;
* unknown pack names are validation errors;
* alias values are strings only;
* aliases are not executed during config load;
* project-local alias packs are not auto-enabled.

---

## Environment Configuration

TOML may define environment variables:

```toml
[env]
EDITOR = "ecli"
PAGER = "less"
PYSH_EXPERIMENTAL = "0"
```

Rules:

* keys must be valid environment variable names;
* values must be strings;
* no shell expansion;
* no command substitution;
* no Python evaluation;
* no secrets should be printed by diagnostics;
* config check may list keys but must not print sensitive values for likely secret names.

Sensitive key detection must mask values for names containing:

```text
TOKEN
SECRET
PASSWORD
PASS
KEY
PRIVATE
CREDENTIAL
```

---

## Startup Hooks

Declarative TOML must not define executable startup hooks.

Startup hooks belong only in `.pyshrc.py`:

```python
def configure(shell):
    def hello():
        print("Welcome to PySH")

    shell.register_startup_hook(hello)
```

Rules:

* hooks run in registration order;
* one failing hook must not prevent later hooks;
* hook errors must be printed to stderr;
* hooks must not run during config validation-only mode;
* hooks must not run during syntax highlighting;
* hooks must not run while parsing TOML.

---

## Config Diagnostics

Add diagnostic commands.

Required builtins:

```text
config_check
config_reset
config_profile
config_theme
config_alias_pack
```

### `config_check`

Usage:

```text
config_check
config_check --validate
config_check --diff
config_check --locations
```

Behavior:

* no args: print active config summary;
* `--validate`: validate current config state;
* `--diff`: show differences from defaults;
* `--locations`: show all config files considered and whether they were loaded;
* return `0` if valid;
* return `1` if validation issues are found;
* do not print secret values.

### `config_reset`

Usage:

```text
config_reset [target]
```

Targets:

```text
all
prompt
editor
history
completion
colors
highlight
cursor
aliases
```

Behavior:

* no arg defaults to `all`;
* resets runtime session state;
* must not overwrite user TOML unless an explicit future `--write` flag is implemented;
* if file reset is implemented, it must create a backup first.

### `config_profile`

Usage:

```text
config_profile list
config_profile show NAME
config_profile use NAME
```

Behavior:

* `list`: print available profiles;
* `show`: print profile contents;
* `use`: apply profile to current shell session;
* no implicit file write.

### `config_theme`

Usage:

```text
config_theme list
config_theme show NAME
config_theme preview NAME
config_theme use NAME
```

Behavior:

* `list`: print available themes;
* `show`: print theme contents;
* `preview`: render sample prompt/highlight lines;
* `use`: apply theme to current shell session;
* no implicit file write.

### `config_alias_pack`

Usage:

```text
config_alias_pack list
config_alias_pack show NAME
config_alias_pack load NAME
```

Behavior:

* `list`: print available packs;
* `show`: print aliases in pack;
* `load`: load aliases into current shell session;
* no implicit file write.

---

## TOML Loader Requirements

Create or extend:

```text
src/pysh/config/paths.py
src/pysh/config/toml_loader.py
src/pysh/config/schema.py
src/pysh/config/themes.py
src/pysh/config/profiles.py
src/pysh/config/alias_packs.py
src/pysh/config/diagnostics.py
```

Use `tomllib` from the Python standard library.

Do not add `tomli`, `tomli-w`, `pydantic`, `dynaconf`, `omegaconf`, `hydra`, or any other runtime dependency.

Rules:

* parse TOML as data;
* validate using explicit schema functions;
* report unknown keys;
* report invalid value types;
* report invalid enum values;
* report invalid color values;
* report invalid alias names;
* report invalid environment names;
* do not execute code from TOML;
* do not perform shell expansion;
* do not perform command substitution;
* do not evaluate Python expressions.

---

## Config Generation

On first run, if no primary config exists, PySH must generate:

```text
~/.config/pysh/config.toml
```

Generated config must:

* include helpful comments;
* include safe defaults;
* include examples for profiles/themes/alias packs;
* not enable unsafe project-local config;
* not enable destructive aliases;
* not overwrite existing files;
* create parent directories if needed;
* report generation only if startup diagnostics are enabled or first-run message is appropriate.

Do not rewrite existing config files during normal startup.

---

## Config Preservation

User edits must be preserved.

Rules:

* never rewrite existing `config.toml` during normal startup;
* never rewrite files in `conf.d/` during normal startup;
* `config_check --fix` is out of scope for this issue;
* if any command writes config in the future, it must create a backup first;
* this issue may print copy-paste snippets instead of modifying user files.

---

## Error Handling

Invalid config must not crash PySH.

Error output must include:

```text
file path
section
key
value when safe
reason
suggested valid values where practical
```

Example:

```text
pysh: config: ~/.config/pysh/config.toml: [theme].active: unknown theme 'draculla'
pysh: config: valid themes: default, dark, light, catppuccin-mocha, nord, tokyo-night
```

Rules:

* startup continues with defaults or last valid values;
* invalid drop-in file does not prevent other drop-ins from loading;
* invalid `.pyshrc.py` still reports through existing ConfigError path;
* secret values must be masked.

---

## Security Requirements

Hard rules:

* TOML config must not execute code;
* no shell evaluation from TOML;
* no Python evaluation from TOML;
* no command substitution from TOML;
* no network access during config load;
* no remote config sync;
* no project-local config auto-enable;
* no plugin enablement from project-local files unless explicitly configured by user;
* no destructive aliases enabled by default;
* no secret values printed in diagnostics;
* no dependency addition.

---

## Performance Requirements

Config loading must be fast.

Requirements:

* no network calls;
* no subprocess calls during config load;
* no scanning outside known config locations;
* deterministic lexical loading for drop-ins;
* TOML parsing must be bounded by file size;
* config diagnostics may be more detailed but must not affect normal startup latency heavily.

Recommended file-size guard:

```text
config.toml max: 256 KiB
each conf.d/*.toml max: 256 KiB
```

If exceeded, report a readable config error and skip the oversized file.

---

## Accessibility and UX Requirements

Themes must be readable.

Rules:

* dark and light themes must have reasonable contrast;
* error/failure must not rely only on dim styling;
* no-color mode must remain understandable;
* plain profile must not require icons;
* Nerd Font symbols must be opt-in;
* generated defaults must work in a basic terminal.

Theme preview should show:

```text
prompt sample
success symbol
failure symbol
valid command
invalid command
builtin
alias
path
string
comment
paste preview
reverse search
```

---

## Non-Goals

Do not implement:

* remote config sync;
* GUI config editor;
* browser-based config UI;
* online theme marketplace;
* automatic project-local config enablement;
* external runtime dependencies;
* Starship integration as a built-in dependency;
* Tide/Powerlevel10k clone;
* full prompt plugin ecosystem;
* automatic rewriting of user TOML;
* destructive alias packs;
* secrets manager;
* release metadata changes;
* version bump;
* GitHub workflow changes;
* package publication;
* Git tag;
* GitHub Release.

---

## Implementation Plan

### Phase 0 — Baseline Audit

Inspect current configuration system:

```text
src/pysh/config/api.py
src/pysh/config/rc.py
src/pysh/config/plugins.py
src/pysh/core/shell.py
src/pysh/editor/history.py
src/pysh/editor/completion.py
src/pysh/editor/lineedit/completion.py
src/pysh/prompt/colors.py
src/pysh/prompt/segments.py
docs/user/configuration.md
tests/test_pyshrc_py.py
```

Find current defaults:

```text
DEFAULT_PROMPT_OPTIONS
DEFAULT_EDITOR_OPTIONS
DEFAULT_PROMPT_COLORS
DEFAULT_PROMPT_COLOR_MODES
DEFAULT_CURSOR_OPTIONS
DEFAULT_HISTORY_PATH
DEFAULT_HISTORY_LENGTH
```

Do not refactor before completing this audit.

---

### Phase 1 — Config Paths and TOML Loader

Implement:

```text
src/pysh/config/paths.py
src/pysh/config/toml_loader.py
src/pysh/config/schema.py
```

Required behavior:

* resolve XDG config path;
* generate missing primary config;
* parse `config.toml`;
* parse `conf.d/*.toml`;
* deterministic lexical merge;
* validate schema;
* return structured config object;
* report diagnostics without crashing.

---

### Phase 2 — Config Schema and Defaults

Add declarative options for:

```text
profile
theme
prompt
editor
completion
history
colors.prompt
colors.highlight
alias_packs
aliases
env
features
```

Implement explicit validators.

No unknown key should silently pass.

Unknown keys must produce diagnostics.

---

### Phase 3 — Profiles

Create:

```text
src/pysh/config/profiles.py
```

Add:

```text
Profile dataclass
BUILTIN_PROFILES
validate_profile()
apply_profile()
list_profiles()
```

Minimum profiles:

```text
default
minimal
developer
server
presentation
plain
```

Profiles may reference themes.

Profiles must not define aliases.

---

### Phase 4 — Themes

Create:

```text
src/pysh/config/themes.py
```

Add:

```text
Theme dataclass
BUILTIN_THEMES
validate_theme()
apply_theme()
preview_theme()
list_themes()
```

Minimum themes:

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

Themes must include both prompt and syntax-highlight roles where appropriate.

---

### Phase 5 — Alias Packs

Create:

```text
src/pysh/config/alias_packs.py
```

Add:

```text
AliasPack dataclass
BUILTIN_ALIAS_PACKS
validate_alias_pack()
apply_alias_pack()
list_alias_packs()
```

Minimum packs:

```text
git
python
project
files
```

No destructive aliases by default.

---

### Phase 6 — ShellConfigAPI Extensions

Extend `ShellConfigAPI` with:

```python
set_profile(name: str) -> None
get_profiles() -> list[str]

set_theme(name: str) -> None
get_themes() -> list[str]
preview_theme(name: str) -> str

load_alias_pack(name: str) -> None
get_alias_packs() -> list[str]

set_history_option(name: str, value: object) -> None
set_completion_option(name: str, value: object) -> None

set_env(name: str, value: str) -> None
register_startup_hook(fn: Callable[[], None]) -> None

reset_config(target: str = "all") -> None
```

Validation must use `ConfigError`.

Errors must be caught by the existing config-loading path.

---

### Phase 7 — Builtins

Add builtins:

```text
config_check
config_reset
config_profile
config_theme
config_alias_pack
```

Each builtin must have:

* clear usage;
* deterministic exit code;
* tests;
* docs.

---

### Phase 8 — Default Config Template

Update default generated TOML template.

Add examples for:

* profiles;
* themes;
* alias packs;
* prompt;
* editor;
* completion;
* history;
* colors;
* environment;
* advanced `.pyshrc.py` hook note.

Do not overwrite existing config.

---

### Phase 9 — Documentation

Create or update:

```text
docs/user/configuration.md
docs/user/themes.md
docs/user/builtins.md
docs/development/configuration-system.md
docs/README.md
```

Documentation must include:

* file locations;
* load order;
* TOML schema;
* profile examples;
* theme examples;
* alias pack examples;
* no-color mode;
* accessibility notes;
* diagnostics;
* reset behavior;
* migration from `.pyshrc.py`;
* advanced Python config layer;
* manual validation checklist.

Every new Markdown file must include SPDX, `File:`, repository, PyPI, and copyright metadata.

---

## Tests Required

### New Tests

Create:

```text
tests/test_config_paths.py
tests/test_config_toml_loader.py
tests/test_config_schema.py
tests/test_profiles.py
tests/test_themes.py
tests/test_alias_packs.py
tests/test_config_check.py
```

### Extend Existing Tests

Extend:

```text
tests/test_pyshrc_py.py
tests/test_history.py
tests/test_completion.py
tests/test_docs_consistency.py
```

### Required Automated Coverage

Tests must cover:

* missing config generation;
* no overwrite of existing config;
* XDG config path resolution;
* TOML parse success;
* TOML parse error diagnostics;
* conf.d lexical load order;
* unknown key diagnostics;
* invalid type diagnostics;
* invalid enum diagnostics;
* profile selection;
* invalid profile;
* custom profile inheritance;
* theme selection;
* invalid theme;
* custom theme inheritance;
* color validation;
* alias pack loading;
* alias pack stacking;
* invalid alias pack;
* alias override diagnostics;
* env validation;
* secret masking in diagnostics;
* history config;
* completion config;
* reset runtime state;
* startup hook registration through `.pyshrc.py`;
* failing startup hook does not stop later hook;
* config_check output;
* config_check --validate;
* config_check --diff;
* config locations output;
* docs consistency.

### Manual Tests

Manual validation on Debian 13:

```text
first run with no config
first run with generated config
invalid TOML recovery
invalid color recovery
theme switching
profile switching
alias pack loading
config_check --validate
config_check --diff
no-color mode
TERM=dumb
```

Manual validation on FreeBSD 14+:

```text
first run with no config
config.toml load
theme preview
profile switching
history config
completion config
no GNU-specific dependency
```

---

## Validation Commands

Required focused validation:

```bash
uv run ruff check src tests
uv run pytest -q tests/test_config_paths.py
uv run pytest -q tests/test_config_toml_loader.py
uv run pytest -q tests/test_config_schema.py
uv run pytest -q tests/test_profiles.py
uv run pytest -q tests/test_themes.py
uv run pytest -q tests/test_alias_packs.py
uv run pytest -q tests/test_config_check.py
uv run pytest -q tests/test_pyshrc_py.py
uv run pytest -q tests/test_history.py
uv run pytest -q tests/test_completion.py
uv run pytest -q tests/test_docs_consistency.py
scripts/check_headers.sh
git diff --check
```

CLI smoke:

```bash
uv run pysh --version
uv run python -m pysh --version
uv run pysh -c "echo ok"
uv run pysh -c "config_check --validate"
uv run pysh -c "config_profile list"
uv run pysh -c "config_theme list"
uv run pysh -c "config_alias_pack list"
uv run pysh -c "exit"
echo "exit_rc=$?"
uv run pysh -c "quit"
echo "quit_rc=$?"
```

If focused validation passes, run:

```bash
uv run pytest -q
```

---

## Definition of Done

Issue #31 is complete when:

* `~/.config/pysh/config.toml` is supported;
* missing config generation works;
* existing config is not overwritten;
* `conf.d/*.toml` drop-ins work in deterministic order;
* invalid config does not crash PySH;
* config diagnostics are readable;
* profiles work;
* themes work;
* alias packs work;
* history config works;
* completion config works;
* prompt config works;
* syntax-highlight color config remains compatible with Issue #30;
* no-color and dumb terminal behavior remain safe;
* environment config works safely;
* startup hooks are supported only through `.pyshrc.py`;
* config reset works for runtime state;
* config_check works;
* docs are updated;
* tests pass;
* no runtime dependency is added;
* no version/dependency/workflow/release/license change is made.

---

## AI Agent Implementation Prompt

Use this prompt when implementing Issue #31.

```text
Your role: Senior Python shell/runtime engineer working on PySH and the wider ECLI platform direction.

Task:
Implement Issue #31 — User Configuration Profiles and Themes.

Before starting, read:

- AGENTS.md
- CODEX.md
- CLAUDE.md
- CURSOR.md
- docs/development/context-engineering.md
- docs/issues/31-user-configuration-profiles-and-themes.md

Repository authority:
- SSobol77 commits manually.
- Do not commit.
- Do not push.
- Do not merge.
- Do not tag.
- Do not publish.
- Do not open PRs.
- Do not bump versions.
- Do not change dependencies.
- Do not change workflows.
- Do not change license or release metadata.

Branch:
Use the branch assigned by SSobol77 for Issue #31.

Goal:
Build a safe, TOML-first user configuration system with profiles, themes, alias packs, diagnostics, and advanced Python config compatibility.

Primary design:
- TOML declarative config:
  ~/.config/pysh/config.toml
  ~/.config/pysh/conf.d/*.toml
- Advanced programmable config remains:
  ~/.pyshrc.py

Core requirements:
- use Python stdlib tomllib;
- do not add runtime dependencies;
- do not execute code from TOML;
- do not shell-evaluate TOML values;
- do not auto-enable unsafe project-local config;
- invalid config must not crash shell startup;
- errors must be readable;
- user edits must not be overwritten;
- generated default config must be safe and commented;
- profiles, themes, and alias packs must be independent;
- startup hooks belong to .pyshrc.py only;
- no destructive aliases by default.

Expected implementation areas:
- src/pysh/config/paths.py
- src/pysh/config/toml_loader.py
- src/pysh/config/schema.py
- src/pysh/config/themes.py
- src/pysh/config/profiles.py
- src/pysh/config/alias_packs.py
- src/pysh/config/diagnostics.py
- src/pysh/config/api.py
- src/pysh/core/shell.py
- src/pysh/editor/history.py
- src/pysh/editor/completion.py
- src/pysh/editor/lineedit/completion.py
- docs/user/configuration.md
- docs/user/themes.md
- docs/user/builtins.md
- docs/development/configuration-system.md
- docs/README.md
- tests/

If some listed files differ in the current repository, inspect the current repository structure and use the current equivalent files. Do not invent paths.

Required phases:
1. Audit current config system.
2. Add XDG config path resolver and TOML loader.
3. Add explicit TOML schema validation.
4. Add built-in profiles.
5. Add built-in themes.
6. Add alias packs.
7. Extend ShellConfigAPI.
8. Add config builtins.
9. Generate safe default config.toml.
10. Update docs.
11. Add comprehensive tests.
12. Run validation.

Required validation:
uv run ruff check src tests
uv run pytest -q tests/test_config_paths.py
uv run pytest -q tests/test_config_toml_loader.py
uv run pytest -q tests/test_config_schema.py
uv run pytest -q tests/test_profiles.py
uv run pytest -q tests/test_themes.py
uv run pytest -q tests/test_alias_packs.py
uv run pytest -q tests/test_config_check.py
uv run pytest -q tests/test_pyshrc_py.py
uv run pytest -q tests/test_history.py
uv run pytest -q tests/test_completion.py
uv run pytest -q tests/test_docs_consistency.py
scripts/check_headers.sh
git diff --check

CLI smoke:
uv run pysh --version
uv run python -m pysh --version
uv run pysh -c "echo ok"
uv run pysh -c "config_check --validate"
uv run pysh -c "config_profile list"
uv run pysh -c "config_theme list"
uv run pysh -c "config_alias_pack list"
uv run pysh -c "exit"
echo "exit_rc=$?"
uv run pysh -c "quit"
echo "quit_rc=$?"

If focused validation passes:
uv run pytest -q

Final report must include:
PASS/FAIL:
Branch:
Commit status:
Files changed:
Implementation summary:
TOML config summary:
Profile summary:
Theme summary:
Alias pack summary:
Config diagnostics summary:
Security notes:
Architecture notes:
Tests added:
Docs updated:
Validation commands:
Exact validation output:
Known limitations:
Unauthorized actions:
Proposed commit message:
Manual commit command for SSobol77:
git status --short:

Do not claim PASS unless validation actually passed.
```
