<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/error-exit-code-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Error and Exit-Code Contract

This document is the canonical reference for PySH error handling and exit-code
semantics, established by GitHub Issue #5.

---

## Canonical exit codes

| Name | Value | Meaning |
| ---- | ----: | ------- |
| `SUCCESS` | 0 | Command completed successfully |
| `GENERAL_ERROR` | 1 | Generic runtime or command error |
| `BUILTIN_MISUSE` | 2 | Builtin usage error: invalid option, missing operand, syntax error |
| `CANNOT_EXECUTE` | 126 | Command found but not executable (permission denied) |
| `COMMAND_NOT_FOUND` | 127 | Command not found in PATH |
| `SIGNAL_BASE` | 128 | Base for signal-termination exit codes |
| `SIGINT` | 130 | Interrupted by SIGINT (128 + 2) |

Signal termination formula: `exit_code = 128 + signal_number`.

All values are defined in `src/pysh/core/errors.py` as `ExitCode(IntEnum)`.

---

## PyShError taxonomy

```text
BaseException
└── Exception
    └── PyShError                  exit_code attribute; default = 1
        ├── CommandNotFoundError   exit_code = 127
        ├── CommandNotExecutableError  exit_code = 126
        ├── BuiltinUsageError      exit_code = 2
        ├── PyShParseError         exit_code = 2
        ├── ExecutionError         caller-supplied exit_code (default 1)
        └── PyShInterruptedError   exit_code = 130
```

All `PyShError` subclasses carry an `exit_code` attribute so callers can
determine the process exit status without pattern-matching on exception type.

Internal exception `_ExitShell` (in `core/shell.py`) is a separate private
mechanism for the `exit`/`quit` builtins and is not part of the public taxonomy.

---

## Module: `pysh.core.errors`

Location: `src/pysh/core/errors.py`

**Rules:**
- Standard library only. No pysh implementation imports.
- No I/O at import time. No printing.
- Intra-package (`pysh.core`); does not introduce new cross-domain imports.

**Public API:**
```python
ExitCode                    # IntEnum with canonical values
signal_exit_code(signum)    # returns 128 + signum
PyShError                   # base exception
CommandNotFoundError        # 127
CommandNotExecutableError   # 126
BuiltinUsageError           # 2
PyShParseError              # 2
ExecutionError              # caller-supplied
PyShInterruptedError        # 130
Diagnostic                  # frozen dataclass: message, exit_code, prefix
exception_to_diagnostic(exc)  # maps BaseException → Diagnostic
diagnostic_to_exit_code(d)    # extracts int from Diagnostic
```

---

## External command exit propagation

Rules:
- Positive process exit codes are propagated exactly: exit code N → status N.
- Exit code 0 means success.
- Signal termination: when a child process terminates due to a signal,
  `subprocess.Popen.wait()` returns a negative value (`-signum`).
  PySH maps negative return codes through
  `pysh.core.signals.returncode_to_exit_status()` per the formula
  `128 + signum`.  Examples: `-SIGINT` (−2) → 130; `-SIGTERM` (−15) → 143.
  This mapping was implemented in Issue #6.
- `KeyboardInterrupt` raised during `proc.wait()` (Ctrl+C in parent):
  child is terminated, wait is collected, and PySH returns `ExitCode.SIGINT`
  (130) directly without passing through `returncode_to_exit_status`.
- `signal_exit_code(signum)` in `pysh.core.errors` is the canonical formula
  helper for constructing signal exit codes from a signal number.
- Command substitution timeout: if a `$()` substitution times out, it
  expands to an empty string and the shell continues. The timeout exit
  code is not propagated to `last_status` in the current implementation.

Specific cases:

| Event | Shell action | Exit code |
| ----- | ------------ | --------- |
| Command not in PATH | Print `pysh: CMD: command not found` to stderr | 127 |
| Command found, not executable | Print `pysh: CMD: <detail>` to stderr | 126 |
| Command completes with exit code N | Propagate N exactly | N |
| Child killed by signal (signum) | `returncode_to_exit_status(-signum)` → `128 + signum` | 128 + signum |
| Child killed by SIGINT (−2) | `returncode_to_exit_status(-2)` → 130 | 130 |
| Child killed by SIGTERM (−15) | `returncode_to_exit_status(-15)` → 143 | 143 |
| Process interrupted by SIGINT during `wait()` | Terminate child, return `ExitCode.SIGINT` | 130 |
| OS-level error before `Popen` | Print `pysh: <detail>` to stderr | 1 |

---

## Builtin return-code contract

| Category | Exit code | Condition |
| -------- | --------- | --------- |
| Success | 0 | Normal completion |
| General failure | 1 | Runtime error (e.g., `cd` to nonexistent directory) |
| Usage error | 2 | Wrong arguments, missing operand, unknown option |
| Command not found | 127 | `mc` when `mc` binary is absent |

Builtin misuse examples that return 2:
- `pushd` with no argument
- `unalias` with no argument
- `source_zsh` / `source_zsh_profile` / `source_sh_aliases` with no file
- `py {` without a collected block (bare unterminated block)
- `zsh_fallback` with an invalid argument

