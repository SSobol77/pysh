<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/release-quality-gate-2-audit.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Release Quality Gate 2.0 — Current-State Audit (Issue #33, Phase RQG-A)

This document is the Phase RQG-A deliverable for Issue #33. It is an audit
only: it records what already exists, what already enforces what, and where
the real gaps are, backed by exact file/line evidence gathered from this
repository. It proposes implementation slices but implements none of them.
See [`docs/issues/33-release-quality-gate-2.0.md`](../issues/33-release-quality-gate-2.0.md)
for the original design intent this audit was checked against.

No production or test code was modified to produce this document.

## 1. Executive Summary

PySH already has a **substantial, mature, mostly-manual release quality
gate**. This is not a greenfield problem. The core pieces exist and are
individually well built:

- `scripts/check_release_quality.sh` is a 12-step, fail-closed local gate
  that builds every artifact family, validates wheel/sdist metadata and
  contents byte-for-byte, inspects `.deb`/`.rpm` contents, and performs a
  clean-virtualenv install + CLI smoke test.
- `tests/test_docs_consistency.py` (1083 lines, 43 test functions) already
  encodes version consistency, changelog currency, FreeBSD-artifact
  mandatoriness, and forbidden-claim checks as automated `pytest` tests.
- `.github/workflows/release-artifacts.yml` performs a **real** FreeBSD
  14.3 build inside a VM (`vmactions/freebsd-vm`), builds real
  wheel/sdist/deb/rpm, and stages flat GitHub Release assets — this is not
  a stub.
- Version, license, and entrypoint metadata (`pysh --version`,
  `python -m pysh --version`, `pysh -c`, `exit`/`quit`) all have real
  automated coverage somewhere in the repository.

The gap is **not** "these checks don't exist." The gap is that the checks
are **split across three uncoordinated surfaces** with different trigger
conditions and different levels of rigor, and several of them **never
actually execute in ordinary CI**:

1. `tests/test_docs_consistency.py` checks that release *scripts and
   workflows contain the right text* (string/regex assertions against
   script and YAML source). It does **not** execute the release pipeline.
2. `scripts/check_release_quality.sh` *does* execute the real pipeline
   (build, install, smoke) but is **never invoked by any GitHub Actions
   workflow** — it is a local, human-run script, and it hard-requires a
   pre-built FreeBSD `.pkg` that a Debian/Linux CI runner cannot produce.
3. `ci.yml` (the workflow that actually runs on every push/PR) builds a
   wheel/sdist, runs `twine check`, and smoke-tests `--version` only —
   `pysh -c`, `exit`/`quit`, and the full artifact-family gate are absent
   or conditionally skipped there.

Consequently: **a broken `pysh -c`, a broken `.deb` contents layout, or a
version drift between `pyproject.toml` and `CHANGELOG.md` would be caught
today only if a human remembers to run `scripts/check_release_quality.sh`
locally, or if `pytest -q` (which includes `test_docs_consistency.py`) is
run** — and even then, several of Issue #33's target scenarios (checksum
corruption, install-from-a-broken-wheel, a real `pysh -c` failure on the
*installed* console-script entrypoint in ordinary CI) have no automated
check anywhere.

FreeBSD validation is the one item that is genuinely infrastructure-real
(a working `vmactions/freebsd-vm` job exists) but is **scoped to release
time only** (`release: published` / `workflow_dispatch`), not to ordinary
pushes — so a FreeBSD-breaking change is not caught until someone actually
publishes a release or manually dispatches the workflow.

## 2. Current Release Pipeline Map

```text
                     ┌─────────────────────────────────────────────┐
                     │  Developer machine (manual, human-run)        │
                     │                                                │
  pyproject.toml ───▶│  scripts/check_release_quality.sh (12 steps)  │
  src/pysh/__init__  │    -> ruff, pytest, headers, git diff --check │
  CHANGELOG.md        │    -> build_release_artifacts.sh              │
                     │       -> build_pysh_package.sh (wheel+sdist)  │
                     │       -> build_deb.sh                          │
                     │       -> build_rpm.sh                          │
                     │       -> build_freebsd_pkg.sh (FreeBSD-only,   │
                     │          REQUIRES a prebuilt .pkg on Linux)    │
                     │    -> check_release_artifacts.sh               │
                     │       -> SHA256SUMS + flat dist/release-assets │
                     │    -> twine check                              │
                     │    -> Python metadata/contents inspection      │
                     │    -> dpkg-deb/rpm content listing              │
                     │    -> clean venv install + `pysh -c` smoke     │
                     └─────────────────────────────────────────────┘
                                        │  (never invoked by CI)
                                        ▼
                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/ci.yml (push:main, PR)     │
                     │    -> pytest -q, ruff                          │
                     │    -> python -m build (wheel+sdist only)       │
                     │    -> twine check                              │
                     │    -> smoke: pysh --version / python -m pysh   │
                     │       --version  (NOT -c, NOT exit/quit)       │
                     │    -> bash -n syntax-check on packaging shell  │
                     │    -> conditionally build .deb/.rpm if tools   │
                     │       present; conditionally run               │
                     │       check_release_artifacts.sh ONLY if all   │
                     │       5 artifact families already exist        │
                     │       (FreeBSD .pkg never exists here, so this │
                     │       step is always skipped in practice)      │
                     └─────────────────────────────────────────────┘

                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/release-artifacts.yml       │
                     │    on: release[published], workflow_dispatch   │
                     │    -> REAL FreeBSD 14.3 VM build (.pkg)        │
                     │    -> REAL wheel/sdist/deb/rpm build           │
                     │    -> check_release_artifacts.sh (real)        │
                     │    -> gh release upload (real assets)          │
                     └─────────────────────────────────────────────┘
                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/publish.yml                 │
                     │    on: release[published], workflow_dispatch   │
                     │    -> independent python -m build + PyPI       │
                     │       Trusted Publishing (no twine check,      │
                     │       does not depend on release-artifacts.yml)│
                     └─────────────────────────────────────────────┘
                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/freebsd-pkg.yml             │
                     │    on: push[branches: release/v*],             │
                     │        workflow_dispatch                       │
                     │    -> duplicate of release-artifacts.yml's     │
                     │       freebsd-pkg job                          │
                     │    -> trigger branch pattern "release/v*" does │
                     │       not match this repo's real branch model  │
                     │       (develop/vX.Y.Z per CLAUDE.md §13; no    │
                     │       release/v* branch exists or is created)  │
                     └─────────────────────────────────────────────┘
```

