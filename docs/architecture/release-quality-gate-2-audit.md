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
  14.4 build inside a VM (`vmactions/freebsd-vm`), builds real
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

## 2. Current Release Pipeline Map (updated by RQG-B/C/D/F/G)

```text
                     ┌─────────────────────────────────────────────┐
                     │  Developer machine (manual, human-run)        │
                     │                                                │
  pyproject.toml ───▶│  scripts/check_release_quality.sh (13 steps)  │
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
                     │    -> smoke_debian_package.sh (RQG-D: REAL     │
                     │       apt-get install in debian:13-slim)       │
                     │    -> clean venv install + `pysh -c` smoke     │
                     └─────────────────────────────────────────────┘
                                        │  (never invoked by CI)
                                        ▼
                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/ci.yml (push:main, PR)     │
                     │    -> pytest -q, ruff                          │
                     │       (includes test_release_metadata_contract,│
                     │        test_release_artifact_contract,         │
                     │        test_debian_package_smoke_contract,     │
                     │        test_installation_docs_contract,        │
                     │        test_release_workflow_contract)         │
                     │    -> check_release_metadata.sh (RQG-B:        │
                     │       version/changelog/license/entrypoint,    │
                     │       no tag required)                         │
                     │    -> python -m build (wheel+sdist only)       │
                     │    -> twine check                              │
                     │    -> smoke: pysh --version / python -m pysh   │
                     │       --version                                │
                     │    -> build .deb/.rpm (tools always present)   │
                     │    -> smoke_debian_package.sh (RQG-D: REAL     │
                     │       install-and-run, unconditional)          │
                     │    -> check_release_artifacts.sh --contract-   │
                     │       only <isolated tmpdir> (RQG-C: real      │
                     │       wheel/sdist/deb/rpm + one labeled         │
                     │       FreeBSD .pkg fixture, unconditional)      │
                     └─────────────────────────────────────────────┘

                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/release-artifacts.yml       │
                     │    on: release[published], workflow_dispatch   │
                     │                                                │
                     │  freebsd-pkg (needs: none)                     │
                     │    -> REAL FreeBSD 14.4 VM build (.pkg)        │
                     │    -> upload-artifact "freebsd-pkg"            │
                     │         │                                      │
                     │         ▼                                      │
                     │  build-and-validate (needs: freebsd-pkg)       │
                     │    -> check_release_metadata.sh --release-mode │
                     │       [+ --tag on a real release event]        │
                     │    -> REAL wheel/sdist/deb/rpm build           │
                     │    -> download-artifact "freebsd-pkg"          │
                     │    -> check_release_artifacts.sh (real, no     │
                     │       --contract-only)                         │
                     │    -> upload-artifact "release-assets"         │
                     │         │                                      │
                     │         ▼                                      │
                     │  upload (needs: build-and-validate,             │
                     │          if: event == 'release')                │
                     │    -> download-artifact "release-assets"       │
                     │    -> gh release upload (real assets)          │
                     └─────────────────────────────────────────────┘
                     ┌─────────────────────────────────────────────┐
                     │  .github/workflows/publish.yml                 │
                     │    on: release[published], workflow_dispatch   │
                     │    -> check_release_metadata.sh --release-mode │
                     │       [+ --tag on a real release event]        │
                     │       (RQG-G: PyPI can no longer publish a      │
                     │       version whose metadata contract fails)   │
                     │    -> python -m build + PyPI Trusted Publishing│
                     │    -> never touches GitHub Release assets;      │
                     │       stays independent of release-artifacts.yml│
                     │       by design (separate responsibility, not  │
                     │       an oversight -- see docs/development/     │
                     │       release.md)                               │
                     └─────────────────────────────────────────────┘
```

`.github/workflows/freebsd-pkg.yml` was retired by RQG-G: it was a
byte-for-byte duplicate of `release-artifacts.yml`'s `freebsd-pkg` job,
with a push trigger that never matched this project's real branch model
and no unique behavior. See §5.3/§6.

