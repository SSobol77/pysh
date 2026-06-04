<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/script-mode-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Script Mode Contract

Issue #14 defines Script Mode v1: deterministic execution of explicit local
PySH script files. It is a PySH-native script interpreter contract, not POSIX
sh, bash or zsh compatibility.

## Scope and non-goals

Supported after Issue #14:

- `pysh script.pysh [args...]`
- `python -m pysh script.pysh [args...]`
- `#!/usr/bin/env pysh` shebang headers when the OS invokes PySH.
- Script positional parameters: `$0`, `$1`, `$2`, `$#`, `$@`, `$*`.
- Existing logical-line parsing: blank lines, comments, chains, conditionals,
  heredocs, here-strings, backslash continuations and `py { ... }` blocks.
- Existing debug trace integration with script file/line context.

Non-goals:

- Python script migration layer; that remains Issue #15.
- Zsh transition hardening; that remains Issue #16.
- System shell integration or `/bin/sh` replacement; that remains Issue #17.
- FreeBSD validation; that remains Issue #18.
- Packaging/release quality gate; that remains Issue #19.
- Full POSIX `set -e`, `set -u` or `set -x` behavior.

## Invocation contract

Command-string mode is unchanged:

```sh
pysh -c 'echo hello'
```

Script mode:

```sh
pysh script.pysh
pysh script.pysh arg1 arg2
python -m pysh script.pysh arg1 arg2
```

The CLI treats the first positional argument as a script path when `-c` is not
used. Remaining positional tokens are script arguments. Unknown options before
the script path are argparse errors; option-like values after the script path
are script arguments.

Any readable file path is allowed. `.pysh` is conventional, not required.
Missing files, directories and unreadable files produce deterministic stderr
diagnostics and return status 1.

## Shebang contract

If the first line starts with `#!`, direct script mode ignores that line as a
script header. PySH does not execute the shebang target manually.

Recommended header:

```sh
#!/usr/bin/env pysh
```

This support is for PySH scripts. It does not make PySH a POSIX `/bin/sh`
provider and does not execute foreign shell startup files.

The `run_script` builtin keeps its transition behavior: bash/sh/zsh shebangs
are explicitly delegated through an argv list. Direct `pysh script.pysh`
remains PySH-native.

## Positional parameters

| Parameter | Value |
| --------- | ----- |
| `$0` | Script path as invoked. |
| `$1`, `$2`, ... | Positional arguments. |
| `$#` | Number of positional arguments, excluding `$0`. |
| `$@` | Space-joined positional argument string. |
| `$*` | Same as `$@` in v1. |
| `$?` | Last PySH command status; unchanged from Issue #5. |

`"$1"` preserves spaces inside one positional argument. `"$@"` is deterministic
string expansion in v1; it does not implement POSIX separate-word semantics.

## Logical-line execution

Script Mode v1 uses `pysh.parsing.multiline.iter_logical_lines()` and
`PyShell.execute()` for each logical line. The same parser/runtime contract as
interactive mode applies to comments, blank lines, chains, conditionals,
pipelines, redirection, heredocs, here-strings, backslash continuations, glob
expansion and `py { ... }` blocks.

Completion is not involved. Background `&` uses the existing non-interactive
job-control behavior; foreground terminal handoff only occurs when a TTY is
available.

## Exit-code policy

- With no explicit `exit`, the script process status is the last executed
  command status.
- `exit N` terminates the script immediately with `N`.
- Parse/usage status `2` stops the script in v1.
- Command-not-found returns `127` for that line. If it is the final command,
  the script status is `127`.
- Signal mappings remain those from Issue #6.
- Python runtime errors keep the existing `py` contract.

## Strict-mode policy

Script Mode v1 does not implement POSIX `set -e`, `set -u` or `set -x`.
Debug tracing is available through `--debug` / `--trace`:

```sh
pysh --debug script.pysh
```

Trace lines go to stderr and are redacted by the Issue #13 policy.

## Security boundary

Scripts are trusted local PySH code. They are not sandboxed and are not safe
for untrusted input. Script mode does not source `.bashrc`, `.zshrc`,
`.profile` or external shell startup files. `run_script` and direct script
invocation are explicit execution surfaces.

Secret redaction applies to diagnostics and trace output only. Normal script
stdout is user command output and is not redacted.

## Validation

Primary evidence:

- `tests/test_script_mode.py`
- `tests/test_script_runner.py`
- `tests/test_error_exit_code_contract.py`
- `tests/test_observability_diagnostics.py`
- `tests/test_architecture_import_boundaries.py`

Validation invariants:

- CLI and module script invocation work.
- Shebang headers are ignored in native script mode.
- Positional parameters expand deterministically.
- Logical-line parser behavior matches interactive mode.
- `exit N`, parse status `2`, and command-not-found `127` propagate correctly.
- Debug trace goes to stderr and includes script context.
- No foreign profile execution occurs.

## Issue relationships

| Issue | Relationship |
| ----- | ------------ |
| #5 | Reuses canonical exit-code and `$?` propagation. |
| #7 | Scripts are trusted local execution, not sandboxed. |
| #8 | Reuses parser and logical-line infrastructure. |
| #10 | Reuses heredoc and here-string contract. |
| #11 | Reuses non-interactive job-control behavior. |
| #13 | Reuses debug/trace and redaction policy. |
| #15 | Python script migration remains out of scope. |
| #16 | Zsh transition hardening remains out of scope. |
| #17 | System shell integration remains out of scope. |
