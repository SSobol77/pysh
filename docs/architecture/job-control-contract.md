<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/job-control-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Job-Control Contract (Issue #11)

This document defines the job-control model established in the PySH 0.6.x line
and still normative for current releases unless superseded by a newer contract
section. All claims are backed by tests in `tests/test_job_control.py`.

---

## Scope

Issue #11 implements the **minimal professional job-control foundation**:

- Background execution with `&`.
- Process-group ownership for external commands and pipelines.
- Job table tracking.
- `jobs`, `fg`, and `bg` builtins.
- Ctrl+Z / SIGTSTP suspension of foreground jobs (interactive TTY only).
- `fg` and `bg` resume of stopped/background jobs.
- Background job reaping before each interactive prompt.

### Non-goals (explicit out-of-scope)

| Feature | Owner issue |
| ------- | ----------- |
| Completion engine v1 | #12 |
| Observability/trace CLI | #13 |
| Script Mode v1 execution contract | #14 |
| zsh transition hardening | #16 |
| FreeBSD full validation | #18 |
| Shell `trap` | — (Unsupported) |
| Process substitution | — (Unsupported) |
| `wait` builtin | — (future) |
| `disown` builtin | — (future) |
| POSIX sh compatibility claim | — |
| zsh/bash compatibility claim | — |

---

## Process-Group Model

### Shell process group

PySH does not call `setsid()` or otherwise change its own session at startup.
It inherits the session established by the login shell or terminal emulator.

In interactive mode (stdin and stdout are both TTYs), PySH:

1. Opens `/dev/tty` once at startup and stores the fd as `_tty_fd`.
2. Sets its own `SIGTSTP` disposition to `SIG_IGN` so the shell process
   itself is never suspended by Ctrl+Z.

These setup steps are performed in `PyShell.run()` only when `stdio_is_tty()`
returns True.  Non-interactive invocations (`pysh -c`, scripts, test harnesses)
skip all job-control setup.

### Foreground external command

When a foreground external command is spawned:

1. The child's `preexec_fn` (`make_child_preexec` from `pysh.core.jobs`) is
   called in the child process after fork but before exec.  It calls
   `os.setpgrp()` to create a new process group with the child's PID as PGID,
   and resets `SIGTSTP`, `SIGTTIN`, `SIGTTOU`, `SIGINT`, `SIGQUIT`, and
   `SIGCHLD` to `SIG_DFL`.
2. The parent gives the terminal to the child's PGID via
   `tcsetpgrp_safely(_tty_fd, pgid)`, which guards TTY availability and
   temporarily ignores `SIGTTIN`/`SIGTTOU` around `os.tcsetpgrp()`.
3. The parent waits using `os.waitpid(pid, WUNTRACED)` to detect both normal
   exit and SIGTSTP suspension.
4. On child stop (`WIFSTOPPED`): the job is registered in the job table as
   Stopped and the shell returns `148` (= `128 + SIGTSTP`).
5. On child exit: the exit status is extracted via `_raw_to_exit()`.
6. In all cases, the terminal is restored to the shell's process group in a
   `finally` block via `tcsetpgrp_safely(_tty_fd, os.getpgrp())`.

**Fallback behavior**: When `os.waitpid` raises `ChildProcessError` (e.g.,
in test environments that mock `subprocess.Popen`), PySH falls back to
`proc.wait()` to maintain test compatibility.

**Non-TTY fallback**: When `_tty_fd` is `None` or `has_tcsetpgrp()` returns
False, `tcsetpgrp` calls are skipped.  `os.waitpid` with `WUNTRACED` is still
used when `has_job_control()` is True, so stopped status is detected even
without terminal handover.

### Background external command

When a command is run with `&`:

1. The same `preexec_fn` puts the child in its own process group.
2. The shell does NOT give the terminal to the background PGID.
3. The shell does NOT wait for the child to finish.
4. The job is registered in `job_table` as Running with `background=True`.
5. The shell prints `[N] PID` to stdout and returns `0` immediately.
6. Background output still writes to the terminal unless redirected.

### Pipeline process-group model

For a pipeline `cmd1 | cmd2 | cmd3`:

1. `cmd1` uses `make_child_preexec` → new PGID = pid1.
2. `cmd2` and `cmd3` each call `os.setpgid(0, pid1)` in their preexec to
   join the first process's group.
3. All three processes share PGID = pid1.
4. For foreground pipelines: `os.tcsetpgrp(_tty_fd, pid1)` hands the
   terminal to the pipeline group.
5. For background pipelines (`cmd1 | cmd2 &`): the entire pipeline is one job
   with all pids listed.

Note: SIGTSTP detection in pipelines relies on `p.wait()` rather than
`os.waitpid(pid, WUNTRACED)` per stage; full per-stage stopped detection is
deferred to a later issue. The process-group isolation still ensures correct
Ctrl+C delivery.

---

## Job Table

`pysh.core.jobs.JobTable` tracks all running and stopped jobs.

### Job lifecycle

```
RUNNING  →  STOPPED  →  RUNNING  (SIGCONT via fg/bg)
         ↓             ↓
         DONE          DONE
         ↓
         TERMINATED
```

### Job ID allocation

Job IDs are monotonically increasing positive integers starting at 1.
The ID is never reused within a shell session.

### Current job

The current job (`+`) is the most recently added alive job.
If the current job finishes, the current pointer falls back to the next-most-
recently-added alive job.

### Reaping policy

Before each interactive prompt, `_reap_and_notify_jobs()` is called:

1. `JobTable.reap_background_jobs()` calls `os.waitpid(pid, WNOHANG|WUNTRACED)`
   for each pid in each Running job — non-blocking.
2. Completed jobs transition to Done.
3. The shell prints `[N]  Done     command_text` to stderr for each newly
   completed job.
4. `jobs` builtin: Done jobs are displayed and then removed from the table
   (displayed once, then gone).
5. On shell exit, background jobs are NOT killed.  They continue running
   under OS parent-process reaping once PySH exits.

---

## Builtin Contract

### `jobs`

```
jobs
```

Lists all tracked jobs (Running, Stopped, Done) in job-ID order.
Each line format is:

```
[N]+ STATUS      command_text
```

where `+` marks the current job and STATUS is one of `Running`, `Stopped`,
`Done`, or `Terminated`.

Done jobs are removed from the table after `jobs` displays them (shown once).

Returns `0` in all cases.

### `fg [job_id]`

```
fg [N | %N]
```

Brings a job to the foreground.

Behavior:
1. Resolves `N` or `%N` to a job.  If no argument, uses the current job.
2. Prints `command_text` to stdout.
3. Gives the terminal to the job's PGID (if TTY available).
4. Sends `SIGCONT` to the job's PGID if the job is Stopped.
5. Waits for the job using `os.waitpid` with `WUNTRACED`.
6. If the job stops again: marks Stopped; returns `148`.
7. If the job exits: marks Done; returns exit status.
8. Restores terminal to shell's PGID in `finally`.

Exit status:
- `0`: job exited 0.
- Job's exit status: for any other exit code.
- `130`: job interrupted by Ctrl+C.
- `148` (= `128 + SIGTSTP`): job stopped by Ctrl+Z.
- `1`: no current job, or unknown job ID.

### `bg [job_id]`

```
bg [N | %N]
```

Resumes a stopped job in the background.

Behavior:
1. Resolves `N` or `%N` to a job.  If no argument, uses the current job.
2. If job is not Stopped: error message; returns `1`.
3. Sends `SIGCONT` to the job's PGID.
4. Marks the job Running with `background=True`.
5. Prints `[N]+ command_text &`.
6. Returns `0`.

Does NOT wait for the job.

---

## Ctrl+C and Ctrl+Z Behavior

### Ctrl+C (SIGINT)

| Context | Effect | `$?` |
| ------- | ------ | ---- |
| Line editor (no child) | Cancels input line; shell continues | 130 |
| Foreground child | Child receives SIGINT; shell catches `KeyboardInterrupt` in waitpid; terminates child | 130 |
| Background child | Child does not receive SIGINT (not terminal foreground) | unaffected |

Behavior is identical to Issue #6.

### Ctrl+Z (SIGTSTP)

| Context | Effect | `$?` |
| ------- | ------ | ---- |
| Interactive TTY, foreground child | Child's process group receives SIGTSTP; child stops; `os.waitpid` with `WUNTRACED` detects stop; job added to table as Stopped | 148 |
| Non-TTY or no `WUNTRACED` | SIGTSTP behavior is OS default; not tracked by PySH | undefined |
| Shell itself | Shell ignores SIGTSTP (`SIG_IGN`) in interactive mode | — |

---

## Exit / Status Mapping

| Condition | `$?` value |
| --------- | ---------- |
| Normal exit(N) | N |
| Signal-killed child | 128 + signum |
| SIGINT | 130 |
| SIGTSTP-stopped foreground job | 148 (= 128 + 20) |
| Background command started | 0 |
| `fg` / `bg` on unknown job | 1 |
| `jobs` always | 0 |

---

## Non-TTY Behavior

`pysh -c 'cmd &'` is supported:

- The command starts in a new process group (if `has_job_control()` is True).
- The job is registered in the job table.
- The shell returns `0` immediately.
- No terminal handover occurs.
- No SIGTSTP detection (no TTY).
- Reaping does not happen (no interactive prompt loop).

---

## Portability Notes

**Linux/Debian (primary validation target):**

`os.setpgid`, `os.getpgrp`, `os.tcsetpgrp`, `os.tcgetpgrp`, `os.WUNTRACED`,
`os.WNOHANG`, `os.WIFSTOPPED`, `os.WIFEXITED`, `os.WIFSIGNALED` are all
available.  Full job-control behavior including Ctrl+Z is supported.

**Non-Linux POSIX (e.g., FreeBSD) — v0.8.0 validation gate:**

All POSIX job-control APIs are guarded by `hasattr(os, ...)` probes.
The architecture degrades gracefully on platforms where APIs are missing.
FreeBSD 14+ validation is tracked in Issue #18 and is release-blocking for
v0.8.0.

**Windows:**

PySH targets Linux/Debian and Unix-like systems.  Windows is not a supported
target.

---

## Security Considerations

- `make_child_preexec` resets `SIGINT`, `SIGQUIT`, and `SIGTSTP` to `SIG_DFL`
  plus `SIGTTIN`, `SIGTTOU`, and `SIGCHLD` in the child so that the child
  receives terminal and job-control signals normally.
- `tcsetpgrp_safely` temporarily ignores `SIGTTIN`/`SIGTTOU` only in the
  shell process while changing terminal foreground process group ownership,
  then restores the previous dispositions.
- PySH does not kill background jobs on exit.  Jobs continue running under
  OS orphan reaping rules.
- No privilege elevation is performed by job control.
- `os.killpg` is used only on pgids of processes started by PySH.

---

## Validation Matrix

| Claim | Test | Status |
| ----- | ---- | ------ |
| `&` parsed as background operator | `TestBackgroundOperatorParsing` | PASS |
| Quoted `&` is literal | `test_quoted_ampersand_is_literal` | PASS |
| `&&` unchanged | `test_double_ampersand_is_and` | PASS |
| `&>` unchanged (redirection) | `test_amp_redirect_is_not_background` | PASS |
| Bare `&` is parse error | `test_bare_ampersand_is_parse_error` | PASS |
| `sleep 0.1 &` returns 0 quickly | `test_background_sleep_returns_zero_immediately` | PASS |
| Job registered in table | `test_background_registers_in_job_table` | PASS |
| `false &` records exit status 1 | `test_false_background_eventually_marks_done` | PASS |
| `jobs` with no jobs | `test_jobs_with_no_jobs_returns_zero` | PASS |
| `fg` no current job → 1 | `test_fg_no_jobs_returns_one` | PASS |
| `fg 999` → 1 | `test_fg_unknown_numeric_job_id_returns_one` | PASS |
| `bg` no current job → 1 | `test_bg_no_jobs_returns_one` | PASS |
| `bg 999` → 1 | `test_bg_unknown_numeric_job_id_returns_one` | PASS |
| `&&` / `\|\|` unchanged | `TestRegressionOperators` | PASS |
| SIGINT maps to 130 | `TestRegressionSignals` | PASS |
| SIGTERM maps to 143 | `TestRegressionSignals` | PASS |

---

## Manual Validation (requires interactive TTY)

```sh
uv run pysh
> sleep 5 &           # prints [1] PID; prompt returns immediately
> jobs                # shows [1]+ Running  sleep 5
> sleep 30            # start foreground job
# Press Ctrl+Z
> jobs                # shows [1]+ Running  sleep 5 / [2]+ Stopped  sleep 30
> bg                  # resumes sleep 30 in background
> fg 1                # brings sleep 5 to foreground
# Press Ctrl+C        # kills it; $? = 130
> echo $?             # 130
```

---

## Relation to Other Issues

| Issue | Relation |
| ----- | -------- |
| #5 (exit codes) | `$?` propagation from job exit status |
| #6 (signal handling) | Ctrl+C behavior preserved; SIGTSTP extends #6 |
| #8 (parser) | `split_chain` extended with `ChainOp.BACKGROUND` |
| #10 (heredocs) | Heredoc bodies passed through chain/background path unchanged |
| #12 (completion) | `jobs`, `fg`, `bg` added to completer BUILTINS list |
| #13 (observability) | Out of scope for #11 |
| #14 (script mode) | `pysh -c 'cmd &'` supported; interactive job control requires TTY |
| #18 (FreeBSD) | Portability probes in place; FreeBSD 14+ validation is release-blocking for v0.8.0 |
