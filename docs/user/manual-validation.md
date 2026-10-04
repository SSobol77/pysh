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
python -m pip install pysh-shell==X.Y.Z
pysh --version
python -m pysh --version
```

Expected result: both version commands report `pysh X.Y.Z`.

Before PyPI publication, the equivalent wheel/sdist install path is validated
by the release quality gate from locally built artifacts.

## Package install

Use the package matching the target platform:

- Debian 13: install `pysh-shell_X.Y.Z-1_all.deb` with `apt install ./...`;
- RPM-based Linux: install `pysh-shell-X.Y.Z-1.noarch.rpm`;
- FreeBSD 14+: install `pysh-shell-X.Y.Z.pkg` with `pkg`.

Then verify:

```sh
pysh --version
python -m pysh --version
pysh --credits
pysh -c "echo package-smoke"
```

`pysh --credits` must print exactly the project-authors list (a title line and one
author per line), exit 0, and start no shell, banner, prompt or configuration load.

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
py print(1 + 1)
```

Then verify:

- command output is correct;
- history records the commands;
- Ctrl+R can find a previous command;
- Ctrl+C returns to a usable prompt;
- multiline paste is staged rather than auto-executed.

One-line `py <code>` uses `exec` semantics: an expression result is not echoed,
which is why the example above uses `py print(1 + 1)`; `py 1 + 1` correctly
prints nothing. Under `TERM=dumb` the readline fallback is used, and its Ctrl+R
searches the history loaded at startup (see [history.md](history.md)).

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

## PySH 1.0.0 candidate record

The 1.0.0 candidate was driven through this checklist on 2026-10-04 on a Debian
13 amd64 workstation, against the locally built wheel and sdist installed into fresh
virtual environments (`pysh --version` and `python -m pysh --version` both report
`pysh 1.0.0`) and a disposable `HOME`. The session was driven by an automated
pseudo-terminal harness, not by a person watching a screen, so it covers behavior
and not visual presentation:

- `pysh --credits` and `python -m pysh --credits` printed the three-author list and
  exited 0 on a real pseudo-terminal and with redirected output, with no banner,
  prompt or configuration load;
- startup without a traceback, prompt rendering, `echo first-run-ok` executes once,
  `exit` exits on the first attempt (`TERM=xterm-256color` and `TERM=dumb`);
- first start created `~/.pyshrc.py`, and a second start left a user-modified file
  byte-for-byte unchanged;
- `pwd`, `echo hello`, `py print(1 + 1)`, a heredoc and a typed multiline `py { ... }`
  block produced the expected output;
- Ctrl+C interrupted `sleep 30` (status 130) and returned to a usable prompt;
- Ctrl+R found a previous command in the raw editor, and found a command from a
  previous session under the `TERM=dumb` readline fallback;
- a bracketed multiline paste was staged and not auto-executed.

The visual items (prompt appearance, syntax-highlight colors, terminal resize) still
require a person at an interactive terminal and are repeated by the maintainer
against the final release candidate before tagging.
