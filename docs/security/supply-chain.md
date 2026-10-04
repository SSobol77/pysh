<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/supply-chain.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Supply-chain assurance contract (PySH 1.0)

This is the repository-owned supply-chain policy defined by Issue #51. It states
what the release pipeline must be able to prove about every PySH release artifact,
and what a verifier must do when proof is missing. It is checked structurally by
`scripts/check_supply_chain_contract.py`, which the Release Quality Gate runs.

Supply-chain evidence is a release property. It is CI and release evidence only
and never becomes a PySH runtime dependency.

<a id="PYSH-SC-SCOPE"></a>

## Scope and implementation status

**Issue #51 defines the supply-chain contract. SPDX 2.3 JSON SBOM generation
(Slice 2), keyless provenance and SBOM attestations with verification before upload
(Slice 3) and per-artifact reproducibility measurement with published evidence
(Slice 4) are implemented, and the final Tier-1 dry-run evidence (Slice 5) is recorded
in [supply-chain-evidence.md](supply-chain-evidence.md).** Attestations are created and
verified only by the release workflow when it runs on GitHub; nothing in this repository
creates one locally, and an SBOM is not provenance. That evidence is a real
`workflow_dispatch` run for package version 0.9.1 and proves the mechanism before v1.0.0; it
is not the final v1.0.0 release attestation, and the v1.0.0 release must rerun the same
assurance pipeline on its final release SHA.

| Capability | Status |
| --- | --- |
| Policy, anchors and structural contract check | IMPLEMENTED (Slice 1) |
| SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2) |
| Keyless provenance and SPDX SBOM attestations, verified before upload | IMPLEMENTED (Slice 3) |
| Reproducibility measurement | IMPLEMENTED (Slice 4) |
| Final Tier-1 dry-run release evidence | IMPLEMENTED (Slice 5) |

Non-goals. This contract does not:

- introduce a PySH runtime dependency on any SBOM, signing or attestation tool;
- require a developer or maintainer workstation signing key, or any long-lived
  private signing key;
- replace PyPI Trusted Publishing or create a second PyPI publisher;
- move the Debian, RPM or FreeBSD packages into official operating-system
  repositories;
- claim bit-for-bit reproducibility before it has been measured;
- make supply-chain metadata part of the PySH language semantics;
- weaken the existing package smoke tests or the canonical artifact naming gates;
- permit any helper to upload release assets and bypass validation.

<a id="PYSH-SC-ARTIFACTS"></a>

## Mandatory artifact families

The canonical public file names are owned by the packaging contract
([packaging.md](../development/packaging.md)) and enforced by
`scripts/check_release_artifacts.sh`. This document names families, not
version-specific file names, and no supply-chain layer may rename a subject.

| Family | Public artifact | SBOM | Provenance |
| --- | --- | --- | --- |
| `wheel` | PyPI wheel (`.whl`) | required | required |
| `sdist` | PyPI source distribution (`.tar.gz`) | required | required |
| `deb` | Debian package (`.deb`) | required | required |
| `rpm` | RPM package (`.rpm`) | required | required |
| `freebsd_pkg` | FreeBSD reference package (`.pkg`) | required | required |
| `checksums` | `SHA256SUMS` integrity manifest | not applicable | required |

`SHA256SUMS` is an integrity manifest, not a package payload, so it has no
package-content SBOM but is still an attested release subject. Published SBOM files
are themselves release subjects once they are published as release assets, and so is
the published reproducibility evidence `REPRODUCIBILITY.json`, which is assurance
metadata rather than an artifact family: it has no SBOM and no reproducibility status
of its own.

<a id="PYSH-SC-TRUST"></a>

## Trust model

GitHub Release artifacts use keyless, OIDC-backed provenance: the signing identity
is the GitHub Actions workflow identity of this repository, `SSobol77/pysh`. There
is no long-lived private signing key: no production signing private key is stored
in the repository, in GitHub Secrets, or on a maintainer workstation, and no release
depends on one. A cached trust root (see below) is verification material, not a
PySH signing key. PySH does not distribute a private signing key.

