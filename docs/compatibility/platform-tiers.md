<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/platform-tiers.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Platform Support and Reference Evidence

This document is the normative source for PySH v1.0 operating-system,
architecture, Python-version, and platform-validation claims. It deliberately
separates runtime support from the exact environments that produce release
evidence. An exact CI version is an evidence anchor, not a runtime allowlist.

## Support and evidence classifications

| Classification | Meaning | Validation consequence |
| --- | --- | --- |
| **Reference-validated** | An exact OS/version/architecture/Python environment has a declared behavioral, package, or performance lane. | The declared gate must pass whenever that evidence is required. |
| **Supported by runtime policy** | The environment belongs to a declared runtime family, runs CPython `>=3.13`, supplies the required Unix/POSIX facilities, and has no documented incompatibility. | PySH intends to operate there. This does not imply a dedicated CI lane for every combination. |
| **Supported, not independently reference-validated** | The environment is inside the runtime policy but has no exact dedicated evidence lane. | Lack of a dedicated lane is not evidence that the environment is unsupported. |
| **Unsupported / unvalidated family** | The OS family is undeclared, Python is older than 3.13, or required facilities are unavailable without a documented fallback. | No v1.0 platform-support claim applies. |

“Supported” describes a runtime family and required capability set.
“Reference-validated” describes evidence from an exact controlled environment.

## Platform validation tiers

The tier label describes the strength of release evidence for a supported
runtime family. It is not an installation allowlist and does not replace the
runtime-family policy.

| Tier | Evidence obligation | Current family/reference evidence |
| --- | --- | --- |
| **Tier 1** | At least one exact native reference environment runs the required release-blocking behavioral and language-conformance suite. Platform-sensitive PTY, termios, signal, process-group, descriptor, startup, and policy checks are required. | Debian-family Linux: Debian 13 / amd64 / CPython 3.13. FreeBSD family: FreeBSD 14.4 / amd64 / CPython 3.13. |
| **Tier 2** | The runtime family is supported by policy and has controlled package-path or other focused native evidence, but does not currently have a dedicated full behavioral/conformance reference lane. | RPM-family Linux: `fedora:43` native RPM install-and-run evidence. |
| **No dedicated reference tier** | A combination is inside a supported Tier 1 or Tier 2 runtime family but has no exact independent reference lane of its own. | Examples include Debian with CPython 3.14 and other compatible releases inside the declared families. |

Tier 1 therefore requires native CI/conformance evidence. Tier 2 is not
“unsupported”; it records a lower level of independent reference evidence.
Neither tier restricts a supported family to the exact OS or Python version
used by its current reference environment.

## Runtime-family matrix

| Runtime family | Included systems | Python policy | Current reference evidence |
| --- | --- | --- | --- |
| Debian-family Linux | Debian, Ubuntu, Kali Linux, Linux Mint, Pop!_OS, and compatible derivatives | CPython `>=3.13` | Debian 13 / amd64 / CPython 3.13 platform-reference gate and Debian package smoke |
| RPM-family Linux | Fedora, Red Hat Enterprise Linux, Rocky Linux, AlmaLinux, CentOS Stream, and compatible derivatives | CPython `>=3.13` | `fedora:43` native RPM install-and-run smoke |
| FreeBSD family | FreeBSD and GhostBSD | CPython `>=3.13` | FreeBSD 14.4 / amd64 / CPython 3.13 behavioral and performance references, plus native package validation evidence |
| Other OS families | — | — | Unsupported/unvalidated unless explicitly added |

PySH requires CPython 3.13 or newer. Compatible newer CPython versions are
inside the runtime policy; CPython 3.13 is the current release-validation
baseline.

There is no upper Python-version bound. Consequently, Debian with CPython
3.14, another compatible Debian-family release, a compatible RPM-family
release, or another compatible FreeBSD-family release is not automatically
unsupported merely because that exact combination does not have its own CI
lane.

Operating-system release numbers used by CI therefore protect evidence
reproducibility. They do not define product installation allowlists.

## Release-reference evidence

### Broad Linux regression infrastructure

The ordinary GitHub Actions `ubuntu-latest` jobs execute the broad test suite,
language conformance, package builds, release-contract checks, and the Linux
performance profile. That infrastructure is broad regression evidence; it is
not a user-facing promise tied to one Ubuntu release.

### Debian reference

The `platform-debian` job runs inside `debian:13-slim` on amd64 with CPython
3.13. It verifies the exact environment to protect the integrity of the
reference lane.

The gate covers:

