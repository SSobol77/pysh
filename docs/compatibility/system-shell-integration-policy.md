<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/system-shell-integration-policy.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# System Shell Integration Policy

This policy defines how PySH may interact with operating-system shell
concepts. It is a safety and compatibility boundary, not a roadmap for making
PySH a POSIX shell.

## Final policy

PySH may be used as an interactive user shell and Python-first command
environment. PySH must not be used as a POSIX `/bin/sh` provider.

PySH is not a POSIX shell, does not implement the full POSIX shell grammar,
and does not guarantee system script compatibility. System scripts, package
manager hooks, init scripts, maintainer scripts and distribution tooling must
continue to run under a real system shell such as `/bin/dash`, `/bin/sh`
provided by the distribution, or another POSIX-compliant shell.

## Recommended integration modes

Use these modes:

- Run `pysh` explicitly for an interactive Python-first shell session.
- Run PySH-native scripts explicitly:

  ```sh
  pysh script.pysh arg1 arg2
  python -m pysh script.pysh arg1 arg2
  ```

- Use `run_script FILE [ARGS...]` when deliberately transitioning an existing
  shell script. Scripts with `zsh`, `bash` or `sh` shebangs are delegated to
  the real interpreter through an argv list.
- Use `zsh COMMAND...` only as explicit delegation to real zsh.
- Keep the operating-system `/bin/sh` unchanged.

## Unsupported integration modes

Do not use these modes:

- Symlinking `/bin/sh` to PySH.
- Replacing the distribution shell with PySH.
- Assuming POSIX sh compatibility for PySH-native script mode.
- Running package-manager, maintainer, init, boot or distro scripts through
  PySH.
- Silently delegating system scripts without explicit user intent.
- Advertising PySH as a bash, zsh, POSIX sh or system-script-compatible shell.

## Invocation diagnostics

If PySH is invoked through a system-shell-like name such as `sh` or `dash`, it
rejects startup before parsing user commands:

```text
pysh: unsupported invocation mode: sh
hint: PySH is not a POSIX /bin/sh provider. Run PySH explicitly as `pysh`.
```

This diagnostic is conservative. It is intended to catch unsafe symlink or
argv0 masquerading configurations while preserving normal `pysh` and
`python -m pysh` invocation.

## Script execution boundaries

PySH has three distinct script paths:

| Mode | Command | Contract |
| ---- | ------- | -------- |
| Native PySH script | `pysh script.pysh` | Executes documented PySH Script Mode v1 semantics. This is not POSIX sh. |
| Explicit transition runner | `run_script FILE [ARGS...]` | Delegates `zsh`, `bash` and `sh` shebang scripts to their real interpreters. |
| External interpreter | `zsh COMMAND...` or direct `bash`/`sh` command | External shell behavior; PySH is not interpreting that grammar. |

Unsupported mode:

| Mode | Command | Contract |
| ---- | ------- | -------- |
| `/bin/sh` provider | `/bin/sh` replaced by PySH | Forbidden. PySH must not be installed or invoked as the system POSIX shell. |

## Packaging and installation guidance

Packages may install the `pysh` command and documentation. Packages must not
register PySH as `/bin/sh`, divert `/bin/sh`, replace `/bin/dash`, rewrite
system maintainer scripts to PySH, or configure package-manager hooks to use
PySH as their shell.

If a distribution chooses to list PySH as an optional login shell for a user,
that integration must remain separate from `/bin/sh` and must preserve an
administrator-controlled recovery path using a standard system shell.
