<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/packaging.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Packaging

PySH publishes three artifact families per release:

1. **PyPI** — wheel and sdist (primary distribution channel for Python users).
2. **Debian `.deb`** — attached to the matching GitHub Release.
3. **Red Hat / Fedora `.rpm`** — attached to the matching GitHub Release.

> The `.deb` and `.rpm` packages are **GitHub Release artifacts**. They
> are **not** yet published to official Debian, Ubuntu, Fedora or
> RHEL/EPEL repositories.

## Package naming standard

| Channel       | Name                                          |
| ------------- | --------------------------------------------- |
| PyPI distribution | `pysh-shell`                              |
| Debian package    | `pysh-shell`                              |
| RPM package       | `pysh-shell`                              |
| Installed command | `pysh`                                    |
| Python import     | `pysh`                                    |

## Canonical artifact filenames

For version `X.Y.Z` and package release `1`:

| Artifact     | Filename                                              |
| ------------ | ----------------------------------------------------- |
| Wheel        | `pysh_shell-X.Y.Z-py3-none-any.whl`                   |
| Sdist        | `pysh_shell-X.Y.Z.tar.gz` (or backend-emitted hyphen form `pysh-shell-X.Y.Z.tar.gz`) |
| Debian       | `pysh-shell_X.Y.Z-1_all.deb`                          |
| RPM          | `pysh-shell-X.Y.Z-1.noarch.rpm`                       |
| Checksums    | `SHA256SUMS`                                          |

The build scripts and CI **fail** if the produced `.deb` / `.rpm`
filenames drift from the canonical names above.

## Output directories

```
dist/
├── pysh_shell-X.Y.Z-py3-none-any.whl
├── pysh_shell-X.Y.Z.tar.gz
├── SHA256SUMS
└── os/
    ├── deb/
    │   └── pysh-shell_X.Y.Z-1_all.deb
    └── rpm/
        └── pysh-shell-X.Y.Z-1.noarch.rpm
```

## Install examples

### From PyPI

```bash
python3.13 -m pip install --upgrade pip
python3.13 -m pip install pysh-shell
pysh --version
```

### From the GitHub Release `.deb`

```bash
sudo apt install ./pysh-shell-X.Y.Z-1_all.deb
pysh --version
```

`apt install ./<path>` resolves a local `.deb` and installs declared
dependencies (currently just `python3 >= 3.13`).

### From the GitHub Release `.rpm`

```bash
sudo dnf install ./pysh-shell-X.Y.Z-1.noarch.rpm
pysh --version
```

### Verify checksums

```bash
sha256sum -c SHA256SUMS
```

## Install layout for `.deb` / `.rpm`

Both OS packages place files in identical paths:

| Path                                | Purpose                          |
| ----------------------------------- | -------------------------------- |
| `/opt/pysh-shell/lib/pysh/`         | Python package source tree       |
| `/usr/bin/pysh`                     | Wrapper that execs `python3 -m pysh` |
| `/usr/share/doc/pysh-shell/copyright` | Debian copyright file (`.deb` only) |

The wrapper sets `PYTHONPATH=/opt/pysh-shell/lib` and invokes
`/usr/bin/python3 -m pysh`. PySH is pure Python (standard library
only) so the packages are architecture-independent
(`Architecture: all` / `BuildArch: noarch`).

## Local packaging commands

Build every artifact locally and verify naming + sha256 sums:

```bash
bash scripts/build_release_artifacts.sh
```

Or run each stage individually:

```bash
bash scripts/build_pysh_package.sh    # dist/*.whl + dist/*.tar.gz
bash scripts/build_deb.sh             # dist/os/deb/pysh-shell_*-1_all.deb
bash scripts/build_rpm.sh             # dist/os/rpm/pysh-shell-*-1.noarch.rpm
bash scripts/check_release_artifacts.sh   # naming + SHA256SUMS
```

`scripts/build_rpm.sh` requires `rpmbuild` (Debian package: `rpm`).
If it is missing, the script fails fast with a deterministic message.

## CI and release workflows

| Workflow                                  | Purpose                                       |
| ----------------------------------------- | --------------------------------------------- |
| `.github/workflows/ci.yml`                | Tests, lint, build, twine, packaging scripts  |
| `.github/workflows/publish.yml`           | **Only** path that publishes to PyPI (Trusted Publishing) |
| `.github/workflows/release-artifacts.yml` | Builds `.deb` + `.rpm` + `SHA256SUMS` and attaches them to the GitHub Release |

There is exactly one PyPI publish path; the OS-packages workflow does
not publish to PyPI.

## Naming contract enforcement

The canonical naming contract is documented in:

- [`AGENTS.md`](../../AGENTS.md)
- [`CLAUDE.md`](../../CLAUDE.md)
- [`CODEX.md`](../../CODEX.md)
- [`CURSOR.md`](../../CURSOR.md)
- [`.codex/rules/packaging-naming.md`](../../.codex/rules/packaging-naming.md)
- [`.claude/rules/packaging-naming.md`](../../.claude/rules/packaging-naming.md)
- [`.cursor/rules/packaging-naming.mdc`](../../.cursor/rules/packaging-naming.mdc)

Any future agent that produces release artifacts must follow that
contract. The contract is enforced by:

- `scripts/build_deb.sh` — fails on `.deb` filename drift.
- `scripts/build_rpm.sh` — fails on `.rpm` filename drift.
- `scripts/check_release_artifacts.sh` — fails when any expected
  artifact is missing or any sibling artifact filename drifts.
