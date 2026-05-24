<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
-->

# Debian packaging for PySH

This directory contains the metadata used to assemble the official
`pysh-shell` `.deb` artifact released alongside each PySH version on
GitHub Releases.

## Canonical artifact name

For PySH version `X.Y.Z` and package release `1`, the resulting file is:

```
dist/os/deb/pysh-shell_X.Y.Z-1_all.deb
```

This filename is mandatory. The build script in
[`scripts/build_deb.sh`](../../scripts/build_deb.sh) fails if the
produced file does not match exactly. The agent rules in
[`AGENTS.md`](../../AGENTS.md),
[`CLAUDE.md`](../../CLAUDE.md),
[`CODEX.md`](../../CODEX.md) and
[`CURSOR.md`](../../CURSOR.md) enforce the same contract for future
automation.

## Files

| File         | Purpose                                                      |
| ------------ | ------------------------------------------------------------ |
| `control`    | Debian control metadata; `@VERSION@` is substituted at build |
| `postinst`   | `dpkg` post-install hook; minimal, no network, no sudo       |
| `prerm`      | `dpkg` pre-remove hook; minimal, no destructive cleanup      |
| `copyright`  | Debian copyright file (GPL-3.0-or-later)                     |

## Install layout

The `.deb` installs PySH under an application prefix:

```
/opt/pysh-shell/lib/pysh/    # Python package source tree
/usr/bin/pysh                # POSIX wrapper invoking python3 -m pysh
```

The wrapper sets `PYTHONPATH=/opt/pysh-shell/lib` and execs
`/usr/bin/python3 -m pysh "$@"`. PySH is pure Python (standard
library only), so no compiled artifacts are shipped and the package
is architecture-independent (`Architecture: all`).

## Build

```bash
bash scripts/build_deb.sh
```

The script:

- derives `X.Y.Z` from `pyproject.toml`,
- stages files under a temporary directory,
- substitutes `@VERSION@` in `control`,
- invokes `dpkg-deb --build`,
- verifies the produced filename matches
  `dist/os/deb/pysh-shell_X.Y.Z-1_all.deb`,
- runs `dpkg-deb --info` and `dpkg-deb --contents` for validation.

## Install (end-user)

```bash
sudo apt install ./pysh-shell_X.Y.Z-1_all.deb
```

`apt install ./<path>` resolves the local file as a package source and
pulls in any declared dependencies (currently just `python3 >= 3.13`).

## Notes for packagers

- `Architecture` is `all`. Do not flip to `amd64`/`arm64` unless PySH
  ships compiled artifacts in the future.
- `Depends` is intentionally limited to `python3 (>= 3.13)`.
- Maintainer scripts must keep `set -eu` and remain free of network
  access, `sudo` calls and destructive cleanup.
- The `.deb` is a GitHub Release artifact; it is **not** uploaded to
  the official Debian archive yet.
