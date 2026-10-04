<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: CHANGELOG.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Changelog

All notable changes to PySH are documented in this file.

## 1.0.0 - 2026-10-04

PySH 1.0.0 is the first stable release. It does not add a new shell feature
family; it makes PySH's guarantees explicit, enforceable, and test-backed:
a frozen public API, enforced architecture boundaries, a documented security
model, a normative language specification with a conformance corpus, bounded
robustness and performance contracts, a tiered platform contract, and a
supply-chain assurance pipeline for every release artifact.

PySH remains a Python-first shell. It is not `/bin/sh` and is not a Bash, Zsh,
or Fish clone. Legacy shells are migration and differential test references
only; the documented PySH contract defines PySH behavior.

### Stable public API and deprecation policy

- Published the stable public surface: the `pysh.api` facade with the
  `ShellSession` embedding lifecycle and the contract protocol re-exports,
  guarded by a public API snapshot test.
- Published the SemVer policy, the package/Plugin API/isolated manifest/IPC
  version domains (independent of each other), and a minimum two-minor
  deprecation lifecycle.
- `pysh.shell.PyShell` stays deprecated in favor of `pysh.api.ShellSession`;
  it is not removed before PySH 1.2.0.

### Architecture and security model

- Froze the internal layer architecture in a machine-readable policy and
  enforced the dependency boundaries by an import-boundary test.
- Published the v1.0 threat model: assets, trust boundaries, a STRIDE threat
  register, and the deterministic `--no-rc` safe-startup contract. Trusted
  configuration and plugins remain trusted code; `py` execution remains
  in-process and unsandboxed by design.
- Added the isolated-plugin runtime: a separate process, a versioned bounded
  JSON IPC protocol, a parent-owned default-deny capability broker, a scrubbed
  launch environment, and closed unrelated file descriptors. It isolates
  process memory and failures; it is not an OS sandbox, and a same-user child
  keeps the operating system's own file, network, and process authority.

### Diagnostics, audit, and redaction

- Added versioned structured diagnostic events with one canonical redaction
  policy applied before serialization or persistence, an opt-in private
  append-only audit log, and a clean separation from standard output. Protected
  terminal bytes are never captured.

### Language specification and conformance

- Published the normative PySH Language Specification (version 1) and a
  declarative conformance corpus with a runner that owns all fixture execution;
  unsupported constructs are specified and diagnosed rather than silently
  misinterpreted.

### Robustness, resource containment, and performance

- Added portable deterministic parser/tokenizer fuzz and property evidence
  (every pull request, Debian and FreeBSD) and an Atheris coverage-guided
  nightly engine on Linux x86_64. Fuzzing asserts robustness only; the language
  specification stays the only semantic oracle.
- Added the resource governor for isolated plugins: wall-clock, memory,
  descriptor, process, and message-size budgets, parent-side watchdog
  enforcement, process-group termination with a hard-kill escalation, and
  structured `resource.limit_exceeded` diagnostics.
- Added versioned performance budgets (cold start, prompt render, completion,
  git context, keystroke render) with CI regression gates on Linux and
  FreeBSD 14.4.

### Migration and compatibility assurance

- Added a legacy-shell differential laboratory (Bash, Zsh, Fish) with pinned
  reference profiles and exactly three outcomes: match, intended divergence,
  and regression. It is test equipment, not a compatibility claim.
- Removed the automatic zsh fallback and the `zsh` builtin before 1.0; `zsh` is
  an ordinary external program.

### Portability and platform tiers

- Defined support by runtime family (Debian-family Linux, RPM-family Linux,
  FreeBSD family) with CPython 3.13 or newer and no upper bound. Debian 13,
  Fedora 43, and FreeBSD 14.4 are reference evidence environments, not
  allowlists. Debian 13 and FreeBSD 14.4 are Tier 1; the RPM family is Tier 2.

### Supply-chain assurance and release engineering

- Every release now produces five package artifacts (wheel, sdist, `.deb`,
  `.rpm`, FreeBSD `.pkg`), five SPDX 2.3 JSON SBOMs, `REPRODUCIBILITY.json`,
  and `SHA256SUMS` (twelve public files), generated and validated before the
  hand-off to the release-upload job.
