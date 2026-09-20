<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/threat-model.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH v1.0 Threat Model and Security Architecture

This document is the v1.0 threat-analysis and assurance contract for PySH
(GitHub Issue #43). It extends, and does not replace, the implemented execution
surface contract in
[Security and Trust Model](../architecture/security-trust-model.md). That
document owns the current trust categories and execution semantics. This
document owns assets, actors, boundaries, data classification, STRIDE analysis,
safe startup, redaction-before-egress requirements, and deferred security
ownership.

Statements are labeled as one of:

- **Implemented control**: enforced by current code and tests.
- **Required invariant**: mandatory for current or future implementations.
- **Deferred control**: not implemented; the named follow-up owns delivery.

PySH is an orchestration shell running with the invoking user's authority. It
does not provide privilege separation, and CPython in-process execution is
**not a security boundary**. `py`, `py { ... }`, `#py`, Python rc files, and
current Python plugins are not safe for untrusted code.

## Method and scope

The analysis uses STRIDE: spoofing, tampering, repudiation, information
disclosure, denial of service, and elevation of privilege. A category is used
only where the component has a technically meaningful threat. Availability is
interpreted as availability of the shell session and deterministic recovery,
not system-wide service availability.

In scope:

- parsing, tokenization, expansion, command dispatch, pipelines, and
  redirections;
- builtins, external processes, and the persistent Python runtime;
- interactive, `-c`, stdin-batch, and script invocation;
- executable and declarative startup inputs;
- current trusted plugins and the separate isolated-extension runtime;
- history, diagnostics, trace, sensitive terminal input, and `secure <cmd>`;
- static compatibility/profile import;
- reserved AI, remote/SSH, and package-management boundaries.

Out of scope as implemented controls: kernel containment, mandatory access
control, seccomp, containers, VM isolation, remote execution, AI providers,
and package signature verification. Requirements for the last three are
recorded now so later features cannot bypass the v1.0 security contract.

## Assets and security-sensitive state

Primary assets are:

1. user files, processes, terminal, and account authority;
2. command intent and command/output integrity;
3. environment values, credentials, agent sockets, cookies, and tokens;
4. protected terminal input owned by authentication programs;
5. startup configuration and plugin source integrity;
6. persistent history and diagnostic output confidentiality;
7. the persistent Python namespace and mutable shell state;
8. package provenance and future remote/AI payload integrity;
9. availability of a recoverable, deterministic shell startup path.

Security-sensitive mutable state includes `os.environ`, shell locals and
aliases, current directory, redirections and open descriptors, job table,
history buffers/files, Python runtime globals, enabled plugin names, plugin
registrations/hooks, loaded configuration paths, and trace configuration.

## Actors and assumptions

| Actor | Trust assumption | Authority and risk |
| --- | --- | --- |
| Interactive user | Trusted to issue commands | Has the same user authority as PySH; can intentionally execute destructive commands. |
| Local startup/config author | Trusted local code author | Executable rc and Python config can exercise the user's full authority. Compromise requires recovery with `--no-rc`. |
| Current Python plugin author | Trusted local code author | Plugin imports execute in-process and are not isolated. |
| External executable | Untrusted with respect to PySH integrity | Runs as a subprocess with explicitly constructed argv and inherited user authority/environment. |
| Input file/profile/package/provider | Untrusted input until parsed or verified | May attempt injection, malformed-input denial of service, or supply-chain compromise. |
| Local attacker with write access to user config | Outside the supported trust assumption | Can obtain user-level execution at normal interactive startup; filesystem ownership/permissions are prerequisite controls. |
| Isolated extension | Protocol-untrusted extension | Receives only explicit parent-broker grants under Issue #44; direct same-UID syscalls require #52 OS policy for confinement. |
| Future AI/remote service | External egress peer and untrusted input source | Must not receive implicit secrets; returned content is never trusted as executable intent. |

PySH does not defend against an attacker who already has arbitrary write access
to the running user's executable startup files. It does provide a deterministic
way to bypass those files for recovery.

## Entry points and egress channels

Entry points:

- TTY input, stdin-batch input, `-c`, and PySH script files;
- parser/tokenizer inputs, expansion values, paths, glob results, heredocs,
  redirections, and process output;
- `~/.pyshrc`, `~/.pyshrc.d/*.pysh`, and `~/.pyshrc.py`;
- XDG/user TOML configuration and per-plugin TOML;
- user and project plugin source;
- history files and environment variables;
- compatibility/profile import files;
- signals, terminal state, and future network/package inputs.

Egress channels:

- external process argv, environment, stdin, stdout/stderr, and inherited file
  descriptors;
- redirection targets, history storage, diagnostic stderr, and terminal control
  sequences;
- plugin callbacks and current in-process Python objects;
- future AI requests, remote/SSH requests, package repositories, telemetry, or
  crash-report paths.

Normal command stdout is an application data channel. Diagnostic redaction must
not rewrite it. Diagnostic/trace output is a separate, trusted emission channel
and must be redacted before emission.

## Trust-boundary diagram

Legend: `====>` crosses a process or external trust boundary; `---->` is an
in-process data/control path; `[TB]` is a trust boundary; `[NOT TB]` is not a
security boundary.

```text
User / controlling TTY
        |
        | command text and terminal ownership
        v
+-------------------------------------------------------------------+
| PySH process                                                       |
|                                                                   |
| parser/tokenizer ----> expansion ----> dispatch/runtime            |
|        |                                  |                       |
|        |                                  +====> [TB] external     |
|        |                                  |       process          |
|        |                                  |                       |
|        |                                  +----> persistent Python |
|        |                                  |       [NOT TB]         |
|        |                                  |                       |
| trusted local startup code --------------+       [NOT TB]         |
|        |                                                          |
|        +----> current trusted plugins             [NOT TB]         |
|                                                                   |
| diagnostics ----> RedactionPolicy ----> diagnostic stderr          |
|                         [data boundary before egress]              |
+-------------------------------------------------------------------+
        |                    |                    |             |
        +====> [TB] isolated +====> [TB] future +====> [TB]   |
               plugin IPC          AI provider         remote/SSH    |
        +====================================================> [TB]  |
               future package source/signature boundary              |
```

The subprocess boundary separates address spaces but does not reduce the
child's user privileges. The current in-process plugin and CPython paths are
explicitly not trust boundaries. `secure <cmd>` adds a PTY bridge, not
containment.

## Data classification

| Class | Examples | Allowed storage | Allowed logging | Allowed egress | Lifetime | Required controls |
| --- | --- | --- | --- | --- | --- | --- |
| Public | Version, license, public paths, documented feature names | Documentation, logs | Yes | Yes | Indefinite | Integrity and correct attribution. |
| User configuration | Non-secret TOML, prompt/theme settings | User config files, process memory | Only redacted/value-bounded diagnostics | Local subsystems; no external egress by default | File/session | Validate schema; deterministic precedence; `--no-rc` bypass. |
| Session-sensitive | Command text, cwd, aliases, command history, diagnostics, Python namespace | Process memory; history only under filtering policy | Only when explicitly enabled and redacted as applicable | External command when explicitly executed; otherwise no implicit egress | Session or configured history retention | Minimize collection; separate stdout from diagnostics; history filters. |
| Secret / credential | Password variables, passphrases, tokens, API keys, private keys, cookies, session credentials | Only owning process/explicit secure store; never history or diagnostics merely due to tracing | Never in cleartext | Only to the explicitly selected credential consumer after redaction policy/intent checks | Minimum necessary | Central name/value redaction; no implicit provider/plugin/remote/package egress. |
| Protected terminal input | Password bytes for `sudo`, `ssh`, `su`, `gpg`; input bridged by explicit `secure` | Must not be persisted by PySH | Never | Only terminal and intended child/explicit PTY bridge | Keystroke/child lifetime | Ordinary commands leave terminal ownership with child; no logging, counting, or history capture. |
| Executable trusted-local code | `.pyshrc`, `.pyshrc.d/*.pysh`, `.pyshrc.py`, current plugin source | User-owned files and process memory | File path/error metadata only; redact values | Executes locally with user authority | Startup/session | User ownership, explicit plugin enablement, transactional registration, `--no-rc` recovery. |
| Untrusted external input | Command output, imported profiles, provider replies, remote data, package metadata | Bounded buffers/files required by feature | Sanitized diagnostics only | No automatic re-execution or propagation | Operation-scoped | Parse without evaluation; validate; bound resources; explicit user intent. |

Explicit classifications:

- command text is session-sensitive and may become history unless filtered;
- command history is session-sensitive persistent data;
- environment variables are user configuration or secret/credential data based
  on name and use;
- password bytes are protected terminal input;
- token values and private keys are secret/credential data;
- `.pyshrc.py` and plugin source are executable trusted-local code;
- diagnostics are session-sensitive and must be redacted before emission;
- the Python runtime namespace is session-sensitive and may contain secrets;
- SSH agent sockets, key material, and passphrases are secret/credential data;
- future AI prompt payloads are external-egress payloads assembled from
  classified data and require explicit intent plus pre-egress redaction.

## Safe startup: `--no-rc`

**Implemented control.** `pysh --no-rc` selects an immutable startup policy at
the CLI/configuration boundary. Command execution does not know why startup
configuration is disabled.

The mode is deliberately strict. It neither reads nor creates:

- `~/.pyshrc`;
- `~/.pyshrc.d/*.pysh`;
- `~/.pyshrc.py`;
- user/XDG declarative TOML;
- per-plugin TOML configuration.

It also skips plugin discovery/import, user startup hooks, and plugin startup
hooks. TOML is skipped because the current schema includes
`features.project_plugins`; therefore treating all TOML as incapable of
changing a trust boundary would be an inaccurate assurance claim. Safe mode
uses built-in configuration defaults and does not create default TOML or Python
rc files. It does not sanitize the inherited process environment or disable
commands explicitly requested after startup.

Invocation contract:

| Form | Startup behavior |
| --- | --- |
| `pysh` | Normal interactive user startup remains enabled. |
| `pysh --no-rc` | Interactive startup with all user configuration disabled. |
| `pysh -c '...'` | Existing non-interactive behavior: user startup is not loaded. |
| `pysh --no-rc -c '...'` | Executes the requested command under the explicit no-user-config policy. |
| `python -m pysh --no-rc ...` | Same parser and policy as the console entry point. |
| script/stdin-batch mode | Existing behavior remains non-interactive and does not initialize interactive startup hooks. |

History remains governed by the normal history subsystem; `--no-rc` is not an
anonymous or forensic mode. Explicit commands such as `source FILE`, `py`, or
plugin-related builtins remain user actions after startup and are not disabled.

## Redaction and diagnostic emission policy

`pysh.diagnostics.trace.RedactionPolicy` is the canonical policy for diagnostic
and trace emission today. Its default policy classifies secret-like names,
redacts sensitive assignments, and replaces known sensitive environment values
before trace text reaches stderr. The protected classes include passwords and
passphrases, authentication tokens, API keys, private-key/credential names,
cookies, sessions, and authorization material.

Required invariants:

1. protected terminal bytes are never logged, persisted, counted, or inferred;
2. diagnostic data is redacted before emission, not after storage;
3. enabling trace/audit must never create new secret persistence;
4. debug and trace stderr must not expose known sensitive environment values;
5. normal command stdout is not modified by diagnostic redaction;
6. future AI, remote, plugin IPC, package, telemetry, and crash-report egress
   must call a core-owned redaction boundary before transmission;
7. providers and plugins may add stricter filtering but cannot own or bypass the
   minimum core policy.

Current legitimate seams are narrower implementations: `env_audit` maintains a
curated output and name filter, configuration diagnostics use
`safe_value_repr`, and history uses configurable ignore patterns. These are
implemented controls but not independent normative policies. Issue #50 owns
their later consolidation behind the canonical policy. No consolidation is
claimed by Issue #43.

## Component security contracts

### Parser, tokenizer, expansion, pipelines, and redirections

The parser treats input as data until dispatch. Parse errors must be
deterministic and must not partially execute an invalid trailing stage.
Subprocesses use explicit argv and never `shell=True`. Redirection targets are
opened explicitly; ordered descriptor actions must not leak unintended file
descriptors. Pipelines create process boundaries, not privilege boundaries.
Expansion and command substitution are execution-relevant transformations and
must remain bounded and observable without leaking secrets.

### Persistent Python runtime

`py`, `py { ... }`, and `#py` share in-process Python execution semantics and
may mutate the persistent namespace and OS state. They perform no import
filtering, capability restriction, or containment. Only trusted code may be
executed through these surfaces.

### Configuration and plugins

Executable startup inputs and current Python plugins are trusted local code.
Declarative TOML is parsed as data, but applying it can change shell policy and
must remain inside the startup boundary. Disabled user plugins are not imported;
project plugins require project opt-in plus name enablement; registration is
transactional. None of these controls converts trusted in-process plugins into
isolated code. Issue #44 provides a separate manifest-driven subprocess and
parent broker; it does not change the authority of current plugins. The
[isolated-plugin contract](plugin-isolation.md) defines its enforced controls
and same-UID OS limitations.

### History, diagnostics, and sensitive input

History stores command text, never command output or protected terminal bytes.
Ignore patterns reduce accidental secret persistence but are not a proof that
arbitrary secrets cannot appear in command text. Diagnostics are advisory and
non-mutating. Ordinary authentication programs own their terminal input.
`secure <cmd>` is an explicit transparent PTY bridge and is not a sandbox.

### Compatibility/profile import

Foreign profiles are static input. Importers extract supported literal aliases,
exports, and assignments without executing `eval`, `source`, functions, or
command substitutions. Explicit delegation (`zsh`, supported shebang execution,
or enabled fallback) crosses into an external interpreter and must remain
visible user intent.

## Threat register

| Threat ID | Component | STRIDE | Attack/precondition | Asset | Existing control | Required control | Residual risk | Owner/follow-up |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TM-PARSER-001 | Parser/tokenizer | Tampering | Crafted quoting/operator input changes intended parse | Command integrity | Typed parser errors; explicit grammar tests | Reject ambiguous/unsupported syntax before execution | Supported syntax can still express destructive intent | Current parser contract |
| TM-PARSER-002 | Expansion/substitution | Tampering, DoS | Malformed or expensive substitution/glob input | Session integrity/availability | Ordered expansion; substitution timeout; deterministic errors | Preserve bounds and no partial execution | Large local directory trees can consume resources | Parser/path contracts; #53 for broader limits |
| TM-EXEC-001 | External execution | Elevation, information disclosure | Attacker-controlled argv/env or descriptor inheritance | User authority, secrets | Explicit argv; no `shell=True`; controlled redirections | Validate boundaries and close unintended descriptors | Child retains invoking user's authority and inherited environment | Current runtime contract |
| TM-PIPE-001 | Pipelines/redirections | Tampering, information disclosure | Redirection targets overwrite files or descriptors route data unexpectedly | Files, command output | Explicit ordered redirection model | Preserve validation, restoration, and failure cleanup | User-requested overwrite remains possible | Current redirection contract |
| TM-RUNTIME-001 | `py`, blocks, `#py` | Elevation of privilege relative to false expectations | Untrusted Python is executed in-process | All user-level assets | Explicit not-sandboxed policy and predicate | Keep warnings/contracts accurate; never accept untrusted code implicitly | Full user-level code execution by design | Current model; Issue #44 only for extensions |
| TM-RUNTIME-002 | Persistent namespace | Information disclosure | Secret remains reachable by later code/plugin | Session secrets | Session-scoped namespace | Do not emit namespace values without redaction/intent | Trusted code can inspect all process memory | Issue #50 for egress consolidation |
| TM-RC-001 | Executable rc | Tampering, elevation | Attacker can write user startup files | User account/session | Treated as trusted local code; failure containment | `--no-rc` deterministic bypass; no mutation in safe mode | Normal startup executes compromised user files | Implemented here; filesystem controls external |
| TM-CONFIG-001 | Declarative TOML | Tampering | Malicious/malformed data changes environment, aliases, or project-plugin policy | Shell state/trust posture | Schema validation and diagnostics | Strict `--no-rc` skips all TOML; keep parsing non-executing | Valid configuration can intentionally alter behavior | Implemented here; #50 for diagnostic seam |
| TM-PLUGIN-001 | Current plugins | Elevation, information disclosure | Trusted plugin is malicious or compromised | All process/user assets | Explicit enablement, project opt-in, transactional registration | Continue describing current plugins as trusted code | Full ambient authority by design | Current trusted model; Issue #44 does not convert it |
| TM-PLUGIN-002 | Isolated plugin | Spoofing, elevation, DoS | Extension forges identity, requests excess parent authority, or floods IPC | Core state and parent-mediated assets | Separate process; identity handshake; bounded protocol; immutable default-deny broker grant; scrubbed env/cwd/fds | Define optional platform syscall hardening and unified resource budgets | Same-UID child retains direct OS filesystem/network syscalls; no kernel sandbox | #44 implemented portable broker; #52 OS tier; #53 resource limits |
| TM-HISTORY-001 | History | Information disclosure | Secret embedded in command text is persisted | Credentials/session data | Space-prefix and pattern filters; no terminal-byte capture | Document limits; central classification before future exports | Novel secret names may bypass substring filters | #50 |
| TM-DIAG-001 | Debug/trace/audit | Information disclosure | Secret enters command/field/environment diagnostic text | Credentials | `RedactionPolicy`; redacted stderr; stdout separation | Core-owned redaction before every diagnostic/future egress | Unknown secret values without classified names may remain | #50 |
| TM-DIAG-002 | Diagnostic tools | Repudiation/tampering | Advisory output is mistaken for enforcement | User decision integrity | Non-mutating contract; explicit risk labels | Never claim `plan` enforces execution policy | User may ignore advisory output | Current diagnostics contract |
| TM-PTY-001 | Ordinary terminal input | Information disclosure | Shell intercepts authentication bytes | Passwords/passphrases | Child inherits terminal; PySH is outside keystroke path | Preserve direct ownership and never log protected bytes | Child/terminal may have independent vulnerabilities | Current sensitive-input contract |
| TM-PTY-002 | `secure <cmd>` | Information disclosure, spoofing | PTY bridge or indicator is mistaken for containment/authentication | Credentials/user trust | Explicit invocation; transparent forwarding; fixed indicator | Preserve no-sandbox wording and no history/logging of PTY bytes | Bridge observes transport bytes by design | Current secure-runner contract |
| TM-COMPAT-001 | Profile import | Tampering/elevation | Profile contains `eval`, source, substitution, or functions | Shell state | Static parse; risky/unsupported classification; no subprocess | Never auto-execute foreign profiles | Literal imports can still change aliases/environment | Current compatibility contract |
| TM-AI-001 | Future AI egress | Information disclosure, spoofing, tampering | Context contains secrets or provider returns hostile command text | Secrets, command integrity | Boundary reserved; no feature today | Explicit intent, core redaction before send, untrusted output, no implicit execution | Provider retention and model behavior remain external risks | Future AI issue (reserved) |
| TM-REMOTE-001 | Future remote/SSH | Information disclosure, spoofing | Key/passphrase leaks or endpoint identity is wrong | Credentials, remote integrity | Existing normal SSH terminal boundary only | Never log key/passphrase material; explicit agent boundary; auditable command text without credentials | Remote host and agent compromise remain external | Future remote/SSH issue (reserved) |
| TM-PKG-001 | Future package management | Tampering, elevation | Unverified package/source supplies executable code | Installation and user assets | Boundary reserved; no managed install path today | Integrity/signature policy before install; activation separate from capability grant | Trusted signer or repository compromise | Future package-assurance issue (reserved) |

No unresolved high-severity risk is hidden: current in-process Python, rc, and
plugin authority is an explicit trusted-code design constraint. Issue #44
isolates parent memory/failure and enforces broker grants but does not provide
portable kernel syscall confinement. OS reinforcement is assigned to #52,
redaction convergence to #50, resource limits to #53, and network/package
boundaries remain disabled until their named requirements are implemented.

### Isolated-plugin host OS authority boundary

The Issue #44 security claim is **no ambient PySH parent-mediated
capability**. The isolated child has no implicit path through the parent to
PySH history, configuration, environment values, builtins or commands, file
handles, service objects, plugin registry, diagnostic state, or other
parent-owned resources. Each supported parent operation requires an explicit
matching grant and a broker authorization decision.

This is not host OS confinement. The child normally has the same OS user
identity as PySH and, unless #52 platform hardening prevents it, can directly
access files permitted to that user, create sockets, spawn or execute
processes, and inspect host-exposed resources. Those direct syscalls bypass the
broker. Consequently, the portable baseline is not a filesystem, network, or
process sandbox for arbitrary same-UID code.

## Capability principles for Issue #44

Issue #44 must implement, not merely document:

- default deny for every isolated-extension capability;
- explicit capability request and an independent explicit grant;
- least privilege and no ambient PySH parent-mediated filesystem, command,
  network, environment, terminal, or other privileged capability;
- capability checks owned by PySH core, never self-asserted by a plugin;
- auditable grant and denial decisions with redaction before emission;
- bounded, versioned IPC messages and deterministic failure handling;
- no `pickle` or equivalent object deserialization across an untrusted process
  boundary;
- no inherited secret environment and no accidental file-descriptor
  inheritance by default;
- explicit lifecycle/revocation behavior;
- a fail-closed seam for CPU, memory, process, descriptor, and time limits
  supplied by #53.

These principles do not retrofit isolation onto today's trusted in-process
Plugin API. Current plugins remain executable trusted-local code. The separate
runtime and its tests are described in [plugin-isolation.md](plugin-isolation.md).
The portable process/broker implementation enforces parent-mediated grants and
removes inherited environment, descriptors, cwd, and terminal access. It
satisfies the Issue #44 portable parent-authority boundary. Direct same-UID
syscalls remain governed by the host platform rather than the broker:
#52 owns platform tiers, Linux hardening, FreeBSD Capsicum integration,
unavailable-primitive behavior, and any future mandatory hardening tier. #53
owns CPU, memory, file-descriptor, process-count, and wall-clock limits plus
watchdog and hard-kill enforcement. Issue #44 provides integration seams for
those follow-up controls but does not implement them.

## Reserved future boundaries

### AI

Command/context transmission requires explicit user intent for each defined
workflow. Core redaction occurs before provider egress. Secrets are never added
implicitly. Provider output is untrusted input and cannot execute without a
separate explicit user action and normal parser/runtime controls.

### Remote and SSH

Private keys, passphrases, agent protocol material, and credential-bearing
environment values are never logged. SSH agent access is an explicit boundary.
Remote command text may be audited only after credential separation/redaction;
remote output remains untrusted input.

### Package management

Package content and metadata are untrusted until integrity and signature policy
passes. Installation and activation are separate decisions. Installing a
package never implies unrestricted capabilities for a future isolated plugin.

## Verification evidence

Implemented controls are exercised by:

- `tests/test_safe_startup.py` for strict startup policy and CLI/module forms;
- `tests/test_security_trust_model.py` for execution/trust predicates, static
  import, diagnostics, sensitive input, and the no-sandbox contract;
- `tests/test_observability_diagnostics.py` for stderr redaction and unchanged
  stdout;
- `tests/test_rc.py`, `tests/test_pyshrc_py.py`, and plugin tests for normal
  startup compatibility;
- `tests/test_docs_consistency.py` for documentation invariants;
- `tests/test_isolated_plugin_manifest.py`,
  `tests/test_isolated_plugin_protocol.py`, and
  `tests/test_isolated_plugin_runtime.py` for the Issue #44 process/broker
  boundary;
- parser, pipeline, redirection, history, secure-runner, architecture, and
  public API suites for their respective boundaries.

Reviewers must distinguish passing current-control tests from deferred controls.
A future feature that crosses a reserved boundary cannot cite this document as
evidence that its enforcement already exists.
