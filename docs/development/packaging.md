<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/packaging.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Packaging

PySH publishes three artifact families per release:

1. **PyPI** — wheel and sdist (primary distribution channel for Python users).
2. **Debian `.deb`** — attached to the matching GitHub Release.
3. **Red Hat / Fedora `.rpm`** — attached to the matching GitHub Release.

A PySH release is incomplete unless all current mandatory artifact families
are built and validated: PyPI wheel + sdist, Debian `.deb`, and RPM `.rpm`.
The release quality gate must fail rather than skip `.deb` or `.rpm`
validation when local packaging tools are missing. FreeBSD `.pkg` support is
deferred to Issue #18 and is not part of the current mandatory release gate.

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

The local build layout keeps PyPI artifacts at `dist/` and OS packages under
`dist/os/`. GitHub Release upload uses a separate flat staging directory so
checksums work after a normal `gh release download`.

```
dist/
├── pysh_shell-X.Y.Z-py3-none-any.whl
├── pysh_shell-X.Y.Z.tar.gz
├── SHA256SUMS
├── release-assets/
│   ├── pysh_shell-X.Y.Z-py3-none-any.whl
│   ├── pysh_shell-X.Y.Z.tar.gz
│   ├── pysh-shell_X.Y.Z-1_all.deb
│   ├── pysh-shell-X.Y.Z-1.noarch.rpm
│   └── SHA256SUMS
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
sudo apt install ./pysh-shell_X.Y.Z-1_all.deb
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

GitHub Release assets are uploaded from `dist/release-assets/` as flat files:
wheel, sdist, `.deb`, `.rpm`, and `SHA256SUMS`. The release-facing
`SHA256SUMS` contains flat filenames only. After downloading all release
assets into one directory, checksum verification requires no directory
reconstruction:

```bash
gh release download vX.Y.Z
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

Run the release quality gate before final release validation:

```bash
scripts/check_release_quality.sh
```

The gate runs linting, tests, header checks, whitespace checks, mandatory
release artifact builds, `twine check`, package metadata inspection,
wheel/sdist hygiene checks, `.deb` / `.rpm` filename checks, checksum checks,
OS package content checks for `/usr/bin/pysh` and
`/opt/pysh-shell/lib/pysh/`, documentation link checks, and a clean temporary
virtualenv install smoke test. It does not publish artifacts, upload files,
create tags, create GitHub releases or require credentials. FreeBSD `.pkg`
validation is intentionally performed after this gate in Issue #18, against
the final packaging/release state.

Build every artifact locally and verify naming + sha256 sums:

```bash
bash scripts/build_release_artifacts.sh
```

Or run each stage individually:

```bash
bash scripts/build_pysh_package.sh    # dist/*.whl + dist/*.tar.gz
bash scripts/build_deb.sh             # dist/os/deb/pysh-shell_*-1_all.deb
bash scripts/build_rpm.sh             # dist/os/rpm/pysh-shell-*-1.noarch.rpm
bash scripts/check_release_artifacts.sh   # naming + local and flat SHA256SUMS
```

`scripts/build_rpm.sh` requires `rpmbuild` (Debian package: `rpm`).
If it is missing, the script fails fast with a deterministic message.

## CI and release workflows

| Workflow                                  | Purpose                                       |
| ----------------------------------------- | --------------------------------------------- |
| `.github/workflows/ci.yml`                | Tests, lint, build, twine, packaging scripts  |
| `.github/workflows/publish.yml`           | **Only** path that publishes to PyPI (Trusted Publishing) |
| `.github/workflows/release-artifacts.yml` | Builds wheel, sdist, `.deb`, `.rpm`, and flat `SHA256SUMS`, then attaches `dist/release-assets/*` to the GitHub Release |

There is exactly one PyPI publish path; the OS-packages workflow does
not publish to PyPI.

## Naming contract enforcement

The public canonical naming contract is the table in this document. Private
agent instruction files may repeat the same contract for local automation, but
public packaging documentation must not depend on ignored or untracked agent
files being present in a source distribution or release archive.

Any future automation that produces release artifacts must follow this
contract. The contract is enforced by:

- `scripts/build_deb.sh` — fails on `.deb` filename drift.
- `scripts/build_rpm.sh` — fails on `.rpm` filename drift.
- `scripts/check_release_artifacts.sh` — fails when any expected
  artifact is missing or any sibling artifact filename drifts, and stages flat
  GitHub Release assets in `dist/release-assets/`.
- `scripts/check_release_quality.sh` — verifies mandatory release artifacts,
  metadata, artifact hygiene, documentation consistency and install smoke
  behavior before release.

## System shell packaging policy

PySH packages install the explicit `pysh` command only. Packaging must not
replace `/bin/sh`, divert `/bin/sh`, register PySH as a POSIX sh provider,
rewrite system scripts to PySH or configure package-manager hooks to run under
PySH. System scripts must continue to use the distribution's real system
shell. See
[system-shell-integration-policy.md](../compatibility/system-shell-integration-policy.md).
