<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Installation

PySH is distributed on PyPI as the package **`pysh-shell`**. It installs a
single console command, `pysh`, and can also be run as a module with
`python -m pysh`.

## Requirements

- Python **3.13 or newer**.
- A POSIX-like operating system (primary validation target is Debian 13).
- A working `readline` (optional, but required for history and Ctrl+R).

## Install from PyPI

```bash
python3.13 -m pip install --upgrade pip
python3.13 -m pip install pysh-shell
```

Verify the installation:

```bash
pysh --version
python -m pysh --version
```

Both commands must print `pysh 0.2.0`.

## Development install (editable)

Use a virtual environment so PySH does not interfere with system Python:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `[dev]` extra pulls in `pytest`, `ruff`, `build`, and `twine`.

## Uninstall

```bash
python3.13 -m pip uninstall pysh-shell
```

## Troubleshooting

- If `pysh: command not found` after install, ensure the Python user-bin
  directory (e.g. `~/.local/bin`) is on your `PATH`.
- If readline-based features such as **Ctrl+R reverse search** do not work,
  your interpreter may have been built against `libedit` instead of GNU
  readline. PySH degrades silently in that case; install a build with GNU
  readline if you need Bash-like history search.
