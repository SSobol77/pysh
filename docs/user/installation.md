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

<!-- pysh-install:version -->Current release: **PySH 0.9.1**.<!-- /pysh-install:version -->

## Requirements

- CPython **3.13.0 or newer**, with no upper minor-version bound.
- A supported Unix family: Debian-family Linux, RPM-family Linux, or the
  FreeBSD family (including GhostBSD), with required Unix/POSIX facilities.
- A working `readline` is optional; PySH's raw editor provides native history
  navigation and Ctrl+R reverse search on capable terminals.

Debian 13, Fedora 43, and FreeBSD 14.4 are reference test environments, not
installation allowlists or minimum operating-system releases.

PySH installs the explicit `pysh` command. It is not a `/bin/sh` provider and
packages must not replace the operating-system shell used by system scripts or
package-manager hooks.

## Install from PyPI

<!-- pysh-install:pypi -->
```bash
python3.13 -m pip install --upgrade pip
python3.13 -m pip install pysh-shell
```
<!-- /pysh-install:pypi -->

Verify the installation:

<!-- pysh-install:pypi-verify -->
```bash
pysh --version
python -m pysh --version
```
<!-- /pysh-install:pypi-verify -->

Both commands must print the installed `pysh` version.

## Install from a GitHub Release `.deb` (Debian family)

For PySH version `X.Y.Z`, the canonical Debian artifact is:

<!-- pysh-install:deb-name -->
```
pysh-shell_X.Y.Z-1_all.deb
```
<!-- /pysh-install:deb-name -->

<!-- pysh-install:deb -->
```bash
sudo apt install ./pysh-shell_X.Y.Z-1_all.deb
pysh --version
```
<!-- /pysh-install:deb -->

The `.deb` installs the Python package under `/opt/pysh-shell/lib/pysh`
and a wrapper at `/usr/bin/pysh`. It depends on `python3 (>= 3.13)` and is
intended for compatible Debian, Ubuntu, Kali Linux, Linux Mint, Pop!_OS, and
other Debian/Ubuntu-derived systems regardless of release number. The wrapper
validates actual interpreter versions and can select a compatible versioned
`python3.N` from `PATH` if the generic `python3` is too old.

## Install from a GitHub Release `.rpm` (RPM family)

For PySH version `X.Y.Z`, the canonical RPM artifact is:

<!-- pysh-install:rpm-name -->
```
pysh-shell-X.Y.Z-1.noarch.rpm
```
<!-- /pysh-install:rpm-name -->

<!-- pysh-install:rpm -->
```bash
sudo dnf install ./pysh-shell-X.Y.Z-1.noarch.rpm
pysh --version
```
<!-- /pysh-install:rpm -->

The `.rpm` shares the install layout with the Debian package and
requires `python3 >= 3.13`. Supported-family examples include Fedora, RHEL,
Rocky Linux, AlmaLinux, and CentOS Stream. Fedora 43 is a reference smoke
environment, not a runtime allowlist.

> The `.deb`, `.rpm`, and `.pkg` packages are GitHub Release artifacts. They
> are **not** yet shipped via the official Debian, Ubuntu, Fedora,
> RHEL/EPEL or FreeBSD package repositories.

## Install the reference `.pkg` (FreeBSD / GhostBSD)

For PySH version `X.Y.Z`, the canonical FreeBSD artifact is:

<!-- pysh-install:freebsd-name -->
```
pysh-shell-X.Y.Z.pkg
```
<!-- /pysh-install:freebsd-name -->

<!-- pysh-install:freebsd -->
```sh
sudo pkg add "./pysh-shell-X.Y.Z.pkg"
pysh --version
```
<!-- /pysh-install:freebsd -->

`pysh-shell-X.Y.Z.pkg` is the official reference prebuilt package, produced on
FreeBSD 14.4 amd64 with CPython 3.13. Its native `pkg` ABI may restrict where
that particular archive can be installed. This does not define PySH runtime
support and must not be bypassed with `pkg add -f` or `IGNORE_OSVERSION`.
On another compatible FreeBSD or GhostBSD ABI, use Python packaging or build
the canonical `.pkg` on that host.

The `.pkg` installs the wrapper at `/usr/local/bin/pysh` and the Python
package under `/usr/local/lib/pysh-shell/pysh/`. It must not replace
`/bin/sh`, divert `/bin/sh`, register PySH as a POSIX sh provider, or overwrite
an existing `~/.pyshrc.py`.

The FreeBSD package is built in a native FreeBSD-family `pkg` environment:

<!-- pysh-install:freebsd-build -->
```sh
sh scripts/build_freebsd_pkg.sh
```
<!-- /pysh-install:freebsd-build -->

The default target is CPython 3.13. A package targeting another compatible
minor must use that same target in its manifest, wrapper, and smoke test:

```sh
PYSH_FREEBSD_PYTHON_VERSION=3.14 sh scripts/build_freebsd_pkg.sh
```

FreeBSD-family validation also includes the Python/wheel smoke path:

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
then upgrade on a host with a matching native package ABI:

```sh
sudo pkg add "./pysh-shell-X.Y.Z.pkg"
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

<!-- pysh-install:dev -->
```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```
<!-- /pysh-install:dev -->

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
