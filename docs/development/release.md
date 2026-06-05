<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/release.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Release Process (`vX.Y.Z`)

> Each release ships **three** artifact families: PyPI (wheel + sdist),
> Debian `.deb`, and Red Hat/Fedora `.rpm`. See
> [`packaging.md`](packaging.md) for the canonical naming contract and
> [`installation.md`](../user/installation.md) for end-user install commands.

A release is incomplete unless all current mandatory artifact families are
built and validated: PyPI wheel + sdist, Debian `.deb`, and RPM `.rpm`. The
local release gate must fail if `.deb` or `.rpm` packaging tools are missing;
those artifact families are not optional. FreeBSD `.pkg` validation is
deferred to Issue #18 and is not part of the current release gate.

PySH is published to PyPI as **`pysh-shell`** through GitHub Actions and
**PyPI Trusted Publishing**. The workflow lives at
[`.github/workflows/publish.yml`](../../.github/workflows/publish.yml) and
uses `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` under
the `pypi` GitHub environment.

> **Do not publish from a developer machine.**
> All publishes happen through GitHub Actions; the maintainer's only
> manual step is creating the git tag after local checks pass.

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
3. Run the full quality gate locally:
   ```bash
   scripts/check_release_quality.sh
   ```
   All steps must pass before tagging.
   The gate builds local artifacts, inspects metadata and contents, installs
   the wheel into a temporary virtual environment, and runs CLI smoke tests.
   The gate must produce and validate PyPI wheel + sdist, Debian `.deb`,
   RPM `.rpm`, and `SHA256SUMS` before a release can proceed. It does not tag,
   publish, upload or create GitHub releases. FreeBSD `.pkg` validation is
   performed after this gate as a separate Issue #18 platform validation step.

## Release checklist

- README updated for the current version and user-visible behavior.
- Dedicated docs updated, including builtins, operators, configuration,
  migration, zsh compatibility, Python runtime and limitations.
- Every builtin is documented in `docs/user/builtins.md`.
- Tests updated for every new builtin or behavior change.
- CI is green.
- `scripts/check_release_quality.sh` passes.
- `twine check dist/*.whl dist/*.tar.gz` passes.
- `pysh --version` and `python -m pysh --version` print the target version.

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
4. The `publish.yml` workflow runs on tag push, builds artifacts in an
   isolated CI environment, and uploads to PyPI using Trusted Publishing.
5. Verify the release on
   [PyPI](https://pypi.org/project/pysh-shell/) and that the GitHub
   release page lists `vX.Y.Z` under
   [Releases](https://github.com/SSobol77/pysh/releases).

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
- If something is wrong, **yank** the release on PyPI rather than deleting
  the tag, and prepare a patch release.

## Notes

- Tag format is always `vX.Y.Z` (lowercase `v`).
- Never run `twine upload` from a developer machine for production
  releases — Trusted Publishing in CI is the only sanctioned path.
- Never push the tag before the local quality gates are green.
- PySH packages must not replace `/bin/sh`, divert the system shell, or claim
  POSIX sh, bash or zsh compatibility beyond the documented compatibility
  matrix.
