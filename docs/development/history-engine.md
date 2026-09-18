<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/history-engine.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# History Engine 2.0 — Developer Guide

## Architecture overview

```
PyShell
  │
  ├── HistoryManager  (readline adapter — Ctrl+R fallback, libedit guard)
  │     populate_from_entries(entries)
  │     disable_auto_history()
  │     bind_reverse_search()
  │
  └── HistoryEngine   (data brain — JSONL, dedup, filter, metadata)
        │
        └── HistoryStorage  (I/O layer — JSONL r/w, legacy migration, locking)
```

### Ownership boundaries

- `HistoryEngine` is the **sole writer** of `~/.pysh_history`.
- `HistoryManager` populates readline's in-memory buffer from
  `HistoryEngine.entries()` on startup.  It does **not** write the data file.
- `pysh.editor.lineedit` does **not** own history persistence (enforced by
  `tests/test_architecture_import_boundaries.py`).

## Data model

```python
class HistoryEntryType(Enum):
    NORMAL    = "normal"
    MULTILINE = "multiline"
    HEREDOC   = "heredoc"

@dataclass
class HistoryEntry:
    command:    str
    timestamp:  float        # Unix epoch seconds
    session_id: str          # hex from uuid4, one per shell instance
    frequency:  int          # increments with global dedup folding
    entry_type: HistoryEntryType
```

## Storage format

One valid JSON object per line.  Empty lines are ignored.  Lines that are
not valid JSON and do not start with `{` are treated as legacy plain-text
commands and migrated to `NORMAL` entries.  Lines starting with `{` that
fail to parse are skipped (corrupt JSON).

```jsonl
{"command": "git diff", "timestamp": 1718000000.0, "session_id": "a1b2c3d4", "frequency": 1, "entry_type": "normal"}
{"command": "echo hello\necho world", "timestamp": 1718000001.0, "session_id": "a1b2c3d4", "frequency": 1, "entry_type": "multiline"}
```

## Locking and atomicity

A **sidecar lock file** (`~/.pysh_history.lock`) guards the critical section.
`fcntl.flock()` is used when available; a no-op context manager is the
fallback.

The sidecar design is required because:
- Atomic save uses `os.replace(tmp → data)`, which changes the inode.
- `flock` is inode-bound.  Locking the data file would not protect concurrent
  appenders after a rename — they would write to the orphaned old inode.
- Locking the **sidecar** (stable inode) serialises all critical sections.

### Append path (per command)

```
acquire exclusive lock on sidecar
  open data file in append mode
  write JSON line + newline
  close data file
release lock
```

### Compaction path (on shell exit)

```
acquire exclusive lock on sidecar
  read all entries from disk (captures concurrent sessions)
  apply dedup
  apply max_length (slice trailing N entries)
  write to temp file
  os.replace(temp → data file)
release lock
```

## Parse-success gating

`PyShell._execute_impl()` sets `self._last_execute_parse_ok = True` at entry
and `False` on each parse-failure early return (`ParseError`, unsupported
syntax, failed `split_chain`).  The interactive loop calls
`history_engine.add(line, raw_line=line)` only when the flag is `True`.

`HistoryEngine.add()` further gates on:
- `parsed_ok` kwarg (shell sets `True`; tests may pass `False`).
- Empty / whitespace command text.
- `ignore_space_prefix` evaluated on the raw line.
- `ignore_patterns` match (case-insensitive substring).

## Dual Ctrl+R integration

### Raw editor path (`RawLineReader`)

`PyShell._read_interactive_line()` passes `history=self.history_engine.entries()`
to `RawLineReader.read_line()`.  The reader's own `_reverse_search` and
`AutoSuggester.suggest()` consume the `Sequence[str]`-compatible list.

### readline fallback path

1. `PyShell._setup_readline()` calls `history_engine.load()`.
2. `HistoryManager.populate_from_entries(engine.entries())` clears the
   readline buffer and re-adds all entries via `readline.add_history`.
3. `HistoryManager.disable_auto_history()` calls
   `readline.set_auto_history(False)` so readline does not add commands on
   its own.
4. Ctrl+R uses readline's `reverse-search-history` binding over the
   prepopulated buffer.

## DedupMode.GLOBAL metadata folding (M4)

When a duplicate is added:

- `timestamp` → max(old, new)
- `session_id` → the session that produced the newer timestamp
- `frequency` → old.frequency + new.frequency
- `entry_type` → from the entry with the newer timestamp

On compaction, the `_dedup_global` function applies this fold across the full
on-disk history so multi-session appends are merged correctly.

## Config integration

`DEFAULT_HISTORY_OPTIONS` in `pysh.config.api` sources defaults from
`DEFAULT_HISTORY_LENGTH` and `DEFAULT_HISTORY_PATH` in
`pysh.editor.history`.

`validate_history_option(name, value)` is a dedicated validator (the
name→type dict machinery used for prompt/editor options cannot express
positivity requirements, enum membership, or list-element types).

`PyShell.set_history_option(name, value)` validates, stores in
`self.history_options`, and calls `history_engine.set_option(name, value)`
to apply changes to the running engine.

## Test coverage

`tests/test_history.py` covers:

- All pre-2.0 `HistoryManager` tests (must stay green).
- `HistoryEntry` (de)serialization and type rejection.
- `HistoryStorage`: load/save, JSONL round-trip, legacy migration, corrupt
  line recovery, atomic compact.
- `HistoryEngine`: lifecycle, classification, parse-failure gating, empty
  input, whitespace, space-prefix, sensitive patterns, dedup modes (none /
  consecutive / global), frequency folding, max-length enforcement,
  concurrent append via `threading.Barrier`, export (plain / json / csv),
  `entries()` as `Sequence[str]`, set_option.
- `validate_history_option`: all branches including bool/non-positive
  max_length, bad dedup mode, malformed ignore_patterns.
- `DEFAULT_HISTORY_OPTIONS` shape and defaults.
- `set_history_option` via `ShellConfigAPI` fake integration.
- `HistoryManager.populate_from_entries` and `disable_auto_history`.

## Security constraints

- Filtering is purely local: no commands are executed, no external tools are
  called, no secret files are read.
- Sensitive commands are filtered **before** reaching disk.
- Heredoc bodies, parse-failure fragments, and whitespace-only input are
  never stored.
- Export is explicit and local only; no network, no cloud, no auto-upload.
- Corrupted files never crash startup.
