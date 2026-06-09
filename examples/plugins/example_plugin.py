# SPDX-License-Identifier: GPL-2.0-only
# File: examples/plugins/example_plugin.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Reference example for PySH Plugin API 1.0.

Installation smoke test:

1. Copy this file to the user plugin directory:

   ~/.config/pysh/plugins/example_plugin.py

2. Enable it from ~/.pyshrc.py:

   def configure(shell):
       shell.enable_plugin("example_plugin")

3. Start PySH and verify:

   * startup hook prints: "example_plugin startup"
   * command works: hello PySH
   * completion works for: hello <TAB>
   * prompt segment shows: plug
   * env hook works: export PYSH_EXAMPLE_TEST=1
   * shutdown hook prints: "example_plugin shutdown"

Important:
The plugin metadata name must match the plugin filename stem. This file is
named example_plugin.py, therefore the plugin name is "example_plugin".

This module is intentionally side-effect-light. Importing it only defines one
plugin class. It performs no I/O, subprocess execution, network activity,
environment mutation, or shell mutation at import time.

PySH plugins are trusted Python code. They are not sandboxed.
"""
from __future__ import annotations

from typing import Any


class ExamplePlugin:
    """Demonstrates command, completion, prompt, startup, shutdown and env hooks."""

    name = "example_plugin"
    version = "0.1.0"
    api_version = (1, 0)
    description = "Example PySH plugin command, completion, prompt and hooks."
    author = "SSobol77 / PySH"

    def register(self, api: Any) -> None:
        """Register all extension points through the public Plugin API.

        PySH passes a PluginAPI object here. The example uses `Any` to avoid
        importing PySH internals from an example plugin file.
        """
        api.register_command("hello", self.hello)
        api.register_completer("hello", self.complete_hello)
        api.register_prompt_segment("example", self.prompt_segment, position="end")
        api.on_startup(self.startup)
        api.on_shutdown(self.shutdown)
        api.on_env_change(self.env_changed)

    def hello(self, argv: list[str]) -> int:
        """Print a deterministic greeting.

        Example:
            hello PySH
        """
        target = " ".join(argv) if argv else "from plugin"
        print(f"hello {target}")
        return 0

    def complete_hello(self, args: list[str], cursor_pos: int) -> list[str]:
        """Return static command-specific completion candidates.

        The arguments are accepted to demonstrate the Plugin API signature.
        This example deliberately returns deterministic static candidates.
        """
        del args, cursor_pos
        return ["world", "pysh", "plugins"]

    def prompt_segment(self) -> str:
        """Render a short prompt segment."""
        return "plug"

    def startup(self) -> None:
        """Run after the plugin is loaded and PySH startup reaches plugin hooks."""
        print("example_plugin startup")

    def shutdown(self) -> None:
        """Run during PySH shutdown."""
        print("example_plugin shutdown")

    def env_changed(self, name: str, old: str | None, new: str | None) -> None:
        """Observe exported PySH environment changes.

        This hook prints only for variables starting with PYSH_EXAMPLE_ so the
        example does not spam the terminal for normal environment changes.
        """
        del old
        if name.startswith("PYSH_EXAMPLE_"):
            print(f"example_plugin env {name}={new}")
