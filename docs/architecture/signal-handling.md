<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/signal-handling.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Signal-Handling Architecture (Issue #6)

This document defines the signal-handling contract for PySH version 0.6.x.
It covers the three current execution contexts and the future job-control
scaffold. All claims are backed by tests in `tests/test_signal_handling.py`.

---

## Scope

Issue #6 implements **deterministic signal handling** for the three current
execution contexts. It does NOT implement:

- Full job control (`jobs`, `fg`, `bg`, `&` background, `wait`) — Issue #11.
- Process-group foreground/background ownership rewrite — Issue #11.
- SIGTSTP/SIGCONT job suspension — Issue #11.
- Script mode — Issue #14.

---

## Signal helper module

`pysh.core.signals` (stdlib only, no I/O at import time):

| Symbol | Type | Description |
| ------ | ---- | ----------- |
| `SignalContext` | `str` constants | Named execution contexts (documentation only) |
| `SignalDisposition` | `IntEnum` | Canonical signal numbers (SIGINT, SIGTERM) |
| `is_signal_returncode(rc)` | `bool` | True when `rc < 0` (signal-killed child) |
| `returncode_to_exit_status(rc)` | `int` | Maps negative subprocess returncode to `128 + signum` |
| `keyboard_interrupt_status()` | `int` | Always returns 130 |
| `signal_name(signum)` | `str` | `'SIGINT'` for 2, etc.; falls back to `'SIG<N>'` |

The module performs no signal registration and no terminal I/O at import time.

---

## Exit-code mapping

PySH follows the POSIX shell convention: `128 + signum`.

| Signal | signum | PySH exit status |
| ------ | ------ | ---------------- |
| SIGINT | 2 | **130** |
| SIGTERM | 15 | **143** |
| SIGKILL | 9 | **137** |
| General signal N | N | **128 + N** |

The formula is implemented in:
- `pysh.core.errors.signal_exit_code(signum)` — maps signal number to exit code.
- `pysh.core.signals.returncode_to_exit_status(rc)` — maps subprocess negative returncode.
- `pysh.security.secure_runner.SecureRunner._status_to_returncode(status)` — maps `os.waitpid` raw status.

---

## Execution context table

| Context | SIGINT / Ctrl+C | SIGTERM | SIGTSTP | Terminal restored? |
| ------- | --------------- | ------- | ------- | ------------------ |
| **Line editor** | Cancels current input line; `last_status = 130`; shell continues | N/A (shell process) | Unsupported — Issue #11 | Yes — `finally` in `read_line` |
| **External command** | Child receives SIGINT via PTY/tty; parent catches `KeyboardInterrupt`, terminates child, returns 130 | Child returncode mapped via `returncode_to_exit_status` → 143 | Unsupported — Issue #11 | Yes — file descriptors closed in `finally` |
| **Python runtime** (`py` builtin) | `KeyboardInterrupt` caught in `_execute_compiled`; returns 130; no traceback | N/A | N/A | N/A (in-process) |
| **Secure PTY runner** | `KeyboardInterrupt` sends SIGINT to child via `os.kill`; waits; terminal state restored in `finally` | Child signal mapped via `_status_to_returncode` → 143 | N/A | Yes — `termios.tcsetattr` in `finally` |
| **Job control** | Preserved (see Issue #6 behavior) | Preserved | SIGTSTP stops foreground child; `os.waitpid(WUNTRACED)` detects it; job added to table as Stopped; `$?=148` | Terminal restored via `tcsetpgrp` in `finally` |

---

## SIGINT behavior

### A. Line editor / interactive prompt

When Ctrl+C is pressed in the raw-mode line editor:

1. The `KeyDecoder` decodes `\x03` as `Key.CTRL_C`.
2. `_handle_event` raises `KeyboardInterrupt`.
3. The `finally` block in `read_line` runs unconditionally:
   - Bracketed paste mode is disabled (`_disable_bracketed_paste`).
   - Terminal state is restored (`termios.tcsetattr` with saved state).
   - The fd is removed from `_saved_termios`.
4. `KeyboardInterrupt` propagates to the `run()` loop.
5. The run loop catches it: prints newline, sets `self.last_status = 130`, continues.

Result: current input line is discarded; shell returns to a clean prompt; `$?` == 130.

### B. External command

When Ctrl+C is pressed while a foreground child is running:

1. The terminal sends SIGINT to the foreground process group.
2. The child (external command) receives SIGINT and typically exits.
3. In the parent, Python raises `KeyboardInterrupt` during `proc.wait()`.
4. The `except KeyboardInterrupt` block in `_run_external` / `_run_pipeline` runs:
   - `proc.terminate()` is called (belt-and-suspenders).
   - `proc.wait()` collects the child.
   - Return value is `ExitCode.SIGINT` (130).

Result: child is interrupted; PySH continues; `last_status = 130`.

If the child is killed by a signal *before* the parent catches `KeyboardInterrupt`
(e.g., killed by SIGTERM from an external source), `proc.wait()` returns a negative
value. `returncode_to_exit_status()` maps it to `128 + signum`.

### C. Python runtime (`py` builtin)

When Ctrl+C is pressed while Python code is executing under the `py` builtin:

1. Python raises `KeyboardInterrupt` inside `exec()` in `_execute_compiled`.
2. `_execute_compiled` catches `KeyboardInterrupt` before `Exception`.
3. Returns 130. No traceback is printed.

Result: `py` builtin exits with status 130; shell continues; `last_status = 130`.

---

## SIGTERM behavior

PySH does not install a custom SIGTERM handler. Default OS behavior applies:

- If PySH receives SIGTERM outside child execution, the Python process is
  terminated by the OS. Terminal restoration runs if `atexit` hooks are
  registered (cursor color reset, termios restore via `_restore_saved_termios`).
- If a foreground child receives SIGTERM, `proc.wait()` returns `-15`.
  `returncode_to_exit_status(-15)` returns 143, which PySH propagates as `last_status`.

---

## SIGTSTP / Ctrl+Z

**Issue #11 implements SIGTSTP job control for foreground external commands.**

When PySH is running in interactive mode (both stdin and stdout are TTYs):

1. PySH sets its own `SIGTSTP` disposition to `SIG_IGN` at startup so the
   shell process itself is never stopped by Ctrl+Z.
2. The foreground child process runs in its own process group.  The child's
   `preexec_fn` (`make_child_preexec`) resets `SIGTSTP` to `SIG_DFL` so the
   child can be stopped.
3. PySH waits with `os.waitpid(pid, WUNTRACED)` so it can detect when the
   child is stopped by SIGTSTP.
4. On detection: the job is registered in the job table as Stopped; the shell
   returns `148` (= `128 + SIGTSTP`) as `$?`.
5. The terminal foreground process group is restored to PySH in a `finally`
   block.

See [job-control-contract.md](job-control-contract.md) for the full model.

---

## Terminal restoration guarantees

For every interrupted path in the line editor:

| Guarantee | Mechanism |
| --------- | --------- |
| Raw mode restored | `termios.tcsetattr(in_fd, TCSADRAIN, old_state)` in `finally` |
| Bracketed paste mode disabled | `_disable_bracketed_paste(out_fd)` in `finally` |
| `_saved_termios` cleared | `_saved_termios.pop(in_fd, None)` in `finally` |
| Process-exit fallback | `atexit.register(_restore_saved_termios)` at module load |

For the secure PTY runner (`secure_runner.py`):

| Guarantee | Mechanism |
| --------- | --------- |
| Raw mode restored | `termios.tcsetattr(in_fd, TCSADRAIN, old_state)` in `finally` |
| Master PTY closed | `os.close(master_fd)` in `finally` |
| Indicator erased | `indicator.erase()` called in `finally` block |

---

## Validation matrix

| Claim | Test file | Test class/function | Status |
| ----- | --------- | ------------------- | ------ |
| `returncode_to_exit_status(0) == 0` | `test_signal_handling.py` | `TestReturnCodeToExitStatus.test_zero` | PASS |
| `returncode_to_exit_status(7) == 7` | `test_signal_handling.py` | `test_positive_7` | PASS |
| `returncode_to_exit_status(-SIGINT) == 130` | `test_signal_handling.py` | `test_sigint` | PASS |
| `returncode_to_exit_status(-SIGTERM) == 143` | `test_signal_handling.py` | `test_sigterm` | PASS |
| `keyboard_interrupt_status() == 130` | `test_signal_handling.py` | `TestKeyboardInterruptStatus` | PASS |
| `signal_name(SIGINT) == 'SIGINT'` | `test_signal_handling.py` | `TestSignalName` | PASS |
| SIGINT-killed subprocess → 130 | `test_signal_handling.py` | `TestExternalCommandSignalMapping` | PASS |
| SIGTERM-killed subprocess → 143 | `test_signal_handling.py` | `test_child_killed_by_sigterm` | PASS |
| Shell external command signal mapping | `test_signal_handling.py` | `TestShellSignalIntegration` | PASS |
| `py raise KeyboardInterrupt()` → 130 | `test_signal_handling.py` | `TestPythonRuntimeKeyboardInterrupt` | PASS |
| SecureRunner signal mapping | `test_signal_handling.py` | `TestSecureRunnerStatusConsistency` | PASS |
| Existing secure runner tests pass | `test_secure_runner.py` | all | PASS |
| Existing exit-code contract tests pass | `test_error_exit_code_contract.py` | all | PASS |

---

## Manual acceptance tests

These tests require a real interactive terminal.

### Test 1: Ctrl+C at empty prompt

```
uv run pysh
```

1. At an empty prompt, press Ctrl+C.
2. Expected: shell prints newline and returns to prompt.
3. Expected: no Python traceback.
4. Expected: terminal remains usable (echo works, cursor is normal).
5. Expected: `echo $?` returns `130`.

### Test 2: Ctrl+C during external command

```
uv run pysh
> sleep 60
```

1. Press Ctrl+C while `sleep 60` is running.
2. Expected: `sleep` is interrupted.
3. Expected: shell returns to prompt.
4. Expected: `echo $?` returns `130`.

### Test 3: Ctrl+C during py execution

```
uv run pysh
> py import time; time.sleep(60)
```

1. Press Ctrl+C while Python sleeps.
2. Expected: `py` builtin returns with status 130.
3. Expected: no traceback printed.
4. Expected: shell continues.

### Test 4: Terminal state after Ctrl+C in editor

1. Launch `uv run pysh`.
2. Type some text (do not press Enter).
3. Press Ctrl+C.
4. Type `echo hello` and press Enter.
5. Expected: `hello` is printed correctly.
6. Expected: no stray raw-mode bytes, no corrupted prompt.

---

## Implementation files

| File | Change | Issue |
| ---- | ------ | ----- |
| `src/pysh/core/signals.py` | Created — signal helper module | #6 |
| `src/pysh/core/shell.py` | `returncode_to_exit_status()` applied in `_run_external` and `_run_pipeline`; `last_status = 130` on line-editor Ctrl+C | #6 |
| `src/pysh/python_layer/runtime.py` | `KeyboardInterrupt` caught in `_execute_compiled`; returns 130 | #6 |
| `tests/test_signal_handling.py` | Created — signal-handling test suite | #6 |
| `docs/architecture/signal-handling.md` | Created — this document | #6 |

---

## Non-goals (Issue #6 boundary)

- No `jobs`, `fg`, `bg`, `&`, `wait` builtin — Issue #11.
- No process-group ownership rewrite — Issue #11.
- No SIGTSTP/SIGCONT job suspension — Issue #11.
- No full POSIX signal mask management.
- No daemon or service mode signal handling.
- No script-mode signal semantics — Issue #14.
