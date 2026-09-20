<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/release.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Release Process (`vX.Y.Z`)

> Each v0.9.0 release ships **four** artifact families: PyPI (wheel + sdist),
> Debian `.deb`, Red Hat/Fedora `.rpm`, and FreeBSD `.pkg`. See
> [`packaging.md`](packaging.md) for the canonical naming contract and
> [`installation.md`](../user/installation.md) for end-user install commands.

A release is incomplete unless all current mandatory artifact families are
built and validated: PyPI wheel + sdist, Debian `.deb`, RPM `.rpm`, FreeBSD
`.pkg`, and `SHA256SUMS`. The local release gate must fail if mandatory
artifacts are missing. On non-FreeBSD hosts it validates an already-produced
`dist/os/freebsd/pysh-shell-X.Y.Z.pkg` from a FreeBSD 14+ builder and fails
clearly if that artifact is absent.

PySH is published to PyPI as **`pysh-shell`** through GitHub Actions and
**PyPI Trusted Publishing**. The workflow lives at
[`.github/workflows/publish.yml`](../../.github/workflows/publish.yml) and
uses `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` under
the `pypi` GitHub environment.

> **Do not publish from a developer machine.**
> All publishes happen through GitHub Actions; the maintainer's only
> manual step is creating the git tag after local checks pass.

Prepare curated GitHub Release notes from
[release-notes-template.md](release-notes-template.md). Public user-path
acceptance follows [manual-validation.md](../user/manual-validation.md).
Public Python, CLI, configuration, and deprecation compatibility must be
reviewed against the normative
[API stability policy](api-stability.md) before assigning the release version.

## Pre-release checklist

1. Make sure `main` is green and clean:
   ```bash
   git status --short
   git pull --ff-only origin main
   ```
2. Bump the version everywhere it appears:
   - [`pyproject.toml`](../../pyproject.toml) → `version = "X.Y.Z"`
   - [`src/pysh/__init__.py`](../../src/pysh/__init__.py) → `__version__ = "X.Y.Z"`
   - Any user-facing version strings in [`README.md`](../../README.md).
   - Confirm the selected MAJOR/MINOR/PATCH transition matches
     [`api-stability.md`](api-stability.md), and record every active
     deprecation's removal-not-before release in the release notes.
