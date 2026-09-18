# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/editor/history.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Persistent history and Ctrl+R reverse search support.

This module wraps the standard library :mod:`readline` so the interactive
shell can offer Bash-like persistent history and reverse incremental search.

Design rules:
  * History file path is configurable so tests can use a temporary location.
  * Loading and saving never raise; failures are silent and the shell keeps
    running.
  * Ctrl+R is bound only when GNU readline (not libedit) is detected. Other
    platforms degrade gracefully.
  * Pure helpers (``split_history_lines``, ``dedupe_consecutive``) are exposed
    for unit testing without touching the global readline state.

History Engine 2.0 (Issue #28)
-------------------------------
``HistoryEngine`` is the storage/dedup/filter/metadata brain.  It owns the
JSONL data file at ``~/.pysh_history``.  Legacy plain-text lines in that file
are transparently migrated to ``NORMAL`` entries on first load.

``HistoryManager`` is retained as the thin readline-binding/fallback adapter.
Its existing interface is unchanged so existing tests stay green.  In the
interactive shell it is populated from ``HistoryEngine.entries()`` via
``populate_from_entries()`` instead of reading the data file directly.

Concurrency
-----------
A dedicated sidecar lock file (``~/.pysh_history.lock``) serialises append and
compaction.  ``fcntl.flock()`` is used on Unix; a no-op fallback is used when
``fcntl`` is absent.  Atomic save uses a temp file + ``os.replace()``.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_PATH = Path("~/.pysh_history").expanduser()
DEFAULT_HISTORY_LENGTH = 10_000

try:
    import fcntl as _fcntl  # type: ignore[import-not-found]
    _FCNTL_AVAILABLE = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    _FCNTL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure helpers (public — reused by tests and HistoryManager)
# ---------------------------------------------------------------------------

def split_history_lines(text: str) -> list[str]:
    """Return non-empty history entries from a raw history file body."""
    return [line for line in text.splitlines() if line.strip()]


def dedupe_consecutive(entries: Iterable[str]) -> list[str]:
    """Collapse runs of duplicate adjacent entries, preserving order."""
    out: list[str] = []
    last: str | None = None
    for entry in entries:
        if entry != last:
            out.append(entry)
            last = entry
    return out


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class HistoryEntryType(Enum):
    NORMAL = "normal"
    MULTILINE = "multiline"
    HEREDOC = "heredoc"


class DedupMode(Enum):
    NONE = "none"
    CONSECUTIVE = "consecutive"
    GLOBAL = "global"


@dataclass
class HistoryEntry:
    """One persisted history record."""

    command: str
    timestamp: float
    session_id: str
    frequency: int
    entry_type: HistoryEntryType

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "frequency": self.frequency,
            "entry_type": self.entry_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            command=str(data["command"]),
            timestamp=float(data["timestamp"]),
            session_id=str(data["session_id"]),
            frequency=int(data["frequency"]),
            entry_type=HistoryEntryType(data["entry_type"]),
        )


def _make_legacy_entry(command: str) -> HistoryEntry:
    """Wrap a plain-text legacy history line as a NORMAL HistoryEntry."""
    return HistoryEntry(
        command=command,
        timestamp=0.0,
        session_id="legacy",
        frequency=1,
        entry_type=HistoryEntryType.NORMAL,
    )


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------

