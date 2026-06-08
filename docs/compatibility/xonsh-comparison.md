<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/xonsh-comparison.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Xonsh Shell Comparison

This document compares PySH and Xonsh at the technical architecture level. It
is not a migration guarantee and does not claim that either shell can
transparently replace the other. PySH is not a `/bin/sh` replacement and does
not claim POSIX shell compatibility.

PySH is a shell-first command environment written in Python. It is
POSIX-influenced, but its compatibility claims are limited to the documented
feature matrix and contract documents in this directory. Python integration is
explicit through the `py` builtin and the Python Command Execution Layer.

Xonsh is a Python-derived shell language and runtime with its own parser. It
extends Python syntax to natively parse and execute subprocess commands,
including subprocess syntax, pipelines, redirects, job control, globs,
subprocess substitution, line continuations, and nesting between Python
expressions and subprocess commands.

---

## Comparison Matrix

| Feature area | PySH | Xonsh | Notes |
| ------------ | ---- | ----- | ----- |
| Language/runtime model | Shell-first command environment written in Python. | Python-derived shell language/runtime with native subprocess syntax. | PySH adds Python execution features explicitly; Xonsh extends Python into a shell language. |
| Python integration | Explicit `py` command and Python Command Execution Layer. | Python is the language substrate; Python expressions and subprocess commands can be nested. | PySH separates shell and Python modes more explicitly. |
| Command execution | Command execution layer for shell-style commands, including documented chains, pipelines, redirections, command substitution, variables, aliases, and builtins. | Native subprocess syntax parsed by its own parser/runtime. | Xonsh has deeper language-level integration. |
| Shell compatibility | POSIX-influenced, not a POSIX replacement. | Custom Python-derived syntax, not a POSIX shell clone. | Neither should be presented as a strict POSIX shell replacement. |
| Job control | Foundational job control with background execution, `jobs`, `fg`, and `bg`. | More mature job-control behavior. | PySH does not claim full mature job control. |
| Completions | PySH-native Completion Engine v1, with a planned Completion Engine 2.0 direction. | Mature completer ecosystem. | PySH completion is still evolving. |
| Configuration | `.pyshrc.py` / PySH configuration model, plus documented startup files and plugin loading. | Xonsh RC and xontrib ecosystem. | Xonsh has a mature extension/configuration ecosystem. |
| Dependencies | Stdlib-only default install; optional extras may add features such as syntax rendering. | Python package with optional ecosystem/extensions. | PySH intentionally keeps the default install minimal. |
| Cross-platform support | Debian/Unix-like focus with FreeBSD validation; FreeBSD 14+ `.pkg` is a mandatory release artifact. | Broader cross-platform support. | PySH's current platform strategy is narrower. |
| Extension model | Project-scoped plugins/configuration are still maturing. | Xontrib ecosystem. | Xonsh has a more mature extension model. |
| Startup and complexity profile | Smaller shell-first project. | Larger parser/runtime ecosystem. | This is an architectural trade-off, not a quality judgment. |

---

## Dependency Posture

PySH's default installation is intentionally stdlib-only:

```sh
python3.13 -m pip install pysh-shell
```

The optional `highlight` extra enables Pygments-backed Python-source rendering:

```sh
python3.13 -m pip install 'pysh-shell[highlight]'
```

When Pygments is absent, Python-source rendering degrades to plain text and
does not raise `ImportError`. Shell command-line highlighting is internal to
PySH and does not require Pygments.

---

## Prefer PySH When...

- You want a shell-first command environment written in Python with explicit
  Python execution entry points.
- You want a stdlib-only default install and optional extras for selected
  presentation features.
- You want PySH's scoped compatibility model: documented native constructs,
  explicit delegation, and static transition helpers for shell-profile
  migration.
- Your target environment is Debian or Unix-like systems aligned with PySH's
  current validation strategy.

## Prefer Xonsh When...

- You want a Python-derived shell language/runtime with native subprocess
  syntax.
- You want language-level nesting between Python expressions and subprocess
  commands.
- You need the more mature Xonsh job-control, completer, configuration, and
  xontrib ecosystems.
- You need broader cross-platform support than PySH currently targets.

