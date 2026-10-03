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
(Slice 2) and keyless provenance and SBOM attestations with verification before
upload (Slice 3) are implemented; reproducibility measurement and the final evidence
run are implemented in later slices.** Attestations are created and verified only by
the release workflow when it runs on GitHub; nothing in this repository creates one
locally, and an SBOM is not provenance.

| Capability | Status |
| --- | --- |
| Policy, anchors and structural contract check | IMPLEMENTED (Slice 1) |
| SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2) |
| Keyless provenance and SPDX SBOM attestations, verified before upload | IMPLEMENTED (Slice 3) |
| Reproducibility measurement | DEFERRED (Slice 4) |
| Final Tier-1 dry-run release evidence | DEFERRED (Slice 5) |

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
are themselves release subjects once they are published as release assets.

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
that could drift. The release has eleven public files and all eleven are provenance
subjects:

- one SLSA provenance attestation takes its subjects from `SHA256SUMS`: the five
  package artifacts and the five `.spdx.json` SBOM files, with exact names and digests;
- `SHA256SUMS`, which intentionally does not hash itself, has its own separate
  provenance attestation (subject name `SHA256SUMS`, digest computed from the file).

**SBOM attestations**: each of the five package artifacts additionally has a signed
SPDX attestation (predicate type `https://spdx.dev/Document/v2.3`) whose subject is the
package and whose predicate is its `<artifact-basename>.spdx.json`. The `.spdx.json`
file is never itself the subject of an SBOM attestation; as a published file it is
covered by `SHA256SUMS` and by the provenance attestation.

**Verification before upload**: after the last attestation is created,
`scripts/verify_release_attestations.py` runs `gh attestation verify` for all eleven
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
   artifacts and their five SBOMs. It is written only after the complete asset set
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

A `NON_REPRODUCIBLE` result is a measured result to be documented with its known
source of variance and release impact. A check may become release-blocking only
after its policy classification is defined. Measurement evidence records the source
commit, canonical basename, build A and build B SHA256, the equality result, the
relevant platform and tool versions, and the classification.

| Family | A/B build environment | Status |
| --- | --- | --- |
| `wheel` | controlled Linux/Python build | NOT_YET_MEASURED |
| `sdist` | controlled Linux/Python build | NOT_YET_MEASURED |
| `deb` | controlled Debian builder | NOT_YET_MEASURED |
| `rpm` | controlled Fedora/RPM builder | NOT_YET_MEASURED |
| `freebsd_pkg` | native FreeBSD reference builder | NOT_YET_MEASURED |

<a id="PYSH-SC-PIPELINE"></a>

## Pipeline ordering

The release upload job stays the only job that attaches validated GitHub Release
assets. The current boundary is preserved and later extended:

```text
freebsd-pkg -> build-and-validate -> dist/release-assets -> upload -> GitHub Release
```

The release flow is strictly ordered, and the hand-off to the upload job happens only
after step 8:

1. build
2. package smoke and static validation
3. stage canonical release artifacts
4. SBOM generation
5. SHA256SUMS finalization
6. artifact-set validation
7. provenance and attestation generation
8. attestation verification against the exact subjects
9. upload of the validated release bundle

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
