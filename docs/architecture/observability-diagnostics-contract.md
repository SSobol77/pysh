<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/observability-diagnostics-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Observability and Diagnostics Contract

Issue #13 defines PySH's explicit observability and diagnostics surface.
Diagnostics are opt-in, read-only unless a documented diagnostic helper must
invoke a read-only external tool, and scoped to explaining how PySH parses,
expands, resolves and plans commands.

## Scope and non-goals

Supported after Issue #13:

- `pysh --debug -c 'command'` and `pysh --trace -c 'command'`.
- Stable human-readable trace lines prefixed with `[PYSH_DEBUG]`.
- Trace output to stderr only.
- Redaction of sensitive environment names and values in diagnostic output.
- Formalized diagnostic builtins: `plan`, `sys_info`, `env_audit`,
  `path_audit`, `which_all`, `apt_check`, `apt_search`, `compat_check`.

Non-goals:

- Full script mode; that remains Issue #14.
- Python script migration layer; that remains Issue #15.
- Zsh transition hardening; that remains Issue #16.
- System shell integration; that remains Issue #17.
- POSIX, bash or zsh compatibility claims beyond the compatibility matrix.
- Diagnostic execution of target commands. `plan` is not execution.

## Diagnostic stages

The canonical stages are:

| Stage | Meaning |
| ----- | ------- |
| `INPUT` | Raw command line accepted by the CLI or shell loop. |
| `LEX` | Quote/comment/token scanning boundary. |
| `PARSE` | Chain and pipeline parsing. |
| `HEREDOC` | Here-document and here-string body collection. |
| `EXPAND` | Variable expansion and command-substitution boundary. |
| `PATH_EXPAND` | Tilde, glob and argv token expansion. |
| `REDIRECT` | Redirection parser result. |
| `RESOLVE` | Builtin/external/missing command resolution. |
| `EXECUTE_PLAN` | Final argv and observed exit status. |
| `JOB_CONTROL` | Future job-control trace points. |
| `COMPLETE` | Completion diagnostics; completion behavior remains Issue #12. |
| `ERROR` | Parse, resolution, execution or diagnostic errors. |

Not every command emits every stage. Future events must use these names rather
than inventing new synonyms.

## Trace contract

Trace mode is explicit:

```sh
pysh --debug -c 'echo hello'
pysh --trace -c 'echo hello'
```

Trace mode:

- Writes only to stderr.
- Does not write trace data to normal command stdout.
- Does not change execution order, command argv, child environment or exit
  status.
- Does not execute extra commands.
- Redacts sensitive values before formatting.
- Emits deterministic `key=value` fields suitable for tests.

Example shape:

```text
[PYSH_DEBUG] stage=INPUT level=DEBUG message='received line' line='echo hello'
[PYSH_DEBUG] stage=RESOLVE level=DEBUG message='command resolved' command=echo kind=external path=/usr/bin/echo
[PYSH_DEBUG] stage=EXECUTE_PLAN level=DEBUG message='command finished' status=0
```

## Stdout and stderr

| Surface | stdout | stderr |
| ------- | ------ | ------ |
| Normal commands | Command output | Runtime errors only |
| `--debug` / `--trace` | Command output only | Trace plus runtime errors |
| Diagnostic builtins | Intentional diagnostic report | Usage/runtime errors |
| `plan` | Advisory plan report | Usage error only |

The invariant is that debug/trace must never contaminate normal command stdout.

## Redaction policy

Names are sensitive when they contain any of:

`PASSWORD`, `PASSWD`, `PASS`, `TOKEN`, `SECRET`, `KEY`, `PRIVATE`,
`CREDENTIAL`, `AUTH`, `COOKIE`, `SESSION`, `API_KEY`, `ACCESS_TOKEN`,
`REFRESH_TOKEN`.

Rules:

- Sensitive values are replaced with `<redacted>`.
- `env_audit` may show variable names, but not sensitive values.
- Trace lines redact sensitive assignments and known sensitive environment
  values.
- `plan` redacts displayed command text. It still classifies the raw command
  without execution.
- Completion remains name-only for variables and never displays values.
- `SSH_AUTH_SOCK` is treated as sensitive by name because it contains `AUTH`;
  the value is redacted.

## Command planning

`plan <command...>` is advisory and non-mutating. It classifies a line as
`builtin`, `external`, `pipeline`, `chain`, `python`, `zsh-delegation`,
`script` or `unknown`, assigns a coarse risk level, and prints a deterministic
report. It never executes the target command, command substitutions inside the
target, redirections, scripts, profile files or PATH candidates.

## Diagnostic builtins

| Builtin | Contract |
| ------- | -------- |
| `sys_info` | Prints read-only platform, Python, cwd, user, home, shell and PATH-count metadata. |
| `env_audit` | Prints a redacted environment audit. Sensitive values are never printed. |
| `path_audit` | Stats PATH entries and reports `ok`, `missing`, `not_dir` or `duplicate`. |
| `which_all NAME` | Lists executable PATH matches in PATH order; never executes them. |
| `apt_check` | Runs `apt list --upgradable` only; no sudo and no mutation. |
| `apt_search QUERY` | Runs `apt search QUERY` only; no sudo and no mutation. |
| `compat_check FILE` | Reads a shell file as text; does not source shell startup files or spawn interpreters. |

`apt_check` and `apt_search` are explicit read-only external diagnostics. If
`apt` is unavailable, they fail deterministically with status 127.

## Security boundaries

Diagnostics do not relax the Issue #7 trust model. Trace mode is not a
security monitor, policy engine, sandbox, audit log or privilege boundary.
It is a developer/operator diagnostic surface. It redacts known sensitive
values but cannot prove that arbitrary command output is non-secret.

## Validation

Automated evidence:

- `tests/test_observability_diagnostics.py`
- `tests/test_command_plan.py`
- `tests/test_system_info.py`
- `tests/test_security_trust_model.py`
- `tests/test_docs_consistency.py`
- `tests/test_architecture_import_boundaries.py`

Validation invariants:

- Debug disabled by default.
- Debug enabled only by explicit CLI flag.
- Trace goes to stderr.
- Command stdout remains clean.
- Exit status is unchanged.
- Parse errors and command-not-found paths do not traceback.
- Sensitive values are redacted from diagnostic output.
- Diagnostic builtins are read-only except documented read-only `apt` calls.

## Issue relationships

| Issue | Relationship |
| ----- | ------------ |
| #5 | Reuses the canonical stderr/exit-code boundary. |
| #7 | Extends diagnostics non-mutation and redaction policy. |
| #8 | Observes parser/expansion stages without changing parser semantics. |
| #9 | Observes path/glob expansion without changing expansion policy. |
| #10 | Observes heredoc collection without changing stdin behavior. |
| #11 | Reserves `JOB_CONTROL` stage; no job-control expansion here. |
| #12 | Completion remains non-executing and value-redacted. |
| #14 | Full script mode remains out of scope. |
| #15 | Python script migration remains out of scope. |
| #16 | Zsh transition hardening remains out of scope. |
| #17 | System shell integration remains out of scope. |