The identity chain is: the GitHub Actions workflow identity, a GitHub OIDC token, a
short-lived Sigstore signing certificate and the GitHub Artifact Attestations
service. The attestation action is `actions/attest` v4.2.2, pinned in the release
workflow to the immutable commit `1e69f48acb82d1966a394da916b4c1698aa569d6`; no other
attestation action and no second signing mechanism (no cosign, no GPG) is used. Only
the `build-and-validate` job holds the OIDC and attestation permissions
(`id-token: write`, `attestations: write`, `artifact-metadata: write`, with
`contents: read`); the `upload` job holds only `contents: write` and neither signs nor
verifies anything.

<a id="PYSH-SC-SBOM"></a>

## SBOM

- The canonical release SBOM format is **SPDX 2.3 JSON** (`SPDX-2.3`).
- It is required for, and generated for, the wheel, sdist, `.deb`, `.rpm` and `.pkg`
  families: exactly one SBOM per package artifact, none for `SHA256SUMS`.
- **Naming**: the SBOM file name is the exact artifact basename plus `.spdx.json`
  (for example `<artifact-basename>.spdx.json`), derived mechanically by
  `scripts/generate_release_sboms.py`. There are no version-independent aliases and no
  separate naming authority.
- **Tool**: Anchore Syft 1.54.0, a CI-only tool. It is fetched by
  `scripts/generate_release_sboms.py fetch-syft` from the official release archive
  and verified against a pinned SHA-256 (the upstream tag commit is recorded beside
  it in that script). It is never a PySH dependency and is not part of any package.
- **Inputs**: the SBOMs are generated only from the validated canonical bytes staged in
  `dist/release-assets`. A wheel, sdist or `.pkg` payload is safely unpacked into a
  private scratch directory and scanned; a `.deb` or `.rpm` is scanned as an archive.
  The artifact itself is never modified. The artifact is bound into its SBOM: the
  described root package is named by the artifact basename and its version is
  `sha256:<artifact digest>`.
- **Content**: the SBOM lists whatever components the tool recognizes. Wheel and
  `.deb` SBOMs list the PySH package; the sdist and FreeBSD `.pkg` SBOMs currently list
  only the bound artifact because the tool has no cataloger for those payloads.
- **Validation** (`validate`, `validate-bundle`): valid JSON, `SPDX-2.3`, data license,
  document namespace, creation info, artifact binding, exact name mapping, exactly one
  SBOM per package family, no unexpected sibling files, and no host paths or secret
  values.
- The generator never uploads. SBOMs enter the same validated release-assets bundle
  and are attached to a release only by the existing upload job.
- Generation is all-or-nothing: no SBOM is written unless all five were produced and
  validated.
- A required artifact without its SBOM is a release-gate failure.
- **Where to find them**: the SBOMs are ordinary GitHub Release assets next to the
  artifacts. Download `<artifact-basename>.spdx.json` and inspect it with any SPDX
  2.3 JSON tool. The SBOM's presence does not prove provenance.

<a id="PYSH-SC-PROVENANCE"></a>

## Provenance and attestations

Every mandatory published artifact has a keyless GitHub OIDC-backed artifact
attestation bound to:

- the exact repository identity, `SSobol77/pysh`;
- the exact release source commit (the Actions `GITHUB_SHA`);
- the expected release workflow identity,
  `SSobol77/pysh/.github/workflows/release-artifacts.yml`;
- the exact subject basename;
- the exact subject digest.

**Subjects** are derived from the final, already-validated `SHA256SUMS` by
`scripts/prepare_attestation_subjects.py`, never from an independent file-name list
that could drift. The release has twelve public files and all twelve are provenance
subjects:

- one SLSA provenance attestation takes its subjects from `SHA256SUMS`: the five
  package artifacts, the five `.spdx.json` SBOM files and `REPRODUCIBILITY.json`,
  with exact names and digests (eleven entries);