Parse errors (unclosed quotes, shlex failure) also return 2 because they are
command-level syntax errors from the user's perspective.

---

## Parse/syntax error mapping

| Error source | Example | Exit code |
| ------------ | ------- | --------- |
| `shlex.split` ValueError (unclosed quote) | `echo 'unclosed` | 2 |
| Empty pipeline stage | `cmd1 \| cmd2 \|` | 2 (in pipeline path) |
| Bare `py {` without closing `}` | `py {` (single line) | 2 |
| Unknown parse condition | Any other `ValueError` from tokeniser | 2 |

These all map to 2 (`BUILTIN_MISUSE`) because parse errors in an interactive
shell are semantically equivalent to incorrect command invocations.

---

## Signal exit-code mapping

```python
exit_code = 128 + signal_number
```

| Signal | Number | Exit code |
| ------ | ------ | --------- |
| SIGHUP | 1 | 129 |
| SIGINT | 2 | 130 |
| SIGQUIT | 3 | 131 |
| SIGKILL | 9 | 137 |
| SIGTERM | 15 | 143 |

The `signal_exit_code(signum)` function in `pysh.core.errors` applies this
formula. PySH handles SIGINT explicitly at the shell level and returns 130
from `_run_external` and `_run_pipeline` when `KeyboardInterrupt` is raised
during `proc.wait()`.

---

## `$?` status propagation

`$?` is the only POSIX special parameter implemented in PySH (Issue #5).

**How it works:**

After each command executes in the shell REPL loop, `self.last_status` is
updated. Before variable expansion for the *next* command, `$?` is injected
via `special_vars={"?": str(self.last_status)}` in the `expand_variables`
call.

**Examples:**

```sh
false
echo $?        # prints 1

true
echo $?        # prints 0

python3 -c 'import sys; sys.exit(7)'
echo $?        # prints 7

missing_cmd
echo $?        # prints 127
```

**Constraints:**
- `$?` is valid inside double quotes (expanded) and outside quotes.
- `$?` is literal inside single quotes (not expanded).
- No other POSIX special parameters are implemented (`$0`, `$$`, `$!`, `$#`,
  `$@`, `$*`, positional parameters). These are not owned by Issue #5.
- Advanced parameter expansion (`${?}`, `${?:-default}`) is not implemented.

---

## CLI boundary function

`pysh.cli.main()` is the single top-level error boundary. Any `BaseException`
that escapes from `shell.execute()` or `shell.run()` is caught and converted
via `exception_to_diagnostic(exc)`:

```python
try:
    return shell.execute(args.command)
except SystemExit as exc:
    return int(exc.code) if exc.code is not None else 0
except BaseException as exc:
    diag = exception_to_diagnostic(exc)
    print(diag.format_stderr(), file=sys.stderr)
    return diag.exit_code
```

This ensures:
- Tracebacks never leak to end users.
- Every exit code corresponds to the canonical table.
- The boundary is a single location (not scattered through the runtime).

---

## Script-mode current behavior and Issue #14

In PySH 0.5.x, script mode is partial:
- `run_script <file>` delegates shebang scripts to the real interpreter.
- No-shebang scripts are executed line-by-line through PySH's native engine.
- The exit code of `run_script` follows the same mapping as interactive mode.
- `set -e` / `set -x` / `set -u` are not implemented.
- Full script-mode exit-code contract (non-zero propagation, `set -e`
  semantics) is owned by GitHub Issue #14.

Until Issue #14 is resolved, script-mode callers should not rely on
consistent exit-code propagation for complex pipelines or multi-command scripts.

---

## Validation matrix

| Claim | Test | Status |
| ----- | ---- | ------ |
| `ExitCode` values are correct | `test_error_exit_code_contract.py::TestExitCodeValues` | PASS |
| `signal_exit_code(2) == 130` | `TestSignalExitCode::test_sigint_is_130` | PASS |
| `PyShError` taxonomy and exit codes | `TestPyShErrorTaxonomy` | PASS |
| `Diagnostic.format_stderr()` | `TestDiagnostic` | PASS |
| `exception_to_diagnostic` mapping | `TestDiagnostic` | PASS |
| External exit code propagation | `TestExternalCommandPropagation` | PASS |
| Command-not-found → 127 | `TestCommandNotFound` | PASS |
| Cannot-execute → 126 | `TestCannotExecute` | PASS |
| Builtin misuse → 2 | `TestBuiltinMisuse` | PASS |
| Parse error → 2 | `TestParseErrorMapping` | PASS |
| `$?` propagation | `TestDollarQuestionPropagation` | PASS |
| `$?` in parser | `TestExpandVariablesDollarQuestion` | PASS |
| SIGINT mapping (non-process) | `TestSigintMapping` | PASS |

---

## Relation to other issues

| Issue | Role |
| ----- | ---- |
| Issue #3 | Import-boundary enforcement: `pysh.core.errors` stays within `pysh.core` |
| Issue #5 | This document |
| Issue #6 | Signal handling: extends SIGINT → 130 to all execution contexts; see [signal-handling.md](signal-handling.md) |
| Issue #8 | Parser hardening: deterministic parser-local diagnostics map to exit status 2 |
| Issue #14 | Script-mode full error contract |
