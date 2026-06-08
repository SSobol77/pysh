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
