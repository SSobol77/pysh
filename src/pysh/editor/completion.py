# SPDX-License-Identifier: GPL-2.0-only
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
    ) -> None:
        self._get_aliases = get_aliases
        self._get_locals = get_locals if get_locals is not None else dict
        self._get_job_ids = get_job_ids if get_job_ids is not None else tuple
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
        return complete_line(
            line,
            cursor,
            builtins=self.BUILTINS,
            aliases=self._get_aliases(),
            env=os.environ,
            locals=self._get_locals(),
            job_ids=self._get_job_ids(),
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
