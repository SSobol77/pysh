<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/development.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Development

This page documents how to work on PySH locally: setting up a development
environment, running the quality gates, and the repository layout.

## Setup

```bash
# Recommended: uv-based dev workflow (uses uv.lock for reproducible deps)
uv sync
uv run pytest -q
uv run ruff check src tests

# Classic venv alternative
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
bash scripts/check_headers.sh
uv run pytest -q
uv run ruff check src tests
python -m build
twine check dist/*
```

To build the full release artifact set locally (wheel, sdist, `.deb`,
`.rpm`, `SHA256SUMS`), use:

```bash
bash scripts/build_release_artifacts.sh
```

See [`packaging.md`](packaging.md) for the canonical artifact naming
contract and per-script details. `scripts/build_rpm.sh` needs the
`rpm` package installed locally (`sudo apt-get install -y rpm` on
Debian); if it is missing, the script fails fast with a deterministic
message.

`bash scripts/check_headers.sh` should print no output. `uv run pytest -q`
should report **all tests passing**. `uv run ruff check` should report
**All checks passed!**. `python -m build` should produce
`dist/pysh_shell-0.5.0.tar.gz` and `dist/pysh_shell-0.5.0-py3-none-any.whl`.
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
│   ├── README.md               # Canonical documentation index
│   ├── img/                    # Logo and screenshots
│   ├── user/                   # End-user guides
│   ├── shell/                  # Shell behavior documentation
│   ├── python/                 # Python layer documentation
│   ├── migration/              # Transition and compatibility guides
│   ├── architecture/           # Architecture decisions and roadmap
│   └── development/            # Contributor and release guides (this file)
├── src/
│   └── pysh/
│       ├── __init__.py         # Package metadata: __version__, LICENSE_NAME
│       ├── __main__.py         # python -m pysh entry point
│       ├── cli.py              # Console script entry point (argparse + --version)
│       ├── shell.py            # Compatibility shim → pysh.core.shell (Issue #19)
│       ├── script_runner.py    # Script transition runner (shebang dispatch)
│       ├── core/               # PyShell: REPL loop, command dispatch, builtins
│       ├── parsing/            # Quote-aware parser, redirection
│       ├── editor/             # Completer, history, ANSI helpers
│       │   └── lineedit/       # Raw-mode line editing engine
│       ├── prompt/             # Prompt rendering, color helpers, sys-profile
│       ├── python_layer/       # Python runtime, #py mode, syntax highlighting
│       ├── config/             # RC loader, plugin loader, ConfigAPI
│       ├── compat/             # Zsh bridge, alias importer, MC detection
│       ├── services/           # svc client, PyInit metadata parser
│       ├── security/           # SecureRunner PTY bridge
│       └── diagnostics/        # plan builtin, sys_info helpers
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
    ├── test_profile_importer.py
    ├── test_script_runner.py
    ├── test_python_runtime.py
    ├── test_system_profile.py
    ├── test_command_plan.py
    └── test_cli.py
```

## Coding conventions

- Python **3.13+** only.
- Code is formatted to **100-column** lines (see `[tool.ruff]` in
  `pyproject.toml`).
- New behavior must come with tests under `tests/`.
- New builtins, parser behavior, configuration behavior, migration helpers
  and limitations must be documented in the same change. See
  [`docs/architecture/documentation-policy.md`](../architecture/documentation-policy.md).
- Builtin and completion lists must stay aligned with the implementation.
- Public modules carry an SPDX `GPL-3.0-or-later` header.
- All documentation is written in **English**.

## CI expectations

The CI workflow installs zsh, installs the package in editable mode, runs
`pytest -q`, runs `ruff check src tests`, builds sdist/wheel artifacts,
validates them with `twine check dist/*`, and smoke-tests both `pysh
--version` and `python -m pysh --version`.

## Useful one-liners

```bash
# Run a single test file:
pytest -q tests/test_substitution.py

# Run a single test:
pytest -q tests/test_shell.py::test_cd_changes_directory

# Build and inspect the wheel contents:
python -m build
unzip -l dist/pysh_shell-0.5.0-py3-none-any.whl
```
