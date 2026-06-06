<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/packaging.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Packaging

PySH publishes four artifact families per v0.8.0 release:

1. **PyPI** — wheel and sdist (primary distribution channel for Python users).
2. **Debian `.deb`** — attached to the matching GitHub Release.
3. **Red Hat / Fedora `.rpm`** — attached to the matching GitHub Release.
4. **FreeBSD `.pkg`** — built by a FreeBSD 14+ builder and attached to the
   matching GitHub Release.

A PySH release is incomplete unless all current mandatory artifact families
are built and validated: PyPI wheel + sdist, Debian `.deb`, RPM `.rpm`,
FreeBSD `.pkg`, and `SHA256SUMS`. The release quality gate must fail rather
than skip mandatory artifacts. On Debian it validates an already-produced
FreeBSD `.pkg`; if that artifact is absent, the gate fails with a deterministic
message requiring a FreeBSD 14+ build.

> The `.deb`, `.rpm`, and `.pkg` packages are **GitHub Release artifacts**.
> They are **not** yet published to official Debian, Ubuntu, Fedora,
> RHEL/EPEL or FreeBSD package repositories.

## Package naming standard

| Channel       | Name                                          |
| ------------- | --------------------------------------------- |
| PyPI distribution | `pysh-shell`                              |
| Debian package    | `pysh-shell`                              |
| RPM package       | `pysh-shell`                              |
| FreeBSD package   | `pysh-shell`                              |
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
| FreeBSD      | `pysh-shell-X.Y.Z.pkg`                                 |
| Checksums    | `SHA256SUMS`                                          |

The build scripts and CI **fail** if produced `.deb`, `.rpm`, or `.pkg`
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
│   ├── pysh-shell-X.Y.Z.pkg
│   └── SHA256SUMS
└── os/
    ├── deb/
    │   └── pysh-shell_X.Y.Z-1_all.deb
    ├── freebsd/
    │   └── pysh-shell-X.Y.Z.pkg
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

### From the GitHub Release `.pkg` on FreeBSD 14+

```sh
sudo pkg install ./pysh-shell-X.Y.Z.pkg
pysh --version
```

## FreeBSD validation and package build for v0.8.0

FreeBSD 14+ validation is mandatory for v0.8.0 release completion. PySH
requires Python 3.13 or newer. The FreeBSD `.pkg` must be built by
FreeBSD-native package tooling; Docker on Debian is not a native FreeBSD
package builder and must not be used to fake `.pkg` bytes.

Recommended FreeBSD builder commands:

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
python -m pip install pytest ruff
python -m pytest -q
python -m ruff check src tests
bash scripts/build_freebsd_pkg.sh
ls -l dist/os/freebsd/pysh-shell-X.Y.Z.pkg
pkg info -F dist/os/freebsd/pysh-shell-X.Y.Z.pkg
pkg query -F dist/os/freebsd/pysh-shell-X.Y.Z.pkg "%Fp"
sudo pkg install ./dist/os/freebsd/pysh-shell-X.Y.Z.pkg
pysh --version
python -m pysh --version
pysh -c "echo freebsd-smoke"
pysh -c "exit"
pysh -c "quit"
```

Interactive smoke validation on FreeBSD must verify:

- startup banner renders;
- framed prompt renders, or falls back cleanly when Unicode rendering is not
  available in the terminal;
- `exit` exits on the first attempt;
- `quit` exits on the first attempt;
- multiline paste safety remains enabled and staged paste does not execute
  without explicit confirmation.

Portability assumptions for this validation:

- PySH is Python-first and should not require Linux-only shell behavior.
- PySH must not replace `/bin/sh`, divert `/bin/sh`, or claim POSIX sh
  compatibility.
- OS packages must install only the explicit `pysh` command and must not
  replace the system shell used by scripts or package-manager hooks.

Known OS-specific areas to watch on FreeBSD:

- terminal and PTY behavior;
- `platform.release()` and kernel display in the prompt/banner;
- CPU model fallback where `/proc/cpuinfo` does not exist;
- package manager semantics;
- filesystem layout and installation prefixes;
- executable wrapper paths.

## FreeBSD `.pkg` package contract

FreeBSD `.pkg` packaging is current mandatory v0.8.0 release work. The package
filename is `pysh-shell-X.Y.Z.pkg`; the local artifact path is
`dist/os/freebsd/pysh-shell-X.Y.Z.pkg`; and the flat GitHub Release asset path
is `dist/release-assets/pysh-shell-X.Y.Z.pkg`.

The `.pkg` must install:

- `/usr/local/bin/pysh`;
- `/usr/local/lib/pysh-shell/pysh/`;
- documentation and license files under `/usr/local/share/doc/pysh-shell/`;
- no `/bin/sh` replacement;
- no system shell diversion;
- no overwrite of an existing `~/.pyshrc.py`.

Any default configuration template must be installed only as an example or
template, never over user configuration. The `.pkg` is included in local and
flat `SHA256SUMS` coverage and is staged into `dist/release-assets/` with the
other mandatory artifacts.

### Verify checksums

GitHub Release assets are uploaded from `dist/release-assets/` as flat files:
wheel, sdist, `.deb`, `.rpm`, `.pkg`, and `SHA256SUMS`. The release-facing
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
wheel/sdist hygiene checks, `.deb` / `.rpm` / `.pkg` filename checks,
checksum checks, OS package content checks for `/usr/bin/pysh` and
`/opt/pysh-shell/lib/pysh/`, documentation link checks, and a clean temporary
virtualenv install smoke test. It does not publish artifacts, upload files,
create tags, create GitHub releases or require credentials. On non-FreeBSD
hosts the gate requires a prebuilt `dist/os/freebsd/pysh-shell-X.Y.Z.pkg`
from the FreeBSD 14+ builder.

Build every artifact locally and verify naming + sha256 sums:

```bash
bash scripts/build_release_artifacts.sh
```

Or run each stage individually:

```bash
bash scripts/build_pysh_package.sh    # dist/*.whl + dist/*.tar.gz
bash scripts/build_deb.sh             # dist/os/deb/pysh-shell_*-1_all.deb
bash scripts/build_rpm.sh             # dist/os/rpm/pysh-shell-*-1.noarch.rpm
bash scripts/build_freebsd_pkg.sh     # dist/os/freebsd/pysh-shell-*.pkg (FreeBSD 14+ only)
bash scripts/check_release_artifacts.sh   # naming + local and flat SHA256SUMS
```

`scripts/build_rpm.sh` requires `rpmbuild` (Debian package: `rpm`).
If it is missing, the script fails fast with a deterministic message.

## CI and release workflows

| Workflow                                  | Purpose                                       |
| ----------------------------------------- | --------------------------------------------- |
| `.github/workflows/ci.yml`                | Tests, lint, build, twine, packaging scripts  |
| `.github/workflows/publish.yml`           | **Only** path that publishes to PyPI (Trusted Publishing) |
| `.github/workflows/freebsd-pkg.yml`       | Builds FreeBSD `.pkg` on a FreeBSD 14+ self-hosted runner and uploads it as a workflow artifact |
| `.github/workflows/release-artifacts.yml` | Builds/stages wheel, sdist, `.deb`, `.rpm`, `.pkg`, and flat `SHA256SUMS`, then attaches `dist/release-assets/*` to the GitHub Release |

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
- `scripts/build_freebsd_pkg.sh` — fails outside FreeBSD 14+ and fails on
  `.pkg` filename or content drift.
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