`tests/test_docs_consistency.py` and the dedicated `test_*_contract.py`
modules sit outside this diagram: they run inside `pytest -q` (both
locally and in `ci.yml`) and validate, by a mix of reading source text
(for GitHub-specific `needs:`/`if:` wiring that cannot run locally) and
real dynamic execution against fixtures (for everything else), that the
scripts/workflows above behave as documented. `check_release_metadata.sh`,
`check_release_artifacts.sh`, `smoke_debian_package.sh`,
`check_installation_docs.py`, and `check_release_workflow.py` are all real,
independently invocable scripts, not test-only logic.

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
| GitHub release asset workflow | IMPLEMENTED (RQG-G) | `release-artifacts.yml` now has an explicit `freebsd-pkg` → `build-and-validate` → `upload` job chain with `needs:` enforcement, no `continue-on-error`, and an `upload` job gated on `if: github.event_name == 'release'` that can only obtain files via a workflow-artifact handoff from the validate job. `scripts/check_release_workflow.py` validates the job-graph structure as text (the one place string checks remain appropriate — `needs:`/`if:` cannot be executed locally) AND dynamically simulates the exact pre-upload sequence (`check_release_metadata.sh` then `check_release_artifacts.sh --contract-only`) against fixture directories in `tests/test_release_workflow_contract.py`, proving PASS/FAIL for complete, missing-artifact, corrupt-checksum, and wrong-version scenarios without executing the workflow itself (still not possible locally) and without publishing anything. |
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

The one workflow that performs a **real** FreeBSD 14.4 build
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

### 5.3 FreeBSD validation is release-scoped, not push-scoped — PARTIALLY RESOLVED (RQG-G)

`release-artifacts.yml`'s FreeBSD job only triggers on
`release: [published]` or manual `workflow_dispatch`. A change that
breaks `scripts/build_freebsd_pkg.sh` or FreeBSD-specific runtime
behavior is still invisible until someone actually cuts a release or
manually dispatches the workflow — by definition, after the fact. This
half of the finding remains open; running a full FreeBSD VM boot on every
push is disproportionately expensive, and no scheduled dry-run was added
in this slice.

**The duplication half is resolved.** `freebsd-pkg.yml` (a byte-for-byte
duplicate of `release-artifacts.yml`'s `freebsd-pkg` job body, confirmed
by direct diff) triggered on `push: branches: [release/v*]`, which this
project's actual branch-workflow convention (CLAUDE.md §13; branches are
`develop/vX.Y.Z`, merged to `main`) never creates — a dead trigger with
zero unique release guarantee, since its `workflow_dispatch` trigger
offered nothing `release-artifacts.yml`'s own `workflow_dispatch` did not
already provide. **Decision: retired.** `.github/workflows/freebsd-pkg.yml`
was deleted; the real FreeBSD 14.4 VM build now lives solely in
`release-artifacts.yml`'s `freebsd-pkg` job, unchanged and still reachable
via both `release: published` and `workflow_dispatch`. See
`tests/test_release_workflow_contract.py::test_freebsd_pkg_workflow_was_retired`
and `::test_release_workflow_still_has_real_freebsd_vm_build`.

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

### 5.5 README/install-doc commands are never executed — RESOLVED (RQG-F)

