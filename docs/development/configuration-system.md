<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/configuration-system.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Configuration System Architecture

This document defines the Issue #31 configuration-system architecture.

## Status Labels

- **Current behavior**: implemented now.
- **Issue #31 behavior**: implemented Issue #31 configuration behavior.
- **Future / out of scope**: intentionally deferred.

## Current Behavior

Current startup configuration is owned by:

- `src/pysh/config/rc.py` for `~/.pyshrc` and `.pyshrc.d/*.pysh`;
- `src/pysh/config/api.py` for `ShellConfigAPI`;
- `src/pysh/config/paths.py` for XDG path resolution;
- `src/pysh/config/toml_loader.py` for non-executing TOML parsing;
- `src/pysh/config/schema.py` for declarative validation and application;
- `src/pysh/config/profiles.py` for profile definitions and inheritance;
- `src/pysh/config/themes.py` for theme definitions and inheritance;
- `src/pysh/config/alias_packs.py` for built-in alias packs;
- `src/pysh/config/diagnostics.py` for config diagnostics;
- `src/pysh/core/shell.py` for applying shell state;
- plugin loading after user configuration.

TOML parsing, validation, diagnostics, registries, and shell application are
kept as separate responsibilities.

## Issue #31 Load Order

Implemented interactive load order:

1. built-in defaults;
2. built-in profile, theme, and alias-pack definitions;
3. legacy compatibility files;
4. primary TOML: `${XDG_CONFIG_HOME}/pysh/config.toml`, falling back to
   `~/.config/pysh/config.toml`;
5. TOML drop-ins: `~/.config/pysh/conf.d/*.toml` in lexical order;
6. `~/.pyshrc.py` advanced overrides through `ShellConfigAPI`;
7. Python config startup hooks;
8. plugin startup hooks;
9. runtime session changes.

Invalid TOML must not crash startup. Valid later layers should still apply
where possible.

## Module Ownership

Implemented modules:

| Module | Ownership |
| ------ | --------- |
| `src/pysh/config/paths.py` | XDG path resolution and config location discovery. |
| `src/pysh/config/toml_loader.py` | Read TOML files with stdlib `tomllib`; no validation side effects. |
| `src/pysh/config/schema.py` | Validate sections, keys, value types, enums, and color names. |
| `src/pysh/config/themes.py` | Built-in and user theme definitions; inheritance and collision rules. |
| `src/pysh/config/profiles.py` | Built-in and user profile definitions; profile inheritance. |
| `src/pysh/config/alias_packs.py` | Built-in alias packs and alias-pack validation. |
| `src/pysh/config/diagnostics.py` | User-facing diagnostic records and formatting. |

Parsing, validation, and application remain separate.

## TOML Loading

Issue #31 uses Python 3.13 stdlib `tomllib` for TOML reading.

Forbidden runtime dependencies:

- `tomli`;
- `tomli-w`;
- `pydantic`;
- `dynaconf`;
- `omegaconf`;
- `hydra`;
- any other configuration framework.

`toml_loader.py` parses files as data only. It does not execute commands,
perform shell expansion, evaluate Python, load plugins, or mutate `PyShell`.

## Validation Ownership

`schema.py` owns declarative validation:

- unknown sections;
- unknown keys;
- invalid value types;
- invalid enum values;
- invalid prompt option names;
- invalid editor option names;
- invalid history option names;
- invalid color roles and values;
- invalid alias names;
- invalid environment variable names;
- unknown profile/theme/alias-pack names.

Existing validators in `src/pysh/config/api.py` should be reused where they
are already the public contract for prompt, editor, history, prompt color,
cursor color, sensitive-input, and syntax-highlight color options.

## Diagnostics Ownership

`diagnostics.py` should define structured diagnostics with:

- severity;
- file path;
- section;
- key;
- safe value representation;
- reason;
- suggested valid values where practical.

Secret-like values must be redacted for names containing:

```text
TOKEN
SECRET
PASSWORD
PASS
KEY
PRIVATE
CREDENTIAL
```