- Added keyless GitHub OIDC/Sigstore provenance and SPDX SBOM attestations,
  verified with `gh attestation verify` before upload and pinned to the
  repository, the release workflow, and the exact source commit. There is no
  long-lived signing key.
- Added per-artifact reproducibility measurement: two independent clean builds
  per family, compared byte for byte and bound to the shipped bytes, with the
  resolved build toolchain recorded. Debian, RPM, and FreeBSD package builds
  honor the commit-timestamp `SOURCE_DATE_EPOCH`.
- Pinned every action in the release workflow to a full commit SHA and removed
  persisted checkout credentials.
- Extended the Release Quality Gate with the supply-chain contract and a
  reproducibility measurement check.

### Command line

- Added `pysh --credits`, an early informational option (like `--version`) that
  prints the project authors and exits 0 without starting a shell, loading
  configuration or plugins, printing a banner, or needing a TTY. All existing
  command-line behavior is unchanged.

### Packaging metadata

- Set the PyPI development status to Production/Stable and added the FreeBSD
  operating-system classifier, matching the Tier 1 platform contract. The
  runtime contract is unchanged: CPython 3.13 or newer.
- Project author metadata now lists all three project authors reported by
  `pysh --credits`.

### Documentation

- Corrected the manual-validation checklist, which showed `py 1 + 1` as
  producing output; one-line `py` code uses `exec` semantics, so it prints
  nothing, and the checklist now uses `py print(1 + 1)`.

## 0.9.1 - 2026-09-29

Maintenance release focused on installation portability and release safety.

### Packaging and platform portability

- Defined support by Debian-family, RPM-family, and FreeBSD-family runtime
  capabilities rather than distribution release numbers. Debian 13, Fedora
  43, and FreeBSD 14.4 remain reference CI environments, not allowlists.
- Preserved the CPython 3.13 minimum with no upper minor-version bound. The
  Debian/RPM launcher now validates actual interpreters and can select a
  qualifying versioned `python3.N` when the generic `python3` is too old.
- Kept one canonical `pysh-shell-0.9.1.pkg` reference release asset, built on
  FreeBSD 14.4 amd64 with CPython 3.13, while retaining native `pkg` ABI
  validation. The reference archive is not claimed to be ABI-universal.
- Made the FreeBSD package's selected Python minor drive its manifest,
  installed wrapper, and native smoke test consistently.
- Hardened release staging so a freshly built FreeBSD package is not replaced
  by preserved bytes and the required reference package reaches the artifact
  gate before release upload.

### CI and terminal portability

- Added explicit Debian 13 and FreeBSD 14.4 platform-reference lanes.
- Installed and verified Bash before FreeBSD PTY tests.
- Normalized the terminal-visible FreeBSD Ctrl+D echo sequence in the
  SecureRunner regression test without weakening exit-status validation.
- Strengthened the PTY smoke contract to inspect every exit/quit invocation.

### Documentation and release contracts

- Corrected installation documentation and its validator for canonical
  distro-neutral package names and the FreeBSD reference-package ABI caveat.
- Required wheel, sdist, `.deb`, `.rpm`, reference `.pkg`, and `SHA256SUMS`
  through the flat GitHub Release artifact contract.

The platform/runtime/installability foundation from Issue #52 ships in this
maintenance release. Any remaining v1.0 assurance evidence and milestone
bookkeeping continue separately.

### Public API

- Added the canonical `pysh.api` facade with the stable `ShellSession`
  embedding lifecycle and stable contract-protocol re-exports.
- Published the package/Python API/Plugin API/isolated manifest/IPC version
  matrix, SemVer rules, and minimum two-minor deprecation lifecycle.
- Deprecated `pysh.shell.PyShell` for the 1.0.0 contract in favor of
  `pysh.api.ShellSession`. Symbol access emits `DeprecationWarning`; removal is
  not permitted before PySH 1.2.0.

## 0.9.0 - 2026-09-19

Fixed in 0.9.0 development:

- Added native, transactional virtual-environment activation and the
  `deactivate` builtin without interpreting foreign activation scripts.
