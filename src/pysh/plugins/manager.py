# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/manager.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Plugin API orchestration and shell integration boundary."""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO

from pysh.plugins.errors import PluginRegistrationError
from pysh.plugins.loader import load_plugin_record
from pysh.plugins.models import (
    EnvChangeHook,
    PluginCommand,
    PluginCompleter,
    PluginPromptSegment,
    PluginRegistrationBundle,
    PluginSource,
    ShutdownHook,
    StartupHook,
)
from pysh.plugins.names import validate_plugin_name
from pysh.plugins.registry import (
    PROJECT_PLUGIN_DIR,
    USER_PLUGIN_DIR,
    PluginRegistry,
    discover_plugin_files,
)


class PluginManager:
    """Owns explicit enablement, discovery, registration and callback dispatch."""

    def __init__(
        self,
        *,
        builtin_names: frozenset[str],
        user_plugin_dir: Path = USER_PLUGIN_DIR,
        project_plugin_dir: Path = PROJECT_PLUGIN_DIR,
        err: IO[str] | None = None,
    ) -> None:
        self.registry = PluginRegistry()
        self._builtin_names = builtin_names
        self._user_plugin_dir = user_plugin_dir
        self._project_plugin_dir = project_plugin_dir
        self._err = err if err is not None else sys.stderr
        self._commands: dict[str, PluginCommand] = {}
        self._completers: dict[str, PluginCompleter] = {}
        self._prompt_segments: list[PluginPromptSegment] = []
        self._startup_hooks: list[tuple[str, StartupHook]] = []
        self._shutdown_hooks: list[tuple[str, ShutdownHook]] = []
        self._env_hooks: list[tuple[str, EnvChangeHook]] = []
        self._dispatching_env_hook = False
        self._loaded = False

    def enable_plugin(self, name: str) -> None:
        """Record explicit plugin enablement."""
        self.registry.enable(name)

    def disable_plugin(self, name: str) -> None:
        """Remove explicit plugin enablement."""
        self.registry.disable(name)

    def enable_project_plugins(self) -> None:
        """Allow explicitly enabled project-local plugins to execute."""
        self.registry.project_plugins_enabled = True

    def is_plugin_enabled(self, name: str) -> bool:
        """Return whether plugin ``name`` is explicitly enabled."""
        return self.registry.is_enabled(name)

    def list_plugins(self) -> list[str]:
        """Return discovered plugin names after discovery has run."""
        names = {record.candidate.discovery_name for record in self.registry.records()}
        names.update(self.registry.enabled_names())
        return sorted(names, key=str.casefold)

    def discover_and_load(self) -> None:
        """Discover candidates and load only policy-enabled plugins."""
        user = discover_plugin_files(self._user_plugin_dir, PluginSource.USER)
        project = discover_plugin_files(self._project_plugin_dir, PluginSource.PROJECT)
        if project and not self.registry.project_plugins_enabled:
            count = len(project)
            print(
                f"pysh: found {count} project plugin(s) in .pysh/plugins/ "
                "(not loaded; use shell.enable_project_plugins() to enable)",
                file=self._err,
            )
        self.registry.discover(*user, *project)
        for record in self.registry.enabled_records():
            try:
                info = load_plugin_record(record, self)
            except BaseException as exc:  # noqa: BLE001 - one plugin must not abort startup
                self._diagnose(record.candidate.discovery_name, str(exc))
                continue
            _ = info
        self._loaded = True

    def begin_registration(self, plugin_name: str) -> PluginRegistrationBundle:
        """Return an empty staged registration transaction for ``plugin_name``."""
        return PluginRegistrationBundle(plugin_name=validate_plugin_name(plugin_name))

    def commit_registration_bundle(self, bundle: PluginRegistrationBundle) -> None:
        """Atomically publish a completed plugin registration bundle."""
        self._validate_bundle_commit(bundle)
        self._commands.update(bundle.commands)
        self._completers.update(bundle.completers)
        self._prompt_segments.extend(bundle.prompt_segments)
        self._startup_hooks.extend(bundle.startup_hooks)
        self._shutdown_hooks.extend(bundle.shutdown_hooks)
        self._env_hooks.extend(bundle.env_hooks)

    def run_startup_hooks(self) -> None:
        """Run startup hooks in deterministic plugin registration order."""
        for plugin_name, hook in list(self._startup_hooks):
            try:
                hook()
            except BaseException as exc:  # noqa: BLE001 - hook failures are contained
                self._diagnose(plugin_name, f"startup hook failed: {exc}")

    def run_shutdown_hooks(self) -> None:
        """Run all shutdown hooks, containing failures."""
        for plugin_name, hook in list(self._shutdown_hooks):
            try:
                hook()
            except BaseException as exc:  # noqa: BLE001 - hook failures are contained
                self._diagnose(plugin_name, f"shutdown hook failed: {exc}")

    def notify_env_change(self, name: str, old: str | None, new: str | None) -> None:
        """Notify environment hooks, guarded against recursive re-entry."""
        if self._dispatching_env_hook:
            return
        self._dispatching_env_hook = True
        try:
            for plugin_name, hook in list(self._env_hooks):
                try:
                    hook(name, old, new)
                except BaseException as exc:  # noqa: BLE001 - hook failures are contained
                    self._diagnose(plugin_name, f"env hook failed: {exc}")
        finally:
            self._dispatching_env_hook = False

    def register_command(
        self,
        plugin_name: str,
        command_name: str,
        handler: Callable[[list[str]], int],
    ) -> None:
        """Register a plugin command."""
        if command_name in self._builtin_names:
            raise PluginRegistrationError(f"plugin command {command_name!r} overrides a builtin")
        existing = self._commands.get(command_name)
        if existing is not None:
            raise PluginRegistrationError(
                f"plugin command {command_name!r} already registered by {existing.plugin_name}"
            )
        self._commands[command_name] = PluginCommand(command_name, plugin_name, handler)

    def stage_command(
        self,
        bundle: PluginRegistrationBundle,
        command_name: str,
        handler: Callable[[list[str]], int],
    ) -> None:
        """Stage a plugin command without mutating active registries."""
        if command_name in self._builtin_names:
            raise PluginRegistrationError(f"plugin command {command_name!r} overrides a builtin")
        if command_name in bundle.commands:
            raise PluginRegistrationError(
                f"plugin command {command_name!r} already staged by {bundle.plugin_name}"
            )
        bundle.commands[command_name] = PluginCommand(command_name, bundle.plugin_name, handler)

    def register_completer(
        self,
        plugin_name: str,
        command_name: str,
        completer: Callable[[list[str], int], list[str]],
    ) -> None:
        """Register a command-specific completer."""
        existing = self._completers.get(command_name)
        if existing is not None:
            raise PluginRegistrationError(
                f"completer for {command_name!r} already registered by {existing.plugin_name}"
            )
        self._completers[command_name] = PluginCompleter(command_name, plugin_name, completer)

    def stage_completer(
        self,
        bundle: PluginRegistrationBundle,
        command_name: str,
        completer: Callable[[list[str], int], list[str]],
    ) -> None:
        """Stage a plugin completer without mutating active registries."""
        if command_name in bundle.completers:
            raise PluginRegistrationError(
                f"completer for {command_name!r} already staged by {bundle.plugin_name}"
            )
        bundle.completers[command_name] = PluginCompleter(
            command_name,
            bundle.plugin_name,
            completer,
        )

    def register_prompt_segment(
        self,
        plugin_name: str,
        name: str,
        renderer: Callable[[], str | None],
        position: str,
    ) -> None:
        """Register a prompt segment."""
        for segment in self._prompt_segments:
            if segment.name == name:
                raise PluginRegistrationError(
                    f"prompt segment {name!r} already registered by {segment.plugin_name}"
                )
        self._prompt_segments.append(PluginPromptSegment(name, plugin_name, renderer, position))

    def stage_prompt_segment(
        self,
        bundle: PluginRegistrationBundle,
        name: str,
        renderer: Callable[[], str | None],
        position: str,
    ) -> None:
        """Stage a prompt segment without mutating active registries."""
        for segment in bundle.prompt_segments:
            if segment.name == name:
                raise PluginRegistrationError(
                    f"prompt segment {name!r} already staged by {bundle.plugin_name}"
                )
        bundle.prompt_segments.append(
            PluginPromptSegment(name, bundle.plugin_name, renderer, position)
        )

    def register_startup_hook(self, plugin_name: str, callback: StartupHook) -> None:
        """Register a startup hook."""
        self._startup_hooks.append((plugin_name, callback))

    def stage_startup_hook(
        self,
        bundle: PluginRegistrationBundle,
        callback: StartupHook,
    ) -> None:
        """Stage a startup hook without mutating active registries."""
        bundle.startup_hooks.append((bundle.plugin_name, callback))

    def register_shutdown_hook(self, plugin_name: str, callback: ShutdownHook) -> None:
        """Register a shutdown hook."""
        self._shutdown_hooks.append((plugin_name, callback))

    def stage_shutdown_hook(
        self,
        bundle: PluginRegistrationBundle,
        callback: ShutdownHook,
    ) -> None:
        """Stage a shutdown hook without mutating active registries."""
        bundle.shutdown_hooks.append((bundle.plugin_name, callback))

    def register_env_hook(self, plugin_name: str, callback: EnvChangeHook) -> None:
        """Register an environment-change hook."""
        self._env_hooks.append((plugin_name, callback))

    def stage_env_hook(
        self,
        bundle: PluginRegistrationBundle,
        callback: EnvChangeHook,
    ) -> None:
        """Stage an environment-change hook without mutating active registries."""
        bundle.env_hooks.append((bundle.plugin_name, callback))

    def command_names(self) -> tuple[str, ...]:
        """Return registered plugin command names."""
        return tuple(sorted(self._commands, key=str.casefold))

    def has_command(self, name: str) -> bool:
        """Return whether ``name`` is a registered plugin command."""
        return name in self._commands

    def run_command(self, name: str, argv: list[str]) -> int:
        """Run a plugin command with contained failure semantics."""
        command = self._commands[name]
        try:
            result = command.handler(list(argv))
        except BaseException as exc:  # noqa: BLE001 - plugin command must not crash shell
            self._diagnose(command.plugin_name, f"command {name}: {exc}")
            return 1
        if isinstance(result, bool) or not isinstance(result, int):
            self._diagnose(command.plugin_name, f"command {name}: handler returned non-int")
            return 1
        return result

    def complete_command(self, command_name: str, args: list[str], cursor_pos: int) -> list[str]:
        """Return command-specific plugin completions with contained failures."""
        completer = self._completers.get(command_name)
        if completer is None:
            return []
        try:
            result = completer.completer(list(args), cursor_pos)
        except BaseException as exc:  # noqa: BLE001 - completion must fail closed
            self._diagnose(completer.plugin_name, f"completer {command_name}: {exc}")
            return []
        if not isinstance(result, (list, tuple)) or not all(isinstance(item, str) for item in result):
            self._diagnose(completer.plugin_name, f"completer {command_name}: invalid result")
            return []
        return list(result)

    def prompt_segments(self, position: str) -> list[str]:
        """Render prompt segments for ``position`` and skip invalid results."""
        out: list[str] = []
        for segment in self._prompt_segments:
            if segment.position != position:
                continue
            try:
                value = segment.renderer()
            except BaseException as exc:  # noqa: BLE001 - prompt must not break
                self._diagnose(segment.plugin_name, f"prompt segment {segment.name}: {exc}")
                continue
            if value is None:
                continue
            if not isinstance(value, str):
                self._diagnose(segment.plugin_name, f"prompt segment {segment.name}: invalid result")
                continue
            out.append(value)
        return out

    def _diagnose(self, plugin_name: str, message: str) -> None:
        try:
            name = validate_plugin_name(plugin_name)
        except Exception:
            name = "<unknown>"
        print(f"pysh: plugin {name}: {message}", file=self._err)

    def _validate_bundle_commit(self, bundle: PluginRegistrationBundle) -> None:
        """Validate all active-registry conflicts before committing ``bundle``."""
        for command_name in bundle.commands:
            if command_name in self._builtin_names:
                raise PluginRegistrationError(
                    f"plugin command {command_name!r} overrides a builtin"
                )
            existing = self._commands.get(command_name)
            if existing is not None:
                raise PluginRegistrationError(
                    f"plugin command {command_name!r} already registered by "
                    f"{existing.plugin_name}"
                )
        for command_name in bundle.completers:
            existing = self._completers.get(command_name)
            if existing is not None:
                raise PluginRegistrationError(
                    f"completer for {command_name!r} already registered by "
                    f"{existing.plugin_name}"
                )
        active_segment_names = {segment.name: segment.plugin_name for segment in self._prompt_segments}
        for segment in bundle.prompt_segments:
            existing_plugin = active_segment_names.get(segment.name)
            if existing_plugin is not None:
                raise PluginRegistrationError(
                    f"prompt segment {segment.name!r} already registered by {existing_plugin}"
                )