class HistoryStorage:
    """JSONL-backed storage with legacy migration, locking, and atomic save.

    The data file is at ``path``; the sidecar lock file is ``path + ".lock"``.
    All writes are protected by an exclusive ``flock`` on the sidecar.  Reads
    use a shared lock where practical.

    Legacy plain-text lines (pre-2.0 ``~/.pysh_history``) are recognised on
    load and migrated transparently so users do not lose history on upgrade.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock_path = Path(str(path) + ".lock")

    # ------------------------------------------------------------------ internal helpers

    @contextlib.contextmanager
    def _locked(self, *, exclusive: bool = False) -> Iterator[None]:
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = open(self._lock_path, "w")  # noqa: SIM115,WPS515
        except OSError:
            yield
            return
        try:
            if _FCNTL_AVAILABLE:
                how = _fcntl.LOCK_EX if exclusive else _fcntl.LOCK_SH
                try:
                    _fcntl.flock(lock_fd, how)
                except OSError:
                    pass
            yield
        finally:
            if _FCNTL_AVAILABLE:
                try:
                    _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                lock_fd.close()
            except OSError:
                pass

    def _load_unlocked(self) -> list[HistoryEntry]:
        """Read and parse the data file; caller must hold the lock."""
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, OSError):
            return []
        entries: list[HistoryEntry] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                if not isinstance(data, dict):
                    continue
                entries.append(HistoryEntry.from_dict(data))
            except json.JSONDecodeError:
                if stripped.startswith("{"):
                    # Corrupt JSON object — skip it
                    continue
                # Legacy plain-text command — migrate
                entries.append(_make_legacy_entry(stripped))
            except (KeyError, ValueError, TypeError):
                # Valid JSON but malformed HistoryEntry structure — skip
                continue
        return entries

    def _save_unlocked(self, entries: list[HistoryEntry]) -> None:
        """Write entries atomically; caller must hold an exclusive lock."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        tmp = Path(str(self.path) + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            os.replace(str(tmp), str(self.path))
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ public API

    def load(self) -> list[HistoryEntry]:
        """Read and return all entries from disk."""
        with self._locked(exclusive=False):
            return self._load_unlocked()

    def save(self, entries: list[HistoryEntry]) -> None:
        """Overwrite the data file with ``entries`` atomically."""
        with self._locked(exclusive=True):
            self._save_unlocked(entries)

    def append(self, entry: HistoryEntry) -> None:
        """Append one entry to the data file under an exclusive lock."""
        with self._locked(exclusive=True):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            except OSError:
                pass

    def atomic_compact(
        self,
        transform: Callable[[list[HistoryEntry]], list[HistoryEntry]],
    ) -> list[HistoryEntry]:
        """Load, transform, and save under a single exclusive lock.

        Using a single lock prevents losing concurrent-session appends: the
        transform receives ALL entries written to disk (including entries from
        other shell instances that appended since the last compaction).
        """
        with self._locked(exclusive=True):
            entries = self._load_unlocked()
            result = transform(entries)
            self._save_unlocked(result)
            return result


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------

def _dedup_global(entries: list[HistoryEntry]) -> list[HistoryEntry]:
    """Collapse all duplicates; keep newest timestamp, summed frequency.

    Deterministic metadata folding (M4):
      * ``timestamp``: NEWEST of all duplicates.
      * ``session_id``: the session that produced the newest timestamp.
      * ``frequency``: SUM of all duplicate frequencies.
      * ``entry_type``: from the last (most-recent) duplicate.

    Insertion order of the FIRST occurrence is preserved so the deduped list
    remains in roughly chronological order; the merged entry carries the
    summed/newest metadata.
    """
    # First pass: build merged metadata per command.
    merged: dict[str, HistoryEntry] = {}
    for entry in entries:
        cmd = entry.command
        if cmd not in merged:
            merged[cmd] = entry
        else:
            prev = merged[cmd]
            if entry.timestamp >= prev.timestamp:
                new_session = entry.session_id
                new_ts = entry.timestamp
                new_type = entry.entry_type
            else:
                new_session = prev.session_id
                new_ts = prev.timestamp
                new_type = prev.entry_type
            merged[cmd] = HistoryEntry(
                command=cmd,
                timestamp=new_ts,
                session_id=new_session,
                frequency=prev.frequency + entry.frequency,
                entry_type=new_type,
            )
    # Second pass: emit in original insertion order (first occurrence).
    seen: set[str] = set()
    result: list[HistoryEntry] = []
    for entry in entries:
        if entry.command not in seen:
            result.append(merged[entry.command])
            seen.add(entry.command)
    return result


# ---------------------------------------------------------------------------
# History Engine
# ---------------------------------------------------------------------------