- Added clean batch-input behavior for bare `pysh` with non-TTY stdin.
- Unified builtin, plugin, Python, and external pipeline/redirection execution,
  including Python block pipeline stages and ordered numeric-fd duplication.
- Made command completion prefix-only and added safe completion-backed ghost
  suggestions after history lookup.
- Resolved effective prompt identity through EUID rather than `USER`/`LOGNAME`.
- Isolated PTY and documentation consistency tests from parent terminal and
  ignored local-file state.
- Added deterministic diagnostics for Python-like `-c` input, unsupported shell
  control flow, and process substitution.

### Release engineering

- Added Release Quality Gate 2.0 with deterministic metadata and artifact
  validation, real Debian/RPM/FreeBSD package install-and-run smoke tests,
  and gated GitHub Release asset validation.

## 0.8.2 - 2026-06-08

Release type: metadata hotfix.

Packaging metadata:

- Added missing package author email metadata.
- Added Karol Sobolewski as a package author.
- No runtime behavior changes.
- No dependency changes.

## 0.8.1 - 2026-06-08

Release type: hotfix / contract-cleanup — stdlib-only runtime invariant
restoration and version-documentation drift fix.

### Runtime dependencies

- Restored the stdlib-only default install. `pip install pysh-shell` no longer
  pulls any runtime dependency.
- Pygments moved from a mandatory runtime dependency to an optional `highlight`
  extra (`pip install pysh-shell[highlight]`). Python-source rendering in
  py-mode, `#show`, `#edit`, and diagnostics degrades to plain text when the
  extra is absent and never raises ImportError. Shell command-line highlighting
  is internal and unaffected.
- Removed the unused PyYAML dependency. No module imported it; it was a dead
  dependency.

### Documentation

