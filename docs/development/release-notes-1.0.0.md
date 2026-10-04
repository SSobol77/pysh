<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/release-notes-1.0.0.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH v1.0.0

Release date: 2026-10-04 (candidate preparation; the publication date is the
date of the GitHub Release)

## Summary

PySH 1.0.0 is the first stable release of PySH, a Python-first interactive shell
and script runner for Debian-family Linux, RPM-family Linux, and FreeBSD-family
systems. It requires **CPython 3.13 or newer** and has no runtime dependencies.
1.0.0 adds no new shell feature family. It makes PySH's guarantees explicit,
enforced by checks, and test-backed: a frozen public API, enforced architecture
boundaries, a documented security model, a normative language specification, bounded
robustness and performance contracts, a platform tier contract, and a verifiable
supply chain for every release artifact.

**PySH is Python-first.** It is not `/bin/sh` and must not replace it. It is not a
Bash, Zsh, or Fish clone. Legacy shells appear only as migration and differential
test references; the documented PySH language specification and compatibility
documents are the contract.

## Highlights

- **Stable public API.** `pysh.api` (`ShellSession` and the contract protocols) is
  the supported embedding surface, covered by an API snapshot test, SemVer, and a
  minimum two-minor deprecation lifecycle. `pysh.shell.PyShell` is deprecated and
  is not removed before PySH 1.2.0.
- **Normative language specification (version 1)** with a declarative conformance
  corpus; unsupported constructs are specified and diagnosed.
- **Security model.** A published threat model, deterministic `--no-rc` safe
  startup, isolated plugins with a default-deny capability broker, structured
  diagnostics with one redaction policy, and an opt-in private audit log.
- **Bounded behavior.** Parser/tokenizer fuzz and property evidence, a resource
  governor for isolated plugins, and versioned performance budgets gated on Linux and
  FreeBSD 14.4.
- **Verifiable releases.** Five package artifacts, SPDX 2.3 SBOMs, reproducibility
  evidence, checksums, and GitHub Artifact Attestations for every release.

## Command line

- New: `pysh --credits` prints the project authors and exits with status 0, like
  `--version`: no shell, configuration or banner is started, and it needs no TTY.
  `python -m pysh --credits` is identical. All other command-line behavior
  (`--version`, `--help`, `--no-rc`, `-c`, script mode) is unchanged.

## Interactive shell

- No change to the interactive contract: multiline paste is staged and never
  auto-executed, heredocs, Ctrl+R reverse search, completion, history, and `exit` /
  `quit` behave as documented. Under `TERM=dumb` the readline fallback is used and
  its Ctrl+R searches history loaded at startup.

## Python Command Execution Layer

- No user-visible changes. One-line `py <code>` uses `exec` semantics, so an
  expression result is not echoed: use `py print(1 + 1)`.

## Configuration and plugins

- Trusted plugins (Plugin API 1.0) and `.pyshrc.py` remain trusted, in-process
  Python code. Isolated plugins run in a separate process under a versioned manifest
  and IPC protocol with explicit capability grants and resource budgets.
- Isolated plugins are **not an OS sandbox**: a same-user child keeps the operating
  system's own file, network, and process authority.

## Compatibility and migration

- Compatibility is the documented PySH contract: see the
  [compatibility documentation](../compatibility/README.md) and the
  [language specification](../spec/pysh-language.md).
- Migration helpers import safe static alias and profile entries only. PySH never
  runs `zsh` on your behalf; `zsh` is an ordinary external program.
- Active deprecations and removal-not-before releases: `pysh.shell.PyShell`,
  not before PySH 1.2.0.
- PySH does not claim Bash, Zsh, Fish, or POSIX `/bin/sh` compatibility beyond the
  documented feature matrix.

## Platforms

Support is defined by runtime family with CPython 3.13 or newer and no upper
bound. Exact versions below are evidence environments, not allowlists; see
[platform-tiers.md](../compatibility/platform-tiers.md).

