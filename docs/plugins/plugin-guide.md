<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/plugins/plugin-guide.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Plugin Guide

This guide shows a local smoke test for PySH Plugin API 1.0. Plugins are
trusted Python code, not sandboxed code. Enable only plugins you trust.

## User Plugin Smoke Test

Create `~/.config/pysh/plugins/example.py`:

```python
class ExamplePlugin:
    name = "example"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("hello", self.hello)
        api.register_completer("hello", self.complete_hello)
        api.register_prompt_segment("example", lambda: "plug", position="end")
        api.on_startup(lambda: print("example startup"))
        api.on_shutdown(lambda: print("example shutdown"))
        api.on_env_change(self.env_changed)

    def hello(self, argv):
        print("hello " + (" ".join(argv) if argv else "world"))
        return 0

    def complete_hello(self, args, cursor_pos):
        return ["world", "pysh", "plugins"]

    def env_changed(self, name, old, new):
        if name == "PYSH_PLUGIN_TEST":
            print(f"{name}={new}")
```

Enable it in `~/.pyshrc.py`:

```python
def configure(shell):
    shell.enable_plugin("example")
```

Manual validation checklist for Debian 13 and FreeBSD 14+:

1. Start `pysh` and verify the startup hook output appears.
2. Run `hello avionics` and verify the command returns status `0`.
3. Type `hello p<TAB>` and verify command-specific completion candidates.
4. Verify the `plug` prompt segment is visible.
5. Run `export PYSH_PLUGIN_TEST=1` and verify the env hook sees old/new state.
6. Exit PySH and verify the shutdown hook runs.
7. Remove or comment `shell.enable_plugin("example")` and verify none of the plugin behavior appears.
8. Create `.pysh/plugins/local.py` in a project and verify PySH warns but does not load it by default.
9. Add `shell.enable_project_plugins()` plus `shell.enable_plugin("local")` and verify the project plugin loads only then.

## Troubleshooting

`module defines no valid plugin class` means the plugin module did not contain
exactly one class with `name`, `version`, `api_version`, and callable
`register(api)`.

`unsupported plugin API version` means the plugin's `api_version` is malformed
or not compatible with PySH's current Plugin API version.

`overrides a builtin` means a plugin attempted to register a command name owned
by core PySH. Plugin API 1.0 does not allow builtin replacement.

Duplicate command, completer, and prompt segment names are rejected
deterministically. Rename the extension point or disable the conflicting
plugin.
