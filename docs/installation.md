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

Both commands must print `pysh 0.3.0` (or the current released version).

## Install from a GitHub Release `.deb` (Debian / Ubuntu)

For PySH version `X.Y.Z`, the canonical Debian artifact is:

```
pysh-shell_X.Y.Z-1_all.deb
```

```bash
sudo apt install ./pysh-shell_X.Y.Z-1_all.deb
pysh --version
```

The `.deb` installs the Python package under `/opt/pysh-shell/lib/pysh`
and a wrapper at `/usr/bin/pysh`. Depends on `python3 (>= 3.13)`.

## Install from a GitHub Release `.rpm` (Fedora / RHEL)

For PySH version `X.Y.Z`, the canonical RPM artifact is:

```
pysh-shell-X.Y.Z-1.noarch.rpm
```

```bash
sudo dnf install ./pysh-shell-X.Y.Z-1.noarch.rpm
pysh --version
```

The `.rpm` shares the install layout with the Debian package and
requires `python3 >= 3.13`.

> The `.deb` and `.rpm` packages are GitHub Release artifacts. They
> are **not** yet shipped via the official Debian, Ubuntu, Fedora or
> RHEL/EPEL repositories.

## Verify GitHub Release artifacts

Each GitHub Release also publishes a `SHA256SUMS` file covering the
wheel, sdist, `.deb` and `.rpm`. Download all artifacts to the same
directory and run:

```bash
sha256sum -c SHA256SUMS
```

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