Diagnostics must be readable on dumb terminals and must not require ANSI color.

## Interaction With `ShellConfigAPI`

TOML application uses the same validated mutation paths as
`ShellConfigAPI` where practical. `.pyshrc.py` remains the advanced override
layer and runs after TOML.

Startup hooks belong only to `.pyshrc.py`. TOML must not define executable
hooks.

## Interaction With `PyShell`

`PyShell` orchestrates configuration load order but does not own TOML
parsing or schema validation. It receives validated settings and applies
them through explicit mutation paths.

Runtime session changes must not rewrite TOML automatically.

## Interaction With Prompt Colors

Prompt color configuration reuses `src/pysh/prompt/colors.py` parsing and
the current prompt color role validation in `src/pysh/config/api.py`.

TOML examples should use supported color names such as `aqua`, `fuchsia`,
`yellow`, `green`, `lime`, `orange`, `red`, `gray`, and `white`.

## Interaction With Issue #30 Highlight Colors

Issue #30 introduced semantic live-highlight roles. Issue #31 exposes
those roles declaratively under `[colors.highlight]` while preserving
`shell.set_highlight_color(role, color)` in `.pyshrc.py`.

Applying highlight colors must not move live highlighting out of the editor
layer and must not change command parsing or execution semantics.

## Profiles

`profiles.py` models built-in and user-defined profiles. Profiles define
behavior and layout, not aliases.

Validation rules:

- unknown base profile is an error;
- cycles in profile inheritance are errors;
- profiles may reference themes;
- profiles must not define alias packs or aliases;
- missing profile keys inherit from the base profile or defaults.

## Themes

`themes.py` models built-in and user-defined themes. Themes define visual
style only.

Validation rules:

- unknown base theme is an error;
- cycles in theme inheritance are errors;
- unknown color keys are errors;
- invalid color values are errors;
- user theme collision with a built-in theme is rejected unless
  `override = true` is set.

Themes must not require Nerd Fonts or external commands.

## Alias Packs

`alias_packs.py` models built-in alias packs. Packs are independent from
profiles and themes.

Validation rules:

- unknown pack names are errors;
- alias names must be valid;
- alias values must be strings;
- alias values are never executed during config load;
- no destructive aliases are enabled by default;
- project-local alias packs are not auto-enabled.

## Plugin Configuration Architecture

### Paths

Plugin configuration files live in a dedicated subdirectory of the PySH config
directory:

```text
${XDG_CONFIG_HOME}/pysh/plugins/<plugin-name>.toml
~/.config/pysh/plugins/<plugin-name>.toml  (XDG fallback)
```

Path resolution functions in `src/pysh/config/paths.py`:

| Function | Purpose |
| -------- | ------- |
| `plugin_config_dir()` | Return the `plugins/` subdirectory path (XDG-aware). |
| `plugin_config_path(name)` | Return the path for one named plugin config. |
| `plugin_config_paths()` | Discover existing plugin TOML files in lexical order. |

### Data Model

`src/pysh/config/schema.py` defines:

```python
@dataclass(frozen=True)
class PluginConfig:
    name: str
    path: Path
    data: dict[str, Any]
    diagnostics: tuple[ConfigDiagnostic, ...]
```

`load_plugin_config(path)` loads and structurally validates one file.
`validate_plugin_name(name)` checks for safe plugin identifier syntax.

### Runtime Orchestration

`src/pysh/config/runtime.py` provides `load_plugin_configs()`, which:

1. discovers plugin TOML files via `plugin_config_paths()`;
2. skips and reports files with unsafe names;
3. loads each file through the non-executing TOML loader;
4. validates `[plugin].name` matches the file stem;
5. returns `dict[str, PluginConfig]`.

`apply_declarative_config()` calls `load_plugin_configs()` and stores the
result on `PyShell.plugin_configs` as `dict[str, dict[str, object]]`.

### Shell Runtime Storage

