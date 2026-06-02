# PySH Issue Backlog

This backlog is the final linear GitHub issue sequence for the architecture
roadmap. GitHub issues are linear; split sub-issue numbering is not used.

PySH is not yet a `/bin/sh` replacement and is not yet zsh-compatible. The
target is a Python-first interactive shell and script interpreter with explicit,
test-backed compatibility claims. Interactive shell replacement and script
interpreter replacement are separate product contracts.

## Ordering Rationale

ISSUE #2 is a pure relocation phase only. It moves files with `git mv`, updates
imports as required, and preserves public CLI behavior. It does not decompose the
parser, add behavior, add placeholder packages, or introduce broad compatibility
layers.

ISSUE #3 adds architecture contracts and import-boundary enforcement immediately
after relocation. Later subsystems must depend on protocols/interfaces rather
than reaching into runtime internals. The import-linter ratchet, public API
snapshot tests, and import-time/cold-start budget test originate in ISSUE #3.

ISSUE #4 defines the shell compatibility contract before behavior expands.
ISSUE #5 through ISSUE #7 define error semantics, signal ownership, and trust
boundaries before parser hardening, job control, scripting, or system-shell
integration consume those decisions.

Parser decomposition belongs to ISSUE #8, not ISSUE #2. That includes any future
`parsing/expansion.py`, `parsing/command_chain.py`, or
`parsing/assignments.py` split.

Job control owns Linux and FreeBSD process-group validation in ISSUE #11.
ISSUE #18 remains full FreeBSD validation across the completed product surface.

## Critical Path and Product Claims

Architecture foundation:

```text
#2 -> #3 -> #4 -> {#5, #6, #7} -> #8
```

Interactive replacement path:

```text
#2 -> #3 -> #4 -> #5 -> #6 -> #8 -> #9 -> #10 -> #11 -> #12 -> #13
```

Script interpreter path:

```text
#4 -> #5 -> #7 -> #8 -> #10 -> #14 -> #15
```

Claim "PySH can replace interactive zsh/bash for daily use" is unlocked by:
`#3, #4, #5, #6, #8, #9, #10, #11, #12, #13`.

Claim "PySH can replace old shell scripts with Python-first PySH scripts" is
unlocked by: `#4, #5, #7, #8, #10, #14, #15`.

Compatibility claims require a documented matrix and backing tests. Until then,
PySH documentation must describe support narrowly and avoid blanket zsh, bash,
or POSIX-sh compatibility claims.

## ISSUE #2 - Refactor Source Tree by Pure Relocation

**Goal.** Reorganize the source tree without behavior changes.

**Scope.**

- Use `git mv`.
- No feature changes.
- No parser decomposition.
- No new behavior.
- No empty placeholder packages.
- No broad compatibility layers.
- Imports updated only as required.
- Public CLI behavior unchanged.
- `core/shell.py` owns `PyShell` runtime.
- `cli.py` owns entrypoint orchestration.
- Top-level `shell.py`, if retained, is only a narrow import shim.
- Command-line highlighting belongs to `editor/highlight.py`.
- Python highlighting belongs to `python_layer/highlighting.py`.
- Config uses clear modules such as `api.py`, `loader.py`, and `plugins.py`.

**Shim policy.** Compatibility shims are re-exports only, for example
`from pysh.core.shell import PyShell`. They must contain no duplicate
implementation and no behavioral logic. `DeprecationWarning` is added only when
appropriate. The default removal milestone is ISSUE #19, the packaging and
release quality gate issue, unless ISSUE #2 documents a narrower milestone.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- `uv run python -m pysh --version`
- `uv run pysh --version`

## ISSUE #3 - Add Architecture Contracts and Import-Boundary Enforcement

**Goal.** Define stable interfaces between runtime, editor, prompt, completion,
configuration, compatibility, and Python execution layers.

**Depends on.** #2.

**Scope.**

- Add `pysh/contracts/` or an equivalent protocol layer.
- Editor, prompt, completion, and compat depend on protocols/interfaces, not
  core internals.
- Add import-boundary enforcement through import-linter or a pytest import-graph
  test.
- Add public API snapshot tests.
- Add import-time/cold-start budget test.
- Keep `__init__.py` files minimal and side-effect free.
- Define the import-linter ratchet used by later issues.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- import-boundary test
- public API snapshot test
- import-time budget test

## ISSUE #4 - Shell Compatibility Contract

**Goal.** State precisely what PySH targets relative to zsh, bash, and POSIX
`sh`, and what it will not emulate. This is documentation and test-matrix work,
not feature implementation.

**Depends on.** #2, #3.

**Scope.**

