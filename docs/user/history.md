<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/history.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Command History

PySH History Engine 2.0 provides persistent, searchable, metadata-aware
command history for daily interactive use.

## What is stored

A command is added to history **only** when:

1. It parses successfully (malformed quotes, broken heredoc openers, and
   paste-error fragments are never stored).
2. It is not empty or whitespace-only.
3. Its raw input line does not start with a space when `ignore_space_prefix`
   is enabled (zsh-style hidden history).
4. None of the configured `ignore_patterns` match the command text
   (case-insensitive).

A command that **exits non-zero** but parses correctly **may** be stored —
exit code does not gate history.

## What is NOT stored

- Malformed input (unmatched quotes, broken heredoc syntax).
- Failed heredoc body collection (Ctrl+C or EOF during body input).
- Paste-error fragments.
- Empty or whitespace-only input.
- Space-prefixed commands when `ignore_space_prefix = True`.
- Commands matching any `ignore_patterns` entry.

## Storage format and path

History is stored as **JSON Lines** (JSONL) at `~/.pysh_history`.  Each
non-empty line is a valid JSON object:

```json
{"command": "git status", "timestamp": 1718000000.0, "session_id": "a1b2c3d4", "frequency": 1, "entry_type": "normal"}
```

### Legacy migration

If `~/.pysh_history` contains plain-text lines from an older PySH version,
each non-empty line that is not valid JSON is treated as a legacy `NORMAL`
command and migrated automatically.  Corrupt JSON-looking lines (lines
starting with `{` that fail to parse) are skipped.

Your pre-upgrade history is **never discarded**.

## Entry types

| Type        | Description                                          |
|-------------|------------------------------------------------------|
| `normal`    | A single-line command.                               |
| `multiline` | A command containing newlines (e.g. `py { ... }`).  |
| `heredoc`   | A command containing a heredoc operator (`<<`).      |

A heredoc command is stored as one entry (the full logical command including
header line and body).  Individual body lines are never stored separately.

## Deduplication modes

Configure via `shell.set_history_option("dedup_mode", ...)` in
`~/.pyshrc.py`.

| Mode           | Behaviour                                                     |
|----------------|---------------------------------------------------------------|
| `consecutive`  | Collapse adjacent runs of the same command. **(default)**     |
| `global`       | Keep one entry per command; frequency accumulates on reuse.   |
| `none`         | Store every execution without deduplication.                  |

In `global` mode the per-command entry carries the **newest** timestamp,
the **most recent** session ID, and the **sum** of all occurrence counts.
Ctrl+R still searches in chronological (recency) order; frequency is not
used for search ranking.

## Ctrl+R reverse search

PySH supports two backends depending on the terminal:

- **Raw editor** (`RawLineReader`) — the default on capable TTYs.  Ctrl+R
  opens an in-process incremental reverse search over
  `HistoryEngine.entries()`.
- **readline fallback** — used when the raw editor is not available (dumb
  terminals, `TERM=dumb`, MC environment).  The readline buffer is populated
  from `HistoryEngine.entries()` on startup.  Readline's built-in
  `reverse-search-history` binding is used.

Malformed or corrupted history lines never break either Ctrl+R path.

## Configuration options

All options are set in `~/.pyshrc.py`:

```python
def configure(shell):
    shell.set_history_option("max_length", 10000)
    shell.set_history_option("dedup_mode", "global")
    shell.set_history_option("ignore_space_prefix", True)
    shell.set_history_option("ignore_patterns", ["password", "secret", "token", "api_key"])
```

| Option                 | Type        | Default                                       | Description                                       |
|------------------------|-------------|-----------------------------------------------|---------------------------------------------------|
| `max_length`           | `int > 0`   | `10000`                                       | Maximum entries retained after compaction.        |
| `dedup_mode`           | `str`       | `"consecutive"`                               | Deduplication strategy.                           |
| `ignore_space_prefix`  | `bool`      | `True`                                        | Discard space-prefixed commands.                  |
| `ignore_patterns`      | `list[str]` | `["password","secret","token","api_key"]`     | Patterns that suppress storage (case-insensitive).|
| `path`                 | `str`       | `"~/.pysh_history"`                           | Data file path (effective on next launch).        |

## Sensitive command filtering

Commands matching any `ignore_patterns` entry are **never written to disk**.
Filtering is purely local: no commands are executed, no external tools are
called, and no secret files are read.  Only the command text is compared.

## Multiline and heredoc behaviour

A heredoc command (e.g. `cat <<EOF\nhello\nEOF`) is stored as a **single**
JSONL entry with `entry_type = "heredoc"`.  Body lines are part of that one
entry and are never stored individually.  If the heredoc collection is
interrupted (EOF or Ctrl+C) the partial input is discarded completely.

## Concurrent sessions and sidecar lock

Each shell instance appends entries to disk incrementally under an exclusive
`flock` on `~/.pysh_history.lock`.  On exit, the shell re-reads the full
file (capturing entries from other concurrent sessions), applies dedup and
`max_length`, and writes a clean compacted file.  On platforms where
`fcntl` is unavailable, the lock is a no-op and appends are best-effort.

## Corrupted-file recovery

A corrupted `~/.pysh_history` never crashes PySH startup.  Lines that fail
to parse are silently skipped; valid entries before and after the corruption
are retained.

## Export

From `~/.pyshrc.py` or a Python `py` block in the shell:

```python
py {
    import pysh.editor.history as h
    from pathlib import Path
    eng = h.HistoryEngine(Path("~/.pysh_history").expanduser(), session_id="export")
    eng.load()
    print(eng.export("plain"))   # one command per line
    # eng.export("json")         # full metadata as JSON array
    # eng.export("csv")          # tabular CSV
}
```

## Debian 13 / FreeBSD 14+ manual checklist

1. Confirm `~/.pysh_history` is created on first interactive launch.
2. Type ` secret`, press Enter — confirm the command is NOT in history
   (space-prefix suppression).
3. Type `export MY_TOKEN=abc`, press Enter — confirm it is NOT in history
   (token pattern).
4. Press Ctrl+R and search for a known previous command.
5. Run `uv run python -c "from pysh.editor.history import HistoryEngine; print('ok')"`.
6. Check that `~/.pysh_history.lock` is created during an active session.