| Family | Evidence | Tier |
| --- | --- | --- |
| Debian-family Linux | Debian 13 / amd64 / CPython 3.13 | Tier 1 |
| FreeBSD family | FreeBSD 14.4 / amd64 / CPython 3.13 (FreeBSD 15 is a validation lane) | Tier 1 |
| RPM-family Linux | `fedora:43` native RPM install-and-run | Tier 2 |

## Packaging

Published artifact families:

- pysh_shell-1.0.0-py3-none-any.whl
- pysh_shell-1.0.0.tar.gz
- pysh-shell_1.0.0-1_all.deb
- pysh-shell-1.0.0-1.noarch.rpm
- pysh-shell-1.0.0.pkg
- SHA256SUMS
- REPRODUCIBILITY.json
- one SPDX 2.3 JSON SBOM per package, named `<artifact-basename>.spdx.json`

That is twelve public files. PyPI package: `pysh-shell`. The FreeBSD `.pkg` is the
official FreeBSD 14.4 amd64 reference package; its embedded native ABI may prevent
installation on a different FreeBSD ABI. That is an archive boundary, not a runtime
support boundary: install through Python packaging, or build the `.pkg` on that host.

## Installation

```sh
python3.13 -m pip install pysh-shell==1.0.0
```

For `.deb`, `.rpm`, and `.pkg` installation see
[installation.md](../user/installation.md). Debian-family and RPM-family launchers
select a qualifying CPython 3.13+ interpreter.

## Verification

Download the release assets into one directory, then:

```sh
sha256sum -c SHA256SUMS

gh attestation verify <artifact> \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
  --source-digest <release-source-SHA>

gh attestation verify <package> \
  --repo SSobol77/pysh \
  --signer-workflow SSobol77/pysh/.github/workflows/release-artifacts.yml \
  --predicate-type https://spdx.dev/Document/v2.3
```

Checksum validation, provenance verification, and SBOM verification are
complementary controls. `REPRODUCIBILITY.json` records, for each package family,
two independent clean builds compared byte for byte and bound to the shipped bytes.
The full procedure, including offline trust-root verification, is in
[supply-chain.md](../security/supply-chain.md).

## Security and trust boundaries

- Trust boundaries are described in the
  [threat model](../security/threat-model.md); the isolated-plugin contract is in
  [plugin-isolation.md](../security/plugin-isolation.md).
- Release signing is keyless GitHub OIDC/Sigstore. There is no long-lived signing
  key.
- Trusted plugins, `.pyshrc.py`, and `py` execution run with the user's full
  authority by design.

## Known limitations

- No full POSIX shell grammar and no `/bin/sh` role; brace expansion is unsupported.
- No full Bash, Zsh, or Fish compatibility; see
  [limitations.md](../user/limitations.md) and the compatibility documents.
- Isolated plugins are not an operating-system sandbox.
- The FreeBSD `.pkg` is one reference archive for FreeBSD 14.4 amd64.
- The sdist and FreeBSD `.pkg` SBOMs list only the bound artifact because the SBOM
  tool has no cataloger for those payloads.
- Reproducibility is a measured result for the release commit and its recorded
  toolchain, not a general claim about other commits or environments.

## Upgrade

From 0.9.x:

    python3.13 -m pip install --upgrade pysh-shell

There are no configuration, plugin API, or command-line changes that require
migration. `pysh.shell.PyShell` still works and emits a `DeprecationWarning` on
symbol access; move embedding code to `pysh.api.ShellSession`. For `.deb`, `.rpm`
and `.pkg` upgrades, follow [installation.md](../user/installation.md).

## Validation evidence

- Readiness audit: [v1.0.0-readiness.md](v1.0.0-readiness.md).
- Final candidate evidence (CI runs, release-artifacts run, attestation IDs and the
  GO / NO-GO decision) is recorded in the Issue #35 final audit comment against the
  exact candidate commit.
- Supply-chain baseline: [supply-chain-evidence.md](../security/supply-chain-evidence.md).
- Manual user validation: [manual-validation.md](../user/manual-validation.md).

## Changes

See [CHANGELOG.md](../../CHANGELOG.md), section 1.0.0.
