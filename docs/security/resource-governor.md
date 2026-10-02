# Resource Governor Contract (Issue #53)

Status: **Slice 1 (policy contract) implemented. Enforcement is NOT
implemented.** Issue #53 is not complete.

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

`IsolatedPluginRuntime(resource_limits=..., resource_catalog=...)` resolves the
budget against the manifest `resource_class`. Policy failure raises
`LifecycleError("resource policy rejected: ...")`. A policy-valid budget still
raises `LifecycleError("resource-limit enforcement requires the Issue #53
launcher")` before any subprocess is spawned. `IsolatedResourceLimits` remains
importable from `pysh.plugins.isolated.runtime` as an alias of `ResourceBudget`.

## Slice 2: enforcement (NOT implemented)

Not yet present: `setrlimit` application, wall-clock watchdog, SIGKILL
containment of budget violations, `RESOURCE` diagnostic events, per-platform
semantics (Debian 13 and FreeBSD 14.4, Issue #52), and message/concurrency
enforcement in the broker. No budget is active until these exist.
