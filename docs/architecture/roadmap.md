<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/roadmap.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Roadmap

PySH aims to become a Python-first interactive shell and script interpreter for
Debian and Unix-like systems. The product has two separate contracts:

1. **Interactive shell replacement**: command execution, prompt, editor,
   history, completion, terminal control, process management, startup files and
   TTY behavior for daily terminal use.
2. **Script interpreter replacement**: deterministic `.pysh` script execution,
   parser and expansion semantics, diagnostics, exit-code behavior, portability
   and migration tooling for user-owned scripts.

PySH is **not yet a `/bin/sh` replacement**. PySH is **not yet
zsh-compatible**. Compatibility claims must be backed by explicit test
matrices, real terminal validation where relevant, and documented negative
cases. PySH must not imply compatibility with `bash`, `zsh`, POSIX `sh`, or
tool-specific shell protocols until the behavior is implemented and tested.

This roadmap is a linear GitHub issue sequence. It separates behavior-neutral
architecture work from semantic changes. Refactors must not be used as a
vehicle for feature changes unless the issue explicitly authorizes them.

## Current Baseline

The v0.6.x release baseline includes:

- core interactive `PyShell` runtime,
- parser, expansion and multiline grammar foundation,
- native glob and path expansion,
- here-documents and here-strings,
- job control and process groups,
- Completion Engine v1,
- observability and diagnostics,
- Script Mode v1,
- Python command execution layer,
- raw line editor with prompt rendering, autosuggest, syntax highlighting,
  plain paste, bracketed paste and compact paste replay,
- Python-native configuration API and generated `~/.pyshrc.py`,
- `command` builtin with `-v`, `-V` and alias-suppressed execution,
- temporary environment assignments for external commands,
- Midnight Commander safe wrapper policy,
- unit and PTY tests for shell-critical behavior.

The baseline is suitable for stabilization work. It is not a license to claim
full script compatibility, POSIX compliance or zsh parity.

## Global Release Gates

Every code-changing issue must run the relevant subset of these gates. Release
candidates must run all of them:

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
uv run --with build python -m build
```

Architecture and packaging issues must additionally include the applicable
evidence:

- import-boundary test,
- public API snapshot test,
- import-time/cold-start budget test,
- package metadata validation,
- focused PTY test for terminal behavior,
- real-terminal transcript for visual terminal behavior.

The validation gates must not be weakened to make a release pass.

## Architecture Decisions

These placement decisions are fixed for the roadmap:

- `core/shell.py` owns the `PyShell` runtime.
- `cli.py` owns entrypoint orchestration.
- Top-level `shell.py`, if retained, is only a narrow import shim.
- Top-level `shell.py` must not become a second implementation.
- Command-line highlighting belongs to `editor/highlight.py`.
- Python highlighting belongs to `python_layer/highlighting.py`.
- Configuration should use `config/api.py`, `config/loader.py` and
  `config/plugins.py`.
- Avoid unclear `rc` / `pyshrc` duplication. A module may parse legacy rc
  syntax or load Python config, but it must have one explicit responsibility.

## Shim Policy

Compatibility shims are allowed only as narrow re-exports, for example:

```python
from pysh.core.shell import PyShell
```

Shim rules:

- no duplicate implementation,
- no behavioral logic,
- no broad permanent compatibility layer,
- no wildcard compatibility namespace,
- `DeprecationWarning` only when it is useful and does not break normal import
  paths,
- exact shim removal milestone must be documented in the issue that creates the
  shim.

Default removal milestone: shims created by ISSUE #2 must be removed by ISSUE
#19, the packaging and release quality gate issue, unless a narrower removal
milestone is documented in ISSUE #2.

## Critical Path and Product Claims

Architecture and compatibility foundation:

```text
#2 -> #3 -> #4 -> {#5, #6, #7} -> #8
```

Interactive-shell replacement path:

```text
#2 -> #3 -> #4 -> #5 -> #6 -> #8 -> #9 -> #10 -> #11 -> #12 -> #13
```

Script-interpreter replacement path:

```text
#4 -> #5 -> #7 -> #8 -> #10 -> #14 -> #15
```

Claim "PySH can replace interactive zsh/bash for daily use" is unlocked by:
`#3, #4, #5, #6, #8, #9, #10, #11, #12, #13`.

