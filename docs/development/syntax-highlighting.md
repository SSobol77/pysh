<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/syntax-highlighting.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Syntax Highlighting Implementation

Live input highlighting belongs to `src/pysh/editor/lineedit/highlight.py`.
It is a pure span classifier and renderer. It must not import
`pysh.core.shell`, execute commands, evaluate Python, expand variables, expand
globs, mutate `LineBuffer`, or perform terminal I/O.

## Data Flow

`PyShell` owns mutable shell state. The raw line editor receives:

- a `LineHighlighter` instance constructed with the builtin set;
- an alias callback that exposes only alias names;
- a `ColorScheme` built from validated configuration;
- the raw `LineBuffer` text.

The highlighter returns spans over the original input. Rendering wraps spans in
ANSI SGR codes only when coloring is enabled. Stripping SGR from rendered input
must recover the original logical input.

## Classification Rules

Command-position classification order is:

1. builtin;
2. alias;
3. external command found by `shutil.which()`;
4. unknown command.

This order mirrors execution precedence for builtins over aliases. External
command detection is bounded to `PATH` lookup and cached per highlighter
instance. The highlighter does not run subprocesses.

Comments begin only outside quotes and only when `#` is at the start of input
or preceded by whitespace. This keeps `value#literal` and quoted strings intact.

Here-document highlighting detects `<<` and `<<-`, highlights the operator,
and highlights the delimiter token. Heredoc body collection remains owned by
the parser/shell flow; the highlighter does not store or interpret heredoc
payload text.

## Visual State Boundaries

Paste preview framing, key hints, and preview line highlighting are in
`src/pysh/prompt/terminal_style.py` and `src/pysh/core/shell.py`.

Reverse search display is owned by `src/pysh/editor/lineedit/reader.py`.

Continuation prompts are owned by `src/pysh/core/shell.py`. Raw-editor
continuation reads disable autosuggest and live syntax highlighting to avoid
state leakage while collecting multiline Python and heredoc bodies.

## Color Configuration

`shell.set_highlight_color(role, color)` is exposed through
`src/pysh/config/api.py`. Validation uses the existing prompt color parser.
`PyShell` stores validated role colors and converts them into a `ColorScheme`
at read time using either ANSI/VGA 16-color SGR or truecolor, following the
configured prompt color mode.

Invalid roles or colors fail during configuration with a deterministic
`ConfigError`. If an invalid default somehow reaches rendering, `PyShell`
falls back to the internal default scheme rather than crashing the prompt.

## Invariants

- Highlighting must not mutate `LineBuffer.text` or `LineBuffer.cursor`.
- Highlighting must not change parsing or execution semantics.
- Highlighting must not evaluate Python expressions in shell mode.
- Highlighting must not execute shell commands or plugins.
- ANSI/CSI bytes must not participate in visible-width calculations.
- `TERM=dumb`, `NO_COLOR`, and non-TTY output must remain readable.
- No runtime dependency may be added for highlighting.

## Verification

Focused checks:

```sh
uv run ruff check src tests
uv run pytest -q tests/test_lineedit_highlight.py
uv run pytest -q tests/test_lineedit_reader_pty.py
uv run pytest -q tests/test_multiline_paste.py
uv run pytest -q tests/test_pty_integration.py
uv run pytest -q tests/test_docs_consistency.py
scripts/check_headers.sh
git diff --check
```

Manual terminal checks:

- edit a long highlighted command and move the cursor through it;
- type wide Unicode and combining characters;
- verify builtin, alias, external, and unknown command colors;
- verify `#` inside quotes is not a comment;
- verify `<<EOF` and `<<-EOF` visually mark heredoc delimiters;
- stage multiline paste and confirm no execution before explicit Enter;
- enter reverse search and confirm query/match separation;
- repeat with `NO_COLOR=1` and `TERM=dumb`.
