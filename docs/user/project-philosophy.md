<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/project-philosophy.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Project Philosophy

PySH is a Python-first interactive shell for developers who want normal shell
workflows and an explicit Python execution layer without pretending that every
other shell language is interchangeable.

## Python-first, not Python-only

External commands, pipelines, redirection, history, completion, prompt
rendering, and interactive editing remain shell workflows. Python is available
through explicit PySH interfaces such as the `py` builtin and Python Command
Execution Layer; users are not required to rewrite ordinary command-line work
as Python.

## Explicit compatibility boundaries

Compatibility claims are intentionally narrow and test-backed. PySH does not
claim to be Bash, Zsh, Fish, or a POSIX `/bin/sh` replacement. Migration
helpers inspect or import only the documented static subset and do not turn
foreign startup files into implicitly trusted executable input.

The authoritative compatibility scope lives under
[../compatibility/](../compatibility/README.md).

## Deterministic behavior over hidden magic

PySH favors behavior that can be explained, reproduced, and regression-tested:

- missing optional tools degrade quietly;
- prompt integrations are explicit and bounded;
- paste requires deliberate execution when staged;
- configuration precedence is documented;
- package and release naming is contractual rather than inferred.

## Safety without false security claims

PySH reduces accidental execution and protects sensitive-input boundaries where
the implementation can enforce them. It does not claim to sandbox arbitrary
Python or untrusted plugins. Trusted-code boundaries, plugin loading, command
planning, and sensitive-input behavior are documented explicitly.

## User control

The shell should not silently replace the system shell, execute foreign profile
files, publish data, or install optional ecosystem tools on behalf of the user.
Potentially consequential actions remain explicit.

## Platform policy

Debian 13 is the primary development and user-validation target. FreeBSD is a
first-class validated Unix-like target where documented. Platform differences
must be visible in tests and documentation rather than hidden behind unsupported
compatibility claims.

## Documentation as a contract

Public documentation must describe current behavior, not aspirations. New
features should update their user guide, limitations, compatibility scope, and
tests together so that the docs remain usable as an operational reference.
