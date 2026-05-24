<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
-->

# Release process (v0.2.2)

PySH is published to PyPI as **`pysh-shell`** through GitHub Actions and
**PyPI Trusted Publishing**. The workflow lives at
[`.github/workflows/publish.yml`](../.github/workflows/publish.yml) and
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
   - [`pyproject.toml`](../pyproject.toml) → `version = "0.2.2"`
   - [`src/pysh/__init__.py`](../src/pysh/__init__.py) → `__version__ = "0.2.2"`
   - Any user-facing version strings in [`README.md`](../README.md).
3. Run the full quality gate locally:
   ```bash
   python3.13 -m venv .venv
   . .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   pytest -q
   ruff check src tests
   python -m build
   twine check dist/*
   ```
   All four steps must pass before tagging.

## Release checklist

- README updated for the current version and user-visible behavior.
- Dedicated docs updated, including builtins, operators, configuration,
  migration, zsh compatibility, Python runtime and limitations.
- Every builtin is documented in `docs/builtins.md`.
- Tests updated for every new builtin or behavior change.
- CI is green.
- Local build passes.
- `twine check dist/*` passes.
- `pysh --version` and `python -m pysh --version` print the target version.

## Cutting the release

1. Commit any pending documentation / metadata changes:
   ```bash
   git add README.md pyproject.toml src tests docs .github/workflows/ci.yml
   git commit -m "feat: add PySH script transition runner"
   ```
2. Create the version tag manually:
   ```bash
   git tag v0.2.2
   ```
3. Push the branch and the tag:
   ```bash
   git push origin main
   git push origin v0.2.2
   ```
4. The `publish.yml` workflow runs on tag push, builds artifacts in an
   isolated CI environment, and uploads to PyPI using Trusted Publishing.
5. Verify the release on
   [PyPI](https://pypi.org/project/pysh-shell/) and that the GitHub
   release page lists `v0.2.2` under
   [Releases](https://github.com/SSobol77/pysh/releases).

## Post-release

- Install the just-published version into a clean venv and run smoke
  tests:
  ```bash
  python3.13 -m venv /tmp/pysh-smoke
  . /tmp/pysh-smoke/bin/activate
  python -m pip install --upgrade pip
  python -m pip install pysh-shell==0.2.2
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