- `docs/compatibility.md`
- `docs/zsh-compatibility.md`
- `docs/posix-sh-scope.md`
- Feature matrix for quoting, expansion, redirection, pipelines, control flow,
  functions, job control, globbing, parameter expansion, arithmetic, traps, and
  unsupported constructs.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`

## ISSUE #5 - Error and Exit-Code Contract

**Goal.** Define canonical exception-to-exit-code mapping and builtin/external
return-code semantics.

**Depends on.** #3, #4.

**Scope.**

- Canonical `ExitCode` values:
  - `0` success.
  - `1` general error.
  - `2` builtin misuse.
  - `126` found but cannot execute.
  - `127` command not found.
  - `128 + signal` for signal termination, including `130` for SIGINT.
- External command exit propagation.
- Builtin return-code contract.
- Script-mode failure behavior.
- Structured `PyShError` taxonomy.
- Single boundary function for converting escaped exceptions into stderr
  diagnostics and exit status.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- Tests for not found, not executable, builtin misuse, parse error, SIGINT, and
  `$?` propagation.

## ISSUE #6 - Signal-Handling Architecture

**Goal.** Define signal ownership and terminal restoration guarantees across
line editing, external command execution, and Python evaluation.

**Depends on.** #3, #5.

**Scope.**

- SIGINT in the line editor aborts the current input line and returns to prompt.
- SIGINT during external command is delivered to the foreground process group;
  the shell survives and records conventional status.
- SIGINT during Python eval raises `KeyboardInterrupt` into eval without killing
  the shell.
- SIGTSTP/SIGCONT preparation for job control.
- Terminal restoration guarantees after interrupts, stopped jobs, exceptions,
  and process-group handoff failures.
- Platform abstraction for `setpgid`, `tcsetpgrp`, and signal masking.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- PTY tests for Ctrl+C at prompt, during `sleep`, and during Python eval.

## ISSUE #7 - Security and Trust Model

**Goal.** Define trust boundaries before PySH imports foreign profiles, runs
configuration code, or integrates with system shells.

**Depends on.** #3, #4.

**Scope.**

- Trusted vs untrusted rc/profile code.
- No arbitrary zsh execution by default.
- `secure_runner` boundaries.
- Profile importer safety.
- Python config power and risk documented clearly.
- Explicit opt-in policy for executing foreign shell code, if ever supported.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- Tests proving profile import extracts data without executing arbitrary shell
  commands by default.

## ISSUE #8 - Parser, Expansion and Multiline Grammar Foundation

**Goal.** Harden parsing and expansion with a grammar designed for multiline
continuation and future heredoc terminators.

**Depends on.** #3, #4, #5, #7.

**Scope.**

- Quotes and escapes.
- Variables and `${VAR}`.
- Command substitution with `$(...)` and backticks.
- Redirections, pipelines, and semicolon chains.
- Temporary environment assignments.
- Comments.
- Multiline continuation grammar.
- Structured parse errors with line/column metadata.
- Parser decomposition deferred from ISSUE #2.

**Non-goals.** No native glob expansion; no heredoc body handling; no shell
functions; no arithmetic expansion.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- Golden parser tests and multiline continuation tests.

## ISSUE #9 - Native Glob and Path Expansion

**Goal.** Implement native path expansion with explicit compatibility policy.

**Depends on.** #4, #5, #8.

**Scope.**

- `*`, `?`, bracket classes, `~`, `~user`.
- Optional recursive `**` if approved by the compatibility matrix.
- Expansion ordering relative to variables, command substitution, quoting, and
  redirection.
- Configurable no-match policy.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`

## ISSUE #10 - Here-Documents

**Goal.** Implement heredocs and here-strings on top of the ISSUE #8 grammar.

**Depends on.** #5, #8, #9.

**Scope.**

- `<<`, quoted delimiters, `<<-` tab stripping, and here-string policy.
- Expansion behavior based on quoted vs unquoted delimiters.
- Ctrl+C behavior during heredoc collection through ISSUE #6.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- PTY tests for interactive heredoc collection and interrupt cleanup.

## ISSUE #11 - Job Control and Process Groups

**Goal.** Add job table and foreground/background control using the signal and
terminal-control architecture.

**Depends on.** #5, #6, #8.

**Scope.**

- Process groups for pipelines.
- Foreground terminal transfer and restoration.
- `jobs`, `fg`, `bg`.
- Stopped, continued, terminated, and exited job states.
- Linux and FreeBSD process-group validation.
- BSD/Linux abstraction for terminal process-group operations.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- Linux PTY process-group tests.
- FreeBSD process-group validation notes or CI/manual gate.

## ISSUE #12 - Completion Engine v1

**Goal.** Provide completion through contracts rather than runtime internals.

**Depends on.** #3, #4, #8, #9.

**Scope.**

- Builtin, alias, variable, path, command, and config completion.
- Completion providers depend on ISSUE #3 protocols/interfaces.
- Parser-aware completion context from ISSUE #8.
- Import-boundary enforcement from ISSUE #3 catches layering violations.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- import-boundary test from ISSUE #3.

