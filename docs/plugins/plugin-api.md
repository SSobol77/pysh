<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/plugins/plugin-api.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Plugin API 1.0

PySH Plugin API 1.0 is a versioned extension boundary for trusted local Python
plugins. It is explicit by policy: plugins never load unless enabled from
`~/.pyshrc.py`, and project-local plugins under `.pysh/plugins/` never execute
unless project plugins are explicitly enabled.

Security model:

```text
PySH plugins are trusted Python code. Enabling a plugin allows that plugin to
execute Python inside the PySH process. Only enable plugins from sources you
trust.
```

Plugins are not sandboxed. The Plugin API boundary validates registrations and
contains callback failures; it is not a security isolation boundary.

## Versioning

PySH exports `pysh.contracts.PLUGIN_API_VERSION == (1, 0)`. A plugin class must
declare:

```python
name: str
version: str
api_version: tuple[int, int]
```

Compatibility for API 1.0 requires the same major version and a plugin minor
version less than or equal to PySH's minor version. Malformed versions, bool
values, future minor versions, newer major versions, and older major versions
are rejected.

## Plugin Class

A plugin module must define exactly one valid plugin class. Zero valid classes
or multiple valid classes are rejected deterministically.

```python
class ExamplePlugin:
    name = "example"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("hello", self.hello)

    def hello(self, argv):
        print("hello from plugin")
        return 0
```

Optional metadata fields are `description: str` and `author: str`.

## Directories

User plugins are direct `.py` files in:

```text
~/.config/pysh/plugins/
```

Project-local plugins are direct `.py` files in:

```text
.pysh/plugins/
```

PySH does not recurse into plugin directories. Plugin infrastructure performs
no auto-installation, no network access, and no marketplace lookup.

## Enablement

Enable plugins from `~/.pyshrc.py`:

```python
def configure(shell):
    shell.enable_plugin("example")
```

Project-local plugins require a second explicit opt-in:

```python
def configure(shell):
    shell.enable_project_plugins()
    shell.enable_plugin("project_tool")
```

If project plugin files exist without project opt-in, PySH prints:

```text
pysh: found N project plugin(s) in .pysh/plugins/ (not loaded; use shell.enable_project_plugins() to enable)
```

## Registration API

Plugin API 1.0 supports:

```python
api.register_command(name, handler)
api.register_completer(command_name, completer)
api.register_prompt_segment(name, renderer, position="end")
api.on_startup(callback)
api.on_shutdown(callback)
api.on_env_change(callback)
```

Command handlers receive `argv: list[str]` without the command name and must
return `int` rather than `bool`. Plugin commands cannot override PySH builtins.

Completers receive `args: list[str]` and `cursor_pos: int`; they must return a
list or tuple of strings. They are command-specific and do not execute commands.

Prompt segment renderers return `str | None`. Allowed positions are
`before_cwd`, `after_git`, and `end`. Returned text is sanitized before prompt
rendering.

Environment hooks receive `(name, old, new)` when exported PySH environment
variables change through the central shell mutation path.

## Failure Behavior

All plugin execution points are contained: import, class discovery,
instantiation, `register(api)`, command handlers, completers, prompt renderers,
startup hooks, shutdown hooks, and environment hooks. Diagnostics use:

```text
pysh: plugin <name>: <message>
```

Command callback failure returns status `1`, completion failure returns no
plugin candidates, prompt failure skips the segment, and lifecycle hook failure
does not abort shell startup or shutdown.
