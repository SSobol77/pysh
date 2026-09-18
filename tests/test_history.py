# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_history.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the history manager and History Engine 2.0 (Issue #28)."""
from __future__ import annotations

import json
import threading
import time  # noqa: F401 - used by timing-sensitive tests
from pathlib import Path

import pytest

from pysh.config.api import DEFAULT_HISTORY_OPTIONS, ConfigError, validate_history_option
from pysh.editor.history import (
    DEFAULT_HISTORY_LENGTH,
    DedupMode,
    HistoryEngine,
    HistoryEntry,
    HistoryEntryType,
    HistoryManager,
    HistoryStorage,
    dedupe_consecutive,
    split_history_lines,
)

# ---------------------------------------------------------------------------
# Pure helpers (unchanged from pre-2.0 — must stay green)
# ---------------------------------------------------------------------------

def test_split_history_lines_drops_blanks() -> None:
    text = "first\n\n  \nsecond\nthird\n"
    assert split_history_lines(text) == ["first", "second", "third"]


def test_dedupe_consecutive_collapses_runs() -> None:
    assert dedupe_consecutive(["a", "a", "b", "a", "a"]) == ["a", "b", "a"]


def test_dedupe_consecutive_empty() -> None:
    assert dedupe_consecutive([]) == []


def test_history_manager_save_creates_parent(tmp_path: Path) -> None:
    nested = tmp_path / "subdir" / "history"
    manager = HistoryManager(nested, max_length=128)
    assert isinstance(manager.save(), bool)


def test_history_manager_load_missing_is_safe(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "absent")
    assert isinstance(manager.load(), bool)


def test_history_manager_bind_does_not_raise() -> None:
    manager = HistoryManager(Path("/tmp/pysh_history_test_dummy"))
    assert isinstance(manager.bind_reverse_search(), bool)


def test_history_manager_read_entries_returns_lines(tmp_path: Path) -> None:
    path = tmp_path / "hist"
    path.write_text("ls\necho hi\n\ncd /tmp\n", encoding="utf-8")
    manager = HistoryManager(path)
    assert manager.read_entries() == ["ls", "echo hi", "cd /tmp"]


def test_history_manager_read_entries_missing(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "nope")
    assert manager.read_entries() == []


@pytest.mark.parametrize("max_len", [0, 1, 1024])
def test_history_manager_accepts_various_lengths(tmp_path: Path, max_len: int) -> None:
    manager = HistoryManager(tmp_path / "h", max_length=max_len)
    assert manager.max_length == max_len


# ---------------------------------------------------------------------------
# HistoryEntryType / DedupMode
# ---------------------------------------------------------------------------

def test_history_entry_type_values() -> None:
    assert HistoryEntryType.NORMAL.value == "normal"
    assert HistoryEntryType.MULTILINE.value == "multiline"
    assert HistoryEntryType.HEREDOC.value == "heredoc"


def test_dedup_mode_values() -> None:
    assert DedupMode.NONE.value == "none"
    assert DedupMode.CONSECUTIVE.value == "consecutive"
    assert DedupMode.GLOBAL.value == "global"


# ---------------------------------------------------------------------------
# HistoryEntry serialization
# ---------------------------------------------------------------------------

def test_history_entry_round_trip() -> None:
    entry = HistoryEntry(
        command="echo hello",
        timestamp=1234567890.0,
        session_id="abc123",
        frequency=1,
        entry_type=HistoryEntryType.NORMAL,
    )
    d = entry.to_dict()
    restored = HistoryEntry.from_dict(d)
    assert restored.command == entry.command
    assert restored.timestamp == entry.timestamp
    assert restored.session_id == entry.session_id
    assert restored.frequency == entry.frequency
    assert restored.entry_type == entry.entry_type


def test_history_entry_from_dict_multiline() -> None:
    data = {
        "command": "echo a\necho b",
        "timestamp": 1.0,
        "session_id": "s1",
        "frequency": 2,
        "entry_type": "multiline",
    }
    entry = HistoryEntry.from_dict(data)
    assert entry.entry_type == HistoryEntryType.MULTILINE
    assert entry.frequency == 2


