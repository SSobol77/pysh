<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/supply-chain-evidence.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Supply-Chain Assurance Evidence

This is the permanent, reviewed evidence baseline for Issue #51. It records one real,
successful end-to-end run of the release-assurance pipeline defined in
[supply-chain.md](supply-chain.md), the two earlier runs that failed closed, and what the
readiness audit (Issue #35) can verify from it. It is checked structurally by
`scripts/check_supply_chain_contract.py`, which stays offline: this document is the
repository-owned record, and nothing here is fetched from GitHub at check time.

## Scope

The run below exercised the mechanism on a `workflow_dispatch` dry run of
`.github/workflows/release-artifacts.yml` for package version 0.9.1. It proves that the
Issue #51 supply-chain mechanism works before v1.0.0. It is **not** the final v1.0.0
release attestation: the actual v1.0.0 release must rerun the same assurance pipeline on its
final release SHA. No release, tag, PyPI publication or GitHub Release asset upload was made.

## Tested Source Identity

Two commits are involved, and they must not be confused.

- **Tested source SHA** (the commit that was built, measured, signed and verified):
  `f642eaa5707456b2ecfa7696919bef2dfa5c4fa6`.
- **Evidence-record commit** (the later commit that adds this document): it built, measured
  and attested nothing, and it is not itself attested. A commit cannot contain its own SHA;
  identify it with `git log -1 -- docs/security/supply-chain-evidence.md`. Its only changes
  are documentation, checker and test files, and the evidence below refers to the tested
  source SHA only.

| Field | Value |
| --- | --- |
| Tested source SHA | f642eaa5707456b2ecfa7696919bef2dfa5c4fa6 |
| Package version | 0.9.1 |
| Source tree digest (SHA-256) | 7c539a38fae270024fe70a0080fc178839d412090bab044871840f133444cd97 |
| Build epoch (SOURCE_DATE_EPOCH) | 1791074759, the commit timestamp of the tested source SHA |
| Run date | 2026-10-04 |

## Workflow Evidence

| Field | Value |
| --- | --- |
| Workflow | .github/workflows/release-artifacts.yml |
| Workflow run | 37166005508 |
| Run URL | https://github.com/SSobol77/pysh/actions/runs/37166005508 |
| Event | workflow_dispatch |
| Branch | issue/51-supply-chain-hardening |
| Conclusion | success |
| Job: FreeBSD 14.4 reference | success |
| Job: FreeBSD 15 validation | success |
| Job: build-and-validate | success |
| Job: GitHub Release upload | SKIPPED |

The release-upload job did not run because `github.event_name != release`.

## Platform Evidence

| Role | Platform | Tooling |
| --- | --- | --- |
| Linux builds and A/B measurement | Ubuntu 24.04 GitHub-hosted runner (ubuntu-24.04), x86_64 | Python 3.13.15, build 1.6.1, twine 7.0.0, hatchling 1.32.4 (resolved), dpkg-deb 1.22.6, fakeroot 1.33, rpmbuild 4.18.2 |
| FreeBSD reference package (official) | FreeBSD 14.4-RELEASE amd64 VM | pkg 2.8.4, Python 3.13.15 |
| FreeBSD validation | FreeBSD 15 amd64 VM | build plus install-and-run smoke only; it does not replace the 14.4 reference result and takes no part in the reproducibility evidence |

Build contract of the measured builds: `LC_ALL=C.UTF-8`, `TZ=UTC`, `umask 0022`, private home
and temporary directories, `SOURCE_DATE_EPOCH` equal to the commit timestamp of the tested
source SHA. SPDX SBOMs were generated with Anchore Syft 1.54.0 (pinned archive SHA-256
`54a87372498168b2d033e876fd41fa4e8035b872699e525a57046e1f2f09c860`, executed on the Linux
runner). Attestations were created with actions/attest v4.2.2, pinned to the immutable commit
`1e69f48acb82d1966a394da916b4c1698aa569d6`.

## Reproducibility Results

Machine-readable source: `REPRODUCIBILITY.json` in the run's `release-assets` artifact,
validated in final mode (`scripts/check_reproducibility_evidence.py --mode final`). For every
family the release artifact, build A and build B are byte-identical (SHA-256), the two build
roots and outputs were independent, and both builds read the same source tree.

| Family | Classification | Release, build A and build B SHA-256 |
| --- | --- | --- |
| wheel | REPRODUCIBLE | 7a2eb8fbe4ff5c27c26f1120bd8862e435e5cbe4f7a44d2b435a51e7b0e4a4a1 |
| sdist | REPRODUCIBLE | d3158114502345567026594f88e4dd2b23bc94fee2b48ae4dca1b3a5029b78af |
| deb | REPRODUCIBLE | 3172db948a7ff20ece0ff3a30e9bf6705c09a471344f309d935bfc89d270b26d |
| rpm | REPRODUCIBLE | 501a0350339449806a00c824eb19e78eb77edea5f77793004f6f15b19106b75c |
| freebsd_pkg | REPRODUCIBLE | ece9a025e6882c93a6b810ea42b0b9f8796662518895b553028c8e2c0abd1c07 |

This is a measured result for the tested source SHA and these toolchain versions, not a claim
about any other commit or environment. The RPM and FreeBSD results depend on the explicit
timestamp controls added after the two historical runs below.

## Release Artifact Set

12 public files: 5 package artifacts, 5 SPDX SBOM files, `REPRODUCIBILITY.json` and
`SHA256SUMS`.

| File | SHA-256 |
| --- | --- |
| pysh_shell-0.9.1-py3-none-any.whl | 7a2eb8fbe4ff5c27c26f1120bd8862e435e5cbe4f7a44d2b435a51e7b0e4a4a1 |
| pysh_shell-0.9.1.tar.gz | d3158114502345567026594f88e4dd2b23bc94fee2b48ae4dca1b3a5029b78af |
| pysh-shell_0.9.1-1_all.deb | 3172db948a7ff20ece0ff3a30e9bf6705c09a471344f309d935bfc89d270b26d |
| pysh-shell-0.9.1-1.noarch.rpm | 501a0350339449806a00c824eb19e78eb77edea5f77793004f6f15b19106b75c |
| pysh-shell-0.9.1.pkg | ece9a025e6882c93a6b810ea42b0b9f8796662518895b553028c8e2c0abd1c07 |
| pysh_shell-0.9.1-py3-none-any.whl.spdx.json | 36c2298da6e42afaadc9fa531136e88f7dd5849445e24f5f0abebc5c469af225 |
| pysh_shell-0.9.1.tar.gz.spdx.json | 878779cc0ac310af80c0f938740b9ad736fe7de7ae51b6e29022c6b0aa408c33 |
| pysh-shell_0.9.1-1_all.deb.spdx.json | f74c39ab5402924052a13a04719db3fef75418336106ad1bb448a195b211df9c |
| pysh-shell-0.9.1-1.noarch.rpm.spdx.json | 8a4782fea9437c0af9eb07261aaf6cad9ed12a728c1c50c008c8134b9e691c97 |
| pysh-shell-0.9.1.pkg.spdx.json | 5aee3d67851253c54a3321d3f2a0ffcabe508b893292e364a78fbf05600820b9 |
| REPRODUCIBILITY.json | 99719f35f4d4060428329cd579b7485f913b12383a2895737c2ff44bff83f5be |
| SHA256SUMS | 8a5be167e4cfe31cf1ad695dfef0e92b646a3dd7f30d62f21725c3dba01080e5 |

## SHA-256 Integrity

| Field | Value |
| --- | --- |
| Release files | 12 |
| SHA256SUMS entries | 11 |
| SHA256SUMS lists itself | no |
| `sha256sum -c SHA256SUMS` on the downloaded bundle | OK for all 11 entries |

`SHA256SUMS` covers the 5 packages, the 5 SBOM files and `REPRODUCIBILITY.json`; it does not
contain its own digest and is attested separately. The run's workflow artifacts (GitHub artifact
digests): release-assets `169393a6b5ec56bfbf293999cb1c011d5b0e1da49975824b301e84876f3d12f6`,
freebsd-reproducibility-evidence
`0c4ba5bc3137844ed2eff22feb1de3981f1a7dcf2470f080d6d06b30cbddac45`.

