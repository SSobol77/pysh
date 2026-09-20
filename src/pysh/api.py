# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/api.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Stable Python API for embedding PySH and consuming public contracts.

Importing this module is side-effect-light. The shell runtime is imported and
constructed only when a :class:`ShellSession` first executes work.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from os import PathLike
from types import TracebackType

from pysh.contracts import (
    PLUGIN_API_VERSION,
    AliasRegistryView,
    CommandResolverView,
    CompatibilityBridge,
    ConfigView,
    EnvironmentView,
    PluginHooks,
    PluginMeta,
    PluginRegistrar,
    ShellStateView,
)

__all__ = [
    "AliasRegistryView",
    "CommandResolverView",
    "CompatibilityBridge",
    "ConfigView",
    "EnvironmentView",
    "PLUGIN_API_VERSION",
    "PluginHooks",
    "PluginMeta",
    "PluginRegistrar",
    "ShellSession",
    "ShellStateView",
]


class ShellSession:
    """Persistent, non-interactive PySH embedding session.

    User startup files, declarative configuration, and plugin discovery are
    never loaded implicitly. The internal runtime is constructed lazily on the
    first call to :meth:`execute` or :meth:`run_script`.
    """

    def __init__(self) -> None:
        self._shell: object | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return whether this session has completed its lifecycle."""
        return self._closed

    def execute(self, command: str) -> int:
        """Execute one PySH command and return its integer exit status.

        An ``exit`` or ``quit`` builtin closes the session and returns the
        requested status without raising ``SystemExit`` in the host process.
        """
        if not isinstance(command, str):
            raise TypeError("command must be str")
        shell = self._runtime()
        return self._invoke(lambda: shell.execute(command))  # type: ignore[attr-defined]

    def run_script(
        self,
        path: str | PathLike[str],
        args: Sequence[str] = (),
    ) -> int:
        """Execute a native PySH script and return its integer exit status.

        The script is always interpreted as PySH input; a foreign-shell
        shebang does not trigger interpreter delegation through this API.
        """
        from pathlib import Path  # noqa: PLC0415 - keep facade import light

        if not isinstance(path, (str, PathLike)):
            raise TypeError("path must be str or os.PathLike[str]")
        if isinstance(args, (str, bytes)):
            raise TypeError("args must be a sequence of str, not str or bytes")
        arguments = list(args)
        if any(not isinstance(argument, str) for argument in arguments):
            raise TypeError("args entries must be str")
        shell = self._runtime()
        return self._invoke(
            lambda: shell.run_script_file(  # type: ignore[attr-defined]
                Path(path),
                arguments,
                native_only=True,
            )
        )

    def close(self) -> None:
        """Close the session; repeated calls are safe."""
        self._shell = None
        self._closed = True

    def __enter__(self) -> ShellSession:
        """Return this open session for context-manager use."""
        if self._closed:
            raise RuntimeError("ShellSession is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session when leaving a context-manager block."""
        _ = (exc_type, exc_value, traceback)
        self.close()

    def _runtime(self) -> object:
        if self._closed:
            raise RuntimeError("ShellSession is closed")
        if self._shell is None:
            from pysh.config.startup import NO_RC_STARTUP_POLICY  # noqa: PLC0415
            from pysh.core.shell import PyShell  # noqa: PLC0415

            self._shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
        return self._shell

    def _invoke(self, operation: Callable[[], int]) -> int:
        try:
            status = operation()
        except SystemExit as exc:
            self.close()
            return _system_exit_status(exc.code)
        except BaseException as exc:  # noqa: BLE001 - internal exit signal is private
            from pysh.core.shell import _ExitShell  # noqa: PLC0415

            if not isinstance(exc, _ExitShell):
                raise
            self.close()
            return exc.code
        if isinstance(status, bool) or not isinstance(status, int):
            raise TypeError("PySH runtime returned a non-integer exit status")
        return status


def _system_exit_status(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    return 1
