<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/release-notes-template.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Release Notes Template

Use this template for GitHub Release notes. Replace every angle-bracket
placeholder before publication; remove sections that genuinely do not apply.

```markdown
# PySH v<version>

Release date: <YYYY-MM-DD>

## Summary

<One short paragraph describing the purpose of this release.>

## Highlights

- <User-visible highlight>
- <User-visible highlight>
- <User-visible highlight>

## Interactive shell

- <Editor, history, completion, prompt, paste, heredoc or job-control change>

## Python Command Execution Layer

- <Python runtime or command-mode change, or "No user-visible changes.">

## Configuration and plugins

- <Configuration, themes, profiles, Plugin API or startup behavior change>

## Compatibility and migration

- <Compatibility boundary or migration-helper change>
- PySH remains a Python-first shell and does not claim Bash, Zsh, Fish, or
  POSIX /bin/sh compatibility beyond the documented feature matrix.

## Platforms

- Debian 13: <validation result>
- FreeBSD 14+: <validation result>
- Other Unix-like systems: <documented support statement>

## Packaging

Published artifact families:

- pysh-shell-<version>-py3-none-any.whl
- pysh_shell-<version>.tar.gz
- pysh-shell_<version>-1_all.deb
- pysh-shell-<version>-1.noarch.rpm
- pysh-shell-<version>.pkg
- SHA256SUMS

PyPI package: pysh-shell

## Security and trust boundaries

- <Security-relevant change, or "No trust-boundary changes.">
- <Any change to plugins, sensitive input, migration import, or external tools>

## Known limitations

- <Known limitation>
- <Known limitation>

## Upgrade

PyPI:

    python3.13 -m pip install --upgrade pysh-shell

For .deb, .rpm and .pkg upgrades, follow docs/user/installation.md.

## Validation evidence

- CI: <URL>
- Release quality gate: <PASS / READY_EXCEPT_PLATFORM_VALIDATION + evidence>
- FreeBSD validation: <URL>
- Manual user validation: <issue/comment or checklist URL>

## Changes

<Curated list or link to the changelog/compare view.>
```

Before publishing, verify the version, artifact names, platform statements,
known limitations, and validation links against the release candidate.
