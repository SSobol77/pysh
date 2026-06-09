# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/completion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tab completion adapter for the interactive shell."""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable

from pysh.contracts.builtins import BUILTIN_NAME_LIST
from pysh.editor.lineedit.completion import (
    CompletionOptions,
    CompletionResult,
    apply_single_completion,
    complete_line,
)


class Completer:
    """Readline and raw-mode completion driver."""

    BUILTINS: tuple[str, ...] = BUILTIN_NAME_LIST

    def __init__(
        self,
        get_aliases: Callable[[], Iterable[str]],
        *,
        get_locals: Callable[[], dict[str, str]] | None = None,
        get_job_ids: Callable[[], Iterable[int]] | None = None,
        get_plugin_commands: Callable[[], Iterable[str]] | None = None,
        complete_plugin_command: Callable[[str, list[str], int], Iterable[str]] | None = None,
    ) -> None:
        self._get_aliases = get_aliases
        self._get_locals = get_locals if get_locals is not None else dict
        self._get_job_ids = get_job_ids if get_job_ids is not None else tuple
        self._get_plugin_commands = (
            get_plugin_commands if get_plugin_commands is not None else tuple
        )
        self._complete_plugin_command = (
            complete_plugin_command if complete_plugin_command is not None else _no_plugin_completion
        )
        self._matches: list[str] = []

    def install(self) -> None:
        """Wire the completer into ``readline`` if it is importable."""
        try:
            import readline
        except ImportError:
            return
        readline.set_completer(self.complete)
        readline.set_completer_delims(" \t\n\"'><=;|&")
        doc = readline.__doc__ or ""
        if "libedit" in doc:
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            self._matches = self._build_matches(text)
        if state < len(self._matches):
            return self._matches[state]
        return None

    def complete_line(self, line: str, cursor: int) -> list[str]:
        """Return completion matches for raw-mode editing."""
        return list(self.raw_completion(line, cursor).candidates)

    def raw_completion(self, line: str, cursor: int) -> CompletionResult:
        """Return raw-mode completion metadata."""
        result = complete_line(
            line,
            cursor,
            builtins=self.BUILTINS,
            aliases=self._get_aliases(),
            env=os.environ,
            locals=self._get_locals(),
            job_ids=self._get_job_ids(),
        )
        context = result.context
        if context is None:
            return result
        candidates = list(result.candidates)
        if context.command_position:
            prefix = context.prefix.casefold()
            for name in sorted(self._get_plugin_commands(), key=str.casefold):
                if name.casefold().startswith(prefix) and name not in candidates:
                    candidates.append(name)
        elif context.command_name:
            args = _split_completion_args(line[:cursor])
            for candidate in self._complete_plugin_command(
                context.command_name,
                args,
                cursor,
            ):
                if candidate not in candidates:
                    candidates.append(candidate)
        if tuple(candidates) == result.candidates:
            return result
        return CompletionResult(
            result.token_start,
            result.token_end,
            result.prefix,
            tuple(candidates),
            (),
            context,
        )

    def apply_raw_completion(self, line: str, result: CompletionResult) -> tuple[str, int]:
        """Apply a single raw-mode completion candidate."""
        return apply_single_completion(line, result)

    def _build_matches(self, text: str) -> list[str]:
        try:
            import readline
        except ImportError:
            result = self.raw_completion(text, len(text))
        else:
            line = readline.get_line_buffer()
            result = self.raw_completion(line, readline.get_endidx())
        return list(result.candidates)

    def filesystem_matches(self, text: str) -> list[str]:
        """Return filesystem entries matching ``text``. Safe on permission errors."""
        result = complete_line(
            text,
            len(text),
            builtins=(),
            aliases=(),
            env={},
            locals={},
            job_ids=(),
        )
        return list(result.candidates)


def options_from_completer(completer: Completer) -> CompletionOptions:
    """Return the current pure completion options for tests and diagnostics."""
    return CompletionOptions(
        builtins=completer.BUILTINS,
        aliases=tuple(completer._get_aliases()),
        env=os.environ,
        locals=completer._get_locals(),
        job_ids=tuple(completer._get_job_ids()),
    )


def _no_plugin_completion(_command_name: str, _args: list[str], _cursor_pos: int) -> tuple[str, ...]:
    return ()


def _split_completion_args(text: str) -> list[str]:
    parts = text.split()
    if not parts:
        return []
    return parts[1:]
