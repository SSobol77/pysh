<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/platform-tiers.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH v1.0 Platform Tier Contract

This document is the normative source for PySH v1.0 operating-system,
architecture, Python-version, and validation claims. It deliberately separates
the runtime compatibility policy from the exact environments that produce
release evidence. A CI reference version is an evidence anchor, not a runtime
allowlist.

Shell-language compatibility is defined separately in
[the shell compatibility contract](shell-compatibility-contract.md). This
contract determines the Unix facilities PySH requires and where that behavior
is validated.

## Support and evidence classifications

| Classification | Meaning | CI and release consequence |
| -------------- | ------- | -------------------------- |
| **Reference-validated** | An exact OS/version/architecture/Python environment has a declared release-blocking behavioral, package, or performance lane. | Every declared gate must pass. Missing or failing evidence blocks an acceptable v1.0 release. |
| **Supported by runtime policy** | The environment belongs to a declared family, runs CPython `>=3.13`, supplies the required POSIX/Unix facilities, and has no documented incompatibility. | PySH intends to operate there. The policy is not a claim that every combination has its own CI lane. |
| **Supported, not independently reference-validated** | A combination is inside a supported runtime family but has no exact dedicated validation lane. | A failure is a compatibility defect to investigate, but absence of per-combination CI is not evidence that the environment is unsupported. Fixes must preserve reference gates. |
| **Unsupported / unvalidated family** | The OS family is not declared supported, Python is older than 3.13, required Unix facilities are absent without a documented fallback, or a known incompatibility is documented. | No v1.0 behavior, package, conformance, performance, or release-evidence promise applies. |

“Supported” therefore describes a runtime family and capability set. “Validated”
describes evidence from an exact controlled environment. Neither word may be
used as a substitute for the other.

## Runtime-family matrix

| Runtime family | Python policy | Runtime policy | Current reference evidence |
| -------------- | ------------- | -------------- | -------------------------- |
| Debian-family Linux | CPython `>=3.13` | Supported when required POSIX/Linux facilities exist | Debian 13 / amd64 / CPython 3.13 focused native behavioral gate and `.deb` install smoke |
| RPM-family Linux | CPython `>=3.13` | Supported when required POSIX/Linux facilities exist | `fedora:43` real RPM install-and-run smoke on the amd64 Linux CI runner; package metadata requires `python3 >= 3.13` |
| FreeBSD | CPython `>=3.13` | Supported when required FreeBSD/POSIX facilities exist | FreeBSD 14.4 / amd64 / CPython 3.13 behavioral and performance baseline; native FreeBSD 14/15 amd64 `.pkg` matrix |
| Other OS families | — | Unsupported/unvalidated unless explicitly added | None |

PySH requires CPython 3.13 or newer. CPython 3.13 is the current
release-validation baseline. Compatible newer CPython versions are inside the
runtime version policy, but do not acquire independent per-version evidence
until a corresponding lane is added.

Consequently, Debian with CPython 3.14, another compatible Debian-family
release, a compatible Fedora/RHEL-family system, or another compatible FreeBSD
release is not automatically unsupported. Such a combination is supported by
runtime policy when it supplies the required facilities, while remaining not
independently reference-validated.

Python `<3.13`, non-POSIX/non-Unix platforms, undeclared OS families, and hosts
missing required process, signal, descriptor, PTY, termios, or wait semantics
without a supported fallback are outside the v1.0 runtime policy.

## Release-reference evidence

### Broad Linux regression infrastructure

GitHub's `ubuntu-latest` image implements the broad Linux full-suite, language
conformance, build, quality, and Linux performance jobs. It is not a
user-facing Ubuntu support promise. The full suite complements, but does not
replace, native reference and package evidence.

### Debian reference

The `platform-debian` job runs a focused platform-sensitive gate inside
`debian:13-slim` on amd64 with CPython 3.13. It verifies the image ID/version
only to protect reference-lane integrity; PySH startup does not reject other
Debian-family releases. The gate covers language conformance, parser/runtime
portability, PTY/editor/termios behavior, resize and signals, job control and
process groups, redirection and descriptor isolation, safe startup, and this
repository policy. Ordinary CI separately performs a real Debian 13 `.deb`
install-and-run smoke.

### RPM package reference

The current RPM package reference is the pinned `fedora:43` container used by
`scripts/smoke_rpm_package.sh`. It installs the local `.rpm` through `dnf`,
requires the container's `python3` to satisfy `>=3.13`, and exercises installed
command, module, batch, and real-PTY entry points. This is package-path evidence,
not a claim that every Fedora, RHEL, Rocky Linux, AlmaLinux, or other RPM-family
release has independent behavioral CI.

### FreeBSD reference

