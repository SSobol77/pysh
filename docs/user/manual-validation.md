<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/manual-validation.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Manual User Validation

This checklist is the final user-path acceptance checklist for the public
manual. It complements automated CI and package-contract tests; visual terminal
behavior still requires an interactive terminal.

## Fresh virtual environment

```sh
python3.13 -m venv /tmp/pysh-user-manual
. /tmp/pysh-user-manual/bin/activate
python -m pip install --upgrade pip
python -m pip install pysh-shell==0.9.0
pysh --version
python -m pysh --version
```

Expected result: both version commands report `pysh 0.9.0`.

Before PyPI publication, the equivalent wheel/sdist install path is validated
by the release quality gate from locally built artifacts.

## Package install

Use the package matching the target platform:

- Debian 13: install `pysh-shell_0.9.0-1_all.deb` with `apt install ./...`;
- RPM-based Linux: install `pysh-shell-0.9.0-1.noarch.rpm`;
- FreeBSD 14+: install `pysh-shell-0.9.0.pkg` with `pkg`.

Then verify:

```sh
pysh --version
python -m pysh --version
pysh -c "echo package-smoke"
```

The release workflows perform real install-and-run smoke tests for the package
families before publication.

## First interactive run

Start:

```sh
pysh
```

Confirm:

- startup completes without a traceback;
- the prompt renders;
- `echo first-run-ok` executes once;
- `exit` exits on the first attempt.

## Configuration generation and preservation

On a disposable HOME with no existing user configuration, start PySH once and
verify the default configuration path is created as documented. Start PySH a
second time and confirm the existing user file is preserved rather than
overwritten.

Configuration behavior and precedence are documented in
[configuration.md](configuration.md).

## Basic command session

In an interactive PySH session run:

```sh
pwd
echo hello
py 1 + 1
```

Then verify:

- command output is correct;
- history records the commands;
- Ctrl+R can find a previous command;
- Ctrl+C returns to a usable prompt;
- multiline paste is staged rather than auto-executed.

## PySH 0.9.0 evidence record

The 0.9.0 manual/documentation acceptance is backed by both interactive and
release-gate evidence:

- Debian 13 interactive validation completed on 2026-09-18 and covered normal
  command execution, Python multiline input, heredoc, Ctrl+C, Ctrl+R,
  completion, history autosuggestion, staged paste, terminal resize, and
  `exit`/`quit`;
- FreeBSD 14.4 native validation run
  [35509718619](https://github.com/SSobol77/pysh/actions/runs/35509718619)
  passed the focused #32/#36 acceptance suites and real PTY `exit`/`quit`
  smoke;
- current `main` CI run
  [35513339524](https://github.com/SSobol77/pysh/actions/runs/35513339524)
  passed 2422 tests with 1 skip, Ruff, release metadata checks, and package
  contract validation;
- fresh-environment installation, config-generation, and package installation
  paths are additionally covered by deterministic release/installation tests,
  while visual terminal behavior remains represented by the manual interactive
  evidence above.

For every future release, repeat this checklist against the release candidate
and record the run or maintainer evidence in the corresponding release issue.
