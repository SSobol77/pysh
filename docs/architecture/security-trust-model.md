<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/security-trust-model.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Security and Trust Model (Issue #7)

This document defines the security and trust model for PySH 0.5.x.
It describes what PySH executes, what it reads, what it delegates, and what
it explicitly does not do.  All claims in this document are backed by tests
in `tests/test_security_trust_model.py`.

---

## Scope

Issue #7 defines and enforces the security and trust model.  It does not provide:

- OS-level sandboxing, seccomp, or capability restriction.
- Privilege separation.
- Package isolation or import filtering for Python code.
- Automatic execution of foreign shell profiles.
- Any confinement mechanism for user-issued commands.

---

## Security principles

| # | Principle |
|---|-----------|
| 1 | **Explicit execution only.** PySH does not silently execute foreign shell code. |
| 2 | **Static import is not execution.** Profile importers parse text; they never execute it. |
| 3 | **Foreign profile execution is forbidden by default.** `.zshrc`, `.bashrc`, `.profile` are not executed automatically. |
| 4 | **Delegation must be explicit.** `zsh <cmd>`, `run_script`, `zsh_fallback on` are opt-in. |
| 5 | **Sensitive input is a strict boundary.** Normal commands inherit the terminal; PySH does not observe password bytes. |
| 6 | **`secure <cmd>` is opt-in.** The PTY bridge is never created for ordinary commands. |
| 7 | **Plugins and rc files are trusted local PySH code.** Not sandboxed; not foreign shell code. |
| 8 | **Python runtime is trusted in-process execution.** Not sandboxed; runs with full OS access. |
| 9 | **Diagnostics are non-mutating.** `plan`, `env_audit`, `path_audit`, `which_all`, `apt_check`, `apt_search` do not mutate system state. |
| 10 | **No security theater.** PySH does not claim sandboxing, privilege separation, capability enforcement, or safe containment of untrusted code. |

---

## Trust categories

| Trust level | Description | Examples |
|-------------|-------------|---------|
| `TRUSTED_LOCAL` | Local user-owned PySH config and code, runs in-process, not sandboxed | `~/.pyshrc`, `~/.pyshrc.py`, `~/.pyshrc.d/*.pysh`, `py` builtin |
| `TRUSTED_DELEGATED` | Explicit user delegation to an external interpreter | `zsh <cmd>`, `run_script`, `zsh_fallback on` |
| `STATIC_IMPORT` | Read-only text parse — no shell code executed | `source_zsh`, `source_zsh_profile`, `source_sh_aliases`, `compat_check` |
| `UNTRUSTED` | Not supported — automatic execution of foreign profiles or untrusted code | (no current surface) |

---

## Execution surfaces table

| Surface | Trust level | Executes code? | Mutates state? | Boundary | Owner issue |
| ------- | ----------- | :------------: | :------------: | -------- | ----------- |
| Normal external command | `TRUSTED_DELEGATED` | Yes (subprocess) | Subprocess may | Terminal inherited | — |
| Builtin command | `TRUSTED_LOCAL` | Yes (in-process) | Shell state | In-process | — |
| `py <code>` | `TRUSTED_LOCAL` | Yes (in-process Python) | Python namespace | In-process, not sandboxed | — |
| `py { ... }` | `TRUSTED_LOCAL` | Yes (in-process Python) | Python namespace | In-process, not sandboxed | — |
| `#py` (Python mode) | `TRUSTED_LOCAL` | Yes (in-process Python) | Python namespace | In-process, not sandboxed | — |
| `source` | `TRUSTED_LOCAL` | Yes (PySH rc engine) | Shell state | In-process PySH only | — |
| `~/.pyshrc` | `TRUSTED_LOCAL` | Yes (PySH rc engine) | Shell state | In-process PySH only | — |
| `~/.pyshrc.py` | `TRUSTED_LOCAL` | Yes (Python exec) | Shell config | In-process, not sandboxed | — |
| `~/.pyshrc.d/*.pysh` | `TRUSTED_LOCAL` | Yes (PySH rc engine) | Shell state | In-process PySH only | — |
| `source_zsh` | `STATIC_IMPORT` | No — text parse only | Aliases (PySH) | Static parse, no subprocess | — |
| `source_zsh_profile` | `STATIC_IMPORT` | No — text parse only | Aliases, exports | Static parse, no subprocess | — |
| `source_sh_aliases` | `STATIC_IMPORT` | No — text parse only | Aliases (PySH) | Static parse, no subprocess | — |
| `compat_check` | `STATIC_IMPORT` | No — text parse only | None | Static parse, no subprocess | — |
| `zsh <command>` | `TRUSTED_DELEGATED` | Yes (zsh subprocess) | External | Explicit `zsh -lc` only | — |
| `zsh_fallback on` | `TRUSTED_DELEGATED` | Yes (zsh subprocess) | External | Explicit opt-in, off by default | — |
| `run_script` | `TRUSTED_DELEGATED` | Yes (interpreter subprocess) | External | Shebang-based explicit delegation | #14 |
| `secure <cmd>` | `TRUSTED_DELEGATED` | Yes (PTY bridge) | Subprocess | Explicit opt-in PTY bridge | — |
| `plan` | `TRUSTED_LOCAL` | No — advisory only | None | Classification only | — |
| `env_audit` | `TRUSTED_LOCAL` | No — read-only display | None | Redacted; no system mutation | — |
| `path_audit` | `TRUSTED_LOCAL` | No — read-only display | None | Filesystem stat only | — |
| `which_all` | `TRUSTED_LOCAL` | No — read-only lookup | None | PATH scan only | — |
| `apt_check` | `TRUSTED_LOCAL` | Yes (`apt list --upgradable`) | None (read-only apt) | No sudo; no system mutation | — |
| `apt_search` | `TRUSTED_LOCAL` | Yes (`apt search`) | None (read-only apt) | No sudo; no system mutation | — |

---

## Foreign shell profile policy

PySH's static importers treat foreign profile files (`.zshrc`, `.bashrc`,
`.profile`, zsh plugins) as **plain text input**.

