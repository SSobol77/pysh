<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/system-profile.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# System profile

PySH 0.3.0 ships a non-mutating Debian/system profile layer. Every helper:

- uses only the Python standard library,
- never calls `sudo`,
- never modifies system state,
- prints deterministic output and returns a deterministic exit code.

## `sys_info`

Print a concise system summary:

```sh
sys_info
```

Fields printed:

- `platform=` — `platform.platform()` value
- `python=` — interpreter version
- `executable=` — interpreter path
- `cwd=` — current working directory
- `user=` — `$USER` or `$LOGNAME`
- `home=` — `$HOME` or `Path.home()`
- `shell=` — `$SHELL`
- `path_entries=` — number of non-empty entries in `$PATH`

Returns 0. No secret values are ever printed.

## `env_audit`

Print a redacted environment audit summary:

```sh
env_audit
```

Output starts with `total=<N>`, prints a curated set of safe variables
(`SHELL`, `TERM`, `LANG`, `PATH`, `HOME`, `USER`, `LOGNAME`, `VIRTUAL_ENV`,
`PYTHONPATH`), and then lists every variable whose name matches any of:

- `KEY`
- `TOKEN`
- `SECRET`
- `PASSWORD`
- `PASS`
- `CREDENTIAL`
- `AUTH`

as `<NAME>=<redacted>`. The actual secret value is never written to stdout
or stderr. Returns 0.

## `path_audit`

Inspect `$PATH`:

```sh
path_audit
```

Each entry is printed as `<status>\t<entry>` where status is one of:

- `ok` — exists and is a directory
- `missing` — does not exist
- `not_dir` — exists but is not a directory
- `duplicate` — same entry appears more than once

Returns 0 when every entry is `ok` with no duplicates. Returns 1 otherwise.

## `which_all <command>`

Print every executable match for `command` along `$PATH`:

```sh
which_all python3
```

Returns 0 when at least one executable match exists, 1 when none, and 2
when the command argument is missing.

## `apt_check`

Debian-oriented upgrade probe. Never calls `sudo`, never modifies state:

```sh
apt_check
```

If `apt` is not on `$PATH`, the command prints `apt_check: apt not found`
to stderr and returns 127. Otherwise it runs `apt list --upgradable` and
returns the apt exit code.

## `apt_search <query>`

Debian-oriented package search:

```sh
apt_search vim
```

If `apt` is not on `$PATH`, returns 127. If the query argument is missing,
returns 2. Otherwise runs `apt search <query>` (no shell, argv list) and
returns the apt exit code.

## No sudo / no mutation policy

These helpers exist to make Debian-friendly automation safe to share. They
do not install, upgrade, remove or reconfigure packages. They do not write
to system files. If you need a mutating operation, run the real `apt`
command yourself in an explicit, audited context.