- `SHA256SUMS`, which intentionally does not hash itself, has its own separate
  provenance attestation (subject name `SHA256SUMS`, digest computed from the file).

**SBOM attestations**: each of the five package artifacts additionally has a signed
SPDX attestation (predicate type `https://spdx.dev/Document/v2.3`) whose subject is the
package and whose predicate is its `<artifact-basename>.spdx.json`. The `.spdx.json`
file is never itself the subject of an SBOM attestation; as a published file it is
covered by `SHA256SUMS` and by the provenance attestation.

**Verification before upload**: after the last attestation is created,
`scripts/verify_release_attestations.py` runs `gh attestation verify` for all twelve
provenance attestations and all five SBOM attestations, pinned to the repository, the
signer workflow and the exact source commit, and requires each attested SBOM predicate
to be semantically equal to the local `.spdx.json` that will be published. A missing,
renamed, duplicated, partial or digest-mismatched subject, a wrong identity, a wrong
predicate type or malformed verification output fails the job, and the validated
bundle is then never handed to the upload job. Attestations are written before they
are queried, so only the narrowly classified "attestation not visible yet" answer is
retried, with a hard bound on attempts and on wall-clock time; signature, identity,
digest and predicate failures are never retried.

The reviewed attestation action is actions/attest v4.2.2 at commit
`1e69f48acb82d1966a394da916b4c1698aa569d6`.

<a id="PYSH-SC-INTEGRITY"></a>

## Integrity

Three independent controls are required, and none substitutes for another:

1. **Checksum integrity**: `sha256sum -c SHA256SUMS`. The published `SHA256SUMS` covers
   every published release file except `SHA256SUMS` itself, that is the five package
   artifacts, their five SBOMs and `REPRODUCIBILITY.json`. It is written only after the complete asset set
   exists (a preliminary manifest of the packages is replaced), so it never lists
   itself.
2. **Provenance verification**: the attestation is verified against the expected
   repository identity, signer workflow and subject digest.
3. **SBOM attestation verification**: the signed SPDX predicate of a package is
   verified and compared with the published SBOM.

Checksum validation is not provenance verification, and provenance verification is not
SBOM verification: they are complementary controls and none replaces another.

<a id="PYSH-SC-VERIFY"></a>

## Verification procedure

Verification is online by default and needs no repository write access or maintainer
credentials. Download the release assets into one directory, then:

```text
sha256sum -c SHA256SUMS

gh attestation verify <artifact> \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml
```

For stronger release verification, also pin the release source commit:

```text
gh attestation verify <artifact> \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
  --source-digest <release-source-SHA>
```

To verify the signed SPDX SBOM of a package artifact:

```text
gh attestation verify <package> \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
  --predicate-type https://spdx.dev/Document/v2.3
```

The only accepted repository identity is `SSobol77/pysh` and the only accepted signer
workflow is `SSobol77/pysh/.github/workflows/release-artifacts.yml`. Treat any failure
as a denial. A checksum match does not prove provenance, and a valid provenance
attestation does not prove that an SBOM is the one shipped; verify all three.

<a id="PYSH-SC-FAIL-CLOSED"></a>

## Fail-closed policy

When policy requires verification of an artifact or package:

- missing verification material -> DENY
- invalid signature or attestation -> DENY
- unexpected signer or repository identity -> DENY
- subject or digest mismatch -> DENY
- verification infrastructure error -> DENY, unless a documented release-gate
  contract classifies it as `PLATFORM_BLOCKED` or `INFRASTRUCTURE_BLOCKED`

There is no fail-open installation or release path for something whose policy
requires verification.

<a id="PYSH-SC-TRUST-ROOT"></a>

## Trust-root distribution and rotation

- **Online**: verification uses the current GitHub and Sigstore trust chain
  directly.