What the static importer does:
- Reads the file as UTF-8 text.
- Parses only safe static constructs: `alias`, `export`, simple assignments.
- Detects and marks `eval`, `source`, command substitution, functions, and
  arrays as `RISKY` or `SKIPPED` in the compatibility report.
- Never spawns a subprocess.
- Never executes any line as shell code.

What the static importer does not do:
- Does not execute `eval`.
- Does not follow `source` or `.` directives.
- Does not expand command substitution (`$(...)` or backticks).
- Does not execute shell functions.
- Does not load zsh plugin managers.

This behavior is machine-verified in `tests/test_security_trust_model.py::TestStaticProfileImportSafety`.

---

## Explicit delegation policy

PySH will execute foreign shell code only when the user **explicitly requests it**:

| Command | When | How |
|---------|------|-----|
| `zsh <command>` | Any time | `zsh -lc "<command>"` with 30 s timeout |
| `run_script <file>` | When file has a supported shebang | `interpreter file` subprocess |
| `zsh_fallback on` | When enabled by the user | Falls back to `zsh -lc` on unknown command |

**`zsh_fallback` is off by default.**  PySH reports a deterministic
"command not found" (exit 127) for unknown commands when fallback is disabled.
Enabling fallback with `zsh_fallback on` is an explicit user action.

No hidden fallback exists.  If a command is not found and fallback is disabled,
PySH does not silently retry through zsh or bash.

---

## Sensitive input boundary

For ordinary external commands (including `sudo`, `ssh`, `su`, `gpg`, and
any interactive program), PySH starts the child process and leaves the
controlling terminal attached to that child.  PySH is not in the keystroke
path and does not observe password bytes.

