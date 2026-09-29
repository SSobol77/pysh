<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/platform-tiers.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Platform Support and Reference Evidence

This document is the normative source for PySH runtime platform support.

## Runtime policy

PySH requires all of the following:

- a supported operating-system family;
- CPython 3.13.0 or newer (`sys.version_info >= (3, 13)`);
- the Unix/POSIX facilities used by the documented shell runtime.

There is no upper Python-version bound. Compatible CPython 3.13 patch
releases and compatible newer minor releases are inside the runtime policy.
Exact versions used in CI are evidence anchors, not runtime allowlists.

| Runtime family | Included systems | Python contract |
| --- | --- | --- |
| Debian-family Linux | Debian, Ubuntu, Kali Linux, Linux Mint, Pop!_OS, and compatible derivatives | CPython `>=3.13` |
| RPM-family Linux | Fedora, Red Hat Enterprise Linux, Rocky Linux, AlmaLinux, CentOS Stream, and compatible derivatives | CPython `>=3.13` |
| FreeBSD family | FreeBSD and GhostBSD | CPython `>=3.13` |

Operating-system release numbers do not define product support. A supported
family member is not automatically unsupported merely because its release is
different from a CI image.

## Reference environments

Current deterministic evidence includes Debian 13, Fedora 43, and FreeBSD
14.4 on amd64 with CPython 3.13. These are continuously tested reference
environments. They are not minimum releases, maximum releases, or installation
allowlists. Other supported-family combinations—such as Debian with CPython
3.14—are supported by policy but not independently reference-validated until
their own CI evidence exists.

## Native package compatibility

The Debian `all` and RPM `noarch` payloads use an installed interpreter whose
actual runtime is CPython 3.13 or newer. The launcher prefers a qualifying
`python3`, then checks versioned `python3.N` candidates. It does not trust an
executable name and imposes no upper minor-version limit.

The official `pysh-shell-X.Y.Z.pkg` GitHub Release asset is a reference
prebuilt package produced on FreeBSD 14.4 amd64 with CPython 3.13. Its native
`pkg` ABI is retained and may restrict installation of that particular
archive. Package ABI compatibility and PySH runtime support are separate
contracts: the generic filename does not make the archive universal, and an
ABI mismatch must never be bypassed with force-install options. Users on
another compatible FreeBSD or GhostBSD host can install via Python packaging
or build the canonical `.pkg` on that host.

A FreeBSD package targets one selected Python minor. The builder derives its
manifest dependency, installed wrapper, and smoke interpreter from
`PYSH_FREEBSD_PYTHON_VERSION` (default `3.13`). Python selection does not
determine OS ABI compatibility.

## Platform-specific facilities

`/proc/self/fd` is Linux-specific and is not a portable PySH abstraction.
FreeBSD validation uses native descriptor and terminal behavior; it does not
mount or emulate Linux `/proc`. PySH does not claim Capsicum confinement.
Plugin isolation is a process/protocol boundary, not a filesystem or network
sandbox.
