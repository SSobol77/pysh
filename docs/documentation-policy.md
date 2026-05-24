<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Documentation Policy

Documentation is part of the PySH release deliverable. A feature is not
complete until user-facing behavior, limitations and verification impact are
documented.

## Required coverage

- Every new builtin must be added to `README.md` and `docs/builtins.md`.
- Every new operator or parser feature must be added to `README.md` and
  `docs/operators.md`.
- Every new configuration or startup behavior must be added to
  `docs/configuration.md`.
- Every migration feature must be added to `docs/migration.md`.
- Every zsh/bash/sh compatibility feature must be added to
  `docs/zsh-compatibility.md`.
- Every Python runtime feature must be added to `docs/python-runtime.md`.
- Every Debian/system profile helper must be added to
  `docs/system-profile.md`.
- Every command-planning behavior must be added to
  `docs/command-planning.md`.
- Every limitation must be added to `docs/limitations.md`.
- Every packaging change (artifact families, filenames, install
  layout, CI/release workflows) must be reflected in
  `docs/packaging.md`, `docs/installation.md` and
  `docs/release.md`.
- Every CLI option must be documented in `README.md`, `docs/usage.md` and,
  when installation-related, `docs/installation.md`.

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