Claim "PySH can replace old shell scripts with Python-first PySH scripts" is
unlocked by: `#4, #5, #7, #8, #10, #14, #15`.

These are deliberately different paths: interactive-shell replacement and
script-interpreter replacement are separate contracts with separate
verification.

## Final GitHub Issue Sequence

### ISSUE #2: Refactor Source Tree by Pure Relocation

Goal: make the source tree reflect the architecture without changing behavior.

Depends on: the original pre-refactor baseline.

Scope:

- Use `git mv` for relocations.
- Move implementation modules to their architecture-owned packages.
- Update imports only as required by relocation.
- Preserve public CLI behavior.
- Preserve public import behavior through narrow shims where required.

Hard exclusions:

- no feature changes,
- no parser decomposition,
- no new behavior,
- no new subsystem design,
- no empty placeholder packages,
- no broad compatibility layers.

Definition of done:

- `git diff --find-renames` shows relocations, not rewrites.
- Existing tests pass before and after relocation.
- Public CLI behavior is unchanged.
- Any retained top-level module is a narrow import shim only.
- Shim removal milestone references ISSUE #19 or the packaging and release
  quality gate issue.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
```

### ISSUE #3: Add Architecture Contracts and Import-Boundary Enforcement

Goal: prevent architectural drift after relocation.

Depends on: #2.

Scope:

- Add `pysh/contracts/` or an equivalent protocol layer.
- Define protocols/interfaces for editor, prompt, completion, command
  execution, compatibility bridges and configuration surfaces.
- Make editor, prompt, completion and compatibility modules depend on
  protocols/interfaces rather than core internals.
- Keep `__init__.py` files minimal and side-effect free.
- Add import-boundary enforcement through `import-linter` or a pytest
  import-graph test.
- Add public API snapshot tests.
- Add import-time/cold-start budget tests.

Definition of done:

- Core runtime boundaries are machine-checked.
- No UI/editor module imports core internals except through contracts.
- Public API snapshots define allowed import surfaces.
- Cold start remains within the documented budget.
- The import-linter ratchet or import-graph test is owned by this issue.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gates:

- import-boundary test,
- public API snapshot test,
- import-time/cold-start budget test.

### ISSUE #4: Shell Compatibility Contract

Goal: state precisely what PySH targets relative to `zsh`, `bash` and POSIX
`sh`, and what it will not emulate. No implementation.

Depends on: #2, #3.

Scope:

```text
docs/compatibility.md
docs/migration/zsh-compatibility.md
docs/posix-sh-scope.md
```

Required matrix coverage:

- quoting,
- expansion,
- redirection,
- pipelines,
- control flow,
- functions,
- job control,
- globbing,
- parameter expansion,
- arithmetic,
- traps.

Non-goals:

- no code,
- no broad zsh compatibility prose until the matrix exists and a construct is
  marked supported with a backing test.

Definition of done:

- Matrix exists.
- Every later implementation issue references a row in it.
- README claims are reduced to exactly what the matrix marks supported.
- Interactive shell and script interpreter claims are separate.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #5: Error and Exit-Code Contract

Goal: define canonical mapping from internal conditions to process exit codes
and the exception taxonomy. This is the foundation for script mode and for
clear shell diagnostics.

Depends on: #2, #3, #4.

Scope:

- canonical `ExitCode` values,
- `signal_exit_code(signum)`,
- `PyShError` base type,
- command-not-found error,
- command-not-executable error,
- parse error,
- builtin usage error,
- a single boundary function converting escaped exceptions into exit codes and
  stderr diagnostics for interactive and script execution.

Contract requirements:

- `0` for success,
- `1` for general error,
- `2` for builtin misuse,
- `126` for found but not executable,
- `127` for command not found,
- `128 + signal` for signal termination,
- `130` for SIGINT,
- `143` for SIGTERM.

Non-goals:

- no new commands,
- no strict-mode semantics,
- no logging framework beyond clean stderr diagnostics.

Definition of done:

- Existing ad hoc exit-code call sites route through the contract.
- Tests assert not-found, not-executable, signal-terminated and parse-error
  mapping.
- `$?` reflects the contract after each command.
- Builtin docs list return codes.
- Script-mode failure behavior consumes this contract.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #6: Signal-Handling Architecture

Goal: define who owns signal disposition in each execution context and provide
a portable foreground/process-group abstraction.

Depends on: #2, #3, #5.

Scope:

```text
context: line editing       -> SIGINT aborts current input, returns to prompt, $?=130
context: external command   -> SIGINT/SIGTSTP delivered to child foreground process group
context: Python eval        -> SIGINT raises KeyboardInterrupt into eval, shell survives
```

Required architecture:

- terminal foreground process-group abstraction,
- `tcsetpgrp` / `setpgid` policy,
- `SIGTTOU` masking policy,
- Linux implementation,
- BSD-correct implementation behind the same interface,
- SIGCHLD reaping policy,
- SIGHUP policy on login-shell exit.

Non-goals:

- no `fg`, `bg` or `jobs` UI; ISSUE #11 consumes this mechanism.

Definition of done:

- Ctrl+C at prompt, during `sleep 100` and during long Python eval behaves per
  contract.
- No orphaned process groups after Ctrl+C of a pipeline.
- `$?` after Ctrl+C of an external command is 130.
- Foreground process-group abstraction has Linux tests and documented FreeBSD
  manual validation.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gate:

- focused PTY signal tests.

### ISSUE #7: Security and Trust Model

Goal: define trust boundaries before any code that ingests untrusted input
executes.

Depends on: #2, #3, #4.

Scope:

```text
docs/security-model.md
```

Required coverage:

- trusted vs untrusted rc/profile code,
- `~/.pyshrc.py` as trusted arbitrary Python by design,
- foreign profile import as data extraction only,
- no arbitrary zsh execution by default,
- `secure_runner` boundary and threat model,
- profile importer safety,
- plugin loading trust model,
- explicit consent policy if executing foreign shell code is ever offered.

Non-goals:

- no sandbox implementation in this issue.

Definition of done:

- Document exists.
- Compatibility modules are annotated against the trust model.
- zsh profile importer extracts aliases/exports without executing arbitrary
  commands.
- Python config power and risk are clearly documented.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #8: Parser, Expansion and Multiline Grammar Foundation

Goal: robust parsing/expansion with a grammar designed for multiline
continuation and heredoc terminators from the start.

Depends on: #3, #4, #5.

Scope:

- parser decomposition deferred from #2,
- `parsing/expansion.py`,
- `parsing/command_chain.py`,
- `parsing/assignments.py`,
- quotes and escapes,
- variables and `${VAR}`,
- `$(...)` command substitution and backticks,
- redirections, pipelines and semicolon chains,
- temporary environment assignments,
- comments,
- multiline continuation grammar,
- open-quote continuation,
- pending heredoc state,
- structured parse errors routed through ISSUE #5.

Non-goals:

- no glob expansion; ISSUE #9 owned and implemented that later,
- inline stdin data was deferred to ISSUE #10, which implemented it later,
- no arithmetic,
- no functions.

Definition of done:

- Characterization tests cover each construct.
- Decomposition introduces no behavior change versus the relocated parser.
- Golden tests preserve behavior.
- Parse errors carry position.
- Grammar exposes a "needs more input" signal for the interactive reader.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #9: Native Glob and Path Expansion

Goal: implement deterministic path expansion without pretending to be zsh.

Depends on: #8.

Scope:

- `*`,
- `?`,
- `[abc]`,
- `[a-z]`,
- `~`,
- `~user`,
- optional recursive `**`,
- configurable no-match policy,
- expansion order relative to variables and command substitution.

Non-goals:

- no extended-glob or zsh qualifier syntax in v1.

Definition of done:

- Matrix rows for each pattern are marked supported with tests.
- No-match default is documented and tested.
- Tilde expansion resolves `~`, `~user` and handles `~unknown` per policy.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #10: Here-Documents

Goal: implement heredocs and here-strings on top of ISSUE #8 grammar.

Depends on: #8.

Scope:

```text
cat <<EOF ... EOF
cat <<'EOF' ... EOF
<<-EOF
<<< "string"
```

Non-goals:

- no grammar redesign; ISSUE #8 owns pending-heredoc grammar state.

Definition of done:

- Expansion vs no-expansion delimiter behavior is tested.
- `<<-` tab stripping is tested.
- Here-string behavior is tested or intentionally rejected in the matrix.
- Multiline interactive entry works through the reader's "needs more input"
  signal.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #11: Job Control and Process Groups

Goal: implement `&`, `jobs`, `fg`, `bg` and Ctrl+Z handling using ISSUE #6
mechanism.

Depends on: #6, #8.

Scope:

- job table,
- foreground/background transitions,
- SIGTSTP/SIGCONT,
- terminal foreground process-group handoff,
- correct `$?` for stopped, continued and terminated jobs,
- Linux and FreeBSD process-group validation.

Non-goals:

- no `disown`, `wait -n` or advanced zsh job syntax in v1.

Definition of done:

- Start, stop, resume and background a process.
- Pipeline job control works.
- No terminal wedging after `fg` of a suspended pipeline.
- Portable process-group abstraction from ISSUE #6 is exercised.
- Linux automated and FreeBSD manual validation are recorded.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gates:

- focused PTY job-control tests,
- Linux/BSD abstraction tests.

### ISSUE #12: Completion Engine v1

Goal: command, path, option and Python-mode completion through an isolated
completion subsystem.

Depends on: #3, #8.

Scope:

- command completion,
- path completion,
- option completion,
- Python-mode completion,
- pluggable completer registration through configuration API,
- completion state access through contracts, not runtime internals.

Non-goals:

- zsh-style menu/selection UI deferred to a later issue.

Definition of done:

- Completion logic is tested headless against synthetic lines.
- Completers are registrable from `~/.pyshrc.py`.
- Completion imports contracts, not `core.shell`.
- Import-boundary enforcement from ISSUE #3 catches violations.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gate:

- import-boundary test from ISSUE #3.

### ISSUE #13: Observability and Diagnostics

Goal: structured diagnostics for debugging shell behavior.

Depends on: #3, #5, #8.

Scope:

- `--debug`,
- `--trace`,
- deterministic stderr trace lines,
- expansion trace,
- redirection and argv trace,
- command resolution trace,
- parser trace,
- redaction policy.

Non-goals:

- no telemetry,
- no remote reporting,
- no performance profiler.
- no startup/import-time profiler.
- no diagnostic execution of target commands.

Definition of done:

- `--debug` produces deterministic parseable trace for a sample line.
- stdout remains clean.
- Command resolution path is visible.
- Sensitive values are redacted.
- Diagnostic builtins remain non-mutating.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gate:

- import-time/cold-start budget test from ISSUE #3.

### ISSUE #14: Script Mode v1

Goal: PySH as a script interpreter: `#!/usr/bin/env pysh`.