class HistoryEngine:
    """Storage/dedup/filter/metadata brain for PySH command history.

    ``HistoryEngine`` is the sole writer of the JSONL data file.
    ``HistoryManager`` reads its entries via ``entries()`` but must not write
    to the same file.

    Parameters
    ----------
    path:
        Path to the JSONL data file.  Defaults to ``DEFAULT_HISTORY_PATH``.
    session_id:
        Opaque string identifying this shell session.  Generate once per shell
        instance via ``uuid.uuid4().hex[:16]``.
    max_length:
        Maximum number of entries retained after compaction.  ``0`` means
        unlimited.
    dedup_mode:
        ``"none"``, ``"consecutive"``, or ``"global"``.
    ignore_space_prefix:
        When True, commands whose RAW input line starts with a space are not
        stored (zsh-style hidden history).
    ignore_patterns:
        Commands containing any of these substrings (case-insensitive) are
        never stored.
    """

    def __init__(
        self,
        path: Path = DEFAULT_HISTORY_PATH,
        *,
        session_id: str | None = None,
        max_length: int = DEFAULT_HISTORY_LENGTH,
        dedup_mode: str = "consecutive",
        ignore_space_prefix: bool = True,
        ignore_patterns: list[str] | None = None,
    ) -> None:
        self._storage = HistoryStorage(path)
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._max_length = max_length
        self._dedup_mode = dedup_mode
        self._ignore_space_prefix = ignore_space_prefix
        self._ignore_patterns: list[str] = ignore_patterns if ignore_patterns is not None else [
            "password", "secret", "token", "api_key",
        ]
        self._entries: list[HistoryEntry] = []

    # ------------------------------------------------------------------ public API

    def load(self) -> None:
        """Load and deduplicate history from disk into memory."""
        raw = self._storage.load()
        self._entries = self._apply_dedup(raw)

    def save(self) -> None:
        """Compact, deduplicate, and persist all history to disk.

        Re-reads from disk first so concurrent session appends are not lost.
        """
        def _compact(disk_entries: list[HistoryEntry]) -> list[HistoryEntry]:
            deduped = self._apply_dedup(disk_entries)
            if self._max_length > 0:
                return deduped[-self._max_length:]
            return deduped

        self._entries = self._storage.atomic_compact(_compact)

    def add(
        self,
        command: str,
        *,
        parsed_ok: bool = True,
        raw_line: str | None = None,
    ) -> None:
        """Add ``command`` to history if it passes all filters.

        Parameters
        ----------
        command:
            The logical command text (may contain ``\\n`` for multiline/heredoc).
        parsed_ok:
            When ``False`` the command is silently discarded (parse failure,
            heredoc-body fragment, or paste error).
        raw_line:
            The original raw input line before stripping.  Used for
            ``ignore_space_prefix`` evaluation.  When ``None``, ``command`` is
            used as a fallback.
        """
        if not parsed_ok:
            return
        check_line = raw_line if raw_line is not None else command
        if self._should_ignore(check_line, command):
            return
        entry = HistoryEntry(
            command=command,
            timestamp=time.time(),
            session_id=self._session_id,
            frequency=1,
            entry_type=self._classify(command),
        )
        self._entries = self._add_with_dedup(self._entries, entry)
        if self._max_length > 0 and len(self._entries) > self._max_length:
            self._entries = self._entries[-self._max_length:]
        self._storage.append(entry)

    def entries(self) -> list[str]:
        """Return plain command strings, oldest-first (Sequence[str]-compatible)."""
        return [e.command for e in self._entries]

    def entries_with_metadata(self) -> list[HistoryEntry]:
        """Return the full HistoryEntry list, oldest-first."""
        return list(self._entries)

    def export(self, format: str = "plain") -> str:  # noqa: A002
        """Export history in the requested format.

        ``format`` must be one of ``plain``, ``json``, or ``csv``.
        """
        if format == "plain":
            return "\n".join(e.command for e in self._entries)
        if format == "json":
            return json.dumps(
                [e.to_dict() for e in self._entries],
                ensure_ascii=False,
                indent=2,
            )
        if format == "csv":
            import csv  # noqa: PLC0415 - lazy import for optional path
            import io  # noqa: PLC0415 - lazy import for optional path
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["command", "timestamp", "session_id", "frequency", "entry_type"])
            for e in self._entries:
                writer.writerow([e.command, e.timestamp, e.session_id, e.frequency, e.entry_type.value])
            return buf.getvalue()
        raise ValueError(f"unknown export format: {format!r}")

    def set_option(self, name: str, value: object) -> None:
        """Apply a runtime option change directly to this engine instance."""
        if name == "max_length":
            self._max_length = int(value)  # type: ignore[arg-type]
        elif name == "dedup_mode":
            self._dedup_mode = str(value)
        elif name == "ignore_space_prefix":
            self._ignore_space_prefix = bool(value)
        elif name == "ignore_patterns":
            self._ignore_patterns = list(value)  # type: ignore[arg-type]
        elif name == "path":
            self._storage = HistoryStorage(Path(str(value)).expanduser())
            self.load()

    # ------------------------------------------------------------------ internal

    @staticmethod
    def _classify(command: str) -> HistoryEntryType:
        if "<<" in command:
            return HistoryEntryType.HEREDOC
        if "\n" in command:
            return HistoryEntryType.MULTILINE
        return HistoryEntryType.NORMAL

    def _should_ignore(self, raw_line: str, command: str) -> bool:
        if self._ignore_space_prefix and raw_line.startswith(" "):
            return True
        if not command.strip():
            return True
        cmd_lower = command.lower()
        for pattern in self._ignore_patterns:
            if pattern.lower() in cmd_lower:
                return True
        return False

    def _apply_dedup(self, entries: list[HistoryEntry]) -> list[HistoryEntry]:
        mode = self._dedup_mode
        if mode == "none":
            return list(entries)
        if mode == "global":
            return _dedup_global(entries)
        # Default: consecutive
        out: list[HistoryEntry] = []
        last: str | None = None
        for entry in entries:
            if entry.command != last:
                out.append(entry)
                last = entry.command
        return out

    def _add_with_dedup(
        self,
        entries: list[HistoryEntry],
        new: HistoryEntry,
    ) -> list[HistoryEntry]:
        """Return a new list with ``new`` appended, respecting the dedup mode."""
        mode = self._dedup_mode
        if mode == "consecutive":
            if entries and entries[-1].command == new.command:
                return entries
            return [*entries, new]
        if mode == "global":
            # Remove the old occurrence (if any), fold metadata, append at end.
            prev_idx = next(
                (i for i, e in enumerate(entries) if e.command == new.command),
                None,
            )
            if prev_idx is not None:
                prev = entries[prev_idx]
                merged = HistoryEntry(
                    command=new.command,
                    timestamp=max(prev.timestamp, new.timestamp),
                    session_id=(
                        new.session_id if new.timestamp >= prev.timestamp else prev.session_id
                    ),
                    frequency=prev.frequency + new.frequency,
                    entry_type=new.entry_type,
                )
                return [*entries[:prev_idx], *entries[prev_idx + 1:], merged]
            return [*entries, new]
        # DedupMode.NONE
        return [*entries, new]


