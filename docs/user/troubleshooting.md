<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/troubleshooting.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Troubleshooting

This guide covers the most common user-facing failures for PySH 0.9.0.
Start with the smallest reproducible command and keep compatibility claims
scoped: PySH is not a drop-in Bash, Zsh, Fish, or POSIX `/bin/sh`
replacement.

## Installation and command discovery

Confirm the interpreter and installed package first:

```sh
python3.13 --version
python3.13 -m pip show pysh-shell
pysh --version
python3.13 -m pysh --version
```

If `pysh` is not found but `python3.13 -m pysh` works, the Python
scripts directory is not on `PATH`. Re-open the shell after changing
`PATH`, then verify with:

```sh
command -v pysh
```

For installation and upgrade commands, use
[installation.md](installation.md). Do not install PySH as `/bin/sh`.

## Wrong Python or virtual environment

PySH requires Python 3.13 or newer. When a virtual environment is active,
verify that `python`, `pip`, and `pysh` resolve to the same environment:

```sh
command -v python
command -v pip
command -v pysh
python --version
python -m pip show pysh-shell
```

If the paths disagree, deactivate the stale environment or reinstall PySH
inside the intended environment.

## Configuration problems

PySH loads declarative TOML configuration and user startup files as described
in [configuration.md](configuration.md). If normal interactive startup fails or
configuration may be malicious, start a deterministic recovery session first:

```sh
pysh --no-rc
```

This bypasses every user startup layer and does not create or rewrite the
default TOML or `~/.pyshrc.py`. If recovery startup succeeds, validate the
normal load order and inspect the startup files before enabling normal startup
again. `--no-rc` does not sandbox commands entered in the recovery session.

Important rules:

- an existing `~/.pyshrc.py` is never overwritten by upgrade logic;
- project-local plugin code is not loaded by default;
- invalid optional integrations must degrade quietly rather than prevent the
  shell from starting.

When diagnosing configuration, record the exact file changed and the first
error emitted on stderr.

## Prompt or integration segment is missing

Tool-version prompt segments are optional. A segment can be absent because:

- the corresponding prompt option is disabled;
- the executable is not on `PATH`;
- the tool is intentionally not installed;
- the detector timed out or returned no usable version.

AWS, Kubernetes, and SSH prompt context is also optional. Missing context must
not produce noisy startup errors. See [prompt.md](prompt.md) for the available
switches.

## History or Ctrl+R behaves unexpectedly

See [history.md](history.md) first. For reverse search:

1. start PySH interactively;
2. execute a unique command;
3. press Ctrl+R;
4. type part of that command;
5. use repeated Ctrl+R to cycle older matches;
6. press Enter to accept, or Esc/Ctrl+G to cancel and restore the original
   buffer.

If copied terminal text looks corrupted, reproduce the behavior in a fresh
terminal before assuming the history store itself is damaged; cursor redraw
artifacts can affect copied output.

## Multiline paste is staged instead of executed

That is intentional. Bracketed multiline paste is captured for review and must
not auto-execute. Use the documented staged-paste controls described in
[multiline-paste.md](../shell/multiline-paste.md). Ctrl+C cancels the staged
payload.

## Completion floods the terminal or returns too many candidates

Completion is prefix-driven and terminal-aware. Use a more specific prefix
before pressing Tab again. See [completion.md](completion.md) for repeated-Tab
behavior, candidate display, and Python-symbol completion.

## Terminal redraw, resize, or Unicode problems

If prompt rendering is incorrect:

- reproduce with `TERM=xterm-256color`;
- try a fresh terminal without multiplexer-specific configuration;
- resize once and verify the prompt redraws;
- use the documented no-color mode if ANSI rendering is the suspected cause.

FreeBSD and Debian both use the native POSIX terminal path, but PTY/termios
details can differ. Platform-specific behavior should be reported with
`uname -a`, terminal type, PySH version, and Python version.

## Plugin problems

Plugins are trusted local Python code, not a sandbox. Disable the suspect
plugin and confirm that core PySH starts normally. Then follow
[plugin-guide.md](../plugins/plugin-guide.md), including project-local opt-in
rules and Plugin API validation errors.

## Useful diagnostics

The following commands are intended for read-only diagnosis:

```sh
pysh --version
python -m pysh --version
sys_info
env_audit
path_audit
which_all pysh
```

Do not paste secrets, tokens, passwords, private keys, or unredacted
environment dumps into bug reports.

## When reporting a bug

Include:

- PySH version;
- Python version;
- operating system and release;
- `TERM`;
- exact command or key sequence;
- expected result;
- actual result;
- whether the problem reproduces with user configuration disabled or reduced.

Known compatibility boundaries are documented in
[limitations.md](limitations.md). Release and packaging validation policy is
documented in [release.md](../development/release.md).