Depends on: #5, #8. Benefits from #10.

Scope:

- deterministic script execution,
- exit codes per ISSUE #5,
- documented v1 strict-mode limitation,
- source semantics,
- positional args `$0`, `$1`, ...,
- script-local variables.

Non-goals:

- not a `/bin/sh` replacement.

Definition of done:

- Script file runs deterministically.
- Exit code matches ISSUE #5.
- Strict-mode policy is explicitly documented.
- `source` shares state per documented semantics.
- Positional args populate correctly.
- Script behavior references ISSUE #4 matrix.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
```

### ISSUE #15: Python Script Migration Layer

Goal: replace legacy `.sh` with Python-first PySH scripts.

Depends on: #14.

Scope:

- Python-native script blocks,
- Python functions registered as shell tasks,
- safe typed subprocess helpers,
- typed environment/path API,
- migration documentation.

Non-goals:

- no automatic `.sh` to Python translator in this issue.

Definition of done:

- Worked migration example exists.
- Subprocess helpers reject unsafe patterns by default.
- Environment/path API is typed and tested.
- Unsupported constructs are reported, not guessed.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #16: zsh Transition Layer Hardening

Goal: safe ingestion of zsh profiles per ISSUE #7 trust model.

Depends on: #4, #7.

Scope:

- alias import,
- export import,
- safe `.zshrc` profile importer,
- data extraction only by default,
- diagnostics for unsupported constructs referencing ISSUE #4 matrix,
- explicit one-session delegation controls.

Non-goals:

- no arbitrary zsh evaluation by default.

Definition of done:

- Importer extracts aliases/exports without executing embedded commands.
- Unsupported constructs produce diagnostics citing the matrix.
- Security test from ISSUE #7 covers no-execution behavior.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

### ISSUE #17: System Shell Integration Policy

Goal: prepare real system migration without risk of bricking a login.

Depends on: #7, #14.

Scope:

- login-shell support,
- `chsh` and `/etc/shells` documentation,
- Debian policy,
- FreeBSD policy,
- explicit non-replacement of `/bin/sh`,
- safe rollback procedure.

Non-goals:

- no `/bin/sh` replacement claim.

Definition of done:

- Documented and tested login-shell startup path.
- Rollback procedure is verified.
- Clear warning against using PySH as `/bin/sh`.
- Common TUI programs are validated.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
uv run python -m pysh --version
uv run pysh --version
```

