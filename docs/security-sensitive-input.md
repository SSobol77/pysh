<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security-sensitive-input.md
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
unless the user explicitly invokes a future wrapper designed for that purpose.

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

## Only Safe Future Direction

The only acceptable future design is an explicit user-invoked PTY wrapper, for
example `secure <cmd>` or `pty <cmd>`. The command name, semantics, warnings,
and implementation details are not active today.

Such a wrapper would have to be opt-in for each invocation. It may show one
fixed blinking symbol on keyboard activity, changing for example from white to
green and back to white. It must not show one symbol per keypress, reveal
password length, expose content, store input, write secret-adjacent data to
history, log keystrokes, or infer password correctness.

The wrapper would also need separate design and verification evidence for
terminal restoration, signal forwarding, echo-mode transitions, child exit
handling, paste handling, audit behavior, plugin isolation, and failure modes.
None of that runtime behavior exists in this release.

## Reserved Configuration Surface

PySH reserves an inert configuration surface for a possible future sensitive
input indicator. The options are validated and stored only:

- `enabled`
- `symbol`
- `idle_color`
- `active_color`
- `mode`

These options do not change the REPL, the raw line editor, prompt rendering, or
external-command execution. They are activated only by a future explicit PTY
wrapper if that wrapper is designed, implemented, reviewed, and tested
separately.