- shell-language conformance;
- parser and runtime portability;
- PTY, terminal resize, termios, and signal behavior;
- process groups and job control;
- redirection and descriptor isolation;
- safe startup plus rc/pyshrc behavior;
- this repository platform-policy contract.

The exact Debian 13 image is evidence, not a Debian-family runtime minimum.

### RPM package reference

`scripts/smoke_rpm_package.sh` uses the pinned `fedora:43` container as native
RPM package-path evidence. It installs the locally built package with `dnf`
and exercises installed command, module, batch, and real-PTY behavior.

The RPM metadata requires `python3 >= 3.13`. Fedora 43 is therefore a package
reference, not a claim that every supported RPM-family host has independent
behavioral CI.

### FreeBSD reference

The `platform-freebsd` job runs in a real FreeBSD 14.4 amd64 VM with CPython
3.13. It covers the same platform-sensitive behavioral surfaces as the Debian
reference using native FreeBSD PTY, termios, process, signal, and descriptor
behavior.

A separate `performance-freebsd` job executes the
`freebsd-14-4-python3-13` performance profile. Platform validation and
performance validation intentionally remain separate jobs.

Native package evidence is produced by
`.github/workflows/release-artifacts.yml`. Its current `freebsd-pkg` matrix
contains:

- FreeBSD 14.4 as `freebsd-reference-pkg`; and
- a FreeBSD 15.x validation leg as `freebsd-validation-15`.

The FreeBSD 14.4 output is the single official `.pkg` promoted into the flat
GitHub Release assets. The FreeBSD 15.x output remains workflow validation
evidence and is not promoted as a second public `.pkg` release asset.
Additional package-validation legs do not broaden or narrow the FreeBSD-family
runtime policy and do not turn their exact releases into installation
allowlists.

### Fuzz and property evidence (Issue #49)

Robustness evidence for the parser and pipeline descriptor handover has two
classes, and platform support depends only on the first.

**Tier 1 portable required evidence** (Debian 13 and FreeBSD 14.4, run through
`scripts/check_fuzz_evidence.sh` in `platform-debian` and `platform-freebsd`):

- deterministic parser property tests;
- conformance-derived seed and mutation replay (Issue #48 is the only
  language oracle);
- permanent regression-record replay;
- portable file-descriptor and pipeline robustness, using a bounded
  `os.fstat()` scan rather than Linux `/proc` or `/dev/fd`.

This evidence needs no Atheris and no unprivileged account.

**Linux reference additional evidence**: coverage-guided Atheris fuzzing
(`.github/workflows/fuzz-nightly.yml`, scheduled and manual only). Atheris is a
Linux x86_64 development dependency.

**FreeBSD** runs the same portable deterministic acceptance evidence and makes
no coverage-guided claim. Coverage-guided engine availability is not platform
support: the absence of Atheris on FreeBSD does not downgrade its Tier 1
status, and Atheris results are never presented as FreeBSD evidence. Native
FreeBSD execution of this evidence is established only by a passing
`platform-freebsd` CI run.

## Native package compatibility

The Debian `all` and RPM `noarch` payloads use a compatible installed CPython
whose actual version is 3.13 or newer. The shared launcher validates the
interpreter at runtime and does not impose an upper Python minor-version
bound.

The official GitHub Release asset uses the canonical basename:

`pysh-shell-X.Y.Z.pkg`

It is a reference prebuilt package produced on FreeBSD 14.4 amd64 with
CPython 3.13. Its embedded native FreeBSD ABI can restrict installation of
that archive. The generic filename does not make the archive ABI-independent.

Package ABI compatibility and PySH runtime-family support are separate
contracts. An ABI mismatch must never be bypassed with force-install options.
A compatible FreeBSD or GhostBSD host whose ABI does not match the reference
archive can install through Python packaging or build the canonical `.pkg`
locally.

## FreeBSD package Python target

PySH source and runtime policy support CPython `>=3.13`. One native FreeBSD
`.pkg`, however, is built against one explicitly selected compatible Python
minor; a single package is not interpreter-version agnostic.

`PYSH_FREEBSD_PYTHON_VERSION` selects that package target and defaults to
`3.13`. The package helper derives all of the following from the same
selection:

- `PYSH_FREEBSD_PYTHON_COMMAND`;
- `PYSH_FREEBSD_PYTHON_PACKAGE`;
- `PYSH_FREEBSD_PYTHON_ORIGIN`.

Current release CI explicitly selects CPython 3.13.

Python selection does not determine OS ABI compatibility. The package builder
and smoke validation separately compare the embedded package ABI with the
native FreeBSD host ABI before installation.

