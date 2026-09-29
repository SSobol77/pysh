<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/release-notes-0.9.1.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# PySH 0.9.1 Release Notes

PySH 0.9.1 is a maintenance release focused on installation portability,
native package safety, and release correctness. It is not the PySH 1.0 feature
release.

## Highlights

- PySH requires CPython 3.13.0 or newer. Compatible 3.13 patch releases and
  compatible newer minor releases are accepted; no upper Python version is
  intentionally imposed.
- Debian-family support is distribution-release-independent and includes
  compatible Debian, Ubuntu, Kali Linux, Linux Mint, and Pop!_OS systems.
- RPM-family support is distribution-release-independent and includes
  compatible Fedora, RHEL, Rocky Linux, AlmaLinux, and CentOS Stream systems.
- FreeBSD/GhostBSD runtime support is release-independent when the host
  provides the required Python and Unix facilities.
- Debian 13, Fedora 43, and FreeBSD 14.4 are reference test environments, not
  installation allowlists.
- Debian/RPM launchers validate actual interpreter versions and can use a
  compatible versioned `python3.N` when the generic `python3` is too old.
- FreeBSD packaging keeps the canonical `pysh-shell-0.9.1.pkg` filename while
  preserving and validating the archive's real native `pkg` ABI.
- FreeBSD package manifests, installed wrappers, and native smoke tests now use
  one consistently selected Python target.
- FreeBSD PTY CI installs Bash, renders the platform's erased Ctrl+D echo
  correctly, and checks every PTY exit/quit invocation for readiness gating.

## Reference FreeBSD package

The GitHub Release includes one official reference prebuilt package:

```text
pysh-shell-0.9.1.pkg
```

It is built on FreeBSD 14.4 amd64 with CPython 3.13. Its embedded native ABI
may prevent installation on a different FreeBSD ABI. That is an archive
compatibility boundary, not a PySH runtime-support boundary. Do not force an
ABI-mismatched install. On another compatible FreeBSD/GhostBSD host, install
through Python packaging or build the canonical `.pkg` on that host.

## Release assets

The flat GitHub Release asset contract is:

```text
pysh_shell-0.9.1-py3-none-any.whl
pysh_shell-0.9.1.tar.gz
pysh-shell_0.9.1-1_all.deb
pysh-shell-0.9.1-1.noarch.rpm
pysh-shell-0.9.1.pkg
SHA256SUMS
```

## Validation status

Local Linux validation proves source contracts, the full pytest suite,
wheel/sdist clean installs, and locally available package builds. It does not
prove a native FreeBSD install. Before publication, release-blocking CI must
pass the real Debian package install, real RPM package install, and the
FreeBSD 14.4 native build/metadata/install/CLI/PTY smoke.

The platform/runtime/installability foundation from Issue #52 is delivered in
0.9.1. Remaining v1.0 assurance evidence and milestone bookkeeping continue
from the post-release mainline baseline.
