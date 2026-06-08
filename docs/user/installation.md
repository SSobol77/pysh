<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/installation.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Installation

PySH is distributed on PyPI as the package **`pysh-shell`**. It installs a
single console command, `pysh`, and can also be run as a module with
`python -m pysh`.

Current release: **PySH 0.8.2**.

## Requirements

- Python **3.13 or newer**.
- A POSIX-like operating system (primary validation target is Debian 13).
- A working `readline` is optional; PySH's raw editor provides native history
  navigation and Ctrl+R reverse search on capable terminals.

PySH installs the explicit `pysh` command. It is not a `/bin/sh` provider and
packages must not replace the operating-system shell used by system scripts or
package-manager hooks.

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

Both commands must print the installed `pysh` version.

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

> The `.deb`, `.rpm`, and `.pkg` packages are GitHub Release artifacts. They
> are **not** yet shipped via the official Debian, Ubuntu, Fedora,
> RHEL/EPEL or FreeBSD package repositories.

## Install from a GitHub Release `.pkg` (FreeBSD 14+)

For PySH version `X.Y.Z`, the canonical FreeBSD artifact is:

```
pysh-shell-X.Y.Z.pkg
```

```sh
sudo pkg install ./pysh-shell-X.Y.Z.pkg
pysh --version
```

The `.pkg` installs the wrapper at `/usr/local/bin/pysh` and the Python
package under `/usr/local/lib/pysh-shell/pysh/`. It must not replace
`/bin/sh`, divert `/bin/sh`, register PySH as a POSIX sh provider, or overwrite
an existing `~/.pyshrc.py`.

The FreeBSD package is built on FreeBSD 14+ with:

```sh
bash scripts/build_freebsd_pkg.sh
```

FreeBSD 14+ validation also includes the Python/wheel smoke path:

```sh
python3.13 -m venv /tmp/pysh-freebsd-smoke
. /tmp/pysh-freebsd-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install pysh-shell==X.Y.Z
pysh --version
python -m pysh --version
pysh -c "echo freebsd-smoke"
pysh -c "exit"
pysh -c "quit"
```

For interactive validation, start `pysh` and verify that the startup banner
renders, the framed prompt falls back cleanly if Unicode is unavailable,
`exit` and `quit` exit on the first attempt, and multiline paste safety remains
enabled.

## Verify GitHub Release artifacts

Each GitHub Release publishes flat assets: wheel, sdist, `.deb`, `.rpm`,
`.pkg`, and `SHA256SUMS`. The checksum file uses flat filenames only, so a normal
download can be verified without recreating the repository's local `dist/os/`
layout:

```bash
gh release download vX.Y.Z
sha256sum -c SHA256SUMS
```

## Upgrading PySH

### Upgrade from PyPI

```bash
python3.13 -m pip install --upgrade pysh-shell
pysh --version
```

### Upgrade from a GitHub Release `.deb`

Download the new `.deb` for the target version from the GitHub Release page,
then install it over the existing package:

```bash
sudo apt install ./pysh-shell_X.Y.Z-1_all.deb
pysh --version
```

`apt install ./<path>` resolves dependencies and upgrades the installed package
in-place.

### Upgrade from a GitHub Release `.rpm`

Download the new `.rpm` for the target version from the GitHub Release page,
then upgrade:

```bash
sudo dnf upgrade ./pysh-shell-X.Y.Z-1.noarch.rpm
pysh --version
```

### Upgrade from a GitHub Release `.pkg`

Download the new `.pkg` for the target version from the GitHub Release page,
then upgrade on FreeBSD 14+:

```sh
sudo pkg install ./pysh-shell-X.Y.Z.pkg
pysh --version
```

### User configuration preservation

Upgrading PySH never overwrites an existing `~/.pyshrc.py`. Your personal
Python-native configuration is preserved across all upgrade paths: PyPI,
`.deb`, `.rpm`, and `.pkg`.

If a future version introduces a new default configuration template, it will be
installed as a template or example file only — it will not be written over an
existing `~/.pyshrc.py`.

The local `dist/os/` tree is an internal build layout used by the release
quality gate. It is not part of the GitHub Release download. See
[Verify GitHub Release artifacts](#verify-github-release-artifacts) for the
flat download workflow.

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
- If readline-mode history search does not work when the raw editor is disabled,
  your interpreter may have been built against `libedit` instead of GNU
  readline. PySH degrades silently in that case; install a build with GNU
  readline if you need Bash-like history search in readline fallback mode.
