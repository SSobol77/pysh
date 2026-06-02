<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/documentation-policy.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Documentation Policy

Documentation is part of the PySH release deliverable. A feature is not
complete until user-facing behavior, limitations and verification impact are
documented.

## Required coverage

- Every new builtin must be added to `README.md` and `docs/user/builtins.md`.
- Every new operator or parser feature must be added to `README.md` and
  `docs/user/operators.md`.
- Every new configuration or startup behavior must be added to
  `docs/user/configuration.md`.
- Every migration feature must be added to `docs/migration/migration.md`.
- Every zsh/bash/sh compatibility feature must be added to
  `docs/migration/zsh-compatibility.md`.
- Every Python runtime feature must be added to `docs/python/python-runtime.md`.
- Every Debian/system profile helper must be added to
  `docs/shell/system-profile.md`.
- Every command-planning behavior must be added to
  `docs/shell/command-planning.md`.
- Every limitation must be added to `docs/user/limitations.md`.
- Every packaging change (artifact families, filenames, install
  layout, CI/release workflows) must be reflected in
  `docs/development/packaging.md`, `docs/user/installation.md` and
  `docs/development/release.md`.
- Every CLI option must be documented in `README.md`, `docs/user/usage.md` and,
  when installation-related, `docs/user/installation.md`.

## Engineering rule

Tests and docs must evolve together. New behavior needs tests that protect
the contract and documentation that explains the contract. If behavior is
intentionally limited, the limitation must be documented in the same change.

## Review checklist

- README gives a concise user-facing overview.
- Dedicated docs explain syntax, examples, return behavior and limitations.
- Builtin lists, completion metadata and implemented builtins do not drift.
- Migration docs do not claim full zsh, bash or POSIX compatibility.
- Static import docs state that profile files are read without execution.