PySH does not:
- Read, count, log, buffer, or infer password bytes.
- Reveal password length.
- Determine password correctness.
- Proxy or wrap ordinary external commands automatically.
- Use `sudo -S` or parse `[sudo] password` prompts.
- Auto-wrap `sudo`, `ssh`, or `gpg`.

The raw-mode line editor is exclusively for PySH's own command-line input.
It is not repurposed to read passwords for external processes.

Full documentation: [Sensitive Input Security Boundary](../shell/security-sensitive-input.md).

---

## Secure runner boundary

`secure <cmd>` creates a PTY bridge between the user's terminal and the
child process.  This is an explicit, opt-in invocation.

The secure runner:
- Allocates a PTY pair for the child.
- Forwards terminal bytes transparently.
- Optionally shows a fixed-size keypress indicator (configured in
  `~/.pyshrc.py`).

The secure runner does not:
- Count password characters.
- Reveal password length.
- Determine password correctness.
- Become the default execution path for ordinary commands.
- Activate automatically for `sudo`, `ssh`, `su`, or `gpg`.

`secure <cmd>` was designed for the PTY indicator use case and not as a
general security boundary.  The PTY bridge does not sandbox or confine the
child process.

---

## Plugin and rc file trust policy

`~/.pyshrc`, `~/.pyshrc.d/*.pysh` (plugin files), and `~/.pyshrc.py` are
**local user-trusted PySH configuration**.

They are:
- Loaded from the user's home directory.
- Treated as trusted user-owned code.
- Executed through the PySH rc engine (shell commands) or Python `exec`
  (`~/.pyshrc.py`).
- **Not sandboxed.**

PySH does not apply import filtering, capability restriction, or content
scanning to rc files or plugins.  A malicious rc file has full access to
the user's session.  This is the same trust level as any shell dotfile.

---

## Python runtime trust policy

The `py`, `py { ... }`, and `#py` builtins execute Python code **in-process**
in the PySH process.

PySH does not:
- Sandbox Python code.
- Filter imports.
- Restrict OS access.
- Apply capability confinement.
- Claim that `py` is safe for running untrusted code.

Python code executed via PySH has full access to the Python interpreter, the
standard library, the OS, and the filesystem with the permissions of the
running user.

---

## Diagnostics non-mutation policy

The following builtins are **advisory and non-mutating**:

| Builtin | What it does | What it does NOT do |
|---------|-------------|---------------------|
| `plan` | Classifies command intent | Executes the command |
| `env_audit` | Displays redacted environment | Modifies environment; prints secret values |
| `path_audit` | Reports PATH entry status | Modifies PATH |
| `which_all` | Finds executables in PATH | Executes anything |
| `sys_info` | Displays system metadata | Modifies system state |
| `apt_check` | Runs `apt list --upgradable` | Installs or upgrades packages; uses sudo |
| `apt_search` | Runs `apt search <query>` | Installs packages; uses sudo |

`env_audit` redacts variables whose names contain: `KEY`, `TOKEN`, `SECRET`,
`PASSWORD`, `PASS`, `CREDENTIAL`, `AUTH`.

---

## Environment variable trust policy

PySH reads environment variables to configure behavior (`PYSH_ZSH_FALLBACK`,
`PYSH_PASTE_DEBUG`, `NO_COLOR`, `TERM`, `HOME`, `USER`, `PATH`, etc.).

PySH does not:
- Blindly execute commands from environment variables.
- Source profiles named in environment variables.
- Expand environment variables that could cause code injection (all expansion
  is via `expand_variables`, which performs substitution, not evaluation).

`PYSH_ZSH_FALLBACK=1` enables zsh fallback.  This is an explicit opt-in;
it is not set by default.

---

## Command planning trust policy

`plan <command>` is advisory only.  It classifies how PySH would route the
command, assigns a risk level, and prints the result.  It never executes the
command or any sub-command.

The planner is not a security enforcement mechanism.  It cannot prevent a
user from running a command that `plan` marks as risky.

---

## Logging and history privacy policy

