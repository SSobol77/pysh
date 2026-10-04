<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/observability-diagnostics-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Observability and Diagnostics Contract

Issue #13 defines PySH's explicit human-readable observability and diagnostics
surface. Issue #50 extends it with a versioned structured event schema,
canonical redaction, structured JSONL diagnostics, and an opt-in persistent
audit log; those additions are specified in
[Structured diagnostics, audit log, and redaction (Issue #50)](#structured-diagnostics-audit-log-and-redaction-issue-50).
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

- Script execution semantics; those are owned by Issue #14.
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
`builtin`, `external`, `plugin`, `pipeline`, `chain`, `python`, `script` or
`unknown`, assigns a coarse risk level, and prints a deterministic
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
values but cannot prove that arbitrary command output is non-secret. The
opt-in `--audit-log` (Issue #50) is a local, redacted event record; it is also
not a sandbox, policy engine, or tamper-proof security monitor.

## Structured diagnostics, audit log, and redaction (Issue #50)

Issue #50 adds machine-consumable diagnostics without changing the Issue #13
human trace above. The three output surfaces are independent:

| Surface | Flag | Format | Destination | Default |
| ------- | ---- | ------ | ----------- | ------- |
| Human diagnostics | `--debug` / `--trace` | `[PYSH_DEBUG] key=value ...` | stderr | off |
| Structured diagnostics | `--diagnostics-json` | schema-v1 JSON Lines | stderr | off |
| Persistent audit | `--audit-log PATH` | schema-v1 JSON Lines | file at `PATH` | off |

CLI interaction:

- `--debug`/`--trace` and `--diagnostics-json` are mutually exclusive; passing
  both is a usage error (exit status 2).
- `--audit-log PATH` may be combined with either presentation mode, or used
  alone. It does not change what is shown on stderr.
- None of these flags is implied by another, by configuration, or by the
  environment.

### A. Human diagnostics

Unchanged from Issue #13: `--debug` and `--trace` write `[PYSH_DEBUG]` lines to
stderr only, never to command stdout.

### B. Structured diagnostics (`--diagnostics-json`)

Writes one JSON object per line to stderr. Output is deterministic (sorted
keys, compact separators, no `NaN`/`Infinity`) and observational: a failure to
construct, redact, serialize, or write an event is contained and never alters
command execution, stdout, or the exit status. Ordinary runtime error messages
that existing shell semantics write to stderr (for example a parse error) may
appear on the same stream between JSON lines; consumers should treat lines that
are not JSON objects as ordinary shell stderr.

### C. Persistent audit log (`--audit-log PATH`)

- Opt-in and completely off by default. Without `--audit-log` no audit file is
  opened or created and no persistent serialization occurs.
- Append-only: the file is opened with `O_APPEND` and is never truncated.
- A newly created log is private (`0600`). `PATH` must resolve to a regular file
  owned by the current user with no group/other permission bits. Symlinks and
  special files (FIFOs, devices, directories) are rejected, and an insecure
  pre-existing file is rejected rather than silently `chmod`-ed.
- If the log cannot be opened safely, PySH prints
  `pysh: audit-log: <reason>` to stderr and exits with status 1 **before**
  running anything: an explicitly requested audit trail is never silently
  skipped.
- After startup, a failing audit write is contained: the sink disables itself,
  and the command's genuine exit status is preserved, not overwritten.
- PySH does not create parent directories, rotate, compress, or upload the log.
  Choose a path in a directory you control, for example one under
  `~/.local/state/`.

### D. Event schema

Every structured event carries `schema_version = 1`
(`pysh.diagnostics.schema.DIAGNOSTIC_EVENT_SCHEMA_VERSION`). Any incompatible
change to the shape requires a new schema version and an explicit versioning
decision; an event with an unsupported version is rejected at construction.

| Field | Required | Meaning |
| ----- | -------- | ------- |
| `schema_version` | yes | Integer, currently `1`. |
| `event_class` | yes | One of the event classes below. |
| `event` | yes | Dot-namespaced lowercase name that starts with its class, for example `plugin.spawn`. |
| `severity` | yes | `debug`, `info`, `warning`, or `error`. |
| `actor` | optional | Who acted, for example a plugin name. |
| `action` | optional | What was attempted, for example an operation name. |
| `target` | optional | What the action was aimed at. |
| `result` | optional | `success`, `failure`, or `denied`. |
| `reason_code` | optional | Short bounded machine-readable reason. |
| `fields` | yes (may be empty) | Bounded JSON-style mapping of strings, numbers, booleans, null, lists, and nested mappings. |

Optional fields are serialized as `null` when absent. They are populated only
where meaningful; placeholders are never invented. Non-finite floats and
arbitrary objects are rejected, so a malformed event fails closed instead of
being serialized.

### E. Event classes

`startup`, `parser`, `runtime`, `plugin`, `security`, `resource`, `package`,
`ai`, `remote`.

The classes `startup`, `parser`, `runtime` (trace-derived), `plugin` and
`security` (isolated-plugin events) have current producers. `resource`,
`package`, `ai`, and `remote` are **reserved** namespaces only: reserving a
class does not mean resource enforcement, package management, AI integration, or
remote execution exists in PySH.

### F. Redaction boundary

```text
raw structured data
    -> validation (schema v1 construction)
    -> canonical redaction (pysh.diagnostics.redaction)
    -> serialization
    -> stderr / file sink
```

Redaction always precedes serialization, and serialization always precedes any
byte reaching stderr or the audit file; nothing is persisted and then redacted.
`pysh.diagnostics.redaction` is the single canonical redaction policy; the
human trace, structured JSONL, and audit log all use it. Redaction is name- and
known-value-based, so a secret with an unclassified name and an unknown value
cannot be guaranteed absent.

### G. Isolated-plugin events

`pysh.plugins.isolated.diagnostics` maps the bounded `IsolatedPluginEvent` seam
to schema v1 and provides `make_structured_plugin_event_sink(sink)`, which
adapts the runtime's injected `event_sink` to a structured sink (JSONL or
audit). Dependency direction is `pysh.plugins.isolated -> pysh.diagnostics`
only. PySH's CLI does not construct an isolated-plugin runtime today, so these
events are produced only by code that wires the seam explicitly.

| Isolated event | Structured `event` | Class | Severity | `result` | Notes |
| -------------- | ------------------ | ----- | -------- | -------- | ----- |
| spawn | `plugin.spawn` | plugin | info | success | `fields` lists requested/granted capability labels. |
| granted | `security.capability_granted` | security | info | success | One event per handshake; `action=capability_grant`; `fields` lists requested/granted capability labels. |
| handshake | `plugin.handshake` | plugin | info | success | |
| running | `plugin.running` | plugin | info | success | |
| denied | `security.capability_denied` | security | warning | denied | `action` is the IPC operation name; `reason_code=capability_denied`. |
| failure | `plugin.failure` | plugin | error | failure | `reason_code` is the existing bounded code. |
| stopped | `plugin.stopped` | plugin | info (warning if forced) | success (none if forced) | A forced stop carries `reason_code=forced`. |

`actor` is the plugin name. Isolated-plugin audit events may include bounded
authorization metadata such as canonical capability declarations (for example
`fs.read:/absolute/root`, `env.read:NAME`, `command:NAME`, or a network
endpoint), an operation name, and a bounded reason code. A declaration may
itself identify a filesystem root, environment-variable name, command name, or
network endpoint; that is authorization metadata, not payload. Request/response
payload values, file contents, environment values, command argv/output, child
stdout/stderr, protected terminal input, and parent objects are not copied into
diagnostic/audit events. Canonical redaction still applies before
serialization/persistence; no additional path redaction is performed and
declared identifiers are not treated as confidential. The `granted` event is
emitted after the child's `hello` identity is validated and before the parent
sends the grant message; the grant itself is fixed when the runtime is
constructed. A sink failure does not alter the plugin runtime's own result or
state.

### H. Sensitive-input boundary

Protected PTY, password, and passphrase bytes (ordinary terminal input to
`sudo`, `ssh`, `su`, `gpg`, and input bridged by `secure`) are not part of the
diagnostic or audit pipeline. The secure runner does not emit events carrying
those bytes, and the audit sink only accepts structured events.

### I. Output distinction

Command stdout and stderr are not copied into audit storage. Command metadata
(for example a trace `message`, resolved command, or exit status) may appear
only as defined by the event contracts and only after redaction. Diagnostics
are not a transcript.

## Validation

Automated evidence:

- `tests/test_observability_diagnostics.py`
- `tests/test_structured_diagnostics.py`
- `tests/test_diagnostics_jsonl.py`
- `tests/test_audit_log.py`
- `tests/test_isolated_plugin_diagnostics.py`
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
- Audit logging is off unless `--audit-log PATH` is given.
- Structured events are redacted before serialization or persistence.

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
| #14 | Script mode adds file/line trace context for direct script execution. |
| #15 | Python script migration remains out of scope. |
| #16 | Zsh transition hardening remains out of scope. |
| #17 | System shell integration remains out of scope. |
| #44 | Isolated-plugin lifecycle/capability events feed the structured seam. |
| #50 | Structured schema v1, JSONL diagnostics, audit log, and canonical redaction. |
