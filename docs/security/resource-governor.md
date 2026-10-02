<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/security/resource-governor.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Resource Governor Contract (Issue #53)

Status: **Slice 1 (policy contract) and Slice 2 (POSIX rlimit and IPC-size
enforcement) implemented. Wall-clock watchdog, concurrency supervision,
structured violation diagnostics and the abuse suite are NOT implemented.**
Issue #53 is not complete.

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
| `concurrency` | simultaneous in-flight requests |

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
| `concurrency` | 8 | Bounds in-flight requests per plugin. |

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
`processes`, `message_size`, `concurrency`. Slice 1 emits none.

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
| `wall_clock_seconds` | **Not enforced** (Slice 3 watchdog) |
| `concurrency` | **Not enforced** (later supervision work) |

Enforceable floors (rejected, never silently raised): descriptors >= 8,
memory >= 32 MiB, message >= 1024 bytes. An explicit request for a field that
nothing enforces (`wall_clock_seconds`, `concurrency`, or `processes` without
the opt-in) fails closed. Profile defaults for those fields are listed in
`deferred_fields` rather than implied to be active. A platform without a
required primitive fails closed before exec.

### Semantics and caveats

* Memory is a **virtual address-space** limit, not a resident-memory meter. It
  does not account physical RAM and is not a cgroup or jail.
* `RLIMIT_NPROC` counts processes of the whole real UID, not a plugin
  descendant tree, so it is not exact per-plugin containment. In opt-in mode an
  absolute value below the user's current process count blocks every `fork` of
  the plugin; a value above it permits other-user-process growth. Per-plugin
  process-tree containment is deferred to the supervisor layer.
* CPU: on exceeding the soft/hard limit the kernel signals the plugin
  (`SIGXCPU`/`SIGKILL`). The parent sees an ordinary child death; it does not
  attribute it as a resource violation yet (Slice 3).
* Linux: `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NOFILE`, `RLIMIT_NPROC` exist;
  `RLIMIT_NPROC` is enforced against the real UID and is ignored for root /
  `CAP_SYS_RESOURCE`.
* FreeBSD: `RLIMIT_VMEM` is the address-space limit (aliased to `RLIMIT_AS` in
  Python); the rest map identically. Capsicum and per-jail accounting are not
  used. FreeBSD validation remains pending (Issue #52) until run on that tier.

## Remaining (NOT implemented)

Independent wall-clock watchdog with TERM -> grace -> KILL, `RESOURCE`
diagnostic events and violation attribution, concurrency supervision, per-
plugin process-tree limits, and the final DoS abuse suite.
