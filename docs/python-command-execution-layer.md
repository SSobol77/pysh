<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/python-command-execution-layer.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Python Command Execution Layer

PySH v0.5.0 introduces an interactive Python command mode that can be entered
from the normal PySH prompt.

## Entering Python command mode

Type `#py` at the normal PySH prompt:

```text
🐍 user@host ~/project > #py
```

You will see the Python mode banner:

```text
PySH Python Command Execution Layer
Python 3.13.2
Type #help for commands.

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

Enter an empty line to close a block:

```text
>>> for i in range(3):
...     print(i)
...
0
1
2
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

## TAB behaviour

Inside Python command mode, **TAB inserts four spaces**. This allows natural
block indentation without triggering shell completion.

```text
>>> def main():
...     print("hello")   ← four spaces inserted by TAB
```

TAB completion is not active in Python command mode in v0.5.0.

## Directives

Directives are recognised **only at the primary prompt** (`>>>`). At a
continuation prompt (`...`), lines beginning with `#` are treated as normal
Python comments.

### `#exit`

Exit Python command mode and return to the PySH prompt.

### `#help`

Show available directives and a usage summary.

### `#open <file>`

Load an existing Python source file into the source buffer.

```text
>>> #open main.py
opened: main.py
```

Rules:

- Path is resolved relative to the current PySH working directory.
- Content is read as UTF-8.
- The target must be a regular file, not a directory.
- The current source buffer is **replaced** with the loaded content.
- The file is **not executed automatically**. Use `#run` to execute it.

### `#save <file>`

Save the current source buffer to a file.

```text
>>> #save session.py
saved: session.py
```

Rules:

- Path is resolved relative to the current PySH working directory.
- Content is written as UTF-8.
- The file is created if it does not exist and overwritten if it does.
- The file always ends with a newline.
- Only Python source code is saved — no prompts, no output, no tracebacks,
  no directive lines.

### `#show`

Display the source buffer with line numbers.

```text
>>> #show
1 | from pathlib import Path
2 |
3 | def main():
4 |     print(Path.cwd())
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

### `#reset`

Clear the source buffer and recreate the runtime namespace.

```text
>>> #reset
```

- The source buffer is emptied.
- All variables, imports, functions, and classes are discarded.
- Python command mode stays active; you are not returned to PySH.

## Source buffer versus runtime state

These are two separate concepts:

| | Source buffer | Runtime state |
|---|---|---|
| **Contains** | Python source text | Live Python objects |
| **Populated by** | Interactive input, `#open` | Interactive execution, `#run` |
| **Cleared by** | `#reset`, `#open` | `#reset` |
| **Used by** | `#save`, `#show`, `#run` | Expression evaluation, variable lookup |

Interactive lines that are executed successfully are appended to the source
buffer. Syntax-error lines are **not** appended.

Directive lines (`#exit`, `#help`, `#open`, `#save`, `#show`, `#run`,
`#reset`) are **never** appended to the source buffer.

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

## Ctrl+C and Ctrl+D behaviour

| Event | Location | Behaviour |
|---|---|---|
| Ctrl+D | Primary prompt (`>>>`) | Exit Python mode (same as `#exit`) |
| Ctrl+D | Continuation prompt (`...`) | Cancel incomplete block; return to `>>>` |
| Ctrl+C | Anywhere | Cancel current input; return to `>>>` |

PySH is never terminated by Ctrl+C inside Python command mode.

## Normal Python comments

Lines starting with `#` that do not exactly match a supported directive
pattern are treated as normal Python comments:

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

## v0.5.0 limitations

- TAB does not trigger Python completion (inserts four spaces only).
- `sys.exit()` from user code exits Python command mode but does not
  terminate PySH.
- Python command mode runtime is session-local; it is not shared with the
  `py` builtin.
- Live input highlighting requires the raw-mode editor path. If raw mode is
  unavailable, PySH falls back to post-entry highlighting.

## Planned future work

- Python symbol completion on TAB.
- Optional persistence of the Python session across `#reset` / `#exit` cycles.
- Integration with the shell's `py` builtin runtime as an opt-in.
