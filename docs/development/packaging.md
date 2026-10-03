<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/packaging.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Packaging

PySH publishes four artifact families per v0.9.1 release:

1. **PyPI** — wheel and sdist (primary distribution channel for Python users).
2. **Debian `.deb`** — attached to the matching GitHub Release.
3. **Red Hat / Fedora `.rpm`** — attached to the matching GitHub Release.
4. **FreeBSD `.pkg`** — one official reference package built on FreeBSD 14.4
   amd64 with CPython 3.13 and attached to the matching GitHub Release.

A PySH release is incomplete unless all current mandatory artifact families
are built and validated: PyPI wheel + sdist, Debian `.deb`, RPM `.rpm`,
FreeBSD `.pkg`, and `SHA256SUMS`. The release quality gate must fail rather
than skip mandatory artifacts. On Debian it validates an already-produced
FreeBSD `.pkg`; if that artifact is absent, the gate fails with a deterministic
message requiring a native FreeBSD-family build.

The reference `.pkg` retains its real native `pkg` ABI. Its neutral public
filename is not a claim that one archive installs on every FreeBSD ABI.

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

These names are the only subject names any supply-chain layer (SBOM,
provenance, `SHA256SUMS`) may use; see
[`supply-chain.md`](../security/supply-chain.md). SPDX 2.3 JSON SBOMs are
generated for every package artifact (Issue #51 Slice 2) and named by appending
`.spdx.json` to the artifact basename, for example
`pysh-shell_X.Y.Z-1_all.deb.spdx.json`. Keyless GitHub OIDC provenance
attestations (all eleven public release files) and signed SPDX SBOM attestations
(the five packages) are created and verified by the release workflow before the
bundle is handed to the upload job (Issue #51 Slice 3).

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
│   ├── pysh_shell-X.Y.Z-py3-none-any.whl.spdx.json
│   ├── pysh_shell-X.Y.Z.tar.gz.spdx.json
│   ├── pysh-shell_X.Y.Z-1_all.deb.spdx.json
│   ├── pysh-shell-X.Y.Z-1.noarch.rpm.spdx.json
│   ├── pysh-shell-X.Y.Z.pkg.spdx.json
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

### From the GitHub Release reference `.pkg`

```sh
sudo pkg add "./pysh-shell-X.Y.Z.pkg"
pysh --version
```

## FreeBSD validation and package build for v0.9.1

Native FreeBSD validation is mandatory for v0.9.1 release completion. PySH
requires CPython 3.13 or newer without an upper bound. The reference `.pkg`
is built on FreeBSD 14.4 amd64 with CPython 3.13. Every `.pkg` must be built by
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
sh scripts/build_freebsd_pkg.sh
ls -l dist/os/freebsd/pysh-shell-X.Y.Z.pkg
pkg info -F dist/os/freebsd/pysh-shell-X.Y.Z.pkg
pkg query -F dist/os/freebsd/pysh-shell-X.Y.Z.pkg "%q %Fp"
sudo pkg add "./dist/os/freebsd/pysh-shell-X.Y.Z.pkg"
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

FreeBSD `.pkg` packaging is mandatory v0.9.1 release work. The package
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

Before installation, compare `pkg query -F <archive> "%q"` with
`pkg config ABI`. Never bypass a mismatch using `pkg add -f` or
`IGNORE_OSVERSION`. Users on another compatible FreeBSD/GhostBSD ABI can use
the Python installation path or build the same canonical basename locally.
The `PYSH_FREEBSD_PYTHON_VERSION` selector controls one package's manifest,
launcher, and smoke interpreter together; it does not change OS ABI.

### Verify checksums

GitHub Release assets are uploaded from `dist/release-assets/` as flat files:
wheel, sdist, `.deb`, `.rpm`, `.pkg`, their five `.spdx.json` SBOMs, and
`SHA256SUMS`. The release-facing `SHA256SUMS` contains flat filenames only and
covers every published file except `SHA256SUMS` itself (packages and SBOMs); it
is written once, after the complete set exists
(`bash scripts/check_release_artifacts.sh --finalize-release-assets`). After downloading all release
assets into one directory, checksum verification requires no directory
reconstruction:

```bash
gh release download vX.Y.Z
sha256sum -c SHA256SUMS
```

Checksums prove integrity only. Each of the eleven release files also has a keyless
GitHub OIDC provenance attestation, and each package has a signed SPDX SBOM
attestation:

```bash
gh attestation verify pysh-shell_X.Y.Z-1_all.deb \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml

gh attestation verify pysh-shell_X.Y.Z-1_all.deb \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
  --predicate-type https://spdx.dev/Document/v2.3
```

Add `--source-digest <release-source-SHA>` to pin the exact source commit. Checksum
validation, provenance verification and SBOM verification are complementary and none
replaces another; the offline trust-root procedure is in
[`supply-chain.md`](../security/supply-chain.md).

## Install layout for `.deb` / `.rpm`

Both OS packages place files in identical paths:

| Path                                | Purpose                          |
| ----------------------------------- | -------------------------------- |
| `/opt/pysh-shell/lib/pysh/`         | Python package source tree       |
| `/usr/bin/pysh`                     | Wrapper that selects a qualifying CPython and runs `-m pysh` |
| `/usr/share/doc/pysh-shell/copyright` | Debian copyright file (`.deb` only) |

The wrapper sets `PYTHONPATH=/opt/pysh-shell/lib`, prefers a qualifying
`python3`, and otherwise probes versioned `python3.N` commands on `PATH` by
their actual runtime version. It accepts CPython `>=3.13` with no upper bound.
PySH is pure Python (standard library only) so the packages are architecture-independent
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
`/opt/pysh-shell/lib/pysh/`, documentation link checks, a real Debian
install-and-run smoke (`scripts/smoke_debian_package.sh`), a real RPM
install-and-run smoke (`scripts/smoke_rpm_package.sh`), and a clean
temporary virtualenv install smoke test. It does not publish artifacts,
upload files, create tags, create GitHub releases or require credentials.
On non-FreeBSD hosts the gate requires a prebuilt
`dist/os/freebsd/pysh-shell-X.Y.Z.pkg` from the native reference builder (its
own real install-and-run smoke, `scripts/smoke_freebsd_package.sh`, can
only execute on real FreeBSD and runs unconditionally in
`.github/workflows/release-artifacts.yml`'s FreeBSD VM job).

The package-quality model for each OS artifact family is now the same
three tiers: **build** (produces the canonical filename), **static
inspection** (`rpm -qip`/`rpm -qlp`, `dpkg-deb --contents`, `pkg info -F`/
`pkg query -F`), and **real install-and-run** (an actual package-manager
install into a disposable environment, followed by CLI and PTY smoke
against the installed entrypoint). Debian and RPM run their real smoke on
every CI push/PR via Docker; FreeBSD's real smoke can only run on native
FreeBSD, so it runs unconditionally in the release workflow's native FreeBSD
VM jobs instead of ordinary CI.

Build every artifact locally and verify naming + sha256 sums:

```bash
bash scripts/build_release_artifacts.sh
```

Or run each stage individually:

```bash
bash scripts/build_pysh_package.sh    # dist/*.whl + dist/*.tar.gz
bash scripts/build_deb.sh             # dist/os/deb/pysh-shell_*-1_all.deb
bash scripts/build_rpm.sh             # dist/os/rpm/pysh-shell-*-1.noarch.rpm
sh scripts/build_freebsd_pkg.sh       # dist/os/freebsd/pysh-shell-X.Y.Z.pkg (native FreeBSD)
bash scripts/check_release_artifacts.sh   # naming + local and flat (package-only) SHA256SUMS
```

`scripts/build_rpm.sh` requires `rpmbuild` (Debian package: `rpm`).
If it is missing, the script fails fast with a deterministic message.

## CI and release workflows

| Workflow                                  | Purpose                                       |
| ----------------------------------------- | --------------------------------------------- |
| `.github/workflows/ci.yml`                | Tests, lint, build, twine, packaging scripts, real Debian/RPM install-and-run smoke |
| `.github/workflows/publish.yml`           | **Only** path that publishes to PyPI (Trusted Publishing) |
| `.github/workflows/release-artifacts.yml` | Builds/smokes the official FreeBSD 14.4 reference `.pkg` plus optional validation-only ABI evidence, then stages wheel, sdist, `.deb`, `.rpm`, the reference `.pkg`, and flat `SHA256SUMS` |

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
- `scripts/build_freebsd_pkg.sh` — requires native FreeBSD `pkg`, validates
  host/archive ABI equality, and fails on `.pkg` filename or content drift.
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