3. Ask "is this release candidate ready?" with the single Release Quality
   Gate 2.0 entrypoint (Issue #33 RQG-H):
   ```bash
   uv run python scripts/release_gate.py --mode full
   ```
   This orchestrates every check below (and does not reimplement any of
   them): `check_release_metadata.sh`, `ruff`, `check_headers.sh`,
   `git diff --check`, `check_installation_docs.py`,
   `check_release_workflow.py`, the full `pytest -q` suite, the PTY
   integration suite under both `TERM=dumb` and `TERM=xterm-256color`, a
   real wheel/sdist/`.deb`/`.rpm` build validated through
   `check_release_artifacts.sh`, the real Debian install-and-run smoke
   (`smoke_debian_package.sh`), the real RPM install-and-run smoke
   (`smoke_rpm_package.sh`), and the real FreeBSD install-and-run smoke
   (`smoke_freebsd_package.sh`, Issue #33 RQG-E). It prints one PASS/FAIL/
   NOT_RUN/PLATFORM_BLOCKED manifest and exits `0` for `PASS` or
   `READY_EXCEPT_PLATFORM_VALIDATION`, `1` for `FAIL`, `2` for a misused
   argument. Add `--json <path>` for a machine-readable manifest, and
   `--keep-logs <dir>` to persist each sub-check's log past the run instead
   of a disposable temp directory. It never publishes, uploads, tags,
   pushes, or mutates the version/changelog -- it is read-only.

   - `--mode fast`: the cheap, source-only checks (metadata, ruff, headers,
     git diff, the doc/workflow contracts in their structural mode) --
     seconds, no build, no Docker.
   - `--mode ci`: everything `fast` runs, plus the full test suite, both
     PTY `TERM` variants, and a real wheel/sdist/`.deb`/`.rpm`
     artifact-naming contract check -- the same checks ordinary CI performs
     (minutes, no Docker required beyond what the test suite itself uses).
   - `--mode full`: everything `ci` runs, plus the real Debian and RPM
     install-and-run smokes (each requires Docker; each reported
     `PLATFORM_BLOCKED`, not `FAIL`, if Docker is unavailable -- a
     successful `build_rpm.sh`/`build_deb.sh` alone is never reported as
     `PASS`) and the real FreeBSD install-and-run smoke. The FreeBSD smoke
     has no daemon-reachability
     capability probe the way Docker does: the orchestrator checks
     `platform.system() == "FreeBSD"` directly. On any host that is not
     real FreeBSD 14+ -- which includes every ordinary Debian/Linux
     developer machine and this project's own CI runners -- it is reported
     `PLATFORM_BLOCKED`, never `FAIL` or a faked `PASS`. On an actual
     FreeBSD 14+ host it builds the `.pkg`
     (`scripts/build_freebsd_pkg.sh`) and runs
     `scripts/smoke_freebsd_package.sh` against it for real, reporting
     `PASS`/`FAIL` on the genuine outcome. The real, unconditional
     execution of this smoke happens in
     `.github/workflows/release-artifacts.yml`'s FreeBSD 14.4 VM job (see
     below); `PLATFORM_BLOCKED` in a local `full`-mode run on Linux is
     expected and does not by itself indicate a problem.

   `READY_EXCEPT_PLATFORM_VALIDATION` means every check that could run on
   the current machine passed, but at least one platform-specific check
   (FreeBSD on a non-FreeBSD host, Debian/RPM if Docker is unavailable)
   could not run here at all -- it is a "clean as far as this environment
   can tell" signal, not a green light to release without separately
   confirming those platforms via the real FreeBSD VM workflow run.

   All steps must pass (or be a documented `PLATFORM_BLOCKED`) before
   tagging. The underlying local gate,
   ```bash
   scripts/check_release_quality.sh
   ```
   remains available and unchanged: it builds local artifacts, inspects
   metadata and contents, installs the wheel into a temporary virtual
   environment, runs CLI smoke tests, and runs
   [`scripts/smoke_debian_package.sh`](../../scripts/smoke_debian_package.sh)
   (Issue #33 RQG-D): a REAL `apt-get install ./pysh-shell_X.Y.Z-1_all.deb`
   into a disposable `debian:13-slim` container, verifying the installed
   `/usr/bin/pysh` entrypoint (`--version`, `python3 -m pysh --version`,
   `pysh -c`, and a real PTY-driven interactive `exit`/`quit`) -- not merely
   `dpkg-deb --contents`. This step requires Docker locally; the same
   script also runs unconditionally in `ci.yml` on every push/PR. It also
   runs [`scripts/smoke_rpm_package.sh`](../../scripts/smoke_rpm_package.sh)
   immediately after: a REAL `dnf install ./pysh-shell-X.Y.Z-1.noarch.rpm`
   into a disposable Fedora container, verifying the same installed-
   entrypoint contract against `/usr/bin/pysh` -- not merely
   `rpm -qip`/`rpm -qlp`. This step also requires Docker locally; the same
   script also runs unconditionally in `ci.yml` on every push/PR and in
   `release-artifacts.yml`'s `build-and-validate` job, before the RPM
   becomes eligible for the validated release-assets bundle.
   `check_release_quality.sh` runs on the maintainer's own (Linux) dev
   machine, so it cannot run the equivalent FreeBSD smoke -- FreeBSD's
   native `.pkg` format and `pkg(8)` tooling do not exist on Linux, with no
   meaningful container/emulation substitute. It keeps its existing
   preserve/restore handling for a prebuilt `dist/os/freebsd/*.pkg` and
   leaves real FreeBSD install/run validation exclusively to
   `release_gate.py --mode full` (`PLATFORM_BLOCKED` on Linux, real
   `PASS`/`FAIL` on FreeBSD) and to `release-artifacts.yml`'s FreeBSD VM
   job, which always runs the real smoke.
   The gate must produce and validate PyPI wheel + sdist, Debian `.deb`,
   RPM `.rpm`, FreeBSD `.pkg`, and `SHA256SUMS` before a release can proceed.
   It does not tag, publish, upload or create GitHub releases. Local build
   internals keep OS packages under `dist/os/deb/`, `dist/os/rpm/`, and
   `dist/os/freebsd/`; GitHub Release upload uses flat files staged under
   `dist/release-assets/`.

## Release checklist

- README updated for the current version and user-visible behavior.
- Dedicated docs updated, including builtins, operators, configuration,
  migration (including Fish guidance), troubleshooting, project philosophy,
  Python runtime and limitations.
- Release notes prepared from
  [release-notes-template.md](release-notes-template.md).
- Final user-path checklist in
  [manual-validation.md](../user/manual-validation.md) reviewed and its
  release evidence recorded.
- Every builtin is documented in `docs/user/builtins.md`.
- Tests updated for every new builtin or behavior change.
- CI is green.
- `uv run python scripts/release_gate.py --mode full` reports `PASS` or
  `READY_EXCEPT_PLATFORM_VALIDATION` (with every `PLATFORM_BLOCKED` entry
  understood and accounted for, never silently ignored).
- `scripts/check_release_quality.sh` passes.
- `twine check dist/*.whl dist/*.tar.gz` passes.
- `pysh --version` and `python -m pysh --version` print the target version.
- FreeBSD 14+ package and smoke validation follows
  [`packaging.md`](packaging.md#freebsd-validation-and-package-build-for-v080).
  The release is incomplete without `dist/os/freebsd/pysh-shell-X.Y.Z.pkg`.

## Cutting the release

1. Commit any pending documentation / metadata changes:
   ```bash
   git add README.md CHANGELOG.md pyproject.toml src tests docs
   git commit -m "chore(release): prepare vX.Y.Z"
   ```
2. Create the version tag manually:
   ```bash
   git tag -a vX.Y.Z -m "PySH vX.Y.Z"
   ```
3. Push the branch and the tag:
   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```
4. Publish a GitHub Release pointing at the pushed tag. **Pushing the tag
   alone does not trigger anything** -- both `publish.yml` and
   `release-artifacts.yml` trigger on `release: types: [published]`, not
   on tag push:
   ```bash
   gh release create vX.Y.Z --title "PySH vX.Y.Z" --generate-notes
   ```
5. Publishing the release triggers, independently:
   - `publish.yml`: re-verifies the release metadata contract in
     `--release-mode --tag vX.Y.Z` (failing closed on version/changelog/tag
     drift), builds sdist+wheel in an isolated CI environment, and uploads
     to PyPI using Trusted Publishing. It never builds or uploads OS
     packages -- that is `release-artifacts.yml`'s exclusive responsibility,
     and the two workflows never overlap.
   - `release-artifacts.yml`, as three jobs that must succeed in order:
     1. `freebsd-pkg` builds the real `pysh-shell-X.Y.Z.pkg` in a FreeBSD
        14.4 VM (`vmactions/freebsd-vm`; this is a real virtual machine
        inside the `ubuntu-latest` runner, not a self-hosted runner),
        statically inspects it (`pkg info -F`, `pkg query -F`), then runs
        `scripts/smoke_freebsd_package.sh` inside that same VM (Issue #33
        RQG-E): a REAL `pkg add <local .pkg>` install on real FreeBSD,
        verifying the installed `/usr/local/bin/pysh` entrypoint
        (`pysh --version`, `python3.13 -m pysh --version`, `pysh -c`, and a
        real PTY-driven interactive `exit`/`quit`) with the module import
        proven to resolve to `/usr/local/lib/pysh-shell/pysh/__init__.py`,
        never the VM's repository checkout. Only after that smoke passes
        does the job upload the `.pkg` as a workflow artifact -- there is
        no `continue-on-error` anywhere in this job, so a smoke failure
        blocks the artifact from ever reaching the later jobs.
     2. `build-and-validate` (needs `freebsd-pkg`) re-verifies the release
        metadata contract, builds wheel/sdist/`.deb`/`.rpm`, downloads the
        FreeBSD `.pkg`, and runs `scripts/check_release_artifacts.sh`
        (naming, non-empty, checksum-complete, checksum-verified) before
        staging the flat `dist/release-assets/` tree as a workflow
        artifact.
     3. `upload` (needs `build-and-validate`, and only runs on a real
        `release` event -- never on a manual `workflow_dispatch` dry run)
        downloads that validated artifact and attaches it to the GitHub
        Release. It has no other way to obtain files, so it structurally
        cannot run before validation succeeds.

   `release-artifacts.yml` can also be run manually
   (`workflow_dispatch`) at any time, including with no tag or release
   present, to dry-run the metadata gate, all four builds, the real
   FreeBSD VM build, and the artifact-naming/checksum gate -- everything
   except the final GitHub upload, which stays disabled outside a real
   `release` event.
6. Verify the release on
   [PyPI](https://pypi.org/project/pysh-shell/) and that the GitHub
   release page lists `vX.Y.Z` under
   [Releases](https://github.com/SSobol77/pysh/releases).
7. Verify downloaded GitHub Release assets:
   ```bash
   mkdir -p /tmp/pysh-release-vX.Y.Z
   cd /tmp/pysh-release-vX.Y.Z
   gh release download vX.Y.Z
   sha256sum -c SHA256SUMS
   ```

## Post-release

- Install the just-published version into a clean venv and run smoke
  tests:
  ```bash
  python3.13 -m venv /tmp/pysh-smoke
  . /tmp/pysh-smoke/bin/activate
  python -m pip install --upgrade pip
  python -m pip install pysh-shell==X.Y.Z
  pysh --version
  python -m pysh --version
  ```
- On FreeBSD 14+, install the release `.pkg` and run smoke tests:
  ```sh
  sudo pkg install ./pysh-shell-X.Y.Z.pkg
  pysh --version
  python -m pysh --version
  pysh -c "echo freebsd-smoke"
  pysh -c "exit"
  pysh -c "quit"
  ```
- If something is wrong, **yank** the release on PyPI rather than deleting
  the tag, and prepare a patch release.

## Notes

- Tag format is always `vX.Y.Z` (lowercase `v`).
- Publishing a GitHub Release (not merely pushing a tag) is what triggers
  `publish.yml` and `release-artifacts.yml`; both listen for
  `release: types: [published]`.
- Never run `twine upload` from a developer machine for production
  releases — Trusted Publishing in CI is the only sanctioned path.
- Never push the tag before the local quality gates are green.
- `.github/workflows/freebsd-pkg.yml` was retired (Issue #33 RQG-G): it was
  a byte-for-byte duplicate of `release-artifacts.yml`'s `freebsd-pkg` job,
  with a `push: branches: [release/v*]` trigger that never matched this
  project's real `develop/vX.Y.Z` branch model. The real FreeBSD VM build
  lives solely in `release-artifacts.yml` now.
- PySH packages must not replace `/bin/sh`, divert the system shell, or claim
  POSIX sh, bash or zsh compatibility beyond the documented compatibility
  matrix.
