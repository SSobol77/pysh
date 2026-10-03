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

**Issue #51 defines the supply-chain contract. SPDX 2.3 JSON SBOM generation is
implemented (Slice 2); provenance and attestations, reproducibility measurement and
the final evidence run are implemented in later slices.** Nothing in this document
claims that attestations or signatures exist yet, and an SBOM is not provenance.

| Capability | Status |
| --- | --- |
| Policy, anchors and structural contract check | IMPLEMENTED (Slice 1) |
| SPDX 2.3 JSON SBOM generation | IMPLEMENTED (Slice 2) |
| Keyless artifact attestations and verification before upload | DEFERRED (Slice 3) |
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

Any attestation action added later must be pinned to an immutable commit SHA in the
release workflow, with minimal explicit workflow permissions.

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

Every mandatory published artifact must have a keyless GitHub OIDC-backed artifact
attestation bound to:

- the exact repository identity, `SSobol77/pysh`;
- the exact release source commit;
- the expected release workflow identity;
- the exact subject basename;
- the exact subject digest.

Subjects are derived from the already-validated release artifact set and its
`SHA256SUMS`, never from an independent file-name list that could drift. A missing,
renamed, duplicated or digest-mismatched required subject is a release-gate failure.

<a id="PYSH-SC-INTEGRITY"></a>

## Integrity

Two independent controls are required, and neither substitutes for the other:

1. **Checksum integrity**: `sha256sum -c SHA256SUMS`. The published `SHA256SUMS` covers
   every published release file except `SHA256SUMS` itself, that is the five package
   artifacts and their five SBOMs. It is written only after the complete asset set
   exists (a preliminary manifest of the packages is replaced), so it never lists
   itself.
2. **Provenance verification**: the attestation is verified against the expected
   repository identity and the expected subject digest.

<a id="PYSH-SC-VERIFY"></a>

## Verification procedure

This procedure is the policy; it becomes executable when attestations exist
(Slice 3). Verification is online by default and needs no repository write access
or maintainer credentials.

```text
sha256sum -c SHA256SUMS
gh attestation verify <artifact> --repo SSobol77/pysh
```

The only accepted repository identity is `SSobol77/pysh`. A user verifies a
downloaded artifact by checking its checksum, then verifying its attestation
against that identity and digest, and treating any failure as a denial.

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
  snapshot.
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

The hardened flow, to be implemented in later slices, is strictly ordered:

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