- Fixed version-documentation drift: current-facing docs now reference 0.8.1.
- Contract documents retain historical establishment wording ("PySH 0.6.x
  line"); they were not mechanically renumbered.
- Verified AI-agent guide files do not contain stale GPL-3.0 license strings.
  The LICENSE file (GPL-2.0) was already correct and is unchanged.

### Validation

- `uv run ruff check src tests` passed.
- `uv run pytest -q` passed.

## 0.8.0 - 2026-06-06

Release type: release hardening — terminal presentation, paste-state safety,
release asset regression guards, FreeBSD packaging validation, and builtin
dispatch fixes.

### Prompt and terminal presentation

- Issue #21: redesigned the prompt/banner presentation while preserving the
  framed prompt behavior required by the interactive shell.
- Added compact system display so terminal startup state remains readable
  without expanding into noisy host diagnostics.

### Multiline paste and stale input hardening

- Issue #22: hardened staged multiline paste handling so stale paste payloads
  and same-batch queued commands cannot silently survive `paste_cancel`,
  `paste_run`, or Ctrl+C into a later prompt.
- Paste parse errors are attributed as paste-originated diagnostics while
  direct typed parse errors retain the normal direct input form.

### Release asset workflow and upgrade documentation

- Issue #23: added release asset workflow regression guards for flat release
  assets and `SHA256SUMS` validation.
- Upgrade documentation now states that an existing `~/.pyshrc.py` is not overwritten
  during upgrades. Future default configuration changes must be
  delivered as templates only.

### Exit and quit dispatch

- Issue #24: fixed the builtin dispatch regression so `exit` and `quit`
  execute through the intended shell builtin path.

### FreeBSD package validation

- Issue #18: FreeBSD 14+ validation and mandatory FreeBSD `.pkg` release
  gating are now part of the release contract.
- A v0.8.0 release is incomplete without all required artifacts: wheel, sdist,
  Debian `.deb`, RPM `.rpm`, FreeBSD `.pkg`, and `SHA256SUMS`.
- The FreeBSD `.pkg` must be built on FreeBSD 14+ with native `pkg` tooling.
- Debian/Linux hosts must not fake `.pkg` artifacts; release quality checks
  must fail deterministically until a real FreeBSD-built `.pkg` is present.

## 0.7.0 - 2026-06-05

Release type: feature release — migration analysis, zsh transition hardening,
system shell integration policy, and packaging release quality gate.

### Python script migration analysis layer

- Added `migrate FILE` and `migrate --text TEXT` builtins.
- Static, non-executing shell-script analysis: detects shebangs, assignments,
  exports, pipelines, redirections, command substitution, simple conditionals,
  simple loops, heredocs and unsafe `eval`/`exec` patterns.
- Severity-based migration report with `info`, `warning`, `unsafe` and
  `unsupported` finding categories.
- `migrate` does not execute, source, expand or automatically convert analyzed
  shell content.

### Zsh transition hardening

- Unsupported zsh syntax diagnostics: reports constructs PySH cannot execute.
- Source-file rejection: the plain `source` builtin now rejects
  `.zshrc`, `.zprofile`, `.zshenv`, `.zlogin`, and `.zlogout` startup files
  with explicit guidance to use the safe static importer or PySH-native
  configuration instead.
- `.pyshrc` is the canonical PySH configuration file. Zsh startup files are
  not sourced automatically by PySH.

### System shell integration policy

- Documented and enforced: PySH is not `/bin/sh` and must not replace the
  distribution system shell.
- `sh`, `dash`, `ash`, and `busybox sh` invocation diagnostics: PySH detects
  and reports when the user attempts to invoke PySH as a POSIX system shell.
- No system shell replacement policy: packages must not divert `/bin/sh` or
  register PySH as a POSIX sh provider.

### Packaging release quality gate

- Mandatory release artifacts: PyPI wheel + sdist, Debian `.deb`, RPM `.rpm`,
  and `SHA256SUMS`. A release is incomplete unless all four artifact families
  are built and validated.
- Package metadata checks: name, version, license, description, entry points,
  Python requirement.
- Artifact hygiene checks: wheel and sdist must not include `.git/`, `.venv/`,
  `__pycache__/` or other development-time directories.
- OS package content checks: both `.deb` and `.rpm` must contain
  `/usr/bin/pysh` and `/opt/pysh-shell/lib/pysh`.
- Clean temporary venv install smoke: wheel is installed into an isolated venv
  and `pysh --version` / `pysh -c "echo release-smoke"` are executed.
- SHA256SUMS coverage check: all four artifact families must have checksum lines.
- FreeBSD `.pkg` support remains deferred to Issue #18.

Validation:

- `uv run ruff check src tests` passed.
- `uv run pytest -q` passed.
- `scripts/check_release_quality.sh` passed.

## 0.6.1 - 2026-06-04

Release type: bugfix and terminal UX hardening.

Compatibility:

- No external runtime dependency was added for this bugfix release.
- PySH remains a Python-first shell with the existing documented compatibility
  boundaries.

Fixed:

- BUG #1: internal command-not-found diagnostics now respect command-level
  stderr and combined-output redirection, including `2>`, `2>>`, `&>` and
  `&>>`.
- BUG #2: interactive heredoc cancellation no longer leaks or replays stale
  delimiter/body state; Ctrl+C returns to a clean prompt and `exit` works after
  cancellation.
- BUG #3: interactive `py { ... }` block collection executes the block once,
  without replaying body lines as shell commands.
- BUG #4: bracketed multiline paste is staged safely. Paste capture shows a
  numbered preview, Enter explicitly runs the staged payload, Ctrl+C cancels it,
  and `paste_show`, `paste_run` and `paste_cancel` manage the pending payload.
  Python block paste and heredoc paste execute through the native PySH
  script/logical-line path after explicit confirmation.
- BUG #5: Ctrl+R reverse history search is visible and usable in the raw line
  editor. Queries and matches are visibly separated, Enter executes the selected
  match, Ctrl+C cancels cleanly and pending staged paste blocks reverse search
  until the paste is run or cancelled.
- Secure runner PTY execution now isolates the direct fork/PTY bridge in a
  helper process, removing the Python 3.13 multi-threaded `os.fork()`
  deprecation warning from the release test gate while preserving terminal-state
  restoration and secure input behavior.
- RPM build validation now uses a temporary private rpmdb path, avoiding host
  `/var/lib/rpm` permission diagnostics during local release builds.

Terminal UX hardening:

- Paste preview, paste-run preview, reverse-search UI, hints, warnings and
  prompt state were made more readable.
- Unsafe ANSI color combinations that could render black or invisible glyphs
  were removed from terminal UI paths.
- `NO_COLOR=1` and `PYSH_NO_COLOR=1` disable ANSI colors only; they do not
  disable raw-editor safety behavior or bracketed-paste protection.

Validation:

- `uv run ruff check src tests` passed.
- `PYTHONWARNINGS=error::DeprecationWarning uv run pytest -q tests/test_secure_runner.py`
  passed.
- Full pytest passed: `1513 passed, 2 skipped`.

## 0.6.0 - 2026-06-04

- Added the parser, expansion and multiline grammar foundation:
  - Quote-aware parser primitives now provide a stronger contract for command
    chains, pipelines, continuations, unsupported syntax and parse errors.
  - Expansion behavior is documented and tested for the supported PySH-native
    subset.
- Added native glob and path expansion:
  - Tilde, relative path and glob expansion are handled inside PySH without
    shell delegation.
  - Dotfile and no-match behavior are documented and test-backed.
- Added here-documents and here-strings for PySH command execution.
- Added job control and process-group handling:
  - Background execution, `jobs`, `fg` and `bg` are implemented for the
    documented POSIX job-control subset.
- Added Completion Engine v1:
  - Completion covers builtins, aliases, PATH commands, filesystem paths,
    variables and jobs.
- Added observability and diagnostics:
  - `--debug` and `--trace` emit structured stderr diagnostics.
  - Diagnostic output applies redaction for sensitive values.
- Added Script Mode v1:
  - `pysh script.pysh [args...]` and `python -m pysh script.pysh [args...]`
    execute explicit PySH-native scripts.
  - Script mode supports positional parameters, heredocs, glob expansion,
    Python blocks and deterministic exit-status behavior.
- Migrated project licensing metadata and headers to GPL-2.0-only.
- Reorganized architecture, compatibility, user and development documentation
  around explicit contracts and validation evidence.

### Compatibility boundary

- PySH remains PySH-native.
- PySH is not a POSIX `/bin/sh` replacement.
- PySH is not zsh-compatible or bash-compatible.
- Foreign-shell migration and delegation paths remain explicit and scoped.

## 0.5.0

- Added Python-native `~/.pyshrc.py` generation on first launch.
- Added production-commented `~/.pyshrc.py` template.
- Added full two-line prompt with tool/version segments.
- Added configurable prompt colors with VGA/truecolor support.
- Added configurable terminal cursor color.
- Added stdlib raw-mode line editor.
- Added live syntax highlighting.
- Added fish-style history autosuggestions.
- Added prefix-filtered TAB completion fixes.
- Added ANSI-safe cursor positioning for colored prompts.
- Added explicit `secure <cmd>` PTY runner.
- Added fixed-size sensitive-input ring indicator.
- Added shell-style comments with unquoted `#`.
- Added uv.lock/dev dependency workflow.
- Added header checker.
- Added Python Command Execution Layer (`#py`):
  - Interactive Python REPL with persistent runtime state.
  - IDLE-like multi-line block input with auto-indentation.
  - Blank Enter closes a complete block (CPython REPL semantics).
  - Syntax highlighting via Pygments across all Python mode views.
  - File-backed edit workspace: `#open`, `#save`, `#show`, `#run`, `#clear`,
    `#reset`, `#edit`, `#insert`, `#replace`, `#delete`.
  - Path expansion for `~`, relative, and absolute paths.
  - TAB completion for file directives; TAB inserts four spaces in code.
  - Safe source-buffer policy: only successfully executed input is saved.
  - Saved files contain clean Python source — no prompts, no ANSI escapes.
- Added `system_info` helper for compact startup banner (`System:` line).
- Updated startup banner: PySH version, Python version, GPL-2.0-only license tag,
  and system summary line.

### Known limitations

- `secure <cmd>` uses fork/PTY and emits pytest DeprecationWarning under
  threaded pytest.
- Bracketed paste is handled safely as byte stream; polish remains future work.
- TAB inside Python command mode inserts four spaces only (no symbol completion).
- Viewport bottom padding without scrollback pollution is deferred.