`tests/test_docs_consistency.py` sits outside this diagram: it runs inside
`pytest -q` (both locally and in `ci.yml`) and validates, by reading
source text, that the scripts/workflows above *say* the right things. It
is a static-text safety net over the pipeline, not a substitute for
running it.

## 3. Requirement-by-Requirement Matrix

| Requirement | Status | Evidence |
| --- | --- | --- |
| Unit tests | IMPLEMENTED | `pytest -q`, 2183+ tests across `tests/*.py`; run in `ci.yml` step "Run pytest" and manually. |
| Integration tests | IMPLEMENTED | e.g. `tests/test_pty_integration.py`, `tests/test_completion_bug020_regression.py`; part of the same `pytest -q` run. |
| Interactive PTY tests | PARTIAL | `tests/test_pty_integration.py` exists and passes, but hardcodes `_PTY_ENV["TERM"] = "xterm-256color"` for the child process (line 57) — an outer `TERM=dumb pytest ...` invocation does not change what the child PTY sees, so "run under both TERM=dumb and TERM=xterm-256color" is currently a no-op for this file. `TERM=dumb` *is* genuinely unit-tested elsewhere (`tests/test_terminal_style.py::test_style_enabled_dumb_term_disables`, `tests/test_cursor_color.py`, etc.) for color-disabling logic, just not through the PTY harness. |
| Package build (wheel+sdist) | IMPLEMENTED (two independent implementations) | `scripts/build_pysh_package.sh` (via `check_release_quality.sh`) and `ci.yml`'s own `python -m build` step both build real wheels/sdists; `twine check` runs in both. |
| Wheel build | IMPLEMENTED | Filename, METADATA fields (Name/Version/License-Expression/Summary/Requires-Python), entry_points.txt, RECORD/WHEEL presence, and forbidden-path exclusion are all checked in `scripts/check_release_quality.sh` step 9 (`check_release_quality.sh:304-348`). |
| Sdist build | IMPLEMENTED | Same step, `check_release_quality.sh:350-366`: required file suffixes present, forbidden paths excluded, either filename convention accepted. |
| Debian package build | IMPLEMENTED | `scripts/build_deb.sh` self-verifies its own output filename; `check_release_quality.sh` step 10 runs `dpkg-deb --contents` and requires `/usr/bin/pysh` and `/opt/pysh-shell/lib/pysh`. |
| FreeBSD package validation | PARTIAL / PLATFORM-BLOCKED (release-time only) | `scripts/build_freebsd_pkg.sh` refuses to run on non-FreeBSD (`build_freebsd_pkg.sh:21`), verified dynamically by `tests/test_docs_consistency.py::test_freebsd_pkg_builder_refuses_non_freebsd_without_fake_pkg` (actually executes the script via `subprocess.run` and asserts non-zero exit — this is a real behavioral test, not just text-matching). Real builds only happen in `.github/workflows/release-artifacts.yml`'s `vmactions/freebsd-vm` job, gated to `release: published` / `workflow_dispatch` — never on ordinary push/PR. |
| Release artifact naming | IMPLEMENTED | `scripts/check_release_artifacts.sh` hard-fails on any sibling `.deb`/`.rpm`/`.pkg` filename drift (lines 68-94) and regenerates/verifies `SHA256SUMS` in both nested (`dist/`) and flat (`dist/release-assets/`) layouts. |
| README installation commands | PARTIAL | `scripts/check_release_quality.sh:368-378` checks that `docs/`-relative links referenced from README.md resolve to real files (link check), and forbidden-phrase scans run over `docs/user/installation.md` (`check_release_quality.sh:393-410`). No test extracts a fenced code block from README.md or `docs/user/installation.md` and actually executes it (`pip install pysh-shell`, `dpkg -i ...`, `pkg install ...`) — command *text* is never machine-run, only doc *links* and *forbidden phrases* are checked. |
| Changelog version | IMPLEMENTED | `tests/test_docs_consistency.py::test_changelog_has_current_version_section` asserts `## {CURRENT_VERSION}` exists; `test_changelog_080_section_covers_mandatory_features` / `_081_section_covers_hotfix_scope` / `_current_release_covers_metadata_hotfix_scope` assert specific content per historical release. No automated check that the **current `0.9.0 - Unreleased`** section content stays in sync with recently merged issue work (observed gap: the Issue #32 slices A-C are not yet mentioned there as of this audit — a content-currency gap, not a tooling gap). |
| License metadata | IMPLEMENTED | `check_release_quality.sh:207-217` and `:336` assert `project.license == "GPL-2.0-only"` in `pyproject.toml` and wheel `METADATA` `License-Expression`. |
| PyPI metadata | IMPLEMENTED | `twine check` (both `ci.yml` and `check_release_quality.sh`); name/version/summary/requires-python cross-checked against wheel METADATA in `check_release_quality.sh`. |
| GitHub release asset workflow | PARTIAL | `tests/test_docs_consistency.py::test_release_workflow_uploads_flat_staged_assets` statically asserts `release-artifacts.yml`/`freebsd-pkg.yml` contain expected strings (script invocations, `vmactions/freebsd-vm`, upload-artifact usage) — it does not execute the workflow. The workflow itself only runs for real on `release: published`/`workflow_dispatch`, so its correctness is unverified between releases except by this text-level test. |
| Broken CLI entrypoint (required failure) | PARTIAL | `tests/test_cli.py` calls `main()` in-process (fast, but never exercises the installed console-script `pysh` binary or its `pyproject.toml` `[project.scripts]` wiring). `ci.yml` smoke-tests the **real installed** `pysh --version` / `python -m pysh --version` on every push/PR. `check_release_quality.sh` step 11 additionally installs into a throwaway venv and runs the real entrypoint. No CI step currently would fail if `[project.scripts]` pointed at a nonexistent function, other than `ci.yml`'s `--version` smoke (which would in fact catch that). |
| Broken `pysh -c` (required failure) | PARTIAL | Unit-level: `tests/test_cli.py::test_dash_c_runs_command` (in-process). Real-entrypoint level: only inside `scripts/check_release_quality.sh` step 11 (`"${VENV_PYSH}" -c "echo release-smoke"`), which never runs in CI. `ci.yml` never runs `pysh -c` at all. |
| Broken interactive smoke (exit/quit) | PARTIAL | Unit-level: `tests/test_cli.py::test_dash_c_exit_and_quit_return_success_without_internal_error` (in-process, via `-c`, not truly interactive). PTY-level: `tests/test_pty_integration.py` exercises real interactive `exit`. No workflow step anywhere runs `pysh -c "exit"` / `pysh -c "quit"` against the **installed** console-script entrypoint; `docs/development/release.md`'s "Post-release" section documents this as a **manual** step only. |
| Incomplete platform artifacts (required failure) | IMPLEMENTED | `scripts/check_release_artifacts.sh` and `check_release_quality.sh` both hard-fail (`fail`/`exit 1`) on any missing wheel/sdist/deb/rpm/pkg; there is no "warn and continue" path in these scripts. The gap is *reachability* (see §5), not the failure behavior itself. |
| Version mismatch (required failure) | IMPLEMENTED | `tests/test_docs_consistency.py::test_pyproject_toml_version_is_current` and `::test_init_py_version_is_current` both fail loudly on drift; see §7 for the full map and its own weak point. |

## 4. Existing Enforcement Points (Detail)

For each IMPLEMENTED/PARTIAL item, the exact mechanism, failure surface,
and CI exposure:

### 4.1 `scripts/check_release_quality.sh` (local, human-run, 439 lines)

- Steps 1-4: `ruff check src tests`, `pytest -q`, `scripts/check_headers.sh`,
  `git diff --check` — same commands CI runs, re-run here for convenience.
- Step 5: `require_file` on 13 release-critical paths (docs, scripts,
  workflow file); fails with `check_release_quality.sh: required file
  missing: <path>` on `exit 1`.
- Step 6: cleans `dist/ build/ *.egg-info`, then delegates to
  `scripts/build_release_artifacts.sh`, which itself calls
  `build_pysh_package.sh`, `build_deb.sh`, `build_rpm.sh`, and either builds
  or requires a prebuilt `dist/os/freebsd/pysh-shell-<VERSION>.pkg`.
- Step 7: `[ "${#wheels[@]}" -ne 1 ]`-style exact-count assertions for every
  artifact family (`check_release_quality.sh:153-167`); fails with a named
  count mismatch message.
- Step 8: `twine check` on the built wheel+sdist.
- Step 9: an embedded Python heredoc (`check_release_quality.sh:175-411`)
  that: cross-checks `pyproject.toml` project metadata; asserts exact
  filenames for all 5 artifacts; verifies `SHA256SUMS` entries exist and
  match real digests for both `dist/` and `dist/release-assets/`; opens the
  wheel as a zip and asserts no VCS/build-cache paths leaked in, required
  package files exist, and METADATA fields match; opens the sdist as a
  tarball with equivalent checks; checks README/`docs/README.md` internal
  links resolve; scans 4 packaging docs for forbidden compatibility claims.
- Step 10: `dpkg-deb --contents` / `rpm -qpl` content-listing assertions
  for `/usr/bin/pysh` and `/opt/pysh-shell/lib/pysh`.
- Step 11: creates a real throwaway `venv`, `pip install --no-deps` the
  built wheel, and runs `${VENV_PYSH} --version`, `${VENV_PY} -m pysh
  --version`, and `${VENV_PYSH} -c "echo release-smoke"` with an exact
  output-match assertion.
- **Never invoked by any GitHub Actions workflow.** `grep -rn
  "check_release_quality" .github/workflows/` returns no matches.
- Requires `dpkg-deb`, `rpm`, `rpmbuild` on the host (`check_release_quality.sh:44-46`)
  — Debian 13 has all three; a plain macOS/Windows dev machine could not run it.

### 4.2 `scripts/check_release_artifacts.sh` (local + CI-conditional + release workflow)

- Hard-fails (`missing=1` then `exit 1`) if any of wheel/deb/rpm/pkg/sdist
  is absent (`check_release_artifacts.sh:47-66`).
- Hard-fails on any sibling filename that doesn't exactly match the
  canonical pattern (`:68-94`) — this is the live enforcement of the
  packaging-naming contract from `.claude/rules/packaging-naming.md`.
- Regenerates and self-verifies `dist/SHA256SUMS` via `sha256sum -c`
  (`:96-115`), then stages and re-verifies a **flat** copy under
  `dist/release-assets/` with its own `SHA256SUMS` (`:117-143`).
- Invoked from: `ci.yml` (conditionally, only if all 5 artifact globs
  already resolved — see §5.1), `check_release_quality.sh` step 7,
  and `release-artifacts.yml`'s "Verify canonical artifact names" step
  (unconditionally, real artifacts, real FreeBSD `.pkg` downloaded from
  the prior job).

### 4.3 `tests/test_docs_consistency.py` (1083 lines, runs in every `pytest -q`)

- Version consistency: `CURRENT_VERSION = "0.8.2"` (line 393) is the
  single test-suite-side source of truth; `pyproject.toml` and
  `src/pysh/__init__.py` are each compared against it independently
  (`:421-441`). See §7 for why this is a 3-way, not 2-way, consistency
  point.
- FreeBSD mandatoriness: `test_docs_freebsd_pkg_is_mandatory_for_current_release`
  scans `packaging.md`/`release.md`/`installation.md` for required phrases
  and forbidden phrases (`"planned/future"`, `"deferred"`), preventing the
  FreeBSD artifact from being silently downgraded to "future work" in docs
  without a matching test failure.
- Fake-`.pkg` detection is a **real dynamic test**, not a text check:
  `test_freebsd_pkg_builder_refuses_non_freebsd_without_fake_pkg`
  (`:733-758`) runs `subprocess.run(["bash", "scripts/build_freebsd_pkg.sh"])`
  on the current (non-FreeBSD) host and asserts a specific non-zero exit
  and stderr message, then asserts no `.pkg` file was created.
- Workflow-content consistency: `test_release_workflow_uploads_flat_staged_assets`
  (`:165-209`) reads `release-artifacts.yml` and `freebsd-pkg.yml` as text
  and asserts required substrings (script invocations, `vmactions/freebsd-vm`,
  FreeBSD release "14.3", required paths). This is **string-presence
  validation of the YAML**, not workflow execution — a change that keeps
  all the required substrings but breaks the actual job graph (e.g. wrong
  `needs:`, wrong artifact path capitalization causing a real download
  mismatch) would not be caught by this test.
- Dependency-metadata claims: `test_pyyaml_is_fully_removed_from_dependency_metadata`,
  `test_default_runtime_is_stdlib_only`, `test_pygments_is_optional_only`
  guard against dependency creep in `pyproject.toml`.

### 4.4 `tests/test_cli.py` (in-process entrypoint unit tests)

Calls `pysh.cli.main()` directly in the test process. Fast and reliable
for argument-parsing/dispatch logic, but does not exercise:
process-spawn overhead, the real `[project.scripts]` wiring, `argv[0]`
as seen by a real shell invocation, or anything about the installed
package layout.

### 4.5 `.github/workflows/ci.yml` (runs on push:main, PR, workflow_dispatch)

Real, CI-executed, per-commit coverage of: `pytest -q`, `ruff check`,
`python -m build`, `twine check dist/*`, and — genuinely against the
**installed console-script** — `pysh --version` / `python -m pysh
--version`. This is the only place those two commands are checked against
a real installed entrypoint on every push/PR.

### 4.6 `.github/workflows/release-artifacts.yml` (release-time only)

The one workflow that performs a **real** FreeBSD 14.3 build
(`vmactions/freebsd-vm@v1`), asserts `uname -s = FreeBSD` and major
version `>= 14` inside the VM, builds the `.pkg`, inspects it with
`pkg info -F` / `pkg query -F` for required paths, uploads it as a
workflow artifact, downloads it into a second job, and runs the real
`check_release_artifacts.sh` against all 5 real artifact families before
uploading flat assets to the GitHub Release. This is a fully real,
non-stubbed pipeline — its only weakness is *when* it runs (§5.3).

## 5. Missing Enforcement Points

### 5.1 The full artifact-family gate never actually runs in ordinary CI

`ci.yml`'s "Verify release artifacts + SHA256SUMS" step
(`ci.yml:94-104`) only calls `check_release_artifacts.sh` when **all
five** globs already resolve (`dist/*.whl`, `dist/*.tar.gz`,
`dist/os/deb/*.deb`, `dist/os/rpm/*.rpm`, `dist/os/freebsd/*.pkg`). The
FreeBSD `.pkg` glob can never resolve on the `ubuntu-latest` runner
`ci.yml` uses (no FreeBSD build step exists in `ci.yml` at all), so this
condition is **always false** and the step **always prints the "Skipping"
message** on every single push/PR. `scripts/check_release_artifacts.sh`
therefore has zero real CI executions today; its only real executions are
local (`check_release_quality.sh`) or at release time
(`release-artifacts.yml`).

- Smallest reasonable implementation location: a new, separate CI job (or
  a step gated on `workflow_dispatch`/a label) that runs
  `build_pysh_package.sh` + `build_deb.sh` + `build_rpm.sh` and a
  **committed fixture `.pkg`** (see 5.4) so `check_release_artifacts.sh`
  can execute for real on every push, without needing a live FreeBSD VM
  on every commit.
- New code required: minimal — mostly workflow YAML plus one small
  "use a fixture pkg in CI, refuse it in the release workflow" branch.
- Proposed test location: `tests/test_docs_consistency.py` already checks
  workflow text; a new test should assert `ci.yml` runs
  `check_release_artifacts.sh` **unconditionally** (or under a clearly
  documented, narrowly-scoped condition), not merely that the script
  exists.

### 5.2 `pysh -c` and interactive `exit`/`quit` are never run against the installed entrypoint in CI

`ci.yml` smoke-tests only `--version` (twice). Real-entrypoint `-c`
execution and `exit`/`quit` against the installed console script exist
only in `scripts/check_release_quality.sh` step 11, which never runs in
CI (§5.1's sibling problem — this script is not wired into any workflow).

- Smallest reasonable implementation location: add 3 steps to `ci.yml`
  right after the existing `--version` smoke steps:
  `pysh -c "echo ok"`, `pysh -c "exit"; echo "exit=$?"`,
  `pysh -c "quit"; echo "exit=$?"` with explicit exit-code assertions.
  No new script needed — these are three `run:` lines.
- New code required: no (workflow YAML only).
- Proposed test location: extend
  `tests/test_docs_consistency.py::test_release_workflow_uploads_flat_staged_assets`-style
  text assertions, or add a new `test_ci_workflow_smokes_dash_c_and_exit_quit`
  in the same file, asserting `ci.yml` contains these three `run:` lines.

### 5.3 FreeBSD validation is release-scoped, not push-scoped

`release-artifacts.yml`'s FreeBSD job only triggers on
`release: [published]` or manual `workflow_dispatch`. A change that
breaks `scripts/build_freebsd_pkg.sh` or FreeBSD-specific runtime
behavior is invisible until someone actually cuts a release or manually
dispatches the workflow — by definition, after the fact.

`freebsd-pkg.yml` (a near-duplicate of `release-artifacts.yml`'s FreeBSD
job) triggers on `push: branches: [release/v*]`. This project's actual
branch-workflow convention (CLAUDE.md §13; confirmed by
`git branch --show-current` → `develop/v0.9.0`) never creates a
`release/v*` branch — development branches are `develop/vX.Y.Z`, merged
directly to `main`. `tests/test_docs_consistency.py:204` pins the literal
string `"release/v*"` as an expected substring, so the test suite has
codified this trigger pattern without verifying it can ever actually
fire under the project's real branching model. This is not necessarily
wrong (it may be intentionally forward-looking for a not-yet-adopted
`release/*` convention), but as written it means `freebsd-pkg.yml` is
very likely **dead weight that has never fired via its push trigger**,
duplicating logic already present and reachable (via `workflow_dispatch`)
in `release-artifacts.yml`.

- Smallest reasonable implementation location: either (a) change
  `freebsd-pkg.yml`'s trigger to match a branch pattern this project
  actually uses (e.g. `develop/v*`) and give it a real purpose distinct
  from `release-artifacts.yml`, or (b) delete `freebsd-pkg.yml` and rely
  solely on `release-artifacts.yml` + `workflow_dispatch` for pre-release
  FreeBSD dry runs, removing the duplication. This is a design decision
  for the product owner, not something to resolve silently in this audit.
  Running FreeBSD builds on *every* push is likely too expensive (a full
  VM boot per commit) — a scheduled or manually-triggered "FreeBSD dry
  run before tagging" step is the more proportionate middle ground and
  matches `docs/development/release.md`'s existing checklist mindset.
- New code required: workflow YAML edits only; no application code.
- Proposed test location: a `test_freebsd_workflow_trigger_matches_actual_branch_model`
  style test, or explicit removal of the stale assertion once the trigger
  question is decided.

### 5.4 No committed FreeBSD `.pkg` fixture for non-release CI

Because a real `.pkg` can only be produced on FreeBSD, and
`check_release_quality.sh`/`check_release_artifacts.sh` both hard-require
one to exist at the canonical path, there is currently no way to exercise
the **artifact-completeness and naming** checks in ordinary Linux CI
without either (a) running the real FreeBSD VM job every time (expensive,
and currently release-scoped only) or (b) staging a fixture.
`test_freebsd_pkg_builder_refuses_non_freebsd_without_fake_pkg` explicitly
protects against a *fake* `.pkg` being silently created by the builder
itself, so any fixture strategy must keep that test's guarantee intact
(a fixture used to unblock *artifact-naming* checks must never be
producible by `build_freebsd_pkg.sh` itself on non-FreeBSD, and must be
clearly out-of-band, e.g. a repo-fixture file consumed only by a
naming/content check, never presented as a real release artifact).

- Smallest reasonable implementation location: a small, clearly-labeled
  fixture (e.g. `tests/fixtures/release/pysh-shell-0.0.0-fixture.pkg` or
  similar, never matching the real version-naming pattern) plus a new,
  narrowly-scoped script mode that accepts an explicit artifacts
  directory (this maps directly onto the original Issue #33 design's
  "Checks that require platform artifacts accept an artifacts directory
  argument" requirement).
- New code required: yes, but small — an optional `--artifacts-dir`
  argument to `check_release_artifacts.sh`/`check_release_quality.sh`,
  or a thin wrapper script.
- Proposed test location: `tests/test_release_artifact_fixture_gate.py`
  (new file) exercising the naming/checksum logic against the fixture
  directory, independent of a real build.

### 5.5 README/install-doc commands are never executed

Confirmed by direct search: no test extracts a fenced code block from
`README.md` or `docs/user/installation.md` and runs it. Coverage today is
limited to (a) link resolution (`test_docs_markdown_local_links_resolve`,
`check_release_quality.sh`'s README-link scan) and (b) forbidden-phrase
scans. The commands themselves (`pip install pysh-shell`,
`sudo dpkg -i ./pysh-shell_X.Y.Z-1_all.deb`, `sudo pkg install
./pysh-shell-X.Y.Z.pkg`, etc.) are template text with an `X.Y.Z`
placeholder and have never been substituted with the real current version
and actually run.

- Smallest reasonable implementation location: a new script,
  `scripts/check_install_docs.sh`, that greps fenced `bash`/`sh` blocks
  from `docs/user/installation.md`, substitutes `X.Y.Z` with the real
  `pyproject.toml` version, and for the PyPI path actually performs the
  `pip install` step against the just-built wheel in a throwaway venv
  (this overlaps with `check_release_quality.sh` step 11 and should reuse
  it rather than duplicate it). For `.deb`/`.rpm`/`.pkg`, exact-command
  extraction plus a dry-run/`--assert-file-exists`-style check is more
  realistic than actually invoking `sudo dpkg -i` in CI.
- New code required: yes, a new script plus a lightweight parser for
  fenced code blocks (regex over Markdown is sufficient given the
  existing codebase's stdlib-only, no-new-dependency policy).
- Proposed test location: `tests/test_install_docs_commands.py` (new
  file), plus a `check_headers.sh`-style CI step.

### 5.6 No single command with a deterministic PASS/FAIL manifest

The original Issue #33 design (`docs/issues/33-release-quality-gate-2.0.md`)
calls for "a single command with a deterministic exit code... prints a
check manifest and a per-check PASS/FAIL summary." `check_release_quality.sh`
is close (it has 12 numbered `log` steps) but uses `set -euo pipefail`,
so it **stops at the first failure** rather than running all checks and
reporting a full PASS/FAIL manifest at the end — a later check's status
is unknown if an earlier one fails. This matches the "fail fast" model
but not the "manifest" model the issue doc describes.

- Smallest reasonable implementation location: this is the natural
  RQG-H orchestration slice — wrap the existing checks so each one's
  result is captured (not `set -e`-propagated) and a summary table is
  printed at the end, exit code `1` if any failed. This can be additive
  (a new top-level script) rather than a rewrite of the 12 existing steps.
- New code required: yes, an orchestration layer; the underlying checks
  do not need to change.
- Proposed test location: a `tests/test_release_gate_orchestration.py`
  exercising the summary/exit-code contract against seeded pass/fail
  fixtures (e.g. monkeypatched sub-check functions), not the full real
  pipeline (too slow/heavy for a unit test).

### 5.7 CHANGELOG "Unreleased" currency is not checked against merged work

Purely observational, low severity: the `## 0.9.0 - Unreleased` section
in `CHANGELOG.md` does not yet mention the Issue #32 (Shell Integrations
Pack) work landed in this development cycle. No test ties CHANGELOG
content to recent git history or closed issues — nor should one
necessarily, since that is normally a human editorial judgment made at
release-prep time, not a per-commit gate. Recorded here for completeness
per the "changelog version" discovery target, not proposed as an RQG
slice.

## 6. Platform-Specific Gaps

| Platform | Gap | Nature |
| --- | --- | --- |
| FreeBSD | Real `.pkg` build only reachable via `release: published` or `workflow_dispatch`, never on ordinary push/PR (§5.3). | Scheduling/trigger gap, not a capability gap — the VM-based build genuinely works (`release-artifacts.yml`). |
| FreeBSD | `freebsd-pkg.yml`'s push trigger (`release/v*`) does not match this project's real branch-naming convention and is very likely dead code. | Trigger-pattern/branch-model mismatch (§5.3). |
| Linux/Debian CI | Cannot produce a FreeBSD `.pkg`, so the full 5-artifact-family gate (`check_release_artifacts.sh`) never runs unconditionally in `ci.yml` (§5.1). | Structural — needs a fixture or an accepted "skip FreeBSD, gate the rest" mode for ordinary CI, distinct from the release-time full gate. |
| macOS / Windows dev machines | `check_release_quality.sh` hard-requires `dpkg-deb`, `rpm`, `rpmbuild` (`:44-46`) — not installable by default on macOS/Windows. | Documented implicitly (Debian-first project) but not stated as a constraint anywhere; not a defect, just worth naming explicitly so RQG slices don't assume a Linux-only contributor base without saying so. |
| RPM | **RESOLVED (RQG-B).** RPM is a formally supported, mandatory release artifact family for the quality gate, on equal footing with Debian `.deb` and FreeBSD `.pkg`. Issue #33's original scope text naming only "Debian and FreeBSD" is superseded by actual, long-standing repository practice: `scripts/check_release_quality.sh`, `scripts/check_release_artifacts.sh`, `scripts/check_release_metadata.sh` (RQG-B), and `docs/development/release.md` (which already documents "four artifact families", RPM included) all treat it as mandatory. RPM install/native smoke testing remains explicitly out of scope for RQG-B — same as Debian and FreeBSD, neither of which has install smoke automated yet either (§8); that belongs to a future native-packaging-validation slice. | Scope-definition gap in the issue text itself, now closed by explicit product-owner-directed decision rather than left ambiguous. |

### 6.1 RQG-B / RQG-C Follow-up

RQG-C closed the Linux/Debian CI gap in the row above: `ci.yml`'s artifact-contract
step now runs unconditionally via `scripts/check_release_artifacts.sh --contract-only`
against an isolated fixture directory, so it is no longer permanently skipped.
RQG-B adds `scripts/check_release_metadata.sh` (version/changelog/tag/license/
Requires-Python/entrypoint consistency), wired into `ci.yml` unconditionally
(no tag required) and into `release-artifacts.yml` in `--release-mode`
(plus `--tag` when triggered by an actual GitHub Release). The FreeBSD
scheduling gap and the `freebsd-pkg.yml` trigger-pattern question (rows above)
remain open for a future slice.

## 7. Version-Consistency Map (updated by RQG-B)

**Pre-RQG-B state** (for historical reference): three independent,
manually-synchronized literal version strings existed — `pyproject.toml`,
`src/pysh/__init__.py`, and a third hardcoded `CURRENT_VERSION` literal in
`tests/test_docs_consistency.py` — each requiring a human to remember to
update it in lockstep on every version bump.

**Current state (RQG-B):** `pyproject.toml` is the single authoritative
version source. `tests/test_docs_consistency.py::CURRENT_VERSION` is now
*derived* from it at import time (`tomllib.loads(...)["project"]["version"]`),
not independently maintained, eliminating that third literal per this
audit's own §9 RQG-B recommendation. Only two literal copies remain by
design: `pyproject.toml` (build/PyPI-authoritative) and
`src/pysh/__init__.py` (packaged runtime metadata, kept as a literal
deliberately — dynamically parsing `pyproject.toml` on every PySH startup
was explicitly rejected to keep runtime startup cheap and package-safe).

```text
pyproject.toml            [project] version = "0.8.2"   (sole authoritative source)
src/pysh/__init__.py      __version__ = "0.8.2"          (packaged runtime metadata; checked, not derived)
```

Cross-checks that exist today:

- `src/pysh/__init__.py` `__version__` == `pyproject.toml` version —
  `test_init_py_version_is_current` (`test_docs_consistency.py`), now a
  direct two-way check rather than "both agree with a third literal."
- `pyproject.toml` version is well-formed (`X.Y.Z`) —
  `test_pyproject_toml_version_is_well_formed` (replaces the now-retired,
  previously-tautological `test_pyproject_toml_version_is_current`).
- `pysh --version` (in-process) and `python -m pysh --version` (real
  subprocess) both print the exact `pyproject.toml` version —
  `tests/test_release_metadata_contract.py::test_cli_version_flag_matches_canonical_version`
  and `::test_module_invocation_version_matches_canonical_version`, tracing
  back to `pyproject.toml` directly rather than transitively through
  `pysh.__version__` alone.
- `scripts/check_release_metadata.sh` (new, RQG-B) consolidates the
  version/license/Requires-Python/entrypoint/changelog/tag checks into one
  reusable, CI-invoked command; wired into `ci.yml` unconditionally (no tag
  required) and into `release-artifacts.yml` in `--release-mode` (plus
  `--tag` when triggered by a real GitHub Release).
- `CHANGELOG.md` heading contract (ordering, duplicates, target-version
  presence, and — in `--release-mode` only — the target section must no
  longer say "Unreleased") is enforced by the same script; see §9 RQG-B
  for the full contract and `tests/test_release_metadata_contract.py` for
  dynamic fixture-based coverage of every branch.
- An explicit release tag (`v<version>`) is validated by the same script
  via `--tag`, only when passed — never required by ordinary CI.
- Release artifact filenames are derived from `pyproject.toml` via
  `scripts/_pysh_version.sh::pysh_read_version` (single shared awk
  extractor used by every build/check script), so **artifact naming is
  transitively tied to `pyproject.toml`**, not independently hardcoded.

What is still **not** cross-checked, and remains open for a later slice:

- Nothing in the default/ordinary-CI path compares the current git
  `HEAD`'s reachable tags against the canonical version — `--tag` only
  validates a tag *string* handed to it explicitly (by a release workflow
  event), not "does this commit actually have a matching tag." This
  matches the task's explicit instruction that ordinary CI must never
  require a tag to exist.

## 8. Artifact Lifecycle Map (source → build → validate → install → smoke → publish)

| Stage | Wheel/Sdist | Debian `.deb` | RPM `.rpm` | FreeBSD `.pkg` |
| --- | --- | --- | --- | --- |
| **Source** | `pyproject.toml` + `src/pysh/` | `packaging/debian/{control,copyright,postinst,prerm}` | `packaging/rpm/pysh-shell.spec` | Inline in `scripts/build_freebsd_pkg.sh` (no static template dir) |
| **Build** | `scripts/build_pysh_package.sh` (hatchling) / `ci.yml`'s `python -m build` | `scripts/build_deb.sh` | `scripts/build_rpm.sh` | `scripts/build_freebsd_pkg.sh` (FreeBSD 14+ only, hard-refuses elsewhere) |
| **Validate (naming)** | `check_release_artifacts.sh` exact-filename checks | same | same | same |
| **Validate (metadata/contents)** | `check_release_quality.sh` step 9 (zip/tar introspection, METADATA fields) | step 10 (`dpkg-deb --contents`) | step 10 (`rpm -qpl`) | `release-artifacts.yml` (`pkg info -F`, `pkg query -F`) — **not** in `check_release_quality.sh` itself beyond filename/checksum |
| **Checksum** | `dist/SHA256SUMS` + flat `dist/release-assets/SHA256SUMS`, both self-verified via `sha256sum -c` | same | same | same |
| **Install smoke** | Real: `check_release_quality.sh` step 11 (throwaway venv, `pip install --no-deps`) | Content-listing only (`dpkg-deb --contents`); **no actual `dpkg -i` install-and-run smoke anywhere** | Content-listing only; **no actual `rpm -i`/`dnf install` smoke anywhere** | Content-listing only inside the FreeBSD VM (`pkg info -F`, not `pkg install` + run); `docs/development/release.md`'s "Post-release" section documents a real `pkg install` + `pysh --version`/`-c` smoke, but only as a **manual, human-run** step |
| **CLI smoke (installed entrypoint)** | `--version` (CI, every push); `-c`/`exit`/`quit` (local gate only, §5.2) | none automated | none automated | none automated (manual doc only) |
| **Publish** | `publish.yml` → PyPI Trusted Publishing, `release: published` only | `release-artifacts.yml` → GitHub Release asset upload | same | same |

The clearest lifecycle gap, visible directly from this table: **wheel/sdist
is the only artifact family with a real install-and-run smoke test
anywhere in the pipeline.** Debian, RPM, and FreeBSD packages are all
validated for naming, checksum, and static content listing, but none of
them are actually installed into a container/VM and exercised with
`pysh --version` / `pysh -c` as part of any automated (CI or local-script)
run — only as a documented **manual** post-release step
(`docs/development/release.md` lines 125-133).

## 9. Proposed Implementation Slices for Issue #33

Adjusted from the suggested structure based on the evidence above — most
of the suggested slices already have strong partial implementations, so
several are re-scoped as "close the gap" rather than "build from
scratch":

- **RQG-B — Version + metadata consistency hardening. IMPLEMENTED.** Added
  `scripts/check_release_metadata.sh` (version/license/Requires-Python/
  entrypoint/changelog/tag consistency); eliminated the `CURRENT_VERSION`
  triple-source-of-truth (§7); resolved RPM's formal scope status (§6).
  Wired into `ci.yml` (unconditional, no tag) and `release-artifacts.yml`
  (`--release-mode`, plus `--tag` on real releases). See
  `tests/test_release_metadata_contract.py`.
- **RQG-C — CI-reachable artifact gate (no FreeBSD dependency). IMPLEMENTED.**
  Wire
  `check_release_artifacts.sh`/`check_release_quality.sh`'s non-FreeBSD
  checks into `ci.yml` unconditionally, using a fixture strategy for the
  FreeBSD `.pkg` slot so the naming/checksum contract is exercised on
  every push without needing a live FreeBSD VM every time (§5.1, §5.4).
  This is the highest-leverage slice: it turns an always-skipped CI step
  into a real one.
- **RQG-D — Debian package install-and-run smoke.** Add a real
  `dpkg -i`/container-based install of the built `.deb` followed by
  `pysh --version` / `pysh -c "echo ok"` / `exit` / `quit`, closing the
  biggest cell in the §8 table for this artifact family.
- **RQG-E — FreeBSD package validation scope decision + install smoke.**
  Product-owner decision on `freebsd-pkg.yml` vs `release-artifacts.yml`
  duplication and trigger scoping (§5.3); if kept, add a real
  `pkg install` + CLI smoke inside the existing `vmactions/freebsd-vm`
  job (currently only `pkg info -F`/`pkg query -F`, never `pkg install`).
- **RQG-F — README/install command validation.** New
  `scripts/check_install_docs.sh` (or equivalent) that substitutes the
  real version into documented install commands and, at minimum for the
  PyPI path, actually runs them against a built wheel (§5.5).
- **RQG-G — GitHub release asset workflow completeness.** Add a
  behavioral (not just text-presence) check — most practically, a
  `workflow_dispatch`-triggered dry run of `release-artifacts.yml` on a
  schedule or on every push to `develop/vX.Y.Z`, rather than only
  trusting static YAML text assertions (§4.3's `test_release_workflow_uploads_flat_staged_assets`
  caveat).
- **RQG-H — Single orchestrated gate with PASS/FAIL manifest.** Wrap the
  now-more-complete set of checks from RQG-B through RQG-G behind one
  command that runs all checks (not stopping at the first failure),
  prints a manifest, and exits non-zero if any failed — closing §5.6 and
  fulfilling the original issue design's "deterministic exit code... full
  check manifest" requirement. This slice should be last because it
  depends on the individual checks it orchestrates being finalized first.

## 10. Recommended Execution Order

1. **RQG-C** first — it has the highest ratio of safety-gained to
   effort-spent (an always-skipped CI step becomes real) and unblocks
   meaningful CI coverage before anything else is layered on top of it.
2. **RQG-B** next — cheap, and removes a known rough edge
   (`CURRENT_VERSION` ergonomics, missing tag check) before more checks
   are added on top of the version-consistency foundation.
3. **RQG-D** and **RQG-F** in either order — both are "close an obvious
   install-smoke gap" slices of comparable size (Debian install smoke;
   README command execution) and do not depend on each other.
4. **RQG-E** — requires a product-owner decision (branch trigger /
   workflow duplication) before implementation, so it should not block
   RQG-B/C/D/F, but should be resolved before RQG-H so the orchestrator
   has a settled FreeBSD story to wrap.
5. **RQG-G** — depends on RQG-C's fixture/CI-reachability work existing
   first, since a meaningful release-workflow dry run wants the same
   "run without a live FreeBSD VM" capability.
6. **RQG-H last** — orchestration should wrap finished, individually
   trustworthy checks, not checks still being redesigned.

This order prioritizes turning existing-but-unreachable checks into
reachable ones (RQG-C) before adding net-new checks, and defers the
single-command orchestration (RQG-H) until there is a stable, complete
set of underlying checks worth orchestrating.
