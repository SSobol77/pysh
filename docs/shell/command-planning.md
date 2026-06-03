<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/shell/command-planning.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Command planning

PySH includes a foundation for command planning through the `plan`
builtin. `plan` previews how PySH would classify and execute a command line
without actually running it. It is advisory only — there is no policy
enforcement.

## Purpose

`plan <command...>` is intended for:

- Inspecting how PySH will route a command (native vs subprocess vs
  Python runtime vs zsh delegation).
- Spotting risky constructs (`sudo`, `eval`, command substitution,
  redirection to system paths) before they execute.
- Building higher-level tooling on top of the same classifier.

## Output fields

`plan` writes five lines:

```
original=<the command line that was planned>
kind=<builtin|external|pipeline|chain|python|zsh-delegation|script|unknown>
execution=<native|subprocess|python-runtime|zsh|bash|sh|none>
risk=<low|medium|high>
reason=<short human-readable explanation>
```

The output is deterministic so it can be parsed by tests and tooling.

## Risk model

`plan` assigns a coarse risk:

- `low` — ordinary builtins, external commands, simple pipelines.
- `medium` — command substitution, `zsh` / `zsh_fallback` delegation,
  `run_script` delegation.
- `high` — commands matching `sudo` or `eval`, or redirection that targets
  a system path such as `/etc`, `/usr`, `/bin`, `/sbin`, `/boot`, `/lib`.

This is a coarse classification, not a security guarantee.

## Examples

```sh
plan cd /tmp
plan alias ll='ls -la'
plan py print("x")
plan source_zsh_profile ~/.zshrc
plan run_script ./x.sh
plan zsh 'echo hi'
plan ls -la
plan ls | head
plan echo a && echo b
plan sudo apt update
plan eval "$(something)"
```

## Limitations

- `plan` is advisory only. Policy enforcement is intentionally **planned
  for a future release**.
- The classifier is line-oriented; it does not deeply evaluate scripts that
  `run_script` would invoke or files that `source_zsh_profile` would read.
- The risk model is intentionally conservative and coarse. A `low` risk
  classification is not a security clearance — review the command yourself.
- `plan` never modifies aliases, env vars, the working directory, or the
  filesystem. It is safe to invoke as often as you want.

## Return behavior

Returns 0 for a successful plan. Returns 2 when no command argument is
supplied.
