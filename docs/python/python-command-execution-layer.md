<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/python/python-command-execution-layer.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Python Command Execution Layer

PySH provides an interactive Python command mode that can be entered
from the normal PySH prompt.

## Entering Python command mode

Type `#py` at the normal PySH prompt:

```text
🐍 user@host ~/project > #py
```

You will see the Python mode banner:

```text
PySH Python Command Execution Layer | GPL-3.0
Python <current runtime>
Type #help for commands. Ctrl+D or #exit to return to PySH.

>>>
```

## Exiting Python command mode

Type `#exit` or press **Ctrl+D** at the primary prompt:

```text
>>> #exit
```

PySH returns to the normal shell prompt. All shell state (aliases, variables,
working directory) is preserved.

## Interactive execution

Python command mode supports the full interactive Python REPL experience.

### Expressions

```text
>>> 1 + 2
3
>>> "GuardBSD"
'GuardBSD'
```

### Assignments

```text
>>> x = 10
>>> x * 5
50
```

### Imports

```text
>>> from pathlib import Path
>>> Path.cwd()
PosixPath('/current/directory')
```

### Functions

```text
>>> def double(value):
...     return value * 2
...
>>> double(21)
42
```

### Classes

```text
>>> class Box:
...     def __init__(self, value):
...         self.value = value
...
>>> Box(7).value
7
```

### Multi-line blocks

Python command mode uses `codeop.compile_command` to detect block
completeness — the same mechanism CPython's own interactive REPL uses. You
do not need to guess indentation or add closing tokens manually.

After a line ending with `:`, the continuation prompt is prefilled with four
spaces. Press **Enter** on the blank continuation line to close the block:

```text
>>> def sum(a, b):
...     c = a + b
...     print(c)
...
>>> sum(7, 6)
13
```

### Auto-indentation

After entering a block-opening line (ending with `:`), the next continuation
prompt is prefilled with the correct indentation. Press Enter without typing
anything additional to close the block.

Nested blocks increase indentation automatically:

```text
>>> def f(values):
...     for v in values:
...         print(v)
...
>>> f([1, 2, 3])
1
2
3
```

## Persistent runtime state

Variables, imports, functions, and classes defined during a session remain
available for the rest of that session:

```text
>>> import math
>>> x = math.pi
>>> round(x, 4)
3.1416
```

`#reset` clears the runtime state (see below).

## Source buffer

Python command mode maintains a **source buffer**: a list of clean Python
source lines that accumulates successful interactive input.

### Buffer append policy

- **Successful** expressions and statements are appended to the source buffer.
- **Failed** input (syntax errors, runtime exceptions, `NameError`, etc.) is
  **not** appended.
- Directive lines (`#exit`, `#help`, `#open`, `#save`, `#show`, `#run`,
  `#reset`, `#clear`, `#edit`) are **never** appended.
- Incomplete multi-line blocks are only appended after the complete block
  executes successfully.

```text
>>> a + b               ← NameError: not appended
>>> x = 1               ← success: appended
>>> #show
1 | x = 1
```

### Source buffer versus runtime state

These are two separate concepts:

| | Source buffer | Runtime state |
|---|---|---|
| **Contains** | Python source text | Live Python objects |
| **Populated by** | Successful interactive input, `#open` | Any executed input, `#run` |
| **Cleared by** | `#reset`, `#clear`, `#open` | `#reset` |
| **Used by** | `#save`, `#show`, `#run`, `#edit` | Expression evaluation, variable lookup |

## TAB behaviour

Inside Python command mode, **TAB inserts four spaces**. This allows natural
block indentation without triggering shell path completion.

```text
>>> def main():
...     print("hello")   ← four spaces inserted by TAB
```

Inside `#open`, `#save`, and `#show` path positions, TAB completes filesystem
paths instead.

## Syntax highlighting

Python command mode uses Pygments for terminal syntax highlighting.
Pygments is a normal runtime dependency for the current PySH release.

- Live input is highlighted as you type (real terminal mode).
- `#show` and `#show <file>` render highlighted source.
- `#edit` renders the buffer with full block-level highlighting.
- Error messages are highlighted.
- Highlighting is **render-only**: ANSI escape sequences are never written to
  files and never passed to the Python runtime.

### Color controls

| Variable | Effect |
|---|---|
| `PYSH_COLOR=0` | Disable all colors |
| `PYSH_COLOR=1` | Normal color (enabled for capable terminals) |
| `PYSH_COLOR=always` | Force ANSI even on non-TTY output |
| `NO_COLOR` | Disable colors; wins over `PYSH_COLOR` |

## Path behaviour

All file directives (`#open`, `#save`, `#show`) support:

```text
>>> #open filename.py          ← relative to current PySH working directory
>>> #open ./subdir/file.py     ← relative with explicit ./
>>> #open ../other/file.py     ← parent directory
>>> #open ~/Downloads/file.py  ← user home expansion
>>> #open /absolute/path.py    ← absolute path
```

Relative paths resolve against the current PySH working directory (the same
directory reported by `pwd`).

## Directives

Directives are recognised **only at the primary prompt** (`>>>`). At a
continuation prompt (`...`), lines beginning with `#` are treated as normal
Python comments.

### `#exit`

Exit Python command mode and return to the PySH prompt.

### `#help`

Show available directives and a usage summary.

### `#open <file>`

Load an existing Python source file into the source buffer and enter
file-backed edit mode.

```text
>>> #open main.py
opened: main.py
editing: main.py
```

Rules:

- Path is expanded (`~`, relative, absolute) and resolved.
- Content is read as UTF-8.
- The target must be a regular file, not a directory.
- The current source buffer is **replaced** with the loaded content.
- The file is **not executed automatically**. Use `#run` to execute it.
- The prompt changes to `[main.py:edit] >>> ` while a file is open.

