<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/plugin-isolation.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Isolated Plugin Process and Capability Contract

This document is the normative Issue #44 contract for PySH's isolated-plugin
process runtime. The governing security principles and threat ownership remain
in the [v1.0 threat model](threat-model.md). The existing
[Plugin API 1.0](../plugins/plugin-api.md) remains a separate trusted,
in-process extension model.

## Security claim and limitation

The Issue #44 security claim is **no ambient PySH parent-mediated
capability**. The child receives no implicit route through the PySH parent to
history, configuration objects, environment values, builtins or commands,
open parent file handles, service objects, the plugin registry, diagnostic
state, or any other privileged parent-owned resource. Every supported access
to such a resource requires an explicit capability grant that PySH core checks
for the individual broker request.

The implemented portable boundary provides:

- process-memory and failure isolation from the PySH parent;
- versioned, bounded JSON IPC over dedicated pipes;
- parent-owned default-deny grants for all broker operations;
- a scrubbed launch environment, dedicated working directory, and closed
  unrelated file descriptors;
- deterministic handshake, shutdown, timeout, and forced-termination paths.

The subprocess normally runs under the same OS user identity as PySH. Without
platform hardening it may directly open, read, or write files permitted by OS
discretionary access control; create sockets; execute or spawn processes; and
inspect resources that the host OS exposes to that user. These operations do
not pass through the PySH broker. The portable stdlib-only baseline cannot
revoke that authority.

Therefore, the portable isolated subprocess is **not an OS sandbox**:

- subprocess isolation is not a filesystem sandbox;
- subprocess isolation is not a network sandbox;
- subprocess isolation is not a process sandbox.

Capability grants govern only parent-mediated operations. They do not
intercept direct child syscalls or make arbitrary same-UID executable code
host-OS-confined. Process-group termination contains ordinary descendants,
but platform and resource controls own stronger guarantees.

## Two extension modes

| Property | Trusted plugin | Isolated plugin |
| --- | --- | --- |
| Runtime | Existing in-process Plugin API 1.0 | Separate subprocess |
| Discovery | `~/.config/pysh/plugins/*.py`, optional project path | Manifest-driven; no automatic discovery/activation yet |
| Authority | Full PySH process and user authority | No parent memory/objects; broker default-deny; direct OS authority remains a documented limitation |
| Registration | Python callbacks and transactional bundle | Versioned JSON messages only |
| Failure | Callback exception wrappers | EOF/crash/protocol/timeout containment and process termination |
| Intended trust | Trusted local code | Protocol-untrusted extension; same-UID host authority remains subject to the platform security model |

Issue #44 does not route trusted plugins through the isolated runtime and does
not change `PluginManager`, `PluginAPI`, or existing enablement semantics.

## Architecture ownership and dependency direction

Issue #46's [layering contract](../architecture/layering.md) assigns the
core-to-extension integration boundary to `pysh.plugins`: `pysh.core` consumes
the trusted plugin manager and its registration records. The distinct
`pysh.plugins.isolated` domain owns manifest parsing, IPC, broker/capability
internals, launch hygiene, and isolated subprocess lifecycle.

The isolated domain may consume exact validation and identity helpers from
the trusted plugin domain. The reverse is forbidden, and `pysh.core` must not
import isolated runtime objects. `pysh.api` exposes neither subsystem's
implementation objects. The manifest and IPC formats are versioned external
contracts; their Python implementations remain internal. These rules are
machine-enforced by `architecture.toml` and the AST boundary tests and do not
alter the Issue #44 security claim.

## Versions and manifest

Three versions are independent:

- Plugin API version `(1, 0)` identifies the trusted in-process callback API;
- isolated manifest version `1` identifies the TOML schema;
- isolated IPC protocol version `1` identifies the wire contract.