def test_history_entry_from_dict_rejects_bad_type() -> None:
    data = {
        "command": "x",
        "timestamp": 0.0,
        "session_id": "s",
        "frequency": 1,
        "entry_type": "invalid_type",
    }
    with pytest.raises((ValueError, KeyError)):
        HistoryEntry.from_dict(data)


# ---------------------------------------------------------------------------
# HistoryStorage load / save
# ---------------------------------------------------------------------------

def test_storage_load_empty_file(tmp_path: Path) -> None:
    storage = HistoryStorage(tmp_path / "h.jsonl")
    assert storage.load() == []


def test_storage_load_missing_file(tmp_path: Path) -> None:
    storage = HistoryStorage(tmp_path / "missing.jsonl")
    assert storage.load() == []


def test_storage_save_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    storage = HistoryStorage(path)
    entries = [
        HistoryEntry("ls", 1.0, "s1", 1, HistoryEntryType.NORMAL),
        HistoryEntry("cd /tmp", 2.0, "s1", 1, HistoryEntryType.NORMAL),
    ]
    storage.save(entries)
    loaded = storage.load()
    assert [e.command for e in loaded] == ["ls", "cd /tmp"]


def test_storage_append(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    storage = HistoryStorage(path)
    e1 = HistoryEntry("ls", 1.0, "s1", 1, HistoryEntryType.NORMAL)
    e2 = HistoryEntry("pwd", 2.0, "s1", 1, HistoryEntryType.NORMAL)
    storage.append(e1)
    storage.append(e2)
    loaded = storage.load()
    assert [e.command for e in loaded] == ["ls", "pwd"]


def test_storage_legacy_migration(tmp_path: Path) -> None:
    path = tmp_path / "hist"
    path.write_text("ls\necho hi\ncd /tmp\n", encoding="utf-8")
    storage = HistoryStorage(path)
    entries = storage.load()
    assert len(entries) == 3
    assert all(e.entry_type == HistoryEntryType.NORMAL for e in entries)
    assert entries[0].command == "ls"
    assert entries[2].command == "cd /tmp"
    assert entries[0].session_id == "legacy"


def test_storage_corrupt_json_skipped(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    # A line starting with { that fails to parse is corrupt JSON — skip it.
    # A line NOT starting with { is legacy plain text — migrate it.
    path.write_text(
        '{"command": "good", "timestamp": 1.0, "session_id": "s", "frequency": 1, "entry_type": "normal"}\n'
        '{"broken": true\n'
        "plain_legacy_command\n",
        encoding="utf-8",
    )
    storage = HistoryStorage(path)
    entries = storage.load()
    commands = [e.command for e in entries]
    assert "good" in commands
    assert "plain_legacy_command" in commands
    # Corrupt JSON line is skipped, not crashing
    assert len(entries) == 2


def test_storage_never_crashes_on_load(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    path.write_bytes(b"\xff\xfe garbage \x00\x01")
    storage = HistoryStorage(path)
    # Must not raise; returns empty or partial list
    result = storage.load()
    assert isinstance(result, list)


def test_storage_atomic_compact(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    storage = HistoryStorage(path)
    storage.save([
        HistoryEntry("a", 1.0, "s", 1, HistoryEntryType.NORMAL),
        HistoryEntry("b", 2.0, "s", 1, HistoryEntryType.NORMAL),
        HistoryEntry("a", 3.0, "s", 1, HistoryEntryType.NORMAL),
    ])
    result = storage.atomic_compact(lambda es: [e for e in es if e.command != "a"])
    assert [e.command for e in result] == ["b"]
    loaded = storage.load()
    assert [e.command for e in loaded] == ["b"]


# ---------------------------------------------------------------------------
# HistoryEngine — basic lifecycle
# ---------------------------------------------------------------------------

def _engine(tmp_path: Path, **kwargs: object) -> HistoryEngine:
    return HistoryEngine(tmp_path / "h.jsonl", session_id="test-session", **kwargs)


def test_engine_load_empty(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    assert eng.entries() == []


def test_engine_add_and_entries(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("echo hello")
    eng.add("ls")
    assert eng.entries() == ["echo hello", "ls"]


def test_engine_persistence_across_sessions(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    eng1 = HistoryEngine(path, session_id="s1")
    eng1.load()
    eng1.add("first")
    eng1.save()

    eng2 = HistoryEngine(path, session_id="s2")
    eng2.load()
    assert "first" in eng2.entries()


def test_engine_entries_with_metadata(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("git status")
    meta = eng.entries_with_metadata()
    assert len(meta) == 1
    assert meta[0].session_id == "test-session"
    assert meta[0].entry_type == HistoryEntryType.NORMAL


# ---------------------------------------------------------------------------
# HistoryEngine — classification
# ---------------------------------------------------------------------------

def test_engine_classifies_multiline(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("echo a\necho b")
    meta = eng.entries_with_metadata()
    assert meta[0].entry_type == HistoryEntryType.MULTILINE


def test_engine_classifies_heredoc(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("cat <<EOF\nhello\nEOF")
    meta = eng.entries_with_metadata()
    assert meta[0].entry_type == HistoryEntryType.HEREDOC


def test_engine_classifies_normal(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("ls -la")
    assert eng.entries_with_metadata()[0].entry_type == HistoryEntryType.NORMAL


# ---------------------------------------------------------------------------
# HistoryEngine — gating: parse failure / empty / whitespace
# ---------------------------------------------------------------------------

def test_engine_parsed_ok_false_not_stored(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("echo 'bad", parsed_ok=False)
    assert eng.entries() == []


def test_engine_empty_not_stored(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("")
    eng.add("   ")
    assert eng.entries() == []


def test_engine_whitespace_only_not_stored(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("\t\n")
    assert eng.entries() == []


def test_engine_nonzero_exit_may_be_stored(tmp_path: Path) -> None:
    """A command that exits non-zero but parses OK may be stored."""
    eng = _engine(tmp_path)
    eng.load()
    # parse_ok=True means the parse succeeded; exit code is separate
    eng.add("false", parsed_ok=True)
    assert eng.entries() == ["false"]


def test_engine_ignore_space_prefix(tmp_path: Path) -> None:
    eng = _engine(tmp_path, ignore_space_prefix=True)
    eng.load()
    eng.add(" secret_cmd", raw_line=" secret_cmd")
    assert eng.entries() == []


def test_engine_ignore_space_prefix_disabled(tmp_path: Path) -> None:
    eng = _engine(tmp_path, ignore_space_prefix=False)
    eng.load()
    eng.add(" echo hi", raw_line=" echo hi")
    assert " echo hi" in eng.entries()


def test_engine_sensitive_pattern_not_stored(tmp_path: Path) -> None:
    eng = _engine(tmp_path, ignore_patterns=["password"])
    eng.load()
    eng.add("git commit -m 'fix password handling'")
    assert eng.entries() == []


def test_engine_sensitive_pattern_case_insensitive(tmp_path: Path) -> None:
    eng = _engine(tmp_path, ignore_patterns=["SECRET"])
    eng.load()
    eng.add("export MY_secret=val")
    assert eng.entries() == []


def test_engine_non_sensitive_stored(tmp_path: Path) -> None:
    eng = _engine(tmp_path, ignore_patterns=["password"])
    eng.load()
    eng.add("echo safe")
    assert eng.entries() == ["echo safe"]


# ---------------------------------------------------------------------------
# HistoryEngine — dedup modes
# ---------------------------------------------------------------------------

def test_engine_dedup_none(tmp_path: Path) -> None:
    eng = _engine(tmp_path, dedup_mode="none")
    eng.load()
    for _ in range(3):
        eng.add("ls")
    assert eng.entries() == ["ls", "ls", "ls"]


def test_engine_dedup_consecutive(tmp_path: Path) -> None:
    eng = _engine(tmp_path, dedup_mode="consecutive")
    eng.load()
    for cmd in ["ls", "ls", "pwd", "ls"]:
        eng.add(cmd)
    assert eng.entries() == ["ls", "pwd", "ls"]


def test_engine_dedup_global(tmp_path: Path) -> None:
    eng = _engine(tmp_path, dedup_mode="global")
    eng.load()
    for cmd in ["ls", "pwd", "ls"]:
        eng.add(cmd)
    # Global: one entry per command; "ls" ends up at the back (most recent)
    assert eng.entries() == ["pwd", "ls"]


def test_engine_dedup_global_frequency_folding(tmp_path: Path) -> None:
    eng = _engine(tmp_path, dedup_mode="global")
    eng.load()
    eng.add("ls")
    eng.add("ls")
    eng.add("ls")
    meta = eng.entries_with_metadata()
    ls_entries = [e for e in meta if e.command == "ls"]
    assert len(ls_entries) == 1
    assert ls_entries[0].frequency == 3


def test_engine_dedup_global_newest_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    storage = HistoryStorage(path)
    storage.save([
        HistoryEntry("ls", 1.0, "old-session", 1, HistoryEntryType.NORMAL),
        HistoryEntry("ls", 5.0, "new-session", 1, HistoryEntryType.NORMAL),
    ])
    eng = HistoryEngine(path, session_id="t", dedup_mode="global")
    eng.load()
    meta = eng.entries_with_metadata()
    ls_meta = next(e for e in meta if e.command == "ls")
    assert ls_meta.timestamp == 5.0
    assert ls_meta.session_id == "new-session"
    assert ls_meta.frequency == 2


# ---------------------------------------------------------------------------
# HistoryEngine — on-disk compaction semantics
#
# Design contract (append-log until compaction):
#   add()  always appends the raw entry to disk (frequency=1 each time).
#   save() calls atomic_compact(), which reads every disk entry, applies the
#          configured dedup transform, and rewrites the file atomically.
#   This means the disk file is an append-log that may contain duplicates
#   *during* a session.  After save() the file is compact and canonical.
# ---------------------------------------------------------------------------

def test_consecutive_dedup_disk_is_append_log_before_save(tmp_path: Path) -> None:
    """Before save(), consecutive duplicates appear as raw appends on disk."""
    eng = _engine(tmp_path, dedup_mode="consecutive")
    eng.load()
    eng.add("ls")
    eng.add("ls")  # consecutive dup — dropped in-memory, still appended to disk
    raw_lines = [
        ln for ln in (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(raw_lines) == 2  # disk is append-log: two raw entries


def test_consecutive_dedup_disk_is_compact_after_save(tmp_path: Path) -> None:
    """After save(), consecutive duplicates are absent from disk and a fresh load is clean."""
    eng = _engine(tmp_path, dedup_mode="consecutive")
    eng.load()
    eng.add("ls")
    eng.add("ls")  # consecutive dup
    assert eng.entries() == ["ls"]  # in-memory already deduped
    eng.save()
    raw_lines = [
        ln for ln in (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(raw_lines) == 1  # disk is now compact
    # Fresh engine must see the same deduplicated state.
    eng2 = _engine(tmp_path, dedup_mode="consecutive")
    eng2.load()
    assert eng2.entries() == ["ls"]


def test_consecutive_dedup_across_session_boundary(tmp_path: Path) -> None:
    """Session ending on 'ls' then restarting and adding 'ls' results in one entry."""
    path = tmp_path / "h.jsonl"
    # Session 1: add ls, save.
    eng1 = HistoryEngine(path, session_id="s1", dedup_mode="consecutive")
    eng1.load()
    eng1.add("ls")
    eng1.save()
    # Session 2: reload and immediately add ls again.
    eng2 = HistoryEngine(path, session_id="s2", dedup_mode="consecutive")
    eng2.load()
    eng2.add("ls")  # same as last command in previous session
    eng2.save()
    # Fresh read: still just one ls.
    eng3 = HistoryEngine(path, session_id="s3", dedup_mode="consecutive")
    eng3.load()
    assert eng3.entries() == ["ls"]


def test_global_dedup_disk_compact_after_save_with_correct_frequency(tmp_path: Path) -> None:
    """After save(), global mode folds all occurrences into one entry with summed frequency."""
    eng = _engine(tmp_path, dedup_mode="global")
    eng.load()
    for cmd in ["ls", "echo hi", "ls"]:  # ls appears twice, non-adjacent
        eng.add(cmd)
    # In-memory already folded.
    meta = {e.command: e for e in eng.entries_with_metadata()}
    assert meta["ls"].frequency == 2
    assert meta["echo hi"].frequency == 1
    eng.save()
    # Disk must have exactly two entries after compaction.
    raw_lines = [
        ln for ln in (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(raw_lines) == 2
    # Fresh engine must reproduce the folded frequencies.
    eng2 = _engine(tmp_path, dedup_mode="global")
    eng2.load()
    meta2 = {e.command: e for e in eng2.entries_with_metadata()}
    assert meta2["ls"].frequency == 2
    assert meta2["echo hi"].frequency == 1


def test_global_dedup_frequency_accumulates_across_sessions(tmp_path: Path) -> None:
    """Global-mode frequency sums correctly across save/reload cycles."""
    path = tmp_path / "h.jsonl"
    # Session 1: add ls three times (non-consecutive so add() runs each time).
    eng1 = HistoryEngine(path, session_id="s1", dedup_mode="global")
    eng1.load()
    eng1.add("ls")
    eng1.add("pwd")
    eng1.add("ls")
    eng1.add("pwd")
    eng1.add("ls")
    eng1.save()
    # After session 1: ls=3, pwd=2.
    eng_check = HistoryEngine(path, session_id="cx", dedup_mode="global")
    eng_check.load()
    meta1 = {e.command: e for e in eng_check.entries_with_metadata()}
    assert meta1["ls"].frequency == 3
    assert meta1["pwd"].frequency == 2
    # Session 2: add ls twice more.
    eng2 = HistoryEngine(path, session_id="s2", dedup_mode="global")
    eng2.load()
    eng2.add("ls")
    eng2.add("ls")
    eng2.save()
    # After session 2: ls=5, pwd=2.
    eng3 = HistoryEngine(path, session_id="s3", dedup_mode="global")
    eng3.load()
    meta3 = {e.command: e for e in eng3.entries_with_metadata()}
    assert meta3["ls"].frequency == 5
    assert meta3["pwd"].frequency == 2


# ---------------------------------------------------------------------------
# HistoryEngine — max_length enforcement
# ---------------------------------------------------------------------------

def test_engine_max_length_enforced(tmp_path: Path) -> None:
    eng = _engine(tmp_path, max_length=3)
    eng.load()
    for i in range(5):
        eng.add(f"cmd{i}")
    assert len(eng.entries()) <= 3
    assert eng.entries() == ["cmd2", "cmd3", "cmd4"]


def test_engine_max_length_on_save(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    # Write 10 entries
    storage = HistoryStorage(path)
    storage.save([
        HistoryEntry(f"cmd{i}", float(i), "s", 1, HistoryEntryType.NORMAL)
        for i in range(10)
    ])
    eng = HistoryEngine(path, session_id="t", max_length=3)
    eng.load()
    eng.save()
    loaded = storage.load()
    assert len(loaded) <= 3


# ---------------------------------------------------------------------------
# HistoryEngine — concurrent append via sidecar lock
# ---------------------------------------------------------------------------

def test_engine_concurrent_append_deterministic(tmp_path: Path) -> None:
    """Two threads appending simultaneously must not corrupt the file."""
    path = tmp_path / "h.jsonl"
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def appender(prefix: str) -> None:
        try:
            storage = HistoryStorage(path)
            barrier.wait()
            for i in range(10):
                entry = HistoryEntry(
                    f"{prefix}-{i}", float(i), prefix, 1, HistoryEntryType.NORMAL
                )
                storage.append(entry)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=appender, args=("A",))
    t2 = threading.Thread(target=appender, args=("B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Concurrent append errors: {errors}"
    storage = HistoryStorage(path)
    loaded = storage.load()
    # Every line must be a valid HistoryEntry
    assert len(loaded) == 20
    commands = {e.command for e in loaded}
    assert all(f"A-{i}" in commands for i in range(10))
    assert all(f"B-{i}" in commands for i in range(10))


# ---------------------------------------------------------------------------
# HistoryEngine — export
# ---------------------------------------------------------------------------

def test_engine_export_plain(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("ls")
    eng.add("pwd")
    result = eng.export("plain")
    assert result == "ls\npwd"


def test_engine_export_json(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("ls")
    result = eng.export("json")
    data = json.loads(result)
    assert isinstance(data, list)
    assert data[0]["command"] == "ls"
    assert "timestamp" in data[0]


def test_engine_export_csv(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    eng.add("ls")
    result = eng.export("csv")
    lines = result.strip().splitlines()
    assert lines[0].startswith("command")
    assert "ls" in lines[1]


def test_engine_export_unknown_format_raises(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.load()
    with pytest.raises(ValueError, match="unknown export format"):
        eng.export("xml")


# ---------------------------------------------------------------------------
# HistoryEngine — reverse search via entries()
# ---------------------------------------------------------------------------

def test_engine_entries_sequence_compatible(tmp_path: Path) -> None:
    """entries() returns a list[str] usable as Sequence[str] for RawLineReader."""
    eng = _engine(tmp_path)
    eng.load()
    eng.add("echo old-command")
    entries = eng.entries()
    assert isinstance(entries, list)
    assert entries == ["echo old-command"]


def test_engine_entries_oldest_first(tmp_path: Path) -> None:
    eng = _engine(tmp_path, dedup_mode="none")
    eng.load()
    for cmd in ["first", "second", "third"]:
        eng.add(cmd)
    assert eng.entries() == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# validate_history_option
# ---------------------------------------------------------------------------

def test_validate_max_length_ok() -> None:
    validate_history_option("max_length", 100)


def test_validate_max_length_rejects_zero() -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        validate_history_option("max_length", 0)


def test_validate_max_length_rejects_negative() -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        validate_history_option("max_length", -1)


def test_validate_max_length_rejects_bool() -> None:
    with pytest.raises(ConfigError, match="bool"):
        validate_history_option("max_length", True)


def test_validate_max_length_rejects_float() -> None:
    with pytest.raises(ConfigError, match="float"):
        validate_history_option("max_length", 1.5)


def test_validate_dedup_mode_ok() -> None:
    for mode in ("none", "consecutive", "global"):
        validate_history_option("dedup_mode", mode)


def test_validate_dedup_mode_bad() -> None:
    with pytest.raises(ConfigError, match="must be one of"):
        validate_history_option("dedup_mode", "fuzzy")


def test_validate_ignore_space_prefix_ok() -> None:
    validate_history_option("ignore_space_prefix", True)
    validate_history_option("ignore_space_prefix", False)


def test_validate_ignore_space_prefix_rejects_int() -> None:
    with pytest.raises(ConfigError, match="bool"):
        validate_history_option("ignore_space_prefix", 1)


def test_validate_ignore_patterns_ok() -> None:
    validate_history_option("ignore_patterns", ["password", "secret"])


def test_validate_ignore_patterns_empty_list_ok() -> None:
    validate_history_option("ignore_patterns", [])


def test_validate_ignore_patterns_rejects_empty_string_element() -> None:
    with pytest.raises(ConfigError, match="malformed ignore patterns"):
        validate_history_option("ignore_patterns", ["ok", ""])


def test_validate_ignore_patterns_rejects_non_str_element() -> None:
    with pytest.raises(ConfigError, match="malformed ignore patterns"):
        validate_history_option("ignore_patterns", ["ok", 42])


def test_validate_ignore_patterns_rejects_non_list() -> None:
    with pytest.raises(ConfigError, match="expects list"):
        validate_history_option("ignore_patterns", "password")


def test_validate_path_ok() -> None:
    validate_history_option("path", "/home/user/.pysh_history")


def test_validate_path_rejects_empty() -> None:
    with pytest.raises(ConfigError, match="non-empty"):
        validate_history_option("path", "")


def test_validate_unknown_option() -> None:
    with pytest.raises(ConfigError, match="unknown history option"):
        validate_history_option("nonexistent", "value")


# ---------------------------------------------------------------------------
# DEFAULT_HISTORY_OPTIONS
# ---------------------------------------------------------------------------

def test_default_history_options_keys() -> None:
    assert set(DEFAULT_HISTORY_OPTIONS) == {
        "max_length", "dedup_mode", "ignore_space_prefix", "ignore_patterns", "path"
    }


def test_default_history_options_max_length() -> None:
    assert DEFAULT_HISTORY_OPTIONS["max_length"] == DEFAULT_HISTORY_LENGTH


def test_default_history_options_dedup_mode() -> None:
    assert DEFAULT_HISTORY_OPTIONS["dedup_mode"] == "consecutive"


# ---------------------------------------------------------------------------
# set_history_option integration (via fake shell)
# ---------------------------------------------------------------------------

class _FakeShell:
    """Minimal fake implementing ConfigurableShell for history option tests."""

    def __init__(self, tmp_path: Path) -> None:
        import uuid

        from pysh.config.api import DEFAULT_HISTORY_OPTIONS
        from pysh.editor.history import HistoryEngine
        self.history_options: dict[str, object] = dict(DEFAULT_HISTORY_OPTIONS)
        self._session_id = uuid.uuid4().hex[:16]
        self.history_engine = HistoryEngine(
            tmp_path / "h.jsonl",
            session_id=self._session_id,
        )

    def set_history_option(self, name: str, value: object) -> None:
        from pysh.config.api import validate_history_option
        validate_history_option(name, value)
        self.history_options[name] = value
        self.history_engine.set_option(name, value)

    # Stubs for other ConfigurableShell methods
    def register_alias(self, name: str, value: str) -> None: ...
    def set_environment(self, name: str, value: str) -> None: ...
    def set_prompt_option(self, name: str, value: object) -> None: ...
    def set_editor_option(self, name: str, value: object) -> None: ...
    def set_mc_integration(self, value: str) -> None: ...
    def set_mc_warning_enabled(self, value: bool) -> None: ...
    def set_prompt_color(self, segment: str, color: str) -> None: ...
    def set_prompt_color_mode(self, name: str, value: object) -> None: ...
    def set_sensitive_input_indicator(self, name: str, value: object) -> None: ...
    def set_cursor_color_enabled(self, value: bool) -> None: ...
    def set_cursor_color(self, color: str) -> None: ...


def test_set_history_option_max_length(tmp_path: Path) -> None:
    shell = _FakeShell(tmp_path)
    shell.set_history_option("max_length", 500)
    assert shell.history_options["max_length"] == 500
    assert shell.history_engine._max_length == 500


def test_set_history_option_dedup_mode(tmp_path: Path) -> None:
    shell = _FakeShell(tmp_path)
    shell.set_history_option("dedup_mode", "global")
    assert shell.history_engine._dedup_mode == "global"


def test_set_history_option_ignore_patterns(tmp_path: Path) -> None:
    shell = _FakeShell(tmp_path)
    shell.set_history_option("ignore_patterns", ["my_secret"])
    assert shell.history_engine._ignore_patterns == ["my_secret"]


def test_set_history_option_rejects_invalid(tmp_path: Path) -> None:
    from pysh.config.api import ConfigError, ShellConfigAPI
    shell = _FakeShell(tmp_path)
    api = ShellConfigAPI(shell)  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        api.set_history_option("max_length", True)


# ---------------------------------------------------------------------------
# HistoryEngine — set_option
# ---------------------------------------------------------------------------

def test_engine_set_option_max_length(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.set_option("max_length", 42)
    assert eng._max_length == 42


def test_engine_set_option_dedup_mode(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.set_option("dedup_mode", "global")
    assert eng._dedup_mode == "global"


def test_engine_set_option_ignore_space_prefix(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.set_option("ignore_space_prefix", False)
    assert eng._ignore_space_prefix is False


def test_engine_set_option_ignore_patterns(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    eng.set_option("ignore_patterns", ["foo", "bar"])
    assert eng._ignore_patterns == ["foo", "bar"]


def test_engine_set_option_path_retargets_storage(tmp_path: Path) -> None:
    path2 = tmp_path / "sub" / "h2.jsonl"
    path2.parent.mkdir()
    e = HistoryEntry("from_path2", 1_000_000.0, "sess", 1, HistoryEntryType.NORMAL)
    path2.write_text(json.dumps(e.to_dict()) + "\n", encoding="utf-8")
    eng = _engine(tmp_path)
    eng.load()
    assert eng.entries() == []
    eng.set_option("path", str(path2))
    assert eng.entries() == ["from_path2"]
    assert eng._storage.path == path2


def test_engine_set_option_path_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    eng = _engine(tmp_path)
    eng.set_option("path", "~/custom_hist")
    assert eng._storage.path == tmp_path / "custom_hist"


def test_engine_set_option_path_persists_to_new_location(tmp_path: Path) -> None:
    path1 = tmp_path / "h1.jsonl"
    path2 = tmp_path / "h2.jsonl"
    eng = HistoryEngine(path1, session_id="s1")
    eng.load()
    eng.set_option("path", str(path2))
    eng.add("ls", parsed_ok=True, raw_line="ls")
    eng.save()
    assert path2.exists()
    assert not path1.exists()
    assert "ls" in path2.read_text(encoding="utf-8")


def test_set_history_option_path_changes_persistence(tmp_path: Path) -> None:
    import uuid
    path1 = tmp_path / "default.jsonl"
    path2 = tmp_path / "custom.jsonl"
    shell = _FakeShell.__new__(_FakeShell)
    from pysh.config.api import DEFAULT_HISTORY_OPTIONS
    from pysh.editor.history import HistoryEngine
    shell.history_options = dict(DEFAULT_HISTORY_OPTIONS)
    shell._session_id = uuid.uuid4().hex[:16]
    shell.history_engine = HistoryEngine(path1, session_id=shell._session_id)
    shell.history_engine.load()
    shell.set_history_option("path", str(path2))
    shell.history_engine.add("mycommand", parsed_ok=True, raw_line="mycommand")
    shell.history_engine.save()
    assert path2.exists()
    assert not path1.exists()
    assert "mycommand" in path2.read_text(encoding="utf-8")


def test_validate_path_rejects_non_str() -> None:
    with pytest.raises(ConfigError):
        validate_history_option("path", Path("/some/path"))


# ---------------------------------------------------------------------------
# HistoryManager — populate_from_entries / disable_auto_history
# ---------------------------------------------------------------------------

def test_history_manager_populate_from_entries_does_not_raise(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "dummy")
    manager.populate_from_entries(["ls", "pwd", "git status"])
    # No assertion needed — must not raise regardless of readline availability


def test_history_manager_disable_auto_history_does_not_raise(tmp_path: Path) -> None:
    manager = HistoryManager(tmp_path / "dummy")
    result = manager.disable_auto_history()
    assert isinstance(result, bool)