### `#save [file]`

Save the current source buffer to a file.

```text
>>> #save session.py   ← save to named file, makes it the active file
>>> #save              ← save to the active file (set by #open or previous #save)
```

Rules:

- Path is expanded and resolved.
- Content is written as UTF-8.
- The file is created if it does not exist and overwritten if it does.
- The file always ends with a newline.
- Only Python source code is saved — no prompts, no output, no tracebacks,
  no directive lines, no ANSI escape sequences.

### `#show [file]`

Display the source buffer with line numbers (`#show`), or print a file like
`cat` without modifying the active buffer or active file (`#show <file>`).

```text
>>> #show
1 | from pathlib import Path
2 |
3 | def main():
4 |     print(Path.cwd())
```

```text
>>> #show other.py   ← cat-style display; does not affect active buffer
```

An empty buffer prints `buffer empty`.

### `#run`

Execute the complete source buffer inside the active Python runtime.

```text
>>> #run
```

- Uses `exec` semantics (`"exec"` compile mode): expression results are **not**
  echoed (unlike interactive input, which uses `"single"` mode).
- Runtime state is **preserved** after execution; variables and imports
  defined by the buffer are visible for further interactive work.
- `#run` does **not** reset the runtime automatically before executing.
- An empty buffer is a no-op (status 0).
- Syntax errors and runtime exceptions are reported clearly; Python command
  mode remains active.

### `#edit`

Display the active source buffer with full Python syntax highlighting
(block-level, not line-by-line). Read-only — does not modify the buffer or
any file.

### `#clear`

Clear the source buffer while keeping the active file reference and runtime
state.

```text
>>> #clear
buffer cleared
```

Use this to start fresh input without losing the active file context.

### `#reset`

Clear the source buffer, discard the active file reference, and recreate the
runtime namespace.

```text
>>> #reset
workspace reset
```

- The source buffer is emptied.
- All variables, imports, functions, and classes are discarded.
- Python command mode stays active; you are not returned to PySH.

### Advanced line-edit commands

These commands allow direct buffer manipulation:

| Command | Description |
|---|---|
| `#insert <line>` | Insert Python source before line number (1-based) |
| `#replace <line>` | Replace line number with new Python source |
| `#delete <line>` | Delete a single line |
| `#delete <a>:<b>` | Delete inclusive line range |
| `#append` | Confirm append mode (default; source is already appended) |

These are advanced commands. The primary editing workflow is:

```text
>>> #open main.py      ← load file
>>> #show              ← inspect buffer
>>> #clear             ← clear buffer for new content
>>> (type new source)
>>> #save              ← write back to active file
>>> #run               ← execute
```

## Clean file execution flow

The canonical way to load and run a file with a clean slate:

```text
>>> #reset          ← discard any previous state
>>> #open main.py   ← load source into buffer (does not execute)
>>> #run            ← execute the buffer
```

This ensures the file runs in a pristine `__main__` namespace without
contamination from previous interactive commands.

## Separation from the `py` builtin

Python command mode (`#py`) uses a **separate runtime namespace** from the
`py` builtin.

Variables defined with `py x = 1` are not visible inside `#py`, and vice
versa. This is intentional: they represent distinct execution contexts.

## Error handling

Syntax and runtime errors are reported clearly without terminating Python
command mode or PySH:

```text
>>> for
SyntaxError: invalid syntax

>>> 1 / 0
ZeroDivisionError: division by zero

>>> 2 + 2
4
```

Failed input is not appended to the source buffer.

## Ctrl+C and Ctrl+D behaviour

| Event | Location | Behaviour |
|---|---|---|
| Ctrl+D | Primary prompt (`>>>`) | Exit Python mode (same as `#exit`) |
| Ctrl+D | Continuation prompt (`...`) | Cancel incomplete block; return to `>>>` |
| Ctrl+C | Anywhere | Cancel current input; return to `>>>` |

PySH is never terminated by Ctrl+C inside Python command mode.

## Missing-`#` hints

If a directive word is typed without the leading `#`, Python command mode
detects it and shows a hint instead of executing it as Python or poisoning the
buffer:

```text
>>> show
pysh(py): use #show to display the active Python edit buffer
>>> open main.py
pysh(py): use #open main.py to open a file into the Python edit buffer
```

Normal Python assignments and function calls that happen to share a name with
a directive are not intercepted:

```text
>>> show = 42       ← valid Python; executed normally
>>> reset()         ← valid function call; executed normally
```

## Normal Python comments

Lines starting with `# ` (hash-space) that do not exactly match a supported
directive pattern are treated as normal Python comments:

```text
>>> # this is a Python comment — not a directive
>>> x = 1  # inline comment works too
```

## Forbidden syntax

The following shell-redirection forms are explicitly **not supported** and
will produce a directive error:

```text
>>> #echo > file.py    ← error
>>> #open < file.py    ← error
>>> #save > file.py    ← error
```

These do not create, overwrite, or load any file. Use Python's built-in
`open()` for arbitrary file I/O inside Python command mode.

## Current limitations

- TAB does not trigger Python symbol completion (inserts four spaces only).
- `sys.exit()` from user code exits Python command mode but does not
  terminate PySH.
- Python command mode runtime is session-local; it is not shared with the
  `py` builtin.
- Live input highlighting requires the raw-mode editor path. If raw mode is
  unavailable, PySH falls back to post-entry highlighting.
- Viewport bottom padding without scrollback pollution is deferred to a future
  release.

## Planned future work

- Python symbol completion on TAB.
- Optional persistence of the Python session across `#reset` / `#exit` cycles.
- Integration with the shell's `py` builtin runtime as an opt-in.
- Viewport bottom spacing without polluting scrollback.