- **Offline**: when offline verification is required, a maintainer or user obtains
  a trusted-root snapshot from the upstream GitHub/Sigstore trust-root
  distribution, records where and when it was obtained, and verifies against that
  snapshot. With the GitHub CLI:

  ```text
  gh attestation trusted-root > trusted_root.jsonl
  gh attestation download <artifact> --repo SSobol77/pysh
  gh attestation verify <artifact> \
    --repo SSobol77/pysh \
    --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
    --bundle <downloaded-bundle>.jsonl \
    --custom-trusted-root trusted_root.jsonl
  ```

  `trusted_root.jsonl` is public verification material. The repository does not
  bundle one, because a committed copy would go stale when the upstream root rotates.
- **Review cadence**: a cached snapshot is reviewed and refreshed at least once per
  release and whenever the upstream root is rotated.
- **Rotation**: rotation of the trust root happens upstream and is handled by
  refreshing the snapshot. It never requires rebuilding or reinstalling PySH
  runtime packages.
- A trust-root snapshot is verification material. It is not a PySH signing key.

<a id="PYSH-SC-REPRODUCIBILITY"></a>

## Reproducibility

Reproducibility is measured, never assumed. The only valid statuses are:

- `REPRODUCIBLE`
- `NON_REPRODUCIBLE`
- `NOT_YET_MEASURED`
- `PLATFORM_BLOCKED`