## SBOM Evidence

One SPDX 2.3 JSON SBOM per package family, named `<artifact-basename>.spdx.json`, generated
only from the validated staged bytes, with the artifact digest bound into the described root
package, and validated (`scripts/generate_release_sboms.py validate-bundle`: structure,
artifact binding, no host-path or secret leakage, no unexpected files). The wheel and `.deb`
SBOMs list the PySH package; the sdist and FreeBSD `.pkg` SBOMs list only the bound artifact
because the tool has no cataloger for those payloads. Catalog depth is an inventory property,
not provenance. The SBOM tooling never uploads anything.

## Provenance Evidence

12 provenance subjects: the 11 entries of `SHA256SUMS` (one attestation over all of them) and
`SHA256SUMS` itself (separate attestation). 5 signed SPDX SBOM attestations, one per package,
predicate type `https://spdx.dev/Document/v2.3`, subject = the package, predicate = its SBOM.

| Field | Value |
| --- | --- |
| Provenance subjects | 12 |
| SPDX SBOM attestations | 5 |

| Attestation | ID |
| --- | --- |
| provenance, 11 SHA256SUMS subjects | 52499029 |
| provenance, SHA256SUMS | 52499033 |
| SPDX SBOM wheel | 52499037 |
| SPDX SBOM sdist | 52499040 |
| SPDX SBOM deb | 52499044 |
| SPDX SBOM rpm | 52499052 |
| SPDX SBOM freebsd_pkg | 52499055 |