PySH records entered command lines in `~/.pysh_history`.

PySH does not:
- Record command output.
- Record terminal content.
- Log password bytes.
- Transmit history to any external service.

Sensitive commands (e.g., `secure sudo -v`) are recorded in history by their
command line text, not by terminal content.

---

## Forbidden documentation claims

The following claims must not appear in PySH documentation unless explicitly
negated:

| Forbidden claim | Correct form |
|-----------------|-------------|
| "PySH is sandboxed" | "PySH is not sandboxed" |
| "sandboxed execution" | (no valid form — do not use this claim) |
| "privilege separation" | "PySH provides no privilege separation" |
| "capability confinement" | "PySH provides no capability confinement" |
| "safe to run untrusted code" | "PySH is not safe for running untrusted code" |
| "executes .zshrc by default" | "PySH does not execute .zshrc by default" |
| "executes .bashrc by default" | "PySH does not execute .bashrc by default" |
| "auto-wraps sudo" | "PySH does not auto-wrap sudo" |
| "knows password correctness" | "PySH does not know password correctness" |

These are enforced by `tests/test_docs_consistency.py::test_no_forbidden_security_claims`.

---

## Validation matrix

| Claim | Test file | Test class | Status |
|-------|-----------|-----------|--------|
| `is_foreign_profile_execution_forbidden_by_default()` returns True | `test_security_trust_model.py` | `TestTrustModel` | PASS |
| `is_pty_bridge_opt_in()` returns True | `test_security_trust_model.py` | `TestTrustModel` | PASS |
| `is_python_runtime_sandboxed()` returns False | `test_security_trust_model.py` | `TestTrustModel` | PASS |
| Static importer does not execute `eval` | `test_security_trust_model.py` | `TestStaticProfileImportSafety` | PASS |
| Static importer marks command substitution UNSUPPORTED | `test_security_trust_model.py` | `TestStaticProfileImportSafety` | PASS |
| Static importer marks `eval` RISKY in compat report | `test_security_trust_model.py` | `TestStaticProfileImportSafety` | PASS |
| Static importer does not spawn subprocess | `test_security_trust_model.py` | `TestStaticProfileImportSafety` | PASS |
| `zsh_fallback` off by default | `test_security_trust_model.py` | `TestExplicitDelegation` | PASS |
| `ZshBridge` uses `zsh -lc` | `test_security_trust_model.py` | `TestExplicitDelegation` | PASS |
| Normal external command does not use SecureRunner | `test_security_trust_model.py` | `TestSensitiveInputBoundary` | PASS |
| `plan` classify does not execute target | `test_security_trust_model.py` | `TestDiagnosticsNonMutation` | PASS |
| `env_audit` redacts secret variable names | `test_security_trust_model.py` | `TestDiagnosticsNonMutation` | PASS |
| `apt_check` uses `apt list` without sudo | `test_security_trust_model.py` | `TestDiagnosticsNonMutation` | PASS |
| Python runtime is not sandboxed (predicate) | `test_security_trust_model.py` | `TestPythonRuntimeTrust` | PASS |
| No forbidden security claims in docs | `test_docs_consistency.py` | `test_no_forbidden_security_claims` | PASS |

---

## Relation to other issues

| Issue | Relation |
|-------|----------|
| Issue #4 | Shell compatibility contract: scope definitions that inform trust boundaries |
| Issue #5 | Error/exit-code contract: exit codes for delegation failure (127, 126) |
| Issue #6 | Signal handling: SIGINT boundary for subprocess and PTY contexts |
| Issue #7 | This document |
| Issue #8 | Parser boundary cleanup: will clean up cross-domain imports |
| Issue #11 | Job control: will introduce process-group ownership (security-relevant) |
| Issue #14 | Script-mode: will formalize script delegation trust model |
| Issue #16 | Shell comparison tests: will validate delegation behavior |
| Issue #17 | POSIX sh scope: reinforces the non-/bin/sh claim |