The complete package/Python API/Plugin API/manifest/IPC relationship is in the
[normative version matrix](../development/api-stability.md#independent-version-domains).
Package SemVer never substitutes for manifest validation or IPC negotiation.

An isolated manifest is bounded to 256 KiB, parsed with `tomllib`, and never
executed. Unknown or missing fields fail closed. Version 1 has this schema:

```toml
manifest_version = 1
name = "example-isolated"
plugin_version = "1.0.0"
protocol_version = 1
entrypoint = ["/absolute/path/to/executable", "--plugin-mode"]
requested_capabilities = [
  "fs.read:/absolute/data/path",
  "env.read:EXAMPLE_VALUE",
  "network.connect:api.example.test:443",
  "command:status",
]
resource_class = "small"
```

`resource_class` is optional metadata reserved for Issue #53. It does not
activate resource enforcement. The executable must resolve to an absolute,
executable regular file. Arguments are bounded strings. Plugin names use the
existing strict Plugin API identifier grammar. Unknown and duplicate
capabilities are rejected.

## Capability model

Manifest strings are parsed once into immutable typed objects:

| Declaration | Internal type | Broker operation |
| --- | --- | --- |
| `fs.read:/absolute/path` | filesystem/read + canonical root | bounded UTF-8 regular-file read |
| `fs.write:/absolute/path` | filesystem/write + canonical root | bounded UTF-8 write |
| `env.read:NAME` | environment + exact variable name | retrieve one explicitly granted parent value |
| `network.connect:host:port` | network + exact endpoint | reserved; protocol v1 returns `operation_unavailable` even when granted |
| `command:NAME` | command + exact validated name | call one parent-registered handler with bounded string argv |

Requested capabilities are not grants. The parent constructs an immutable
grant independently, and every granted capability must be a subset of the
manifest request. No declaration and no explicit grant means denial. Child
messages cannot mutate that set or self-authorize.

The broker has an explicit dispatcher; it performs no arbitrary attribute or
Python-call dispatch, imports no child-selected module, and exposes no parent
objects. Denied and malformed requests receive stable error codes without
including secret values.

### Brokered filesystem authorization

Both manifest roots and requested paths are canonicalized. Authorization uses
path component semantics (`Path.is_relative_to`), not string prefixes. This
rejects:

- `..` traversal;
- existing symlink traversal outside the grant root;
- relative paths;
- prefix confusion such as `/tmp/foo` versus `/tmp/foobar`.

These checks authorize only filesystem operations requested through the
broker. They do not confine `open()` or other filesystem syscalls issued by the
child itself, and this mechanism must not be described as a filesystem
sandbox.

The portable stdlib implementation has a documented TOCTOU limitation: a
filesystem object can be replaced between canonical authorization and the
subsequent open/write operation. Race-free confinement requires descriptor-
relative OS APIs and platform policy owned by Issue #52. Broker reads and
writes are each bounded to 256 KiB.

### Network capability

Broker-mediated network access is default-deny. Protocol version 1 defines the
`network.connect:host:port` capability syntax for version stability, but it
implements no raw network proxy: even an explicitly granted matching request
returns `operation_unavailable`. The declaration and grant do not block or
mediate sockets created directly by a same-UID child. Preventing those socket
syscalls requires platform hardening owned by Issue #52.

### Command capability

A `command:NAME` grant authorizes a request for the PySH parent to invoke the
matching registered operation. It exposes neither arbitrary parent command
dispatch nor PySH builtins. It also does not prevent the child from invoking an
executable directly when the host OS permits that operation. Issue #44 claims
no process-execution confinement for direct child syscalls.

## IPC protocol version 1

The transport is child stdin/stdout pipes. Each message is:

```text
4-byte unsigned big-endian body length
UTF-8 JSON object body
```

Every JSON object contains exactly:

```json
{
  "protocol_version": 1,
  "message_type": "...",
  "request_id": "...",
  "payload": {}
}
```

Hard bounds:

- frame body: 256 KiB;
- JSON nesting: 16 levels;
- JSON values/nodes: 4096;
- one JSON string/key: 64 KiB;
- request ID: 128 UTF-8 bytes;
- JSON integers: signed 64-bit range;
- non-finite numbers: forbidden.

Invalid UTF-8, malformed/trailing JSON, mismatched frame lengths, unknown
message types, unknown fields, oversized frames, and unsupported protocol
versions fail closed. The length is checked before the body allocation. IPC
uses no `pickle`, `marshal`, `eval`, `exec`, or arbitrary object
deserialization.

Known message families are handshake, broker request, response, and lifecycle.
Requests before completion of the handshake are protocol violations.

## Handshake and lifecycle

```text
parent                         child
  | spawn (scrubbed state)       |
  | <----- handshake.hello ------| identity + protocol
  | ------ handshake.grant ----->| requested and granted labels
  | <----- handshake.ready ------| verified identity
  |       running / broker       |
  | ------ lifecycle.shutdown -->|
  | <--- lifecycle.shutdown_ack -|
  | close/wait or terminate/kill |
```

The manifest, not the child, is authoritative for identity, version, and
requested capabilities. Identity or protocol mismatch terminates the child.
Crash, unexpected EOF, malformed IPC, a request timeout, and a handshake
timeout move the runtime to `failed` and terminate the child. Shutdown is
graceful when possible and uses terminate/kill after a bounded timeout.
Failures are exceptions local to the runtime boundary and do not terminate the
PySH process.

## Environment, working directory, and descriptors

The parent passes this explicit baseline environment only:

```text
PYTHONNOUSERSITE=1
PYTHONUTF8=1
```

It does not pass parent `HOME`, `PATH`, `PYTHONPATH`, tokens, API keys, SSH
agent variables, cookies, or session credentials. An interpreter may add its
own locale/runtime bookkeeping after process start; no additional parent value
is inherited.

Each child receives a new mode-0700 temporary working directory, which is
removed after shutdown/failure. It does not inherit the project cwd.

The descriptor contract is:

- fd 0: parent-to-child protocol pipe;
- fd 1: child-to-parent protocol pipe;
- fd 2: `/dev/null`;
- all unrelated descriptors closed with `close_fds=True`;
- a new process session prevents inheritance of the shell's controlling
  process group relationship.

No TTY, config, history, or arbitrary open parent descriptor is intentionally
passed.

## Audit and resource seams

The runtime emits bounded internal event objects for identity, requested and
granted capabilities, denial, failure, and stop. Events contain no child
payload or returned secret values. Issue #50 owns integration with structured
diagnostics and persistent audit policy.

`IsolatedResourceLimits` names CPU, memory, wall-clock, descriptor, and process
limits. Configuring any limit currently fails closed before spawn. Issue #53
owns CPU, memory, file-descriptor, process-count, and wall-clock limits plus
watchdog and hard-kill enforcement. Issue #44 supplies integration seams only
and does not silently accept unenforced budgets.

Issue #52 owns platform-tier guarantees, optional Linux hardening, FreeBSD
Capsicum integration, behavior when a hardening primitive is unavailable, and
any future decision to require hardening for a platform tier. Such hardening
may strengthen this baseline but is not part of the portable Issue #44
contract.

## Portability and verification

The baseline uses only `subprocess`, pipes, `selectors`, `tempfile`, `json`,
`struct`, `tomllib`, and other Python standard-library facilities. It uses no
`/proc` inspection and no Linux-only syscall assumptions. Focused tests cover
manifest/capability validation, protocol bounds, environment/cwd/fd hygiene,
handshake, broker authorization, canonical paths, crash, malformed input, and
hang containment.

Local Debian validation does not establish FreeBSD behavior. The same portable
test modules must run in the FreeBSD 14.4 CI/VM environment; until that evidence
exists, FreeBSD validation is pending rather than PASS.