# ---------------------------------------------------------------------------
# HistoryManager (readline fallback adapter — unchanged public interface)
# ---------------------------------------------------------------------------

class HistoryManager:
    """Wrap readline history loading, saving, and Ctrl+R binding.

    In History Engine 2.0 this class acts as a thin readline adapter.  The
    interactive shell populates readline from ``HistoryEngine.entries()`` via
    ``populate_from_entries()`` rather than loading the data file directly.
    ``save()`` is no longer called on the engine's data path.
    """

    def __init__(
        self,
        path: Path = DEFAULT_HISTORY_PATH,
        max_length: int = DEFAULT_HISTORY_LENGTH,
    ) -> None:
        self.path = Path(path)
        self.max_length = max_length

    # ------------------------------------------------------------------ load
    def load(self) -> bool:
        """Load history from disk. Returns True if anything was loaded."""
        try:
            import readline
        except ImportError:
            return False
        try:
            if self.path.exists():
                readline.read_history_file(str(self.path))
        except OSError:
            return False
        try:
            readline.set_history_length(self.max_length)
        except (AttributeError, ValueError):
            pass
        return True

    # ------------------------------------------------------------------ save
    def save(self) -> bool:
        """Persist current readline history to disk. Returns success."""
        try:
            import readline
        except ImportError:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        try:
            readline.write_history_file(str(self.path))
        except OSError:
            return False
        return True

    # ----------------------------------------------------------------- reverse
    def bind_reverse_search(self) -> bool:
        """Bind Ctrl+R to reverse-search-history if the backend supports it.

        Returns True on success, False if readline is unavailable or the bind
        directive is rejected (e.g. libedit).
        """
        try:
            import readline
        except ImportError:
            return False
        doc = readline.__doc__ or ""
        try:
            if "libedit" in doc:
                # libedit uses a different bind syntax and historically lacks a
                # working reverse-i-search; do not break the user's terminal.
                return False
            readline.parse_and_bind(r'"\C-r": reverse-search-history')
        except Exception:  # noqa: BLE001 - any backend failure must be silent
            return False
        return True

    # ----------------------------------------------------------------- helpers
    def read_entries(self) -> list[str]:
        """Read entries directly from the on-disk history file."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return []
        return split_history_lines(text)

    def entries(self) -> list[str]:
        """Return current readline history if available, else on-disk entries."""
        try:
            import readline
        except ImportError:
            return self.read_entries()
        try:
            length = readline.get_current_history_length()
            return [
                item
                for i in range(1, length + 1)
                if (item := readline.get_history_item(i)) is not None
            ]
        except Exception:  # noqa: BLE001 - backend failures must not break editing
            return self.read_entries()

    def add(self, line: str) -> None:
        """Add one non-empty entry to readline history when available."""
        if not line.strip():
            return
        try:
            import readline
        except ImportError:
            return
        try:
            readline.add_history(line)
        except Exception:  # noqa: BLE001 - history backend failures are non-fatal
            return

    def populate_from_entries(self, entries: list[str]) -> None:
        """Populate readline's in-memory buffer from a list of plain strings.

        Clears the existing readline buffer first, then re-adds every non-empty
        entry.  This lets ``HistoryEngine`` own the canonical history data
        while readline's Ctrl+R still searches it.
        """
        try:
            import readline
        except ImportError:
            return
        try:
            readline.clear_history()
            for entry in entries:
                if entry.strip():
                    readline.add_history(entry)
        except Exception:  # noqa: BLE001
            pass

    def disable_auto_history(self) -> bool:
        """Ask readline not to add lines automatically on Enter.

        Returns True when the readline backend supports the call.  When False,
        readline will still auto-add; callers should accept that gracefully.
        """
        try:
            import readline
            readline.set_auto_history(False)
        except (ImportError, AttributeError):
            return False
        return True
