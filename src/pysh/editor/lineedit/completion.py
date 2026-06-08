# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/lineedit/completion.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Pure completion engine for the raw-mode line editor.

The engine is non-executing and non-mutating.  It reads only local process
state provided through :class:`CompletionOptions` plus directory entries for
path completion and PATH executable discovery.
"""
from __future__ import annotations

import os
import stat
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CompletionKind(StrEnum):
    """Classification for one completion candidate."""

    ALIAS = "alias"
    BUILTIN = "builtin"
    COMMAND = "command"
    PATH = "path"
    DIRECTORY = "directory"
    VARIABLE = "variable"
    PYTHON_SYMBOL = "python-symbol"
    JOB = "job"


class CompletionMatchType(StrEnum):
    """How a candidate matched the current prefix."""

    PREFIX = "prefix"
    SUBSTRING = "substring"


@dataclass(frozen=True)
class CompletionCandidate:
    """One completion candidate.

    ``value`` is the text inserted into the command line.  ``display`` is the
    stable text shown in a multi-candidate menu.
    """

    value: str
    kind: CompletionKind
    display: str | None = None
    append_space: bool = True
    match_type: CompletionMatchType = CompletionMatchType.PREFIX

    @property
    def menu_text(self) -> str:
        """Return the deterministic display string for this candidate."""
        return self.display if self.display is not None else self.value

    @property
    def labeled_menu_text(self) -> str:
        """Return the display string annotated with candidate kind."""
        return f"{self.menu_text} [{self.kind.value}]"


@dataclass(frozen=True)
class CompletionContext:
    """Parsed completion context for ``line`` at ``cursor``."""

    line: str
    cursor: int
    token_start: int
    token_end: int
    prefix: str
    quote: str | None
    command_position: bool
    command_name: str | None
    argument_index: int
    after_redirection: bool
    variable_style: str | None
    variable_prefix: str
    in_comment: bool


@dataclass(frozen=True)
class CompletionOptions:
    """Inputs available to the completion engine."""

    builtins: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    path: str | None = None
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    locals: Mapping[str, str] | None = None
    job_ids: tuple[int, ...] = ()
    python_namespace: Mapping[str, object] | None = None
    path_cache: _PathCache | None = None


@dataclass(frozen=True)
class CompletionResult:
    """Completion candidates and token replacement metadata."""

    token_start: int
    token_end: int
    prefix: str
    candidates: tuple[str, ...]
    rich_candidates: tuple[CompletionCandidate, ...] = ()
    context: CompletionContext | None = None

    @property
    def display_candidates(self) -> tuple[str, ...]:
        """Return stable candidate labels for menu display."""
        if not self.rich_candidates:
            return self.candidates
        return tuple(candidate.labeled_menu_text for candidate in self.rich_candidates)


_REDIRECTION_OPERATORS = {"<", ">", ">>", "2>", "2>>", "&>", "&>>", "<<", "<<-", "<<<"}
_DIRECTORY_ONLY_COMMANDS = {"cd", "pushd"}
_JOB_COMMANDS = {"fg", "bg"}
_COMMAND_SEPARATORS = {";", "&&", "||", "&", "|"}
_SHELL_META_CHARS = set(" \t\n\\'\"$`;&|<>()[]{}*?!#")
_DEFAULT_PATH_CACHE_MAX_ENTRIES = 4096
_DEFAULT_PATH_CACHE_TTL = 5.0


class _PathCache:
    """Bounded, TTL-based PATH executable inventory cache.

    The cache is keyed by the complete PATH string, not by completion prefix.
    Prefix filtering happens in memory so a large number of typed prefixes
    cannot create unbounded cache keys.
    """

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_PATH_CACHE_MAX_ENTRIES,
        ttl: float = _DEFAULT_PATH_CACHE_TTL,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max(1, max_entries)
        self.ttl = max(0.0, ttl)
        self._monotonic = monotonic
        self._cache: OrderedDict[str, tuple[float, tuple[str, ...]]] = OrderedDict()

    def invalidate(self) -> None:
        """Drop all cached executable inventories."""
        self._cache.clear()

    def commands(self, path_value: str) -> tuple[str, ...]:
        """Return the executable inventory for *path_value*."""
        now = self._monotonic()
        cached = self._cache.get(path_value)
        if cached is not None:
            timestamp, inventory = cached
            if now - timestamp <= self.ttl:
                self._cache.move_to_end(path_value)
                return inventory
            self._cache.pop(path_value, None)

        inventory = self._scan_path(path_value)
        self._cache[path_value] = (now, inventory)
        self._cache.move_to_end(path_value)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return inventory

    def _scan_path(self, path_value: str) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for raw_dir in path_value.split(os.pathsep):
            if not raw_dir:
                continue
            directory = Path(raw_dir)
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name in seen:
                    continue
                try:
                    mode = entry.stat().st_mode
                except OSError:
                    continue
                if stat.S_ISREG(mode) and os.access(entry, os.X_OK):
                    seen.add(name)
                    out.append(name)
                    if len(out) >= self.max_entries:
                        return tuple(sorted(out, key=str.casefold))
        return tuple(sorted(out, key=str.casefold))


_GLOBAL_PATH_CACHE = _PathCache()


class CompletionEngine:
    """Deterministic, non-executing completion engine."""

    def __init__(self, options: CompletionOptions | None = None) -> None:
        self.options = options or CompletionOptions()

    def complete(self, line: str, cursor: int) -> CompletionResult:
        """Return completion candidates for ``line`` at ``cursor``."""
        context = parse_completion_context(line, cursor)
        if context.in_comment:
            return CompletionResult(
                context.token_start,
                context.token_end,
                context.prefix,
                (),
                (),
                context,
            )

        candidates: list[CompletionCandidate] = []
        if self.options.python_namespace is not None:
            candidates.extend(self._python_symbol_candidates(context))
        elif context.variable_style is not None:
            candidates.extend(self._variable_candidates(context))
        elif context.command_name in _JOB_COMMANDS and context.argument_index >= 1:
            candidates.extend(self._job_candidates(context))
        elif context.command_position:
            candidates.extend(self._command_candidates(context))
        elif context.after_redirection or context.command_name in _DIRECTORY_ONLY_COMMANDS:
            candidates.extend(
                self._path_candidates(
                    context,
                    directories_only=context.command_name in _DIRECTORY_ONLY_COMMANDS,
                )
            )
        else:
            candidates.extend(self._path_candidates(context, directories_only=False))

        rich = tuple(_dedupe_candidates(candidates))
        return CompletionResult(
            context.token_start,
            context.token_end,
            context.prefix,
            tuple(candidate.value for candidate in rich),
            rich,
            context,
        )

    def _command_candidates(self, context: CompletionContext) -> list[CompletionCandidate]:
        prefix = context.prefix
        candidates: list[CompletionCandidate] = []
        for name in sorted(self.options.builtins, key=str.casefold):
            match_type = _match_type(name, prefix)
            if match_type is not None:
                candidates.append(
                    CompletionCandidate(
                        name,
                        CompletionKind.BUILTIN,
                        append_space=True,
                        match_type=match_type,
                    )
                )
        for name in sorted(self.options.aliases, key=str.casefold):
            match_type = _match_type(name, prefix)
            if match_type is not None:
                candidates.append(
                    CompletionCandidate(
                        name,
                        CompletionKind.ALIAS,
                        append_space=True,
                        match_type=match_type,
                    )
                )
        candidates.extend(self._path_command_candidates(prefix))
        candidates.extend(self._path_candidates(context, directories_only=False))
        return _rank_candidates(candidates, prefix)

    def _path_command_candidates(self, prefix: str) -> list[CompletionCandidate]:
        path_value = os.environ.get("PATH", "") if self.options.path is None else self.options.path
        cache = self.options.path_cache if self.options.path_cache is not None else _GLOBAL_PATH_CACHE
        out: list[CompletionCandidate] = []
        for name in cache.commands(path_value):
            match_type = _match_type(name, prefix)
            if match_type is None:
                continue
            out.append(
                CompletionCandidate(
                    name,
                    CompletionKind.COMMAND,
                    append_space=True,
                    match_type=match_type,
                )
            )
        return out

    def _path_candidates(
        self,
        context: CompletionContext,
        *,
        directories_only: bool,
    ) -> list[CompletionCandidate]:
        search = _path_search(context.prefix, self.options.cwd)
        if search is None:
            return []
        search_dir, visible_dir, name_prefix = search
        try:
            entries = sorted(search_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            return []

        out: list[CompletionCandidate] = []
        include_hidden = name_prefix.startswith(".")
        for entry in entries:
            name = entry.name
            if name.startswith(".") and not include_hidden:
                continue
            match_type = _match_type(name, name_prefix)
            if match_type is None:
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            if directories_only and not is_dir:
                continue
            raw_value = f"{visible_dir}{name}{os.sep if is_dir else ''}"
            value = _quote_path_value(raw_value, context.quote)
            out.append(
                CompletionCandidate(
                    value,
                    CompletionKind.DIRECTORY if is_dir else CompletionKind.PATH,
                    display=raw_value,
                    append_space=not is_dir,
                    match_type=match_type,
                )
            )
        return _rank_candidates(out, name_prefix)

    def _variable_candidates(self, context: CompletionContext) -> list[CompletionCandidate]:
        names = set(os.environ if self.options.env is None else self.options.env)
        if self.options.locals is not None:
            names.update(self.options.locals)
        out: list[CompletionCandidate] = []
        for name in sorted(names):
            match_type = _match_type(name, context.variable_prefix)
            if match_type is None:
                continue
            if context.variable_style == "brace":
                value = "${" + name + "}"
            else:
                value = "$" + name
            out.append(
                CompletionCandidate(
                    value,
                    CompletionKind.VARIABLE,
                    display=value,
                    append_space=False,
                    match_type=match_type,
                )
            )
        return _rank_candidates(out, context.variable_prefix)

    def _job_candidates(self, context: CompletionContext) -> list[CompletionCandidate]:
        prefix = context.prefix.removeprefix("%")
        out: list[CompletionCandidate] = []
        for job_id in sorted(self.options.job_ids):
            value = str(job_id)
            match_type = _match_type(value, prefix)
            if match_type is not CompletionMatchType.PREFIX:
                continue
            if value.startswith(prefix):
                inserted = "%" + value if context.prefix.startswith("%") else value
                out.append(
                    CompletionCandidate(
                        inserted,
                        CompletionKind.JOB,
                        display=inserted,
                        append_space=True,
                        match_type=CompletionMatchType.PREFIX,
                    )
                )
        return out

    def _python_symbol_candidates(self, context: CompletionContext) -> list[CompletionCandidate]:
        namespace = self.options.python_namespace
        if namespace is None:
            return []
        prefix = context.prefix
        dotted = _dotted_python_context(prefix)
        out: list[CompletionCandidate] = []
        if dotted is None:
            for name in sorted(namespace, key=str.casefold):
                match_type = _match_type(name, prefix)
                if match_type is None:
                    continue
                out.append(
                    CompletionCandidate(
                        name,
                        CompletionKind.PYTHON_SYMBOL,
                        append_space=False,
                        match_type=match_type,
                    )
                )
            return _rank_candidates(out, prefix)

        base_name, attr_prefix = dotted
        obj = namespace.get(base_name)
        if obj is None:
            return []
        for attr_name in _safe_attribute_names(obj):
            match_type = _match_type(attr_name, attr_prefix)
            if match_type is None:
                continue
            out.append(
                CompletionCandidate(
                    f"{base_name}.{attr_name}",
                    CompletionKind.PYTHON_SYMBOL,
                    append_space=False,
                    match_type=match_type,
                )
            )
        return _rank_candidates(out, attr_prefix)


def complete_line(
    line: str,
    cursor: int,
    *,
    builtins: Iterable[str],
    aliases: Iterable[str],
    env: Mapping[str, str] | None = None,
    locals: Mapping[str, str] | None = None,
    job_ids: Iterable[int] = (),
    path: str | None = None,
    cwd: Path | None = None,
    python_namespace: Mapping[str, object] | None = None,
    path_cache: _PathCache | None = None,
) -> CompletionResult:
    """Return completion candidates for ``line`` at ``cursor``."""
    engine = CompletionEngine(
        CompletionOptions(
            builtins=tuple(builtins),
            aliases=tuple(aliases),
            path=path,
            cwd=cwd,
            env=env,
            locals=locals,
            job_ids=tuple(job_ids),
            python_namespace=python_namespace,
            path_cache=path_cache,
        )
    )
    return engine.complete(line, cursor)


def parse_completion_context(line: str, cursor: int) -> CompletionContext:
    """Parse quote-aware completion context without executing expansions."""
    cursor = max(0, min(len(line), cursor))
    start, prefix, quote = current_token(line, cursor)
    tokens = _tokens_before(line, start)
    in_comment = _in_comment(line, cursor)

    command_start = 0
    for idx, token in enumerate(tokens):
        if token in _COMMAND_SEPARATORS:
            command_start = idx + 1
    command_tokens = tokens[command_start:]
    command_name = command_tokens[0] if command_tokens else None
    command_position = not command_tokens
    argument_index = 0 if command_position else len(command_tokens)
    after_redirection = bool(command_tokens and command_tokens[-1] in _REDIRECTION_OPERATORS)
    variable_style, variable_prefix, variable_start = _variable_context(line, start, cursor, quote)
    if variable_style is not None:
        start = variable_start
    return CompletionContext(
        line=line,
        cursor=cursor,
        token_start=start,
        token_end=cursor,
        prefix=prefix,
        quote=quote,
        command_position=command_position,
        command_name=command_name,
        argument_index=argument_index,
        after_redirection=after_redirection,
        variable_style=variable_style,
        variable_prefix=variable_prefix,
        in_comment=in_comment,
    )


def current_token(line: str, cursor: int) -> tuple[int, str, str | None]:
    """Return ``(start, token_text, quote)`` for the token under the cursor."""
    cursor = max(0, min(len(line), cursor))
    in_single = False
    in_double = False
    token_start = 0
    quote: str | None = None
    pos = 0
    while pos < cursor:
        ch = line[pos]
        if in_single:
            if ch == "'":
                in_single = False
            pos += 1
            continue
        if in_double:
            if ch == "\\" and pos + 1 < cursor and line[pos + 1] in ('"', "\\", "$", "`"):
                pos += 2
                continue
            if ch == '"':
                in_double = False
            pos += 1
            continue
        if ch == "\\" and pos + 1 < cursor:
            pos += 2
            continue
        if ch == "'":
            in_single = True
            if pos == token_start:
                token_start = pos + 1
                quote = "'"
            pos += 1
            continue
        if ch == '"':
            in_double = True
            if pos == token_start:
                token_start = pos + 1
                quote = '"'
            pos += 1
            continue
        if ch.isspace() or ch in _COMMAND_SEPARATORS:
            token_start = pos + 1
            quote = None
        pos += 1
    return token_start, _unescape_token_prefix(line[token_start:cursor], quote), quote


def apply_single_completion(line: str, result: CompletionResult) -> tuple[str, int]:
    """Apply a single completion candidate and return ``(text, cursor)``."""
    if len(result.rich_candidates) == 1:
        candidate = result.rich_candidates[0]
        suffix = " " if candidate.append_space else ""
        replacement = candidate.value + suffix
    elif len(result.candidates) == 1:
        candidate_value = result.candidates[0]
        suffix = "" if candidate_value.endswith(os.sep) else " "
        replacement = candidate_value + suffix
    else:
        return line, result.token_end
    text = line[: result.token_start] + replacement + line[result.token_end :]
    return text, result.token_start + len(replacement)


def common_completion_prefix(result: CompletionResult) -> str:
    """Return the common candidate value prefix, or the existing prefix."""
    values = [candidate.value for candidate in result.rich_candidates]
    if not values:
        values = list(result.candidates)
    if len(values) < 2:
        return result.prefix
    common = os.path.commonprefix(values)
    return common if len(common) > len(result.prefix) else result.prefix


def filesystem_matches(prefix: str) -> list[str]:
    """Return filesystem entries matching ``prefix`` using v1 path policy."""
    context = CompletionContext(
        line=prefix,
        cursor=len(prefix),
        token_start=0,
        token_end=len(prefix),
        prefix=prefix,
        quote=None,
        command_position=False,
        command_name=None,
        argument_index=0,
        after_redirection=False,
        variable_style=None,
        variable_prefix="",
        in_comment=False,
    )
    engine = CompletionEngine()
    return [candidate.value for candidate in engine._path_candidates(context, directories_only=False)]


def _tokens_before(line: str, end: int) -> list[str]:
    tokens: list[str] = []
    chars: list[str] = []
    in_single = False
    in_double = False
    pos = 0
    while pos < end:
        ch = line[pos]
        if in_single:
            if ch == "'":
                in_single = False
            else:
                chars.append(ch)
            pos += 1
            continue
        if in_double:
            if ch == "\\" and pos + 1 < end and line[pos + 1] in ('"', "\\", "$", "`"):
                chars.append(line[pos + 1])
                pos += 2
                continue
            if ch == '"':
                in_double = False
            else:
                chars.append(ch)
            pos += 1
            continue
        if ch == "\\" and pos + 1 < end:
            chars.append(line[pos + 1])
            pos += 2
            continue
        if ch == "'":
            in_single = True
            pos += 1
            continue
        if ch == '"':
            in_double = True
            pos += 1
            continue
        two = line[pos:pos + 2]
        if two in {"&&", "||"}:
            _append_token(tokens, chars)
            tokens.append(two)
            pos += 2
            continue
        if ch in _COMMAND_SEPARATORS:
            _append_token(tokens, chars)
            tokens.append(ch)
            pos += 1
            continue
        if ch.isspace():
            _append_token(tokens, chars)
            pos += 1
            continue
        chars.append(ch)
        pos += 1
    _append_token(tokens, chars)
    return tokens


def _append_token(tokens: list[str], chars: list[str]) -> None:
    if chars:
        tokens.append("".join(chars))
        chars.clear()


def _in_comment(line: str, cursor: int) -> bool:
    in_single = False
    in_double = False
    at_boundary = True
    pos = 0
    while pos < cursor:
        ch = line[pos]
        if in_single:
            if ch == "'":
                in_single = False
            at_boundary = False
            pos += 1
            continue
        if in_double:
            if ch == "\\" and pos + 1 < cursor and line[pos + 1] in ('"', "\\", "$", "`"):
                pos += 2
                at_boundary = False
                continue
            if ch == '"':
                in_double = False
            at_boundary = False
            pos += 1
            continue
        if ch == "\\" and pos + 1 < cursor:
            pos += 2
            at_boundary = False
            continue
        if ch.isspace():
            at_boundary = True
            pos += 1
            continue
        if ch == "#" and at_boundary:
            return True
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        at_boundary = False
        pos += 1
    return False


def _variable_context(
    line: str,
    token_start: int,
    cursor: int,
    quote: str | None,
) -> tuple[str | None, str, int]:
    if quote == "'":
        return None, "", token_start
    segment = line[token_start:cursor]
    idx = len(segment) - 1
    while idx >= 0:
        if segment[idx] == "$" and (idx == 0 or segment[idx - 1] != "\\"):
            if idx + 1 < len(segment) and segment[idx + 1] == "{":
                return "brace", segment[idx + 2:], token_start + idx
            return "plain", segment[idx + 1:], token_start + idx
        idx -= 1
    return None, "", token_start


def _path_search(prefix: str, cwd: Path | None) -> tuple[Path, str, str] | None:
    effective_cwd = Path.cwd() if cwd is None else cwd
    if prefix.startswith("~"):
        expanded = os.path.expanduser(prefix)
        directory, name_prefix = os.path.split(expanded)
        visible_dir, _ = os.path.split(prefix)
        visible_prefix = visible_dir + os.sep if visible_dir else ""
        return Path(directory or os.path.expanduser("~")), visible_prefix, name_prefix
    directory, name_prefix = os.path.split(prefix)
    search_dir = Path(directory) if os.path.isabs(directory) else effective_cwd / directory
    visible_dir = directory + os.sep if directory else ""
    return search_dir, visible_dir, name_prefix


def _quote_path_value(value: str, quote: str | None) -> str:
    if quote == "'":
        return value.replace("'", "'\\''")
    if quote == '"':
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return "".join("\\" + ch if ch in _SHELL_META_CHARS else ch for ch in value)


def _unescape_token_prefix(value: str, quote: str | None) -> str:
    if quote == "'":
        return value
    out: list[str] = []
    idx = 0
    while idx < len(value):
        ch = value[idx]
        if ch == "\\" and idx + 1 < len(value):
            out.append(value[idx + 1])
            idx += 2
            continue
        out.append(ch)
        idx += 1
    return "".join(out)


def _dedupe_candidates(values: Sequence[CompletionCandidate]) -> list[CompletionCandidate]:
    seen: set[str] = set()
    out: list[CompletionCandidate] = []
    for candidate in values:
        if candidate.value in seen:
            continue
        seen.add(candidate.value)
        out.append(candidate)
    return out


def _match_type(value: str, prefix: str) -> CompletionMatchType | None:
    """Return prefix/substring match type using case-insensitive matching."""
    if not prefix:
        return CompletionMatchType.PREFIX
    folded_value = value.casefold()
    folded_prefix = prefix.casefold()
    if folded_value.startswith(folded_prefix):
        return CompletionMatchType.PREFIX
    if folded_prefix in folded_value:
        return CompletionMatchType.SUBSTRING
    return None


def _rank_candidates(
    candidates: Sequence[CompletionCandidate],
    prefix: str,
) -> list[CompletionCandidate]:
    """Return deterministic candidates with substring fallback semantics."""
    del prefix
    deduped = _dedupe_candidates(candidates)
    prefix_matches = [
        candidate for candidate in deduped
        if candidate.match_type is CompletionMatchType.PREFIX
    ]
    selected = prefix_matches if prefix_matches else [
        candidate for candidate in deduped
        if candidate.match_type is CompletionMatchType.SUBSTRING
    ]
    return sorted(
        selected,
        key=lambda candidate: (
            _kind_rank(candidate.kind),
            candidate.menu_text.casefold(),
            candidate.value.casefold(),
        ),
    )


def _kind_rank(kind: CompletionKind) -> int:
    """Return deterministic display priority for candidate kinds."""
    order = {
        CompletionKind.ALIAS: 0,
        CompletionKind.BUILTIN: 1,
        CompletionKind.COMMAND: 2,
        CompletionKind.DIRECTORY: 3,
        CompletionKind.PATH: 4,
        CompletionKind.VARIABLE: 5,
        CompletionKind.PYTHON_SYMBOL: 6,
        CompletionKind.JOB: 7,
    }
    return order[kind]


def _dotted_python_context(prefix: str) -> tuple[str, str] | None:
    """Return ``(base, attr_prefix)`` for a simple dotted Python prefix."""
    if "." not in prefix:
        return None
    base_name, attr_prefix = prefix.rsplit(".", 1)
    if not base_name.isidentifier():
        return None
    return base_name, attr_prefix


def _safe_attribute_names(obj: object) -> tuple[str, ...]:
    """Return attribute names without evaluating properties or __getattr__."""
    names: set[str] = set()
    try:
        names.update(dir(type(obj)))
    except Exception:  # noqa: BLE001 - completion must fail closed
        return ()
    if isinstance(obj, type(os)):
        try:
            names.update(str(name) for name in vars(obj))
        except Exception:  # noqa: BLE001 - completion must fail closed
            pass
    else:
        try:
            instance_dict = object.__getattribute__(obj, "__dict__")
        except Exception:  # noqa: BLE001 - completion must fail closed
            pass
        else:
            if isinstance(instance_dict, dict):
                names.update(str(name) for name in instance_dict)
    return tuple(sorted(names, key=str.casefold))