`scripts/check_installation_docs.py` now parses explicitly marked
(`<!-- pysh-install:NAME -->`) snippets in `README.md` and
`docs/user/installation.md`, validates every documented install path
structurally (package name, explicit version statement, OS-package naming
pattern, Python-version requirement, referenced script existence, no
legacy `setup.py install` syntax, README-vs-guide agreement on shared
commands), and, for the PyPI path specifically, builds a real local wheel
and sdist and installs each into a disposable temporary virtualenv,
verifying `pysh --version` / `python -m pysh --version` /
`pysh -c "echo ..."` against the installed artifact -- no PyPI/network
access, no repo-source PYTHONPATH contamination (checked explicitly). The
`.deb`/`.rpm`/`.pkg` commands remain structural-only, as originally
proposed: their naming and local-file-argument shape is validated, but
`apt`/`dnf`/`pkg` are never invoked here (that is RQG-D's job for Debian).
This closes the "never executed" gap for the one artifact family
(PyPI/wheel/sdist) it was ever realistic to portably execute; see
`tests/test_installation_docs_contract.py` for fixture-based coverage of
every failure mode and one real end-to-end dynamic test.

### 5.6 No single command with a deterministic PASS/FAIL manifest — RESOLVED (RQG-H)

The original Issue #33 design (`docs/issues/33-release-quality-gate-2.0.md`)
calls for "a single command with a deterministic exit code... prints a
check manifest and a per-check PASS/FAIL summary." `scripts/check_release_quality.sh`
still uses `set -euo pipefail` and still stops at the first failure
internally (unchanged, by design — it is a strict, fail-fast local gate,
not the manifest orchestrator).

**`scripts/release_gate.py` is the new, additive orchestration layer.** It
invokes `check_release_metadata.sh`, `check_release_artifacts.sh`
(`--contract-only` against a locally-built fixture set),
`check_installation_docs.py`, `check_release_workflow.py`, `ruff`,
`scripts/check_headers.sh`, `git diff --check`, the full `pytest -q`
suite, the PTY suite under both `TERM` values, and
`scripts/smoke_debian_package.sh` as independent subprocess checks; each
one's PASS/FAIL/PLATFORM_BLOCKED/NOT_RUN status is captured (not
`set -e`-propagated), and every check that can safely run does, even
after an earlier one fails — there is no destructive/release step to
protect by stopping early, since this orchestrator never publishes,
tags, or pushes. It exits `0` for `PASS`/`READY_EXCEPT_PLATFORM_VALIDATION`,
`1` for `FAIL`, `2` for misuse, and supports `--json` for a
machine-readable manifest and `--keep-logs` to persist each sub-check's
captured stdout/stderr. See `tests/test_release_gate.py`.

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
| FreeBSD | **RESOLVED (RQG-G).** `freebsd-pkg.yml`'s push trigger (`release/v*`) never matched this project's real branch-naming convention and was proven (byte-for-byte diff) to duplicate `release-artifacts.yml`'s `freebsd-pkg` job with no unique behavior. It was retired; the real FreeBSD VM build is now single-sourced in `release-artifacts.yml`. | Trigger-pattern/branch-model mismatch, now closed by deletion rather than left ambiguous (§5.3). |
| Linux/Debian CI | Cannot produce a FreeBSD `.pkg`, so the full 5-artifact-family gate (`check_release_artifacts.sh`) never runs unconditionally in `ci.yml` (§5.1). | Structural — needs a fixture or an accepted "skip FreeBSD, gate the rest" mode for ordinary CI, distinct from the release-time full gate. |
| macOS / Windows dev machines | `check_release_quality.sh` hard-requires `dpkg-deb`, `rpm`, `rpmbuild` (`:44-46`) — not installable by default on macOS/Windows. | Documented implicitly (Debian-first project) but not stated as a constraint anywhere; not a defect, just worth naming explicitly so RQG slices don't assume a Linux-only contributor base without saying so. |
| RPM | **RESOLVED (RQG-B).** RPM is a formally supported, mandatory release artifact family for the quality gate, on equal footing with Debian `.deb` and FreeBSD `.pkg`. Issue #33's original scope text naming only "Debian and FreeBSD" is superseded by actual, long-standing repository practice: `scripts/check_release_quality.sh`, `scripts/check_release_artifacts.sh`, `scripts/check_release_metadata.sh` (RQG-B), and `docs/development/release.md` (which already documents "four artifact families", RPM included) all treat it as mandatory. RPM install/native smoke testing remains explicitly out of scope for RQG-B — same as Debian and FreeBSD, neither of which has install smoke automated yet either (§8); that belongs to a future native-packaging-validation slice. **RPM's real install-and-run smoke was added in the RPM install-smoke follow-up after RQG-E** (`scripts/smoke_rpm_package.sh`, §8), closing this gap on the same footing as Debian (RQG-D) and FreeBSD (RQG-E). | Scope-definition gap in the issue text itself, now closed by explicit product-owner-directed decision rather than left ambiguous. |

### 6.1 RQG-B / RQG-C / RQG-D / RQG-F / RQG-G Follow-up

