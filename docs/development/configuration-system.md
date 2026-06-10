<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/configuration-system.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Configuration System Architecture

This document defines the planned Issue #31 configuration-system architecture.
It is a strategy document, not an implementation record. Current implementation
still uses legacy rc files and `~/.pyshrc.py`.

## Status Labels

- **Current behavior**: implemented now.
- **Issue #31 planned behavior**: implementation target.
- **Future / out of scope**: intentionally deferred.

## Current Behavior

Current startup configuration is owned by:

- `src/pysh/config/rc.py` for `~/.pyshrc` and `.pyshrc.d/*.pysh`;
- `src/pysh/config/api.py` for `ShellConfigAPI`;
- `src/pysh/core/shell.py` for applying shell state;
- plugin loading after user configuration.

There is no TOML loader, profile registry, theme registry, or alias-pack
registry yet.

## Issue #31 Planned Load Order

Planned load order:

1. built-in defaults;
2. built-in profile, theme, and alias-pack definitions;
3. primary TOML: `${XDG_CONFIG_HOME}/pysh/config.toml`, falling back to
   `~/.config/pysh/config.toml`;
4. TOML drop-ins: `~/.config/pysh/conf.d/*.toml` in lexical order;
5. legacy compatibility files where retained by startup policy;
6. `~/.pyshrc.py` advanced overrides through `ShellConfigAPI`;
7. runtime session changes.

Invalid TOML must not crash startup. Valid later layers should still apply
where possible.

## Planned Module Ownership

Expected modules:

| Module | Ownership |
| ------ | --------- |
| `src/pysh/config/paths.py` | XDG path resolution and config location discovery. |
| `src/pysh/config/toml_loader.py` | Read TOML files with stdlib `tomllib`; no validation side effects. |
| `src/pysh/config/schema.py` | Validate sections, keys, value types, enums, and color names. |
| `src/pysh/config/themes.py` | Built-in and user theme definitions; inheritance and collision rules. |
| `src/pysh/config/profiles.py` | Built-in and user profile definitions; profile inheritance. |
| `src/pysh/config/alias_packs.py` | Built-in alias packs and alias-pack validation. |
| `src/pysh/config/diagnostics.py` | User-facing diagnostic records and formatting. |

Implementation should keep parsing, validation, and application separate.

## TOML Loading

Issue #31 must use Python 3.13 stdlib `tomllib` for TOML reading.

Forbidden runtime dependencies:

- `tomli`;
- `tomli-w`;
- `pydantic`;
- `dynaconf`;
- `omegaconf`;
- `hydra`;
- any other configuration framework.

`toml_loader.py` should parse files as data only. It must not execute commands,
perform shell expansion, evaluate Python, load plugins, or mutate `PyShell`.

## Validation Ownership

`schema.py` should own declarative validation:

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

TOML application should use the same validated mutation paths as
`ShellConfigAPI` where practical. `.pyshrc.py` remains the advanced override
layer and runs after TOML.

Startup hooks belong only to `.pyshrc.py`. TOML must not define executable
hooks.

## Interaction With `PyShell`

`PyShell` should orchestrate configuration load order but should not own TOML
parsing or schema validation. It should receive validated settings and apply
them through explicit mutation paths.

Runtime session changes must not rewrite TOML automatically.

## Interaction With Prompt Colors

Prompt color configuration should reuse `src/pysh/prompt/colors.py` parsing and
the current prompt color role validation in `src/pysh/config/api.py`.

TOML examples should use supported color names such as `aqua`, `fuchsia`,
`yellow`, `green`, `lime`, `orange`, `red`, `gray`, and `white`.

## Interaction With Issue #30 Highlight Colors

Issue #30 introduced semantic live-highlight roles. Issue #31 should expose
those roles declaratively under `[colors.highlight]` while preserving
`shell.set_highlight_color(role, color)` in `.pyshrc.py`.

Applying highlight colors must not move live highlighting out of the editor
layer and must not change command parsing or execution semantics.

## Profiles

`profiles.py` should model built-in and user-defined profiles. Profiles define
behavior and layout, not aliases.

Validation rules:

- unknown base profile is an error;
- cycles in profile inheritance are errors;
- profiles may reference themes;
- profiles must not define alias packs or aliases;
- missing profile keys inherit from the base profile or defaults.

## Themes

`themes.py` should model built-in and user-defined themes. Themes define visual
style only.

Validation rules:

- unknown base theme is an error;
- cycles in theme inheritance are errors;
- unknown color keys are errors;
- invalid color values are errors;
- user theme collision with a built-in theme is rejected unless an explicit
  override field is implemented.

Themes must not require Nerd Fonts or external commands.

## Alias Packs

`alias_packs.py` should model built-in alias packs. Packs are independent from
profiles and themes.

Validation rules:

- unknown pack names are errors;
- alias names must be valid;
- alias values must be strings;
- alias values are never executed during config load;
- no destructive aliases are enabled by default;
- project-local alias packs are not auto-enabled.

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

Issue #31 should preserve existing users:

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
- docs consistency and manual validation notes.

## Implementation Phases

Recommended sequence:

1. Add path discovery and non-mutating TOML file reads.
2. Add schema validation and diagnostics.
3. Add built-in theme/profile/alias-pack registries.
4. Add TOML application into existing shell mutation paths.
5. Add `conf.d` deterministic override behavior.
6. Add config diagnostics builtins.
7. Add generation of a safe default `config.toml` template.
8. Add migration documentation and validation matrix updates.

## Future / Out Of Scope

Not required for Issue #31:

- GUI or browser configuration;
- network theme downloads;
- third-party configuration frameworks;
- project-local config auto-enable;
- automatic rewriting of user TOML;
- `config_check --fix`;
- theme marketplace.