**Definition.** An artifact is `REPRODUCIBLE` only when the same source commit, the
same declared build contract and toolchain, and two independent clean build roots
produce byte-for-byte identical public artifacts. The comparison is SHA-256 equality of
the two files, computed by the measurement harness itself. Semantic equivalence is never
reproducibility. If the bytes differ the result is `NON_REPRODUCIBLE`, a measured result
that records the reason (how the archives differ) and whose release impact is reviewed in
the readiness audit (#35). `PLATFORM_BLOCKED` means the host genuinely cannot build the
family; `NOT_YET_MEASURED` means no A/B build was attempted. An unattempted build is never
reported as reproducible. A build that fails is an error, not a classification.

**A/B methodology.** `scripts/measure_release_reproducibility.py` extracts the exact
source commit twice (`git archive`, or a host-provided archive of that commit) into two
separate source/build roots, checks that both trees are identical, and runs the existing
repository builder in each: `scripts/build_pysh_package.sh` (wheel and sdist, measured
and classified independently), `scripts/build_deb.sh`, `scripts/build_rpm.sh` and
`scripts/build_freebsd_pkg.sh`. The extracted tree has the file modes a `git checkout` creates
under umask 022 (`git archive` records group-writable modes that a checkout does not have).
The two builds share no `dist/`, `build/`, staging tree or output file, run under a private
home and temporary directory with a fixed locale, time zone and umask (022, also the default
of GitHub-hosted runners: package directory modes depend on it), and are bounded by a timeout. Filenames reported by a builder are never trusted: the
canonical names are validated. No artifact is renamed, copied between builds or rewritten
after the build.

**SOURCE_DATE_EPOCH policy.** The only deterministic build epoch is the commit timestamp of
the exact source commit (`git log -1 --format=%ct`), never wall-clock time. It was adopted
after measurement: without it, two independent Debian builds differ because `dpkg-deb`
records the build-time modification times of the staging directories; with it the clamped
timestamps no longer vary. The release workflow exports the same epoch for the shipped
builds. It changes only timestamps, no package contents, and no output is normalized after
the build. The RPM builder needed an explicit control: the first real dry run showed
`rpmbuild` ignoring the epoch (it records the build time and the modification times of the
files and directories it creates, so a package built from a checkout differed from the A/B
builds). `scripts/build_rpm.sh` therefore enables the standard rpm macros
`use_source_date_epoch_as_buildtime` and `clamp_mtime_to_source_date_epoch` whenever
`SOURCE_DATE_EPOCH` is set, and was confirmed with a real `rpmbuild`. For the FreeBSD
package, `scripts/build_freebsd_pkg.sh` passes the same value to pkg's native reproducible
timestamp control, `pkg create -t "${SOURCE_DATE_EPOCH}"` (decimal digits only; an unset or
empty epoch leaves the ordinary manual build unchanged and no timestamp is ever invented).
PySH does not rewrite the resulting `.pkg`, and the release-byte binding still requires the
shipped package to equal build A or build B. Whether the FreeBSD package is actually
reproducible is established only by the native FreeBSD 14.4 measurement, not assumed.

**Platform requirements.** The RPM measurement needs a real `rpmbuild`; without one the
result is `PLATFORM_BLOCKED`, never a substitute. A FreeBSD `.pkg` is measured only by a
native FreeBSD builder (the FreeBSD 14.4 reference job) with the real pkg tooling; on any
other host the only valid result is `PLATFORM_BLOCKED`. Placeholder, renamed or emulated
packages are never evidence.

**Resolved toolchain.** The evidence records the exact versions that performed the build,
separately from what pyproject.toml merely declares. For wheel and sdist the build backend
floats within its declared requirement (`declared_requirements`), so the real `hatchling`
resolved version is read from the pip log of the isolated build environments (`PIP_LOG`) and
corroborated by the `Generator` line of the built wheel; builds that resolved different
versions, or a version that cannot be proven, are errors. A measured result must carry exact
resolved versions: Python, `build` and `hatchling` for wheel and sdist, `dpkg-deb` for the
Debian package, `rpmbuild` for the RPM, and `pkg` and Python for the FreeBSD package. A
requirement such as `>=1.27.0` is never a version.

**Release-byte binding.** A measurement of two build roots says nothing about the artifact
that ships unless the two are tied together. With `--release-dir` the harness hashes the
already-staged public artifact (it is only read, never copied into the release tree) and
records `release_sha256`, `release_matches_build_a` and `release_matches_build_b`. The release
artifact must equal build A or build B: for `REPRODUCIBLE` it therefore equals both, for
`NON_REPRODUCIBLE` it must equal at least one measured output. If it equals neither, the
evidence does not describe the shipped bytes and the measurement fails. Local evidence may
omit the binding only when measured before a release artifact exists, and such evidence never
satisfies final mode.

**Evidence.** Each result records the family, the canonical artifact name, the source
commit, the A and B SHA-256, the equality result, the classification, the platform,
architecture and Python version, the tool versions, the epoch and its origin, the source
tree digest of both builds, the independence of their roots and outputs, the release-byte binding, and a diagnostic.
`scripts/check_reproducibility_evidence.py` validates the schema (version 1) and the
semantics: the classification cannot contradict the hashes, families are unique and known,
the source commit is bound, and a RPM or FreeBSD result needs the real tooling and platform, and tool versions must be exact.
Local mode accepts `PLATFORM_BLOCKED` and `NOT_YET_MEASURED` with a diagnostic; final mode
requires all five families to be measured (`REPRODUCIBLE` or `NON_REPRODUCIBLE`) on their
required platform and rejects `PLATFORM_BLOCKED` and `NOT_YET_MEASURED`.

**Publication.** The merged final evidence is published as `REPRODUCIBILITY.json`. It is
created after the SBOMs and before the final `SHA256SUMS`, so it is listed in the checksums
and is a provenance subject; it does not depend on the provenance bundle. The Linux job
measures wheel, sdist, deb and rpm; the native FreeBSD reference job measures `freebsd_pkg`;
the two are combined only when both succeeded.

**Release policy.** Measurement must exist for every family and a missing measurement blocks
the release. `REPRODUCIBLE` is preferred; `NON_REPRODUCIBLE` is permitted only with a
documented reason, no evidence of source or artifact substitution, a reviewed impact in #35,
and a shipped artifact that still equals a measured build (a family whose builds differ from
one another and from the shipped bytes cannot yield final evidence). Reproducibility and provenance are independent controls: provenance says who built the
artifact from which source, reproducibility says whether the build can be repeated, and
neither implies the other. No claim that PySH artifacts are reproducible is made beyond
what the recorded measurements show; the final Tier-1 measurement is Slice 5.

Recorded baseline: the Issue #51 Slice 5 dry run (workflow run 37166005508, source
f642eaa5707456b2ecfa7696919bef2dfa5c4fa6, package version 0.9.1). The statuses below are
those measured results, validated in final mode; the digests are in
[supply-chain-evidence.md](supply-chain-evidence.md).