RQG-C closed the Linux/Debian CI gap in the row above: `ci.yml`'s artifact-contract
step now runs unconditionally via `scripts/check_release_artifacts.sh --contract-only`
against an isolated fixture directory, so it is no longer permanently skipped.
RQG-B adds `scripts/check_release_metadata.sh` (version/changelog/tag/license/
Requires-Python/entrypoint consistency), wired into `ci.yml` unconditionally
(no tag required) and into `release-artifacts.yml` in `--release-mode`
(plus `--tag` when triggered by an actual GitHub Release). RQG-D added a
real Debian install-and-run smoke, reused by both `ci.yml` and
`scripts/check_release_quality.sh`. RQG-F added a structural + portable-execution
contract for README/installation-guide install commands. RQG-G closed the
`freebsd-pkg.yml` duplication (row above, deleted), gave
`release-artifacts.yml` an explicit build → validate → upload job boundary
with `needs:`-enforced ordering, and added the same `--release-mode`
metadata gate to `publish.yml` so PyPI publication cannot proceed on a
version whose release metadata contract fails. The FreeBSD
release-time-only scheduling gap (first row above) remains open for a
future slice.

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
pyproject.toml            [project] version = "0.9.0"   (sole authoritative source)
src/pysh/__init__.py      __version__ = "0.9.0"          (packaged runtime metadata; checked, not derived)
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
| **Validate (metadata/contents)** | `check_release_quality.sh` step 9 (zip/tar introspection, METADATA fields) | step 10 (`dpkg-deb --contents`) | step 10 (`rpm -qpl`, plus `rpm -qip`/`rpm -qlp` inside `build_rpm.sh` itself) | `release-artifacts.yml` (`pkg info -F`, `pkg query -F`) — **not** in `check_release_quality.sh` itself beyond filename/checksum |
| **Checksum** | `dist/SHA256SUMS` + flat `dist/release-assets/SHA256SUMS`, both self-verified via `sha256sum -c` | same | same | same |
| **Install smoke** | Real: `check_release_quality.sh` step 13 (throwaway venv, `pip install --no-deps`) | **Real (RQG-D):** `scripts/smoke_debian_package.sh` — genuine `apt-get install ./<pkg>.deb` inside a disposable `debian:13-slim` container, on every CI push/PR (unconditional, no `continue-on-error`) and in `check_release_quality.sh` step 11 | **Real (RPM follow-up):** `scripts/smoke_rpm_package.sh` — genuine `dnf install ./<pkg>.rpm` inside a disposable `fedora:43` container, on every CI push/PR (unconditional, no `continue-on-error`), in `release-artifacts.yml`'s `build-and-validate` job before the artifact gate, and in `check_release_quality.sh` step 12 | **Real (RQG-E):** `scripts/smoke_freebsd_package.sh` — genuine `pkg add <local .pkg>` directly on real FreeBSD 14+, run inside `release-artifacts.yml`'s `vmactions/freebsd-vm` job immediately after the existing `pkg info -F`/`pkg query -F` static checks, unconditionally, no `continue-on-error`. `check_release_quality.sh` still cannot run it (it executes on a Linux dev machine and FreeBSD's `pkg(8)` has no Linux/container equivalent), so it keeps its existing preserve/restore-prebuilt-`.pkg` handling instead |
| **CLI smoke (installed entrypoint)** | `--version` (CI, every push); `-c`/`exit`/`quit` (local gate only, §5.2) | **Real (RQG-D):** `--version`, `python3 -m pysh --version`, `pysh -c "echo deb-smoke"`, `pysh -c "exit"`, `pysh -c "quit"`, a non-TTY batch-mode check, and a genuine stdlib-`pty`-driven interactive `exit`/`quit` check — all against the installed `/usr/bin/pysh`, on every CI run | **Real (RPM follow-up):** `--version`, `python3 -m pysh --version`, `pysh -c "echo rpm-smoke"`, `pysh -c "exit"`, `pysh -c "quit"`, a non-TTY batch-mode check, and a genuine stdlib-`pty`-driven interactive `exit`/`quit` check — all against the installed `/usr/bin/pysh`, on every CI run | **Real (RQG-E):** `--version`, `python3.13 -m pysh --version`, `pysh -c "echo freebsd-smoke"`, `pysh -c "exit"`, `pysh -c "quit"`, a non-TTY batch-mode check, and a genuine stdlib-`pty`-driven interactive `exit`/`quit` check — all against the installed `/usr/local/bin/pysh`, inside the FreeBSD VM job |
| **Package isolation proof** | n/a | **New (RQG-D):** `command -v pysh` == `/usr/bin/pysh`; `PYTHONPATH=/opt/pysh-shell/lib python3 -c 'import pysh; print(pysh.__file__)'` == `/opt/pysh-shell/lib/pysh/__init__.py` — never the repo checkout or a venv | **New (RPM follow-up):** `command -v pysh` == `/usr/bin/pysh`; `PYTHONPATH=/opt/pysh-shell/lib python3 -c 'import pysh; print(pysh.__file__)'` == `/opt/pysh-shell/lib/pysh/__init__.py` — never the repo checkout or a venv (same wrapper contract as Debian: `packaging/wrappers/pysh.sh`) | **New (RQG-E):** `command -v pysh` == `/usr/local/bin/pysh`; `PYTHONPATH=/usr/local/lib/pysh-shell python3.13 -c 'import pysh; print(pysh.__file__)'` == `/usr/local/lib/pysh-shell/pysh/__init__.py` — never the VM's repository checkout |
| **Publish** | `publish.yml` → PyPI Trusted Publishing, `release: published` only | `release-artifacts.yml` → GitHub Release asset upload | same | same |

**Updated by RQG-D, then RQG-E, then the RPM install-and-run follow-up:**
Debian, RPM, and FreeBSD are no longer the "content-listing only" cases —
all three now have the same tier of real install-and-run smoke as
wheel/sdist. Debian reuses one script (`scripts/smoke_debian_package.sh`)
from both `ci.yml` and `scripts/check_release_quality.sh`; RPM reuses one
script (`scripts/smoke_rpm_package.sh`) from `ci.yml`,
`release-artifacts.yml`, and `scripts/check_release_quality.sh`; FreeBSD
reuses one script (`scripts/smoke_freebsd_package.sh`) from both
`release-artifacts.yml`'s FreeBSD VM job and
`scripts/release_gate.py --mode full` (on an actual FreeBSD host) — no
duplicate implementation for any of the three. Every OS artifact family
now has an independent `release_gate.py` check with proper
`PASS`/`FAIL`/`PLATFORM_BLOCKED` semantics: Docker unavailability blocks
Debian and RPM, and non-FreeBSD hosts block FreeBSD, but none is ever
faked as `PASS` from a successful build alone. RPM remains the one family
without automated `dnf`/`rpm` repository publication (it is a GitHub
Release artifact only, per `packaging/rpm/README.md`), which is a
distribution-channel gap, not an install-smoke gap.

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
- **RQG-D — Debian package install-and-run smoke. IMPLEMENTED.** Added
  `scripts/smoke_debian_package.sh`: a real `apt-get install ./<pkg>.deb`
  into a disposable `debian:13-slim` container, followed by
  `pysh --version`, `python3 -m pysh --version`, `pysh -c "echo deb-smoke"`,
  `pysh -c "exit"`/`"quit"`, a non-TTY batch-mode check, a genuine
  `pty`-driven interactive `exit`/`quit` check, and a package-isolation
  proof (`command -v pysh`, `pysh.__file__` under `/opt/pysh-shell/lib`).
  Wired into `ci.yml` unconditionally (no `continue-on-error`) and reused
  as-is by `check_release_quality.sh`; the pre-existing
  `dpkg-deb --contents` check is preserved unchanged. See
  `tests/test_debian_package_smoke_contract.py`.
- **RQG-E — FreeBSD package install-and-run smoke. IMPLEMENTED.** Added
  `scripts/smoke_freebsd_package.sh`: a real `pkg add <local .pkg>` on
  real FreeBSD 14+, followed by `pysh --version`,
  `python3.13 -m pysh --version`, `pysh -c "echo freebsd-smoke"`,
  `pysh -c "exit"`/`"quit"`, a non-TTY batch-mode check, a genuine
  `pty`-driven interactive `exit`/`quit` check, and a package-isolation
  proof (`command -v pysh`, `pysh.__file__` under
  `/usr/local/lib/pysh-shell`). The script refuses to run on any host
  that is not real FreeBSD 14+ (`uname -s` check, no silent skip, no
  container/emulation fallback — FreeBSD's `.pkg` format and `pkg(8)`
  simply do not exist elsewhere). Wired into
  `release-artifacts.yml`'s FreeBSD VM job, immediately after the
  pre-existing `pkg info -F`/`pkg query -F` static checks (preserved
  unchanged) and before the artifact-verify/upload steps, with no
  `continue-on-error`. `scripts/release_gate.py`'s `check_freebsd_smoke()`
  now checks `platform.system() == "FreeBSD"` directly (there is no
  daemon-reachability capability probe the way Docker has one for
  Debian — the host either is FreeBSD or it isn't): `PLATFORM_BLOCKED`
  with an accurate diagnostic on any other host, a real build-install-run
  attempt (`PASS`/`FAIL` on the genuine outcome) on FreeBSD itself.
  `check_release_quality.sh` is unchanged — it runs on a Linux dev machine
  and keeps its existing preserve/restore-prebuilt-`.pkg` handling, since
  it structurally cannot execute FreeBSD-native `pkg(8)` tooling. This
  session's environment is Debian Linux, not FreeBSD, so the real smoke
  was verified by full local host-side contract tests
  (`tests/test_freebsd_package_smoke_contract.py`) plus argument
  validation, static-content checks, and workflow wiring; the genuine
  build→install→query→execute sequence itself was not re-run inside an
  actual FreeBSD VM as part of this change (see the final report's
  "REAL FREEBSD SMOKE" line). See
  `tests/test_freebsd_package_smoke_contract.py` and
  `tests/test_release_gate.py`.
- **RQG-F — README/install command validation. IMPLEMENTED.** Added
  `scripts/check_installation_docs.py`: parses only explicitly marked
  (`<!-- pysh-install:NAME -->`) snippets in README.md and
  docs/user/installation.md, validates package name/version/Python-version/
  OS-package-naming/legacy-syntax/script-existence structurally against
  pyproject.toml, cross-checks README against the installation guide for
  shared-command agreement, and (by default; `--skip-portable` to disable)
  builds a real local wheel and sdist and installs each into a disposable
  temporary virtualenv for a genuine `pysh --version`/`-c "echo ..."` smoke
  -- with no PyPI/network access. Debian/RPM/FreeBSD install commands are
  validated structurally only, never executed (that remains RQG-D's job
  for Debian, and a future slice's for RPM/FreeBSD). No new CI step was
  added: `pytest -q` already runs unconditionally on every PR/push, and
  this gate's tests are part of that suite. See
  `tests/test_installation_docs_contract.py`.
- **RQG-G — GitHub release asset workflow completeness. IMPLEMENTED.**
  Restructured `release-artifacts.yml` into an explicit
  `freebsd-pkg` → `build-and-validate` → `upload` job chain (`needs:`
  enforced, no `continue-on-error`, upload gated on a real `release`
  event and only able to see files the validate job explicitly staged and
  uploaded). Added `scripts/check_release_workflow.py`: static job-graph
  checks (the one place text assertions remain appropriate) plus a dynamic
  `simulate_pre_upload_sequence()` that runs the real metadata-then-artifact
  gate sequence against fixture directories. Retired `freebsd-pkg.yml`
  (proven byte-for-byte duplicate, §5.3/§6). Added the same
  `--release-mode` metadata gate to `publish.yml`, and confirmed textually
  that it never uploads GitHub Release assets (that responsibility stays
  exclusive to `release-artifacts.yml`). A true scheduled/push-triggered
  `workflow_dispatch` dry run of the real workflow remains a possible
  future refinement but was not required to close this slice's contract.
  See `tests/test_release_workflow_contract.py`.
- **RQG-H — Single orchestrated gate with PASS/FAIL manifest. IMPLEMENTED.**
  Added `scripts/release_gate.py`, wrapping the RQG-B through RQG-G checks
  (plus ruff/pytest/PTY/headers/git-diff) behind three modes (`fast`,
  `ci`, `full`) with a four-state status model (`PASS`/`FAIL`/`NOT_RUN`/
  `PLATFORM_BLOCKED`), a deterministic overall status
  (`PASS`/`FAIL`/`READY_EXCEPT_PLATFORM_VALIDATION`) and exit code
  (`0`/`1`/`2`), and both human-readable and `--json` manifests — closing
  §5.6 and fulfilling the original issue design's "deterministic exit
  code... full check manifest" requirement. At the time RQG-H shipped,
  FreeBSD install smoke was intentionally always `PLATFORM_BLOCKED`
  (RQG-E did not exist yet); **since RQG-E, it is `PLATFORM_BLOCKED` only
  on non-FreeBSD hosts and attempts a real build/install/run on FreeBSD
  itself**, on the same footing as Debian install smoke being
  `PLATFORM_BLOCKED` specifically when Docker is unavailable — neither is
  ever faked as `PASS`. See `tests/test_release_gate.py`.

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
4. **RQG-G** — the branch-trigger/workflow-duplication decision this
   audit originally filed under a placeholder "RQG-E" was actually
   resolved here: `freebsd-pkg.yml` was retired and
   `release-artifacts.yml` got its explicit build → validate → upload job
   boundary, depending on RQG-C's fixture/CI-reachability work already
   existing.
5. **RQG-H last** — orchestration wraps the finished, individually
   trustworthy checks from RQG-B/C/D/F/G, not checks still being
   redesigned.

This order prioritized turning existing-but-unreachable checks into
reachable ones (RQG-C) before adding net-new checks, and deferred the
single-command orchestration (RQG-H) until there was a stable, complete
set of underlying checks worth orchestrating.

**Status as of RQG-E: every slice above (RQG-A through RQG-H) is
implemented.** The genuine native FreeBSD install-and-run smoke — the
Debian-parallel counterpart to RQG-D that RQG-H's initial ship left as an
explicit, honestly-reported gap — now exists as
`scripts/smoke_freebsd_package.sh`, wired into both
`release-artifacts.yml`'s FreeBSD 14.4 VM job (unconditional, real
build→install→query→execute) and `scripts/release_gate.py --mode full`
(real on a FreeBSD host, `PLATFORM_BLOCKED` — never faked `PASS` — on
every other host, including this project's own Linux dev/CI machines).
`READY_EXCEPT_PLATFORM_VALIDATION` therefore now reflects only genuine,
unavoidable environment gaps (no FreeBSD host, no Docker daemon) rather
than a permanently-unimplemented check. This repository's own development
environment is Debian Linux, not FreeBSD, so RQG-E's real
build→install→query→execute sequence has not been re-verified end-to-end
inside an actual FreeBSD VM as part of landing this slice; that
verification is what `release-artifacts.yml`'s FreeBSD job performs on
every `workflow_dispatch`/release run going forward.

**Post-RQG-E finding and fix: FreeBSD VM/pkg-repository ABI skew.** A
real `workflow_dispatch` run of the FreeBSD job (against the RQG-E
commit) failed before any PySH code executed: `pkg update -f` refused to
proceed because the live FreeBSD package repository now serves packages
built for FreeBSD 14.4's userland (`1404000`) while the pinned
`vmactions/freebsd-vm@v1` image was still FreeBSD 14.3 (`1403000`) —
`pkg`'s own ABI-version protection, not a bug in `scripts/build_freebsd_pkg.sh`
or `scripts/smoke_freebsd_package.sh`. The fix was the smallest safe
correction: bump `release: "14.3"` to `release: "14.4"` in
`release-artifacts.yml` (confirmed available for the same pinned builder
release via the `anyvm-org/freebsd-builder` release assets before
changing it), matching the ABI the live repository now expects, with no
`IGNORE_OSVERSION` override and no weakening of `pkg`'s own protection.
All prose/tests describing the *current* VM version were updated to
14.4; historical audit findings that describe a specific past test's
original wording were left alone. This is the same class of staleness
risk RQG-A/RQG-B already named for Fedora/RPM-family point releases
(§8's "RPM follow-up" entry uses an explicitly version-pinned `fedora:43`
for the same reason, verified against Fedora's own supported-release
window rather than assumed) — a pinned-OS-version smoke target will
eventually drift and needs an occasional, deliberate bump; this is
expected maintenance, not a design flaw.