## ISSUE #13 - Observability and Diagnostics

**Goal.** Add diagnosability without entangling normal shell execution.

**Depends on.** #3, #5, #6, #8.

**Scope.**

- `--debug`.
- Structured debug logs.
- Command resolution trace.
- Parser trace.
- Paste debug.
- Startup/import-time diagnostics.
- Diagnostics redaction policy for paths, environment, and command content where
  relevant.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- import-time/cold-start budget test from ISSUE #3.

## ISSUE #14 - Script Mode v1

**Goal.** Define PySH as a script interpreter contract separate from interactive
replacement.

**Depends on.** #4, #5, #7, #8, #10.

**Scope.**

- File execution.
- `-c` behavior.
- Shebang behavior.
- Exit behavior and error policy using ISSUE #5.
- Script-mode failure behavior.
- Explicit unsupported-syntax diagnostics.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- Script fixtures for success, parse error, command failure, interrupts, and
  unsupported constructs.

## ISSUE #15 - Python Script Migration Layer

**Goal.** Provide Python-first migration primitives for users replacing legacy
shell scripts.

**Depends on.** #5, #7, #8, #10, #14.

**Scope.**

- Documented Python-first patterns for subprocesses, environment, path handling,
  and failure propagation.
- Migration helpers that preserve explicit safety boundaries.
- Diagnostics for unsupported legacy shell constructs.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`

## ISSUE #16 - zsh Transition Layer Hardening

**Goal.** Harden the transition layer without claiming zsh compatibility beyond
the matrix.

**Depends on.** #4, #7, #13.

**Scope.**

- Safe zsh alias/profile import.
- Unsupported-construct diagnostics.
- No arbitrary zsh execution by default.
- Explicit consent if foreign shell execution is offered.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`

## ISSUE #17 - System Shell Integration Policy

**Goal.** Define how PySH may be installed, selected, and used as a user shell
without risking system stability.

**Depends on.** #7, #14, #16.

**Scope.**

- `/etc/shells` policy.
- Login shell readiness criteria.
- Debian/FreeBSD integration notes.
- Recovery path if PySH fails at login.
- Explicit statement that PySH is not a `/bin/sh` provider until the script
  compatibility matrix proves it.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- `uv run python -m pysh --version`
- `uv run pysh --version`

## ISSUE #18 - FreeBSD Validation

**Goal.** Validate PySH behavior on FreeBSD after platform-sensitive interfaces
exist.

**Depends on.** #6, #11, #17.

**Scope.**

- PTY behavior.
- Process groups.
- Signal handling.
- Filesystem/path behavior.
- Packaging assumptions.
- Shell integration policy.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- FreeBSD validation report for process groups, PTY handling, and signals.

## ISSUE #19 - Packaging and Release Quality Gate

**Goal.** Reproducible packaging and release readiness after the full issue
sequence is integrated.

**Depends on.** #2 through #18.

**Scope.**

- Packaging artifact contract.
- CLI and module entrypoint checks.
- Build verification.
- Removal of ISSUE #2 backward-compatibility shims unless explicitly retained
  by documented policy.
- Final compatibility-claim audit.

**Validation.**

- `uv run ruff check src tests`
- `uv run pytest -q`
- `uv run python -m pysh --version`
- `uv run pysh --version`
- `uv run --with build python -m build`
- import-boundary test
- public API snapshot test
- import-time budget test

## Final Issue Sequence

| Issue | Title |
| --- | --- |
| #2 | Refactor source tree by pure relocation |
| #3 | Add architecture contracts and import-boundary enforcement |
| #4 | Shell compatibility contract |
| #5 | Error and exit-code contract |
| #6 | Signal-handling architecture |
| #7 | Security and trust model |
| #8 | Parser, expansion and multiline grammar foundation |
| #9 | Native glob and path expansion |
| #10 | Here-documents |
| #11 | Job control and process groups |
| #12 | Completion engine v1 |
| #13 | Observability and diagnostics |
| #14 | Script mode v1 |
| #15 | Python script migration layer |
| #16 | zsh transition layer hardening |
| #17 | System shell integration policy |
| #18 | FreeBSD validation |
| #19 | Packaging and release quality gate |

## Previous Backlog Mapping

| Final issue | Previous backlog item |
| --- | --- |
| #2 | Source-tree relocation phase |
| #3 | New architecture contracts issue |
| #4 | old #3 |
| #5 | old #4 |
| #6 | old #5 |
| #7 | old #6 |
| #8 | old #7 |
| #9 | old #8 |
| #10 | old #9 |
| #11 | old #10 |
| #12 | old #11 |
| #13 | old #12 |
| #14 | old #13 |
| #15 | old #14 |
| #16 | old #15 |
| #17 | old #16 |
| #18 | old #17 |
| #19 | old #18 |