| Family | A/B build environment | Status |
| --- | --- | --- |
| `wheel` | Ubuntu 24.04 GitHub-hosted runner, Linux/Python 3.13 | REPRODUCIBLE |
| `sdist` | Ubuntu 24.04 GitHub-hosted runner, Linux/Python 3.13 | REPRODUCIBLE |
| `deb` | Ubuntu 24.04 GitHub-hosted runner, dpkg-deb | REPRODUCIBLE |
| `rpm` | Ubuntu 24.04 GitHub-hosted runner, rpmbuild | REPRODUCIBLE |
| `freebsd_pkg` | native FreeBSD 14.4 reference VM, pkg | REPRODUCIBLE |

These statuses are the Issue #51 / 0.9.1 assurance baseline and prove the mechanism. They do
not transfer to v1.0.0: the v1.0.0 release must rerun the full pipeline on its exact final
release candidate SHA and record its own results. A local developer measurement never changes
them.

<a id="PYSH-SC-PIPELINE"></a>

## Pipeline ordering

The release upload job stays the only job that attaches validated GitHub Release
assets. The current boundary is preserved and later extended:

```text
freebsd-pkg -> build-and-validate -> dist/release-assets -> upload -> GitHub Release
```

The release flow is strictly ordered, and the hand-off to the upload job happens only
after step 9:

1. build
2. package smoke and static validation
3. stage canonical release artifacts
4. SBOM generation
5. reproducibility evidence (A/B measurement, combined into `REPRODUCIBILITY.json`)
6. SHA256SUMS finalization
7. artifact-set validation
8. provenance and attestation generation
9. attestation verification against the exact subjects
10. upload of the validated release bundle

No SBOM generator, attestation helper or signing action may upload release assets
itself; doing so would bypass the validate-to-upload boundary.

<a id="PYSH-SC-PYPI"></a>

## PyPI

PyPI publication remains on **Trusted Publishing**:
`.github/workflows/publish.yml` is the only PyPI publication workflow and uses
GitHub OIDC. There is no second PyPI publisher and no token-based or `twine`
publication path. PyPI attestations and GitHub Release attestations are related but
separate surfaces.

<a id="PYSH-SC-ECOSYSTEM"></a>

## Future ecosystem packages

For any future ecosystem package (plugin, theme or profile) whose policy requires
signature or attestation verification, installation is **default-deny**: missing or
invalid verification material, an unexpected signer or a digest mismatch prevents
installation. There is no fail-open path for such a package.

<a id="PYSH-SC-RELEASE-EVIDENCE"></a>

## Release evidence

Before a production release, maintainers must be able to show the release source
SHA, tag and version consistency, checksum completeness, SBOM completeness,
attestation completeness and identity, reproducibility status, native package
validation status, the exact artifact set attached to the release, and that the PyPI
Trusted Publishing path was unchanged. This evidence is consumed directly by the
readiness audit in Issue #35 and must be linked there before v1.0.0 approval.

The reviewed baseline for Issue #51 is [supply-chain-evidence.md](supply-chain-evidence.md):
a real successful `workflow_dispatch` run (run 37166005508, source
f642eaa5707456b2ecfa7696919bef2dfa5c4fa6, package version 0.9.1) with its attestation IDs, its
per-family reproducibility results, the two fail-closed historical runs and the acceptance
mapping. It distinguishes the tested source SHA from the later evidence-record commit, which is
not itself attested. For v1.0.0 the same pipeline must run again on the final release SHA and
that run must be linked in the Issue #35 audit next to the baseline.
