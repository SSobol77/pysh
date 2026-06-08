<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/prompt-engine.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Prompt Engine Development

Prompt rendering is implemented in `src/pysh/core/shell.py` on `PyShell`. It is
not owned by `src/pysh/prompt/system_profile.py`; that module provides
diagnostic builtins such as `sys_info`, `env_audit`, and `path_audit`.

## Render Paths

There are two prompt render paths and both must enumerate prompt segments:

- `_prompt_body(options)` renders the historical inline body used by
  `prompt_layout="single"`.
- `_build_framed_info_lines(options)` renders the information block for the
  default `prompt_layout="two_line"`.

The `two_line` command prompt returned by `_prompt()` must remain only the
closing line, for example `└─❯ `. Do not add colored informational content to
that readline string; width-sensitive rendering belongs in the separate info
block.

## Segment Invariants

Prompt Engine 2.0 keeps prompt rendering deterministic and bounded:

- No external dependencies.
- No network calls.
- No background threads.
- No AWS CLI, `kubectl`, or `git` invocation.
- Tool version probes use cached, timeout-bounded subprocess calls.
- Segment failures omit that segment instead of raising from prompt rendering.
- Environment/config-derived segment values are sanitized before rendering.

Command duration is measured in `execute()` around command dispatch only. It
excludes prompt rendering and line input wait time. Whitespace-only input resets
duration state.

Kubernetes context parsing is intentionally conservative: bounded file size,
stdlib text scanning, top-level `current-context`, first defining file wins for
multi-path `KUBECONFIG`, and malformed or multi-document inputs are omitted.

Git prompt support reads `.git` metadata directly. Normal repositories,
worktree `.git` pointer files, detached HEADs, obvious dirty metadata, and
strong-signal bare repositories are supported. Unclear or unreadable states are
omitted.

## Validation

Focused validation:

```sh
uv run ruff check src tests
uv run pytest -q tests/test_pyshrc_py.py
uv run pytest -q tests/test_shell.py
uv run pytest -q tests/test_system_profile.py
uv run pytest -q tests/test_terminal_style.py
uv run pytest -q tests/test_pty_integration.py
uv run pytest -q tests/test_docs_consistency.py
scripts/check_headers.sh
git diff --check
uv run pysh --version
uv run python -m pysh --version
uv run pysh -c "echo ok"
uv run pysh -c "exit"
uv run pysh -c "quit"
```

Manual Debian 13 checks should include SSH/AWS/Kubernetes environment
combinations and missing-tool paths. FreeBSD 14+ checks should verify
`python3.13 -m pysh --version` and `python3.13 -m pysh -c "echo ok"` on a real
or VM FreeBSD host.
