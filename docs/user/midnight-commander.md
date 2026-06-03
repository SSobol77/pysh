<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/midnight-commander.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Midnight Commander Integration

Midnight Commander (`mc`) has shell-specific concurrent subshell support.  On
the local Debian 13 / MC 4.8.33 build, the manual lists support for bash,
ash/dash, ksh variants, tcsh, zsh and fish.  PySH is a custom shell and is not
recognized by MC as a supported concurrent subshell.

`$SHELL` alone is therefore not sufficient.  Setting `SHELL=/path/to/pysh` tells
MC what shell path to inspect, but it does not make MC implement PySH's prompt,
directory and control protocol.

## PySH `mc` Wrapper

PySH provides an `mc` builtin wrapper.  The wrapper resolves the real external
`mc` executable and then applies the configured integration policy.  Explicit
paths such as `/usr/bin/mc` bypass the builtin and run the external program
directly.

Supported forms:

```sh
mc
mc -u
mc <args...>
/usr/bin/mc
```

## Configuration

Python-native configuration supports:

```python
def configure(shell):
    shell.set_mc_integration("auto")
    shell.set_mc_warning_enabled(True)
```

Allowed values:

| Mode | Behavior |
|---|---|
| `auto` | Default.  Use PySH-safe MC launch behavior when MC cannot safely use PySH as a concurrent subshell. |
| `safe` | Always launch wrapped `mc` with MC subshell disabled. |
| `subshell` | Pass wrapped `mc` through unchanged.  This is for advanced users who explicitly accept MC's shell-specific behavior. |
| `off` | Disable PySH's MC policy and pass wrapped `mc` through unchanged. |

In `auto` and `safe`, PySH adds `-u` unless the command already contains
`-u` or `--nosubshell`.  If `-U` or `--subshell` is present, PySH removes it in
these safe modes and still launches MC without a concurrent subshell.

In `auto` mode, PySH prints one warning per shell session explaining that
Ctrl+O is not a live PySH prompt in safe mode.  To suppress it:

```python
def configure(shell):
    shell.set_mc_warning_enabled(False)
```

## No-Subshell Mode

`mc -u` disables MC's concurrent subshell.  Ctrl+O then shows the previous user
screen rather than a live shell managed by MC.  The cursor may appear inactive
or stuck on that previous terminal screen; that is expected MC no-subshell
behavior, not PySH terminal corruption.

This mode does not provide MC's persistent subshell environment.  Commands typed
on MC's panel command line are still executed by MC through its normal command
execution path.

Full Ctrl+O live-shell behavior is available only with MC-supported shells such
as bash, zsh and fish.  PySH safe mode intentionally uses `-u` because MC does
not support PySH as a live Ctrl+O subshell.

## MC Environment Detection

When MC successfully starts a supported concurrent subshell, it exports
variables such as:

| Variable | Meaning |
|---|---|
| `MC_TMPDIR` | MC temporary directory for the subshell session. |
| `MC_SID` | MC subshell session/process identifier. |
| `MC_CONTROL_FILE` | Control file path when MC uses one. |
| `MC_CONTROL_FILE_NAME` | Control file name when MC uses one. |

PySH checks these variables to disable its raw-mode line editor if PySH is ever
started inside an MC-managed environment.  This detection is not sufficient by
itself for unsupported shells: if MC refuses to start PySH as a subshell, no
PySH process exists and no `MC_*` variables can be observed by PySH.

## Recommended Policy

Use the default:

```python
shell.set_mc_integration("auto")
```

Use `safe` if you want deterministic no-subshell behavior without relying on
future MC detection:

```python
shell.set_mc_integration("safe")
```

Use `subshell` only for controlled experiments after validating the exact MC
version and shell protocol behavior on your terminal.