Public URLs have the form `https://github.com/SSobol77/pysh/attestations/<ID>`.

## Attestation Verification

`scripts/verify_release_attestations.py` ran real `gh attestation verify` before the workflow
artifact hand-off and reported: 12 provenance attestations verified and 5 SPDX SBOM
attestations verified. Each verification was pinned to the repository `SSobol77/pysh`, the
signer workflow `SSobol77/pysh/.github/workflows/release-artifacts.yml` and the source digest
`f642eaa5707456b2ecfa7696919bef2dfa5c4fa6`. Each attested SBOM predicate was compared with the
published `.spdx.json`. The real `gh attestation verify --format json` output matched the
verifier's expected shape. No attestation-visibility retry was needed.

## Trust Model

GitHub Actions workflow identity, a GitHub OIDC token, a short-lived Sigstore certificate and
the GitHub Artifact Attestations service. There is no long-lived private signing key, no GPG or
cosign key and no signing secret; only `build-and-validate` holds `id-token`, `attestations` and
`artifact-metadata` write permission, and the `upload` job holds only `contents: write`. PyPI
Trusted Publishing (`publish.yml`) is unchanged. Offline verification uses a refreshed public
trust root, which is verification material and not a PySH signing key.

## Publication Boundary

| Field | Value |
| --- | --- |
| Release upload job | SKIPPED |
| GitHub Release created | no |
| Tag created | no |
| PyPI publication | no |
| Release assets attached | none |

The only job that can attach release assets is `upload`, which needs `build-and-validate` and
runs only on a real `release` event. The run was a `workflow_dispatch` dry run.

## Historical Negative Evidence

Two earlier real runs failed closed. They are negative-control evidence that the release-byte
binding works, not unresolved release failures: both stopped before any attestation, before
attestation verification and before the release hand-off, and the release upload stayed skipped.

| Run | Source SHA | Result | Meaning |
| --- | --- | --- | --- |
| 37164782394 | 86be6f60e948df8a119598575619377839f5009b | failed in the Linux measurement | the staged RPM did not match the A/B RPM bytes: the release-byte binding caught RPM timestamp nondeterminism (fixed by enabling the rpm epoch macros) |
| 37165299323 | 12067296c6d184daaeaed1ca6e373d4acd312605 | failed at the cross-platform merge | the staged FreeBSD `.pkg` did not match the native A/B bytes: the release-byte binding caught FreeBSD package timestamp nondeterminism (fixed with `pkg create -t`) |

