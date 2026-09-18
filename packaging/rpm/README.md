<!--
File: packaging/rpm/README.md
SPDX-License-Identifier: GPL-2.0-only
Copyright (C) 2026 Siergej Sobolewski
-->

# RPM packaging for PySH

This directory contains the RPM spec used to assemble the official
`pysh-shell` `.rpm` artifact released alongside each PySH version on
GitHub Releases.

## Canonical artifact name

For PySH version `X.Y.Z` and package release `1`, the resulting file is:

```
dist/os/rpm/pysh-shell-X.Y.Z-1.noarch.rpm
```

This filename is mandatory. The build script in
[`scripts/build_rpm.sh`](../../scripts/build_rpm.sh) fails if the
produced file does not match exactly. The agent rules in
[`AGENTS.md`](../../AGENTS.md),
[`CLAUDE.md`](../../CLAUDE.md),
[`CODEX.md`](../../CODEX.md) and
[`CURSOR.md`](../../CURSOR.md) enforce the same contract for future
automation.

## Files

| File                    | Purpose                                          |
| ----------------------- | ------------------------------------------------ |
| `pysh-shell.spec`       | RPM spec describing the noarch pure-Python build |

## Install layout

The `.rpm` installs PySH under an application prefix matching the
Debian package:

```
/opt/pysh-shell/lib/pysh/    # Python package source tree
/usr/bin/pysh                # POSIX wrapper invoking python3 -m pysh
```

`BuildArch: noarch` because PySH ships no compiled artifacts.

## Build

```bash
bash scripts/build_rpm.sh
```

The script:

- derives `X.Y.Z` from `pyproject.toml`,
- creates a temporary `rpmbuild` tree,
- packs an `pysh-shell-X.Y.Z.tar.gz` source tarball,
- runs `rpmbuild -bb` (binary RPM only) with `pysh_version=X.Y.Z`,
- moves the produced RPM to `dist/os/rpm/`,
- verifies the produced filename matches
  `dist/os/rpm/pysh-shell-X.Y.Z-1.noarch.rpm`,
- runs `rpm -qip` and `rpm -qlp` for validation.

`rpmbuild` is not always installed on Debian dev hosts. The script
fails fast with a deterministic message when `rpmbuild` is missing.

## Install (end-user)

```bash
sudo dnf install ./pysh-shell-X.Y.Z-1.noarch.rpm
```

## Notes for packagers

- `BuildArch` must remain `noarch`. Do not switch to `x86_64` etc.
  unless PySH starts shipping compiled artifacts.
- `Requires: python3 >= 3.13` matches the Debian dependency.
- The `.rpm` is a GitHub Release artifact; it is **not** uploaded to
  Fedora/RHEL/EPEL repositories yet.