The `platform-freebsd` job runs in a real FreeBSD 14.4 amd64 VM with CPython
3.13. It gates language conformance; parser/runtime portability; real PTY and
editor behavior; termios restoration; resize and signal handling; job control
and process groups; redirection and descriptor isolation; strict `--no-rc`
startup; this repository policy; and the FreeBSD performance profile.

Native `.pkg` evidence remains separate in `release-artifacts.yml`: a
major-version matrix builds FreeBSD 14 and FreeBSD 15 amd64 packages on their
target ABI, inspects the embedded ABI with native `pkg` tooling, installs only
the package matching the VM's native ABI with `pkg add`, and exercises
non-interactive and real-PTY entry points. A package pass cannot replace the
behavioral gate, and a performance pass cannot replace either.

The historical `freebsd-32-36-validation.yml` workflow remains specialized
evidence for Issues #32 and #36. Its branch-only trigger and explicitly
non-gating broad diagnostic do not satisfy the current reference contract.

## FreeBSD package Python target

PySH source and runtime policy supports CPython `>=3.13`. One native FreeBSD
`.pkg`, however, is built against one explicit compatible interpreter; a
single package is not interpreter-version agnostic.

`PYSH_FREEBSD_PYTHON_VERSION` selects that package target. It defaults to
`3.13`, rejects malformed versions and values below 3.13, and derives the
interpreter, dependency package, and origin together. For example:

| Selection | Interpreter | Dependency | Origin |
| --------- | ----------- | ---------- | ------ |
| `3.13` | `/usr/local/bin/python3.13` | `python313` | `lang/python313` |
| `3.14` | `/usr/local/bin/python3.14` | `python314` | `lang/python314` |

Current release CI explicitly selects 3.13. A future release may select a
newer compatible interpreter only through an explicit package/CI decision and
native validation; the runtime policy alone does not certify that package.

The Python selection does not determine OS ABI compatibility. `pkg create`
embeds a FreeBSD ABI such as `FreeBSD:14:amd64`; the builder reads that metadata,
requires it to equal the native build host ABI, and derives the release filename
from it. Current release assets are
`pysh-shell-X.Y.Z-freebsd14-amd64.pkg` and
`pysh-shell-X.Y.Z-freebsd15-amd64.pkg`. The smoke gate compares the embedded
package ABI with `pkg config ABI` before installation and never force-installs a
cross-major package.

## OS-dependent behavior

| Surface | Supported runtime contract | Capability unavailable |
| ------- | -------------------------- | ---------------------- |
| TTY detection | Interactive terminal behavior requires standard input and output to report `isatty()`. `TERM` must be non-empty and not `dumb` for the VT-style raw editor. | Non-TTY input uses batch behavior; an unsuitable terminal uses the plain input/readline path. Color preferences do not disable paste safety. |
| PTY allocation | `pty.openpty()` provides a real master/slave pair for native PTY tests and the explicit `secure` bridge. The child receives a controlling terminal where supported. | `secure` has no transparent direct-execution fallback. A missing PTY in a reference environment is a blocking defect; another environment needs an explicit unsupported diagnostic before its behavior can be claimed. |
| termios | The editor saves attributes before raw mode, uses bounded terminal operations, and restores attributes in `finally`; the secure bridge does the same when its input is a TTY. | Raw-editor setup failure falls back to the plain input path. After raw mode begins, restoration failure is a defect and must not be hidden. |
| Terminal restoration | Ctrl+C, Ctrl+D, normal return, parse errors, and child exit must leave the terminal usable; bracketed-paste mode and temporary signal handlers are removed. | There is no silent degraded success. Process-exit restoration is a last-resort safeguard, not primary control flow. |
| SIGINT | Prompt interruption recovers the prompt and records status 130; foreground child interruption maps to 130. | A platform without POSIX SIGINT semantics is outside the supported runtime policy. |
| SIGTERM | A child terminated by SIGTERM maps to status 143; bounded cleanup paths may use SIGTERM before stronger termination. | A platform without the required signal/wait semantics is outside the supported runtime policy. |
| SIGTSTP and job control | An interactive foreground job may stop with SIGTSTP, becomes a stopped job, and maps to status 148. `fg`/`bg` operate on the recorded process group. | Without a controlling TTY or job-control APIs, PySH must not claim foreground handoff. Non-interactive execution remains available; interactive job-control absence must be explicit. |
| Process groups | Children are placed in process groups; the foreground pipeline owns the terminal while it runs; the shell regains foreground ownership in `finally`. | If process-group creation or ownership transfer fails, PySH must fail that job-control operation deterministically and recover shell ownership; it must not pretend handoff succeeded. |
| File descriptors | Redirection ordering is preserved, unrelated child descriptors use close-on-exec/`close_fds=True`, and temporary PTY, pipe, TTY, and redirection descriptors are closed on every path. | A feature that cannot preserve its descriptor-isolation invariant must fail closed. Tests may skip only when this contract explicitly permits the capability to be absent. |
| Filesystem | PySH relies on POSIX path and permission behavior, `/dev/tty` for interactive ownership when available, executable permission bits, local-file replacement used by its stores, and writable user-selected config/history locations. | Missing `/dev/tty` selects the non-job-control path. An unavailable requested file produces the documented filesystem diagnostic; PySH must not invent a substitute path. |
| Temporary files | Standard-library temporary directories/files are private where requested and are removed during normal and failure cleanup. | Creation failure aborts the requesting operation with an OS-derived diagnostic; no shared predictable fallback path is allowed. |
| Executable lookup | External commands use explicit argv execution and `PATH`/`execvp`-equivalent lookup; not found is 127 and not executable is 126. | No implicit shell delegation or guessed executable location is permitted. |
| Package installation | Debian uses `pysh-shell_X.Y.Z-1_all.deb`, RPM-family systems use `pysh-shell-X.Y.Z-1.noarch.rpm`, and FreeBSD publishes `pysh-shell-X.Y.Z-freebsd14-amd64.pkg` plus `pysh-shell-X.Y.Z-freebsd15-amd64.pkg`. Installed command/module and PTY smoke tests must pass in each declared package reference. | Source/wheel success cannot replace a failed native reference package smoke; a FreeBSD package for another ABI must be rejected before installation. |
| Native format | Debian evidence uses `dpkg`/`apt`, RPM evidence uses `rpm`/`dnf`, and FreeBSD evidence uses `pkg(8)`. | Cross-platform extraction, renamed placeholders, and contract-only fixtures are not native install evidence. |