`PyShell` stores plugin configs in:

```python
self.plugin_configs: dict[str, dict[str, object]] = {}
```

Access through:

```python
def get_plugin_config(self, name: str) -> dict[str, object]:
    ...
```

The returned value is always a fresh copy. Callers may not mutate internal
state through the returned dict.

### API Surface

`ConfigurableShell` protocol and `ShellConfigAPI` expose:

```python
def get_plugin_config(self, name: str) -> dict[str, object]:
    ...
```

Plugin authors use this in `register(api)` to read their config data.

### Plugin Name Validation

Safe plugin names match the pattern:

```
^[a-z0-9][a-z0-9._-]*$
```

- Lowercase letters, digits, `_`, `-`, `.` only.
- Must start with a letter or digit.
- No uppercase, no path separators, no spaces.

### Plugin Config vs Plugin Activation

These are separate concerns:

| Concern | Mechanism |
| ------- | --------- |
| Plugin configuration | `plugins/<name>.toml` — data only |
| Plugin activation / trust | `shell.enable_plugin("name")` in `~/.pyshrc.py` |

A plugin config file does not cause its plugin to load or execute.  A plugin
file may be absent even when its plugin is enabled, and vice versa.

### Security Rules For Plugin TOML

Plugin TOML files must:

- contain data only;
- not execute commands;
- not evaluate shell or Python expressions;
- not enable project-local plugins;
- not access the network;
- not load plugin code by themselves;
- not apply `env` values to the process environment directly (plugins must do
  this explicitly from their `register` function if desired).

Invalid plugin TOML produces diagnostics and is skipped.  Shell startup is
not affected by a broken plugin config.

Secret-like values in plugin TOML diagnostics are redacted using the same
`safe_value_repr()` rules as main config diagnostics.

## Security Rules

TOML configuration must:

- execute no commands;
- evaluate no shell expressions;
- evaluate no Python expressions;
- perform no command substitution;
- load no plugins;
- run no startup hooks;
- perform no network calls;
- add no runtime dependencies;
- avoid project-local auto-enable behavior;
- preserve user files without rewriting them during startup.

## Migration Rules

Issue #31 preserves existing users:

- keep `.pyshrc`;
- keep `.pyshrc.d/*.pysh`;
- keep `.pyshrc.py`;
- keep `ShellConfigAPI`;
- do not overwrite existing user files;
- generate templates only when a target file does not exist;
- provide diagnostics and copy-paste migration snippets instead of rewriting
  user files automatically.

## Testing Strategy

Required test groups for implementation:

- path resolution for `XDG_CONFIG_HOME` and fallback paths;
- primary TOML loading;
- `conf.d/*.toml` lexical ordering;
- invalid TOML parse diagnostics;
- unknown section/key diagnostics;
- invalid value type diagnostics;
- prompt/editor/history/color schema validation;
- profile/theme/alias-pack validation;
- inheritance and cycle detection;
- redaction of secret-like values;
- `.pyshrc.py` override order after TOML;
- no command execution from TOML values;
- no file overwrite during startup;
- plugin config directory path resolution;
- plugin config discovery order;
- missing plugin config is not an error;
- valid plugin TOML loads as data;
- invalid plugin TOML produces diagnostic;
- unsafe plugin filename is rejected with diagnostic;
- `[plugin].name` mismatch produces diagnostic;
- `get_plugin_config()` returns a copy;
- plugin TOML does not enable or load plugins;
- `config_check --locations` includes plugin config paths;
- secret masking for plugin config diagnostics;
- docs consistency and manual validation notes.

## Implementation Notes

Runtime application is intentionally one-way: session changes and builtins do
not rewrite TOML files. `config_reset` resets in-memory state only.

## Future / Out Of Scope

Not required for Issue #31:

- GUI or browser configuration;
- network theme downloads;
- third-party configuration frameworks;
- project-local config auto-enable;
- automatic rewriting of user TOML;
- `config_check --fix`;
- theme marketplace.