## OS-dependent behavior

| Surface | Supported runtime contract | Capability unavailable |
| --- | --- | --- |
| TTY detection | Interactive terminal behavior requires native TTY detection. The VT-style raw editor also requires a suitable `TERM`. | Non-TTY input uses batch behavior; an unsuitable terminal uses the documented plain-input path. |
| PTY allocation | Native PTYs back interactive integration tests and the explicit secure bridge. | A required PTY missing from a reference environment fails the reference gate; there is no silent direct-execution substitute for a secure PTY operation. |
| termios | Terminal attributes are saved before raw mode and restored on normal and exceptional paths. | Failure after raw mode begins must not be hidden as successful execution. |
| Terminal restoration | Ctrl+C, Ctrl+D, normal return, parse errors, and child exit must leave the terminal usable. | Silent degraded success is not permitted. |
| Signals | POSIX signal/wait behavior supplies the documented shell status mapping, including SIGINT status 130 and SIGTERM status 143. | A platform lacking required POSIX signal semantics is outside the supported runtime policy unless an explicit equivalent contract is added. |
| Job control | Interactive foreground jobs use process groups and foreground-terminal ownership. | Without the required APIs PySH must not claim successful foreground handoff. |
| File descriptors | Redirection ordering is preserved and unrelated child descriptors remain isolated. Temporary descriptors are closed on all paths. | A feature unable to preserve descriptor-isolation invariants must fail closed. |
| Filesystem | PySH relies on Unix/POSIX path, permission, executable-bit, and local-file semantics. | Missing requested files or paths produce explicit filesystem errors rather than invented substitutes. |
| Temporary files | Standard-library private temporary locations are used where required and cleaned up on success and failure paths. | Creation failure aborts the requesting operation; no shared predictable fallback is allowed. |
| Executable lookup | External commands use explicit argv execution and PATH lookup. Not-found maps to 127 and not-executable maps to 126. | PySH must not silently delegate an unresolved command to another shell. |
| Native packaging | Debian uses `.deb`, RPM-family systems use `.rpm`, and FreeBSD/GhostBSD use host-compatible `.pkg` artifacts. | Source/wheel success does not convert a failed required native package reference into a pass. |

## Linux-specific mechanisms

Linux-only facilities may be used only by Linux-specific implementation,
diagnostic, or test paths. They must not become requirements of the portable
parser, runtime, plugin, or editor contracts.

In particular, `/proc/self/fd` is Linux-specific and is not a portable PySH
abstraction. Descriptor-leak checks that use it must remain Linux-specific or
be hidden behind a platform-aware probe.

## FreeBSD-specific mechanisms

FreeBSD validation must work without mounting, emulating, or assuming a Linux
`/proc` filesystem.

Descriptor accounting can use native FreeBSD facilities such as `fstat`, or a
bounded `os.fstat()` scan when its descriptor range is derived safely. A probe
must distinguish “no leak” from “probe unavailable”; failure of the probe is
not automatically a passing result.

FreeBSD PTYs, termios, signals, `waitpid`, process groups, foreground-terminal
ownership, and native packages are validated through FreeBSD execution rather
than inferred from Linux results.

## Capability fallback policy

Every platform-sensitive feature must have one of these explicit outcomes when
a required capability is unavailable:

1. a deterministic supported fallback preserving the required safety
   invariants;
2. an explicit `pysh: <component>: unsupported on this platform` diagnostic
   with a documented non-zero status; or
3. a test skip explicitly permitted because the capability is outside that
   test's declared validation surface.

Silent behavior changes, skips caused only by an unknown platform, and success
after dropping a required safety invariant are defects. A reference runner
missing a required capability fails its gate rather than being silently
downgraded.

## Optional OS hardening and Capsicum

FreeBSD Capsicum is an architectural option for future explicit hardening, not
a current v1.0 security claim.

PySH v1.0 does **not** implement or claim Capsicum confinement. The current
isolated-plugin runtime provides a process/protocol boundary, descriptor
hygiene, controlled environment handling, and brokered parent operations. The
child still executes with the authority of the same OS user. The broker is not
a filesystem or network sandbox.

## Changing this contract

Adding a runtime family requires an explicit capability and contract review.

Adding reference evidence requires a controlled platform, package, or
performance lane plus repository-policy tests.

Changing an exact runner version, Python validation baseline, native package
target, or workflow artifact does not silently broaden or narrow the runtime
family policy.

Removing or narrowing declared runtime support requires an explicit documented
change and release communication.
