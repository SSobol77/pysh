<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Development

This page documents how to work on PySH locally: setting up a development
environment, running the quality gates, and the repository layout.

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `[dev]` extra installs:

- `pytest` — test runner
- `ruff`   — linter / formatter
- `build`  — wheel + sdist builder
- `twine`  — package metadata validator

## Quality gates

Run all of these before opening a pull request:

```bash
pytest -q
ruff check src tests
python -m build
twine check dist/*
```

`pytest -q` should report **all tests passing**. `ruff check` should report
**All checks passed!**. `python -m build` should produce
`dist/pysh_shell-0.2.0.tar.gz` and `dist/pysh_shell-0.2.0-py3-none-any.whl`.
`twine check` should report `PASSED` for both artifacts.

## Smoke tests

```bash
pysh --version
python -m pysh --version
pysh -c 'echo "hello, pysh"'
```

## Repository layout

```
pysh/
├── README.md
├── LICENSE
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── publish.yml         # PyPI Trusted Publishing workflow
├── docs/
│   ├── img/                    # Logo and screenshots
│   ├── installation.md
│   ├── usage.md
│   ├── configuration.md
│   ├── zsh-compatibility.md
│   ├── python-runtime.md
│   ├── development.md
│   └── release.md
├── src/
│   └── pysh/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py              # Console entry point (argparse + --version)
│       ├── shell.py            # Main interactive shell
│       ├── parser.py           # Quote-aware parser + command substitution
│       ├── redirection.py      # Redirection parser
│       ├── rc.py               # rc loader + mini-interpreter
│       ├── plugins.py          # ~/.pyshrc.d/*.pysh loader
│       ├── history.py          # Persistent history + Ctrl+R wiring
│       ├── highlighting.py     # ANSI color helpers and classifier
│       ├── completion.py       # Tab completion
│       ├── service.py          # svc builtin client (PID-file based)
│       ├── pyinit.py           # PyInit service metadata parser
│       ├── zsh_bridge.py       # Optional zsh -lc execution bridge
│       ├── zsh_aliases.py      # Static zsh alias importer
│       └── python_runtime.py   # Persistent Python runtime for py builtin
└── tests/
    ├── test_parser.py
    ├── test_redirection.py
    ├── test_rc.py
    ├── test_rc_interpreter.py
    ├── test_shell.py
    ├── test_substitution.py
    ├── test_plugins.py
    ├── test_history.py
    ├── test_highlighting.py
    ├── test_completion.py
    ├── test_dirstack.py
    ├── test_unalias.py
    ├── test_service.py
    ├── test_pyinit.py
    ├── test_zsh_bridge.py
    ├── test_zsh_transition.py
    ├── test_python_runtime.py
    └── test_cli.py
```

## Coding conventions

- Python **3.13+** only.
- Code is formatted to **100-column** lines (see `[tool.ruff]` in
  `pyproject.toml`).
- New behavior must come with tests under `tests/`.
- Public modules carry an SPDX `GPL-3.0-or-later` header.
- All documentation is written in **English**.

## Useful one-liners

```bash
# Run a single test file:
pytest -q tests/test_substitution.py

# Run a single test:
pytest -q tests/test_shell.py::test_cd_changes_directory

# Build and inspect the wheel contents:
python -m build
unzip -l dist/pysh_shell-0.2.0-py3-none-any.whl
```