## Linux-specific mechanisms

Linux-only mechanisms may be used only inside a Linux implementation adapter,
a Linux-specific diagnostic, or a Linux-specific test. They may not leak into
the portable parser, execution, plugin, or editor contract.

In particular, `/proc/self/fd` is a Linux-specific descriptor-enumeration
probe. It is not a portable PySH abstraction or a FreeBSD precondition. A
future descriptor-leak test that uses it must either be Linux-only or call a
platform-aware probe that selects an equivalent native implementation.

## FreeBSD-specific mechanisms

FreeBSD behavior must be validated without mounting, emulating, or assuming a
Linux `/proc` filesystem. A descriptor-accounting test may use deterministic
native facilities such as `fstat`, or a bounded `os.fstat()` scan when its
descriptor range is derived safely. The probe must distinguish “no leak” from
“probe unavailable”; probe absence is not a passing result.

FreeBSD PTYs, termios, signals, `waitpid`, process groups, foreground ownership,
and native packages are tested through FreeBSD execution, not inferred from
Linux results.

## Capability fallback policy

Every platform-sensitive feature must declare its required capability before
support for a new family or behavior is claimed. The declaration chooses one
outcome:

1. a deterministic supported fallback with equivalent safety invariants;
2. an explicit `pysh: <component>: unsupported on this platform` diagnostic
   and a documented non-zero status; or
3. a test skip expressly allowed by this contract because the feature is not
   part of that validation surface.

Silent behavior changes, a skip caused only by an unknown platform, and success
after dropping a safety invariant are defects. A reference runner missing a
required capability fails its gate; it is not silently downgraded. Tests must
distinguish a missing optional tool from failure of the probe used to establish
the result.

## Optional OS hardening and Capsicum

FreeBSD Capsicum is the architectural anchor for a possible future, explicit
opt-in hardening adapter. Such an adapter would require native capability
detection, fail-closed setup before untrusted work, documented broker/resource
access, and native FreeBSD tests. If Capsicum is absent or disabled, the only
permitted current fallback is the existing portable isolated-process contract;
PySH must not report kernel confinement.

PySH v1.0 does **not** implement or claim Capsicum confinement. Issue #44
isolated plugins provide process separation, bounded versioned IPC, a scrubbed
environment/private working directory, descriptor hygiene, and a parent
capability broker. The child retains the same OS user authority, and direct
filesystem, network, and process syscalls are not kernel-sandboxed. The broker
limits parent-mediated authority; it is not a filesystem or network sandbox.

## Changing this contract

Adding a runtime family requires an explicit contract and capability review.
Adding reference evidence requires controlled CI/package/performance lanes and
focused policy tests. Changing an exact runner label, Python baseline, package
target, or artifact does not silently broaden or narrow the runtime-family
policy. Demotion or removal requires an explicit documented change and release
communication.