## Residual Limitations

- The evidence is for source SHA f642eaa5707456b2ecfa7696919bef2dfa5c4fa6 and version 0.9.1.
  The final v1.0.0 release must rerun the assurance pipeline on its final SHA; this record does
  not replace that run and is not the final v1.0.0 release attestation.
- The evidence-record commit is not itself attested.
- The failure paths of the attestation verifier (missing, invalid or wrongly identified
  attestation) are proven by hermetic tests against a fake GitHub CLI, not by a real invalid
  attestation. The real run proves the success path and the real output shape.
- Reproducibility is measured for this commit and toolchain. The build backend floats within its
  declared requirement, so a later run may resolve a newer `hatchling`; the resolved version is
  recorded per run.
- The sdist and FreeBSD `.pkg` SBOMs list only the bound artifact.
- The FreeBSD 15 leg is validation evidence (build and smoke), not a reproducibility result.
- The workflow was not run on a `release` event, by design.

## Issue #51 Acceptance Mapping

Every row has an implementation, a test and real evidence; a row without all three is a FAIL.
Tests are in `tests/` (the contract checker's structural rules are in
`tests/test_supply_chain_contract.py`).

| Acceptance item | Implementation | Test | Evidence | Result |
| --- | --- | --- | --- | --- |
| SPDX SBOM generated for all five package families | scripts/generate_release_sboms.py | tests/test_release_sbom.py | five .spdx.json files in run 37166005508; validate-bundle OK | PASS |
| SBOM format SPDX 2.3 JSON | SPDX_VERSION and validate_document in the generator | tests/test_release_sbom.py | five documents validated as SPDX-2.3; predicate type verified | PASS |
| Public SBOM filenames tied to canonical package basenames | sbom_name in the generator | tests/test_release_sbom.py | file names in the Release Artifact Set | PASS |
| Final SHA256SUMS covers all public files except itself | check_release_artifacts.sh --finalize-release-assets; validate_checksums | tests/test_release_sbom.py | sha256sum -c OK, 11 entries, no self-listing | PASS |
| Exact source provenance | actions/attest with --source-digest pinned in the verifier | tests/test_release_attestations.py | 12 provenance attestations verified for f642eaa | PASS |
| Canonical subject names | scripts/prepare_attestation_subjects.py | tests/test_release_attestations.py | subjects derived from the final SHA256SUMS | PASS |
| Canonical subject digests | scripts/prepare_attestation_subjects.py | tests/test_release_attestations.py | subject digests equal the file digests | PASS |
| Repository identity pinned | PINNED_REPO in scripts/verify_release_attestations.py | tests/test_release_attestations.py | verification pinned to SSobol77/pysh | PASS |
| Signer workflow pinned | PINNED_SIGNER_WORKFLOW in the verifier | tests/test_release_attestations.py | verification pinned to the release-artifacts workflow | PASS |
| Source digest pinned | --source-digest in the verifier | tests/test_release_attestations.py | verification pinned to f642eaa | PASS |
| Verification before handoff | ATT-ORDER rules in scripts/check_supply_chain_contract.py | tests/test_supply_chain_contract.py | verification step precedes the workflow-artifact hand-off in run 37166005508 | PASS |
| Fail closed on missing or invalid attestation | scripts/verify_release_attestations.py | tests/test_release_attestations.py | real success path verified; failure paths proven against a fake gh | PASS |
| No release upload bypass | WF-UPLOAD-BYPASS rules; the upload job is the only uploader | tests/test_supply_chain_contract.py | upload job skipped | PASS |
| No long-lived private signing key | WF-SECRETS and ATT-ALTERNATIVE rules | tests/test_supply_chain_contract.py | no signing secret in the workflow | PASS |
| GitHub OIDC and Sigstore trust model | job permissions and actions/attest in the workflow | tests/test_supply_chain_contract.py | 7 attestations created by the workflow identity | PASS |
| PyPI Trusted Publishing preserved | .github/workflows/publish.yml unchanged; WF-PYPI rules | tests/test_supply_chain_contract.py | publish.yml has no diff against develop/v1.0.0 | PASS |
| User verification documented | PYSH-SC-VERIFY in docs/security/supply-chain.md | tests/test_supply_chain_contract.py | documented commands | PASS |
| Maintainer verification documented | docs/development/release.md verification step | tests/test_supply_chain_contract.py | gh attestation verify in the release checklist | PASS |
| Trust-root rotation documented | PYSH-SC-TRUST-ROOT in supply-chain.md | tests/test_supply_chain_contract.py | documented policy | PASS |
| Future ecosystem verification is default-deny | PYSH-SC-ECOSYSTEM in supply-chain.md | tests/test_supply_chain_contract.py | documented policy | PASS |
| Reproducibility measured for all five package families | scripts/measure_release_reproducibility.py | tests/test_release_reproducibility.py | five REPRODUCIBLE results in REPRODUCIBILITY.json | PASS |
| Shipped-byte binding | bind_release in the measurement harness | tests/test_release_reproducibility.py | release equals build A and build B for every family | PASS |
| Exact resolved toolchain evidence | tools and EXACT_VERSION_RE in the evidence validator | tests/test_release_reproducibility.py | resolved versions in Platform Evidence | PASS |
| RPM deterministic build | rpm epoch macros in scripts/build_rpm.sh | tests/test_release_reproducibility.py | rpm REPRODUCIBLE; negative control run 37164782394 | PASS |
| Native FreeBSD deterministic build | pkg create -t in scripts/build_freebsd_pkg.sh | tests/test_release_reproducibility.py | freebsd_pkg REPRODUCIBLE; negative control run 37165299323 | PASS |
| Real FreeBSD 14.4 evidence | measurement harness in the 14.4 VM | tests/test_release_reproducibility.py | FreeBSD 14.4-RELEASE amd64, pkg 2.8.4 | PASS |
| FreeBSD 15 validation | the freebsd-pkg matrix in the workflow | tests/test_release_workflow_contract.py | FreeBSD 15 job success | PASS |
| Real GitHub attestation creation | actions/attest steps in the workflow | tests/test_supply_chain_contract.py | attestation IDs 52499029 to 52499055 | PASS |
| Real gh attestation verification | scripts/verify_release_attestations.py | tests/test_release_attestations.py | 12 provenance and 5 SBOM attestations verified | PASS |
| Release upload skipped for workflow_dispatch | the upload job is gated on the release event | tests/test_supply_chain_contract.py | upload job skipped | PASS |
| Historical fail-closed negative controls | release-byte binding in the harness and merge | tests/test_release_reproducibility.py | runs 37164782394 and 37165299323 | PASS |
| Release Quality Gate integration | scripts/release_gate.py | tests/test_release_gate.py | gate fast mode PASS; full mode reports PLATFORM_BLOCKED on hosts that cannot build a family | PASS |
| Issue #35 evidence handoff | the Issue #35 Handoff section and docs/development/release.md | tests/test_supply_chain_contract.py | this document | PASS |

## Issue #35 Handoff

This record is the mandatory supply-chain evidence input to the PySH v1.0.0 readiness audit
(Issue #35). The audit can verify from this document and the repository:

- exact source identity: the tested source SHA, the package version and the source tree digest;
- packaging coverage: all five package families built from that commit, with canonical names;
- SBOM coverage: five SPDX 2.3 documents, one per family, bound to the artifact digests;
- provenance: 12 attested subjects and 5 SBOM attestations, with the attestation IDs above;
- attestation verification: real `gh attestation verify` pinned to repository, signer
  workflow and source digest, run before the hand-off;
- reproducibility: five measured families in `REPRODUCIBILITY.json`, each bound to the shipped
  bytes, with the resolved toolchain;
- fail-closed behaviour: the two negative-control runs and the hermetic failure-path tests;
- publication boundary: the upload job skipped, no release, no tag, no PyPI publication.

For v1.0.0 the same pipeline must run again on the final release SHA, and the audit must link
that run next to this baseline.
