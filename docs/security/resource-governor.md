<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/resource-governor.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Resource Governor Contract (Issue #53)

Status: **Slices 1-4 implemented and audited** (policy contract; POSIX rlimit
and IPC-size enforcement; default governance, total wall-clock watchdog,
concurrency permits and `RESOURCE` diagnostic events; bounded abuse evidence and
this audit). FreeBSD execution evidence is pending. Issue #53 is not complete:
it is not closed until the maintainer accepts the audit and the FreeBSD lane
evidence below.

## Slice 1: policy contract (implemented)

Implemented in `pysh.plugins.isolated.resources` (stdlib-only, no platform
imports, no environment reads, contract version `1`).

### Budget fields

| Field | Unit |
| --- | --- |
| `cpu_seconds` | CPU time, whole seconds |
| `memory_bytes` | bytes |
| `wall_clock_seconds` | elapsed real time, whole seconds |
| `file_descriptors` | open descriptor count |
| `processes` | simultaneous processes/threads in the plugin group |
| `message_bytes` | bytes per IPC message/output |
| `concurrency` | maximum simultaneously active runtimes of the same plugin (keyed by manifest name) in this process |

Values are positive integers or `None` (unspecified). `bool`, non-integers,
zero, negatives, and non-finite values are rejected with `ResourcePolicyError`.
`ResourceBudget` is frozen and slots-based.

### Hard ceilings (immutable project policy)

| Field | Ceiling | Rationale |
| --- | --- | --- |
| `cpu_seconds` | 120 | Caps a busy loop at two minutes. |
| `memory_bytes` | 1 GiB | Ample for a CPython helper; protects a workstation. |
| `wall_clock_seconds` | 600 | Bounds hangs; existing point timeouts are 2-5 s. |
| `file_descriptors` | 256 | Covers brokered pipes/sockets. |
| `processes` | 32 | Bounds fork amplification. |
| `message_bytes` | `MAX_FRAME_BYTES` (256 KiB) | Never above the IPC protocol limit. |
| `concurrency` | 8 | Bounds simultaneous runtimes of one plugin. |

Ceilings are constants. No configuration value, manifest field, plugin value,
or environment variable can raise them. The wire protocol is unchanged.

### Production profiles

| Field | `small` | `standard` | `large` |
| --- | --- | --- | --- |
| `cpu_seconds` | 5 | 15 | 60 |
| `memory_bytes` | 128 MiB | 256 MiB | 512 MiB |
| `wall_clock_seconds` | 10 | 30 | 300 |
| `file_descriptors` | 32 | 64 | 128 |
| `processes` | 4 | 8 | 16 |
| `message_bytes` | 64 KiB | 128 KiB | 256 KiB |
| `concurrency` | 1 | 2 | 4 |

Every profile is complete and validated against the ceilings at construction.
Tests inject their own catalog (`build_profile_catalog`); `test` is not a
production profile.

### Resolution rule

```text
requested <= profile budget <= hard ceiling
effective  = requested if present else profile budget
```

Equivalently `effective = min(profile, requested, ceiling)`, but raising
overrides are **rejected**, never silently clamped. A missing or unknown
`resource_class` fails closed; there is no fallback profile. The manifest
parser still accepts any bounded identifier; resolution belongs to the
governor.

### Violation vocabulary

`ResourceViolation`: `wall_clock`, `cpu`, `memory`, `file_descriptors`,
`processes`, `message_size`, `concurrency`. Slice 3 emits `wall_clock`, `message_size` and `concurrency` (see Slice 3).

### Runtime seam

`IsolatedPluginRuntime(resource_limits=..., resource_catalog=...,
process_limit_mode=...)`. `resource_limits=None` means ungoverned (the
pre-Issue-#53 direct spawn, protocol limit only). Any `ResourceBudget`, even an
empty override, activates enforcement: the budget is resolved against the
manifest `resource_class`, planned (`plan_enforcement`), and spawned through
the launcher. Any policy failure raises
`LifecycleError("resource policy rejected: ...")` before a subprocess exists.
`runtime.enforcement` exposes the active `ResourceEnforcementPlan`, including
`deferred_fields`. `IsolatedResourceLimits` remains an alias of `ResourceBudget`.

## Slice 2: enforcement (implemented)

### Launcher boundary

`pysh.plugins.isolated.launcher` is an INTERNAL trusted script. The parent runs

```text
python -I launcher.py --cpu-seconds N --memory-bytes N --file-descriptors N \
       [--processes N] -- /abs/plugin arg...
```

with `start_new_session=True`, `close_fds=True`, scrubbed environment and a
dedicated cwd, as before. The launcher re-validates the numbers (canonical
positive integers, no unknown/duplicate options, `--` required, Slice 1 hard
ceilings, enforceable floors), applies `setrlimit`, then replaces itself with
the plugin via `os.execve` (same PID, no shell, no `preexec_fn`). The plugin's
first instruction therefore already runs under the limits and no supervisor
process remains. Limits come only from the parent-owned argv; each is set
soft == hard and never above an inherited lower hard limit. A launcher failure
exits `78` (policy rejected) or `71` (cannot apply/exec); the runtime reports a
deterministic `LifecycleError` and cleans up.

### Exact mappings

| Budget field | Enforcement |
| --- | --- |
| `cpu_seconds` | `RLIMIT_CPU` (soft == hard). Launcher start-up CPU time counts toward it. |
| `memory_bytes` | `RLIMIT_AS`, or `RLIMIT_VMEM` where that is the only name |
| `file_descriptors` | `RLIMIT_NOFILE` |
| `processes` | Not enforced by default. Opt-in `ProcessLimitMode.OS_PER_UID` applies `RLIMIT_NPROC` |
| `message_bytes` | Parent IPC bound for reads **and** writes (`max_bytes`); never above `MAX_FRAME_BYTES` |
| `wall_clock_seconds` | Parent watchdog (Slice 3) |
| `concurrency` | Parent permit (Slice 3) |

Enforceable floors (rejected, never silently raised): descriptors >= 8,
memory >= 32 MiB, message >= 1024 bytes. An explicit `processes` request without the
opt-in fails closed. The `processes` profile default is listed in
`deferred_fields` rather than implied to be active. A platform without a
required primitive fails closed before exec.

### Semantics and caveats

* Memory is a **virtual address-space** limit, not a resident-memory meter. It
  does not account physical RAM. There is no cgroup or jail: no cgroup or jail claim is made.
* `RLIMIT_NPROC` counts processes of the whole real UID, not a plugin
  descendant tree, so it is not exact per-plugin containment. In opt-in mode an
  absolute value below the user's current process count blocks every `fork` of
  the plugin; a value above it permits other-user-process growth. Per-plugin
  process-tree containment is deferred to the supervisor layer.
* CPU: on exceeding the soft/hard limit the kernel signals the plugin
  (`SIGXCPU`/`SIGKILL`). The parent sees an ordinary child death; it does not
  attribute it as a resource violation (see "OS-death attribution").
* Linux: `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NOFILE`, `RLIMIT_NPROC` exist;
  `RLIMIT_NPROC` is enforced against the real UID and is ignored for root /
  `CAP_SYS_RESOURCE`.
* FreeBSD: `RLIMIT_VMEM` is the address-space limit (aliased to `RLIMIT_AS` in
  Python); the rest map identically. Capsicum and per-jail accounting are not
  used. Issue #52 defines the platform-tier contract; Issue #53 owns the resource-governor execution evidence, and no FreeBSD execution evidence exists yet.

## Slice 3: supervision (implemented)

### Default governance

There is no ungoverned production startup. Every runtime resolves an
effective budget before spawn: the manifest `resource_class` if present,
otherwise `standard` (`DEFAULT_RESOURCE_CLASS`). An unknown non-empty class
fails closed before spawn and is never mapped to `standard`. `resource_limits`
is only an override that may lower the profile. Tests inject a catalog for
non-production classes such as `test`.

### Total wall-clock watchdog

`wall_clock_seconds` is the **total governed lifetime**, measured on
`time.monotonic()` by an independent parent-owned daemon thread
(`supervisor.WallClockWatchdog`). The deadline starts immediately before the
spawn call, so launcher and handshake time count, and it is never reset by a
successful handshake, `serve_once()`, request completion or shutdown
initiation. It uses no `SIGALRM`, process-global timer, child timer or `/proc`.
It is distinct from the per-operation `handshake_timeout`, `request_timeout`
and `shutdown_timeout`.

Lifecycle: created after the spawn call returns; cancelled and joined on
shutdown, failed start, handshake/launcher/protocol failure, `close()` and
violation, so no watchdog thread outlives the runtime.

Expiry sequence (only the child's own session/process group is signalled,
`pid == pgid` via `start_new_session=True`, and never again after the sequence
completes):

```text
claim violation (first claimant wins) -> emit one RESOURCE event
-> SIGTERM group -> bounded grace (shutdown_timeout) -> SIGKILL group
-> reap -> close pipes, remove temp cwd, release permit -> state FAILED
```

Precedence: whichever of {shutdown, watchdog, message violation} claims the
runtime first decides the outcome. Once `shutdown()` has begun, an expiry is
ignored and shutdown's own bounded terminate/kill applies. If a violation was
claimed first, `shutdown()` only completes the containment, returns `False` and
emits no `STOPPED`/generic `FAILURE`. If the child already exited when the
deadline fires, nothing is claimed (no resource was being consumed).

### Concurrency

`concurrency` is the maximum number of simultaneously active governed runtimes
of the same plugin (manifest name) in this parent process, enforced by a
lock-protected counter (`supervisor.ConcurrencyGovernor`). The permit is taken
before spawn, never queues or waits, and is released exactly once on every exit
path. Exceeding it raises `LifecycleError("... resource limit exceeded:
concurrency")` before any process exists and leaves the runtime in `new`. It is
unrelated to `RLIMIT_NPROC`, and a plugin cannot alter it.

### `RESOURCE` events (Issue #50, schema version 1)

`event_class = resource`, `event = resource.limit_exceeded`, severity `error`,
`actor` = plugin name, `result = failure`, `reason_code = <resource>_exceeded`,
`fields` = `plugin_name`, `resource`, `configured_limit`, `enforcement`
(`watchdog`, `ipc_bound` or `permit`). No argv, environment, file content, IPC
payload or output is ever included. Exactly one event is emitted per violation
and no generic `FAILURE` duplicates it. Oversized inbound or outbound frames
(`message_size`) are attributed and contained the same way. A sink raising an
ordinary `Exception` never prevents containment or changes the outcome;
`BaseException` still propagates after containment.

### OS-death attribution

Only `wall_clock`, `message_size` and `concurrency` are attributed, because the
parent observes them directly. A child killed by `RLIMIT_CPU`, an allocation
failure under `RLIMIT_AS`, `EMFILE` or `fork` failure is an ordinary child
failure: the parent cannot attribute it uniquely, so it keeps the generic
failure classification and does not claim a CPU/memory/descriptor violation.

### `RLIMIT_NPROC`

Unchanged and honest: per-real-UID, opt-in via `ProcessLimitMode.OS_PER_UID`,
no child-tree counting, no `/proc`.

### Evidence

Linux (Debian) execution evidence exists in `tests/test_resource_supervisor.py`
and `tests/test_resource_enforcement.py`. The code uses no `/proc`, cgroups,
systemd or root, but FreeBSD execution evidence is pending; nothing here
claims it ran on FreeBSD.

## Slice 4: controlled abuse evidence

`tests/test_resource_abuse.py` forces each hostile behaviour in isolation and
asserts containment plus a healthy session afterwards (a normal governed plugin
still starts, serves and shuts down gracefully). Every scenario is bounded so it
cannot harm the host even if enforcement failed: allocation is capped at 40
chunks of 4 MiB under a 64 MiB budget, fork attempts at 16 with immediately
exiting children, descendants at three idle sleepers.

| Abuse | Result |
| --- | --- |
| Hung plugin | Stopped by the wall-clock watchdog; one `RESOURCE` event |
| CPU-bound busy loop | Stopped by the watchdog (needs no child cooperation) |
| Request flood | Served until the total lifetime ends, then contained; the caller is told `wall_clock` |
| Unbounded allocation | `MemoryError` inside the plugin under `RLIMIT_AS`; host untouched |
| Fork loop | Blocked by opt-in per-UID `RLIMIT_NPROC` (non-root only) |
| Idle descendants | Killed with the plugin's process group |
| Descriptor exhaustion | `EMFILE` inside the plugin; parent descriptors unchanged |
| Oversized message | One `message_size` event; plugin contained |
| Spawn storm of one plugin | Capped by the concurrency permit; no leaked permit |
| Raising limits | Configuration above a ceiling or profile is rejected; the plugin cannot raise its own limits |

## Platform and CI evidence

Run the same command on each Tier 1 platform:

```sh
PYSH_PYTEST="python3 -m pytest" scripts/check_resource_governor_evidence.sh
# in this repository's uv environment: PYSH_PYTEST="uv run python -m pytest"
```

It needs no root, `/proc`, cgroups or systemd. The repository's
`platform-debian` and `platform-freebsd` CI jobs in `.github/workflows/ci.yml`
invoke this script (`PYSH_PYTEST="python -m pytest" sh
scripts/check_resource_governor_evidence.sh`); the script owns the resource
test list, so the workflow does not duplicate it, and
`tests/test_platform_tier_contract.py` pins the entrypoint in both jobs.

| Platform | State |
| --- | --- |
| Debian 13 / amd64 / CPython 3.13 | Implementation tested locally; Tier-1 CI wired; PR CI execution pending. |
| FreeBSD 14.4 / amd64 / CPython 3.13 | Implementation ready; Tier-1 CI wired; FreeBSD execution evidence is pending. The code has never run on FreeBSD (`RLIMIT_VMEM` alias detection, no `/proc`), and no native evidence is claimed until GitHub CI runs it successfully. |

Issue #52 defines the platform-tier contract; Issue #53 owns the resource
governor execution evidence.

## Definition-of-Done audit

Roadmap acceptance criteria for Issue #53, with evidence:

| Criterion | Status | Evidence |
| --- | --- | --- |
| Task exceeding budget is stopped without taking down the session | Met on Linux | `test_resource_abuse.py` (session-healthy check after each scenario) |
| Tests force timeout / OOM / fork-bomb in isolation and verify containment | Met on Linux, bounded | Hang and busy loop (watchdog), allocation (`RLIMIT_AS`), fork loop (per-UID `RLIMIT_NPROC`, opt-in) |
| Limits documented and versioned; hard ceilings enforced over user config | Met | Contract version `1`; `test_resource_governor_contract.py` pins this document to the constants |
| Budget violations are contained and reported through Issue #50 | Met for wall clock, message size, concurrency | `resource.limit_exceeded`, schema version 1; OS deaths deliberately unattributed |
| Default budgets per task class | Met | `small`, `standard`, `large`; `standard` default; unknown fails closed |
| Wall-clock enforcement independent of the child | Met | Parent watchdog, TERM -> grace -> KILL on the owned process group |

Known limitations (not hidden):

* Memory is a virtual address-space limit, not a resident-memory meter.
* `processes` is not a per-plugin tree count: `RLIMIT_NPROC` is per-real-UID and
  opt-in, so a fork bomb is only blocked when that mode is chosen. Without it,
  descendants are still bounded by the wall-clock deadline and killed with the
  process group.
* CPU, memory, descriptor and fork deaths are not attributed to a resource.
* `concurrency` counts runtimes of one plugin in one parent process; it is not a
  cross-process or system-wide limit.
* FreeBSD execution evidence is pending PR CI; the Tier-1 CI jobs are wired but
  have not yet run.

## Remaining (NOT implemented)

FreeBSD (and Debian CI) execution evidence from a successful PR CI run, and
per-plugin process-tree containment.
