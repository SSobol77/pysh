<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/shell/security-sensitive-input.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Sensitive Input Security Boundary

PySH treats passwords, passphrases, PINs, and other secret terminal input as a
strict security boundary. For ordinary external commands such as `sudo`, `ssh`,
`su`, and `gpg`, PySH starts the child process and leaves the controlling
terminal attached to that child. When those programs ask for a secret, they
normally read directly from the controlling terminal with echo disabled. PySH is
the parent process; it is not in the password byte path and does not see the
keypress stream.

This boundary is deliberate. A shell that observes secret keystrokes can leak
content, timing, length, or behavioral metadata through bugs, logs, plugins,
history, crash reports, terminal redraw state, or future code paths. PySH
therefore keeps the default external-command path simple: the child process and
the terminal own sensitive input.

## What PySH Does Not Do

PySH does not intercept, read, count, store, log, or buffer password bytes.

PySH does not reveal password length. In particular, it does not implement
one-star-per-character password feedback.

PySH does not determine password correctness and does not change any indicator
color based on whether a secret is valid.

PySH does not proxy, wrap, or mediate ordinary external commands automatically.
Commands such as `sudo`, `ssh`, `su`, and `gpg` inherit the terminal unchanged
unless the user explicitly invokes `secure <cmd>`.

PySH does not use `sudo -S`, parse prompts such as `[sudo] password`, or
auto-wrap `sudo`.

PySH does not modify the external-command path to observe keystrokes.

PySH's custom raw-mode line editor is only for PySH's own command line. It must
not be repurposed to read passwords for external processes.

## Why A Normal `sudo` Indicator Cannot Exist

For a normal command such as `sudo apt update`, `sudo` reads the password from
the controlling terminal with terminal echo disabled. PySH does not receive
those bytes. It cannot know that a keypress occurred without inserting itself
between the terminal and `sudo`.

That insertion would require a PTY proxy architecture: PySH would allocate a
pseudoterminal, run the child process behind it, forward terminal traffic, and
observe keyboard activity while the child is asking for a secret. That is
exactly the default architecture this security boundary forbids. It creates a
new password-path component and therefore a new high-value failure mode.

As a result, PySH cannot and must not show a keypress indicator for ordinary
`sudo`, `ssh`, `su`, `gpg`, or similar commands.

## Explicit `secure <cmd>` Wrapper

PySH provides one explicit PTY wrapper:

```sh
secure <command> [args ...]
```

For example:

```sh
secure sudo -v
```

This wrapper is opt-in for each invocation. It is not applied to ordinary
commands, aliases, command substitution, or the normal external-command path.
The command `sudo apt upgrade` still runs exactly as a normal external command;
only `secure sudo apt upgrade` uses the PTY bridge.

The wrapper forwards bytes between the user's terminal and the child PTY. It
does not persist password bytes, does not append PTY input to history, and does
not parse prompts. Sensitive-input phase is inferred only from the child PTY
terminal `ECHO` flag. If that termios state cannot be read, PySH treats the
phase as inactive and shows no indicator.

When configured and enabled, `secure` may show a fixed-width cyclic indicator
while the child PTY has echo disabled. In ring mode, the indicator renders a
constant number of slots such as `* * * * *`; each keypress advances one
volatile active slot modulo the configured slot count. It must not grow one
symbol per keypress, reveal password length, expose content, store input, log
keystrokes, or infer password correctness. It must not become permanently green
on success or red on failure.

## Indicator Configuration

PySH exposes configuration for the explicit `secure` indicator:

- `enabled`
- `symbol`
- `idle_color`
- `active_color`
- `mode`
- `slots`

These options do not change the REPL, the raw line editor, prompt rendering, or
normal external-command execution. Even when `enabled` is `True`, the indicator
is active only inside an explicit `secure <cmd>` invocation. If `enabled` is
`False`, `secure <cmd>` still runs the PTY bridge without the visual indicator.

`mode="ring"` is the default indicator mode and accepts `slots` in the inclusive
range `3..9`. `mode="single-blink"` remains available for compatibility.

## Security trust model

This document describes the sensitive-input boundary in isolation.  For the
full security and trust model — including trust levels, execution surfaces,
static import policy, and diagnostics non-mutation policy — see
[Security and Trust Model](../architecture/security-trust-model.md).