### ISSUE #18: FreeBSD Validation

Goal: full-platform validation on FreeBSD. ISSUE #11 already owns FreeBSD
process-group validation; this issue covers the remaining surface.

Depends on: #11, #17.

Scope:

- FreeBSD install,
- terminal behavior,
- Midnight Commander no-subshell policy,
- path tools,
- Python version constraints,
- packaging notes for ISSUE #19.

Definition of done:

- Test suite runs on FreeBSD or blocked evidence is documented.
- Platform deltas are documented.
- Packaging notes are captured for ISSUE #19.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
```

Additional required gate:

- FreeBSD test run or documented blocked evidence.

### ISSUE #19: Packaging and Release Quality Gate

Goal: reproducible packaging and release checklist; remove ISSUE #2
deprecation shims here unless ISSUE #2 defines a narrower removal point.

Depends on: #2 through #18.

Scope:

- wheel,
- sdist,
- Debian package,
- RPM package,
- Arch `PKGBUILD`,
- FreeBSD port draft,
- Nix package draft,
- release checklist,
- removal of ISSUE #2 backward-compatibility shims.

Definition of done:

- Each artifact builds in CI.
- Installed `pysh` works from each artifact class.
- ISSUE #2 shims are deleted or explicitly retained by documented policy.
- Test confirms removed import paths are gone when shims are removed.
- Release checklist passes end to end.

Validation:

```sh
uv run ruff check src tests
uv run pytest -q
uv run --with build python -m build
```

Additional required gates:

- packaging script checks,
- artifact filename checks,
- package metadata validation.

## New Issue Mapping

| Final issue | Previous backlog issue | Note |
|---|---|---|
| #2 | #2 | source relocation only |
| #3 | new | architecture contracts and import-boundary enforcement |
| #4 | old #3 | shell compatibility contract |
| #5 | old #4 | error and exit-code contract |
| #6 | old #5 | signal-handling architecture |
| #7 | old #6 | security and trust model |
| #8 | old #7 | parser, expansion and multiline grammar |
| #9 | old #8 | native glob and path expansion |
| #10 | old #9 | here-documents |
| #11 | old #10 | job control and process groups |
| #12 | old #11 | completion engine v1 |
| #13 | old #12 | observability and diagnostics |
| #14 | old #13 | script mode v1 |
| #15 | old #14 | Python script migration layer |
| #16 | old #15 | zsh transition layer hardening |
| #17 | old #16 | system shell integration policy |
| #18 | old #17 | FreeBSD validation |
| #19 | old #18 | packaging and release quality gate |

## Compatibility Matrix Policy

Compatibility matrices are required before public compatibility claims.

Minimum matrices:

- interactive shell behavior,
- script interpreter behavior,
- zsh migration behavior,
- external command/process behavior,
- terminal/editor behavior.

Each matrix row must be one of:

- implemented and tested,
- intentionally different and documented,
- planned,
- unsupported.

## Non-Goals Until Explicitly Scheduled

- Replacing system `/bin/sh` for OS boot scripts.
- Silently executing arbitrary `.bashrc` or `.zshrc` code.
- Claiming zsh compatibility before the matrix supports it.
- Pretending to be bash/zsh/fish for tool-specific protocols.
- Permanent broad import compatibility layers.
- Parser rewrites hidden inside source-tree relocation.

## Documentation Standard

Documentation must distinguish:

- implemented behavior,
- planned behavior,
- compatibility differences,
- safe-mode behavior,
- unsupported behavior.

Every shell-facing feature page must include:

- syntax,
- examples,
- return codes where relevant,
- failure behavior,
- compatibility notes,
- validation requirements when terminal behavior is involved.
