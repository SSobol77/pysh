<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/roadmap/ROADMAP-v1-2.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# PySH Roadmap to v1.0.0 (and v1.1.0 / v1.2.0)

Planning document for the release line built on top of the open
**v1.0.0 Readiness Audit (#35)**. It supersedes the loose post-0.8.0
backlog and organizes work into three milestones, with the **assurance
and contract layer** (security, API stability, performance budgets,
specification, supply chain) placed *before* feature expansion.

Status reference: released stable **PySH 0.9.0**, next milestone
**PySH v1.0.0** (see [Milestones](#2-milestones) below), target
**Python 3.13+**, validated on **Debian 13** and Unix-like systems,
GPL-2.0-only.

---

## 1. Rationale

The original post-0.9 feature backlog was drafted before the current GitHub
issue numbering and is almost entirely *functional*. The v1.1/v1.2 feature
entries below remain planned and are intentionally unnumbered until they are
filed as GitHub issues. For a project whose README already advertises **fast**,
**test-backed**, a hard **sensitive-input boundary**, and **determinism**,
those properties are the real 1.0 contract — and they are currently
under-specified. Three deferred features also ship new attack surface that
must not precede their security foundation:

- **Plugin SDK v1** ships third-party code execution.
- **AI Assistant Layer** ships network egress of command text and logs.
- **Remote Operations Framework** / **PySH Package Manager** ship SSH key handling and package signing.

Therefore the critical path is: **stabilize the editor → fix the contracts
(security, API, perf, language) → harden the core (fuzzing, differential
conformance, resource limits, supply chain) → only then expand features.**

Two original feature framings are corrected:

- The planned **Plugin SDK v1** "sandboxed execution model" in pure CPython is **not** a real
  security boundary. It is re-scoped through `#44` (process isolation +
  capability grants).
- **AI Assistant Layer** and **Interactive System Dashboard** add attack surface / cost but not
  stability; both are moved to **v1.2.0** (post-1.0).

---

## 2. Milestones

### PySH v1.0.0 — Critical Path (assurance + contract layer)

Ordered as three clusters. Within the *correctness* cluster the issues
share a single test harness (see `#48`/`#54`).

| # | Title | Cluster |
|---|-------|---------|
| #35 | PySH v1.0.0 Readiness Audit | umbrella / tracking |
| #36 | Interactive Line Editor Stabilization | foundation |
| #43 | Threat Model & Security Architecture | security |
| #44 | Plugin Isolation & Capability Model | security |
| #45 | Stable Public API, SemVer & Deprecation Policy | contract |
| #46 | Internal Architecture Freeze & Dependency Boundary Enforcement | contract |
| #47 | Performance Budget & CI Regression Gates | contract |
| #48 | PySH Language Specification & Conformance Suite | correctness |
| #49 | Parser/Tokenizer Fuzzing & Property-Based Robustness | correctness |
| #50 | Structured Diagnostics, Audit Log & Redaction Schema | observability |
| #51 | Supply-Chain Hardening: SBOM, Provenance & Signature Verification | supply chain |
| #52 | Portability & Platform Tier Contract | platform |
| #53 | Resource Governor & DoS Containment | platform |
| #54 | Shell Compatibility & Differential Migration Suite | correctness |

### PySH v1.1.0 — daily-value features

| # | Title |
|---|-------|
| TBD | Native File Viewer Framework |
| TBD | Advanced Completion Engine |
| TBD | Native Search Toolkit |
| TBD | Structured Data Toolkit |
| TBD | Plugin SDK v1 |
| TBD | Native Git Experience |

### PySH v1.2.0 — extended / networked features

| # | Title |
|---|-------|
| TBD | Interactive System Dashboard |
| TBD | AI Assistant Layer |
| TBD | Session Recording and Replay |
| TBD | Workspace Profiles |
| TBD | Remote Operations Framework |
| TBD | PySH Package Manager |

### PySH + ECLI Unification — post-1.0 / v1.3.0 candidate

Separate track. Not part of the 1.0.0 critical path; starts only after the
contract layer is stable. See the full section after the v1.2.0 issues.

| # | Title |
|---|-------|
| #60 | Monorepo Workspace and Package Boundary Setup |
| #61 | Shared Typed Core Contracts |
| #62 | Preview-Only ECLI Capability Boundary |
| #63 | Unified Terminal Ownership Model |
| #64 | Unified `wb` Launcher and Product Entry Points |

### Platform Expansion — post-1.0 candidate, feasibility-gated

Separate track. Not part of the 1.0.0 critical path and not a 1.x
compatibility promise. PySH remains a Python-first shell for Unix-like
systems. On Windows, the supported path today is WSL2 with full PySH
semantics and, after unification, the native ECLI workbench in preview
mode with delegated execution. A native Windows execution layer is
subject to a feasibility study (#65) and is not part of any 1.x
compatibility promise. PySH does not claim POSIX, Bash, or PowerShell
compatibility on any platform.

`#65` decides whether a native `pysh.exe` in PowerShell/ConPTY is worth
the engineering cost; `#66` is inert until `#65` concludes **go**. The
ECLI bridge, unified launcher, monorepo, shared contracts, preview-only
boundary, terminal ownership, and the `wb` launcher remain in `#60`–`#64`
and are not duplicated here. Issue specs live in `docs/issues/`.

| # | Title | Gate |
|---|-------|------|
| #65 | Windows Platform Feasibility Study | research / go–no-go decision |
| #66 | PowerShell Launch and Compatibility Layer | blocked by #65 go |
| #67 | Cross-Platform Path and Environment Translation | spec + library, no runtime changes |
| #68 | VSCode Terminal Integration | current supported Windows path (WSL2) |

---

## 3. Dependency graph

```
                         #35 v1.0.0 Readiness Audit (umbrella)
                                       │
                         #36 Line Editor (completed foundation)
                                       │
        ┌──────────── security ─────────────┐   ┌──────── contract ────────┐
        │ #43 Threat Model ────────▶ #44    │   │ #45 Public API ───▶ #46 │
        │     Plugin Isolation/Capabilities │   │     Architecture Freeze  │
        └───────────────────────────────────┘   └──────────────────────────┘
                                       │
        ┌──────────── correctness ─────────────┐
        │ #48 Language Spec ─────────▶ #49     │
        │          │                  Fuzzing  │
        │          └───────────────▶ #54       │
        │                    Differential Suite│
        └──────────────────────────────────────┘
                                       │
        ┌──── observability ────┐  ┌── supply chain ──┐  ┌──── platform ─────┐
        │ #50 Diagnostics/Audit │  │ #51 SBOM/Prov.   │  │ #52 Platform Tiers│
        │     + Redaction       │  │     + Signatures │  │ #53 Resource Gov  │
        └────────────────────────┘  └──────────────────┘  └───────────────────┘

Downstream planned features (v1.1/v1.2) consume these contracts but remain
unnumbered until filed as GitHub issues. In particular: Plugin SDK v1 depends
on #44/#45/#46/#53; Native Git and completion depend on #47/#52; AI/remote/pkg
work depends on #43/#50/#51/#53 as applicable.
```

**Minimum gate if scope must be cut before 1.0:** `#43 + #44 + #45 + #51`.
These close the largest risks (new-surface security + API/supply-chain
stability); without them the rest of the features become unrepayable debt.

---

## 4. Labels

Existing labels in use: `enhancement`, `architecture`, `platform`,
`testing`, `documentation`, `packaging`.

**New labels to create** (referenced below): `security`, `performance`,
`observability`, `release-blocking`. Unification track (`#60`–`#64`) also
introduces `runtime`, `terminal`, `ux`.

---

# Critical Path Issues (v1.0.0)

---

## #35 PySH v1.0.0 Readiness Audit
**Labels:** `architecture` `release-blocking` `documentation`
**Milestone:** v1.0.0 · **Status:** existing (umbrella/tracking)
**Depends on:** all critical-path issues below · **Blocks:** 1.0.0 tag

> Anchor tracking issue. Canonical body is maintained in the repository;
> this entry records its roadmap role and exit criteria so the audit gate
> is explicit.

**Description**
Single tracking issue that gates the 1.0.0 release. It does not contain
implementation; it aggregates the critical-path items and their exit
evidence, and freezes the definition of "1.0.0-ready".

**Exit criteria (release gate)**
- Every critical-path issue (`#36`, `#43`–`#54`) is closed with linked
  evidence (test runs, CI gates, docs).
- Performance budgets (`#47`) green on tier-1 platforms (`#52`).
- No open `regression`-class divergence in `#54`; no open security issue
  from the `#43` threat model.
- API surface frozen and documented (`#45`); SemVer policy published.
- Release artifacts carry SBOM + provenance + signatures (`#51`).

**Watch out for**
- Do not let planned v1.1/v1.2 feature work be pulled into the 1.0.0 milestone
  under schedule pressure; the audit's value is the freeze it enforces.

---

## #36 Interactive Line Editor Stabilization
**Labels:** `enhancement` `platform` `testing`
**Milestone:** v0.9.0 (completed prerequisite) · **Status:** closed
**Depends on:** — · **Supports:** [Advanced Completion Engine](#advanced-completion-engine), #47 (per-keystroke budget), #52 (termios/PTY contract)

**Description**
Stabilize the stdlib raw-mode line editor (character-by-character editing,
live syntax highlighting, fish-style autosuggestions, Ctrl+R reverse
search, bracketed paste) as the foundation every interactive feature
builds on. The editor's per-keystroke latency and correctness are
prerequisites for the planned [Advanced Completion Engine](#advanced-completion-engine) and the performance
budget (`#47`).

**Design & implementation**
- Treat the editor as the single owner of terminal state. All rendering
  goes through one redraw path; no feature writes to the TTY directly.
- Maintain an explicit input state machine (normal / reverse-search /
  paste-capture / continuation) with documented transitions; this is the
  surface fuzzed and tested by `#49`-adjacent editor tests.
- UTF-8 / wide-character correctness: cursor movement and redraw must use
  display width (`wcwidth` semantics), not byte or codepoint counts.
  Combining marks and CJK width are the common breakage points.
- Highlighting must be **non-blocking**: Pygments lexing runs on a bounded
  budget; if it exceeds the budget the editor falls back to plain text for
  that frame rather than stalling input (ties into `#47`).
- Restore terminal state deterministically on every exit path, including
  `SIGINT`, `SIGTSTP`/`SIGCONT`, and exceptions (termios `tcsetattr`
  restore in a `finally`/context manager).

**Watch out for**
- Bracketed paste must never let pasted control sequences execute or
  corrupt the screen; paste content is captured, not interpreted.
- `readline` fallback path and raw path must agree on Ctrl+R semantics so
  behavior does not depend on which editor is active.
- Resize (`SIGWINCH`) mid-edit must reflow without losing the buffer.

**Acceptance Criteria**
- Per-keystroke render latency within the budget set in `#47`.
- UTF-8 / wide-char / combining-mark editing verified by tests.
- Terminal state restored on every exit path (verified, including signals).
- No deadlock or corruption under paste of large multiline blocks.
- Behavior identical across raw and readline-fallback editors for Ctrl+R.

---

## #43 Threat Model & Security Architecture
**Labels:** `architecture` `security` `documentation` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #43 (keystone)
**Depends on:** — · **Blocks:** #44 and the planned Plugin SDK v1, AI Assistant Layer, Remote Operations Framework, and PySH Package Manager

**Description**
Keystone, cross-cutting security issue. Produces a formal threat model for
all of PySH, and **reserves the trust boundaries** for the deferred
AI Assistant Layer, Remote Operations Framework, and PySH Package Manager so their architecture is not
retrofitted in v1.2.

**Design & implementation**
- STRIDE per component: parser, persistent `py` runtime, `~/.pyshrc.py`
  loader, plugin loader, AI layer, remote exec, package manager.
- Define and diagram trust boundaries and every egress channel. Reserve
  boundaries for v1.2 features now (AI network egress; SSH key / agent
  handling for remote operations; signing/verification keys for package management).
- Treat **`~/.pyshrc.py` as a trust boundary**: it is arbitrary Python
  executed on startup. Specify a `safe-mode` / `--no-rc` launch path that
  loads no user code, used by CI, conformance (`#48`/`#54`) and recovery.
- Define the **capability model** that `#44` implements (default-deny;
  explicit grants; least privilege per component).
- Single, centralized **redaction policy** extending the existing
  sensitive-input boundary (passwords, tokens, keys never logged,
  buffered, or transmitted). This is the contract `#50` enforces in code.
- Data classification: enumerate what PySH must never persist or send
  (history secrets, env secrets, command bytes for sudo/ssh/gpg).

**Watch out for**
- "Sandbox" language: do not claim isolation that CPython cannot provide
  in-process; the threat model must explicitly state in-process is *not* a
  boundary and point to `#44`.
- Plugins, AI prompts and remote payloads can all carry injected secrets;
  redaction must be applied at the boundary, not at each call site.

**Acceptance Criteria**
- `docs/security/threat-model.md` with a trust-boundary diagram.
- Each of plugin / AI / remote / pkg has an assigned threat class and
  required controls, including the reserved-but-deferred boundaries.
- `--no-rc` / safe-mode launch path implemented and tested.
- The planned Plugin SDK v1, AI Assistant Layer, Remote Operations Framework, and PySH Package Manager must reference #43 as their security blocker.

---

## #44 Plugin Isolation & Capability Model
**Labels:** `architecture` `security` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #44 (re-scope of the planned Plugin SDK sandbox model)
**Depends on:** #43 · **Blocks:** planned Plugin SDK v1

**Description**
Replaces the unrealistic in-process "sandbox" with a verifiable isolation
model. This is the architectural decision that unblocks the planned
[Plugin SDK v1](#plugin-sdk-v1).

**Analysis / options**
1. **In-process** — rejected as a security boundary. Acceptable only for
   trusted/signed plugins (trust-on-install), never for untrusted code.
2. **Subprocess + IPC** — plugin runs as a separate process; an explicit
   wire protocol (length-prefixed JSON or msgpack over pipe/socket) is the
   only channel; capabilities are passed explicitly. Portable, a real
   boundary. **Recommended baseline.**
3. **OS-level** — `seccomp-bpf` (Linux) / `Capsicum` (FreeBSD) applied to
   the isolated process from option 2. Optional tier-1 hardening.

**Design & implementation**
- Adopt **option 2 as the portable contract** (Debian + FreeBSD), with
  option 3 as opt-in reinforcement gated by platform tier (`#52`).
- Plugin **manifest** declares requested capabilities (fs paths, network,
  env keys, builtins). No declaration ⇒ no access (**default-deny**).
- Capability tokens are unforgeable handles passed across IPC; the plugin
  process holds no ambient authority (no inherited fds beyond the IPC
  channel, scrubbed environment, dedicated cwd).
- Lifecycle: spawn, handshake (version + capability grant), serve,
  graceful drain, hard kill on timeout. A crashed or hung plugin must not
  take down the session (**fault containment**) and is reported through
  `#50`.
- Resource limits for the plugin process come from `#53` (CPU/mem/wallclock/
  fd/process budgets), applied at spawn.

**Watch out for**
- IPC deserialization is itself attack surface: bound message size, reject
  unknown types, never `pickle` across the boundary.
- Capability checks must be enforced in the *core* on each request, not
  trusted from the plugin side.
- File-descriptor leakage into the child must be prevented
  (`CLOEXEC` / explicit close).

**Acceptance Criteria**
- A plugin has no default access to fs / network / env without an explicit
  grant.
- Test: a malicious plugin cannot read `~/.pysh_history` or environment
  secrets without a matching capability.
- Test: plugin timeout / crash / fork attempt is contained; the session
  survives.
- Manifest format and capability versioning documented.

---

## #45 Stable Public API, SemVer & Deprecation Policy
**Labels:** `architecture` `documentation` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #45
**Depends on:** — · **Blocks:** planned Plugin SDK v1 and PySH Package Manager

**Description**
Freeze the public API surface before 1.0. Without a stable contract the
planned Plugin SDK v1 and PySH Package Manager ecosystem fragments on the
first release and every minor bump breaks plugins.

**Design & implementation**
- Explicit split: public vs. internal. Public API lives in a dedicated
  `pysh.api` module (re-exporting stable symbols); everything else is
  internal and `_`-prefixed or excluded from `__all__`.
- Publish a **SemVer** policy with a deprecation window (minimum one minor
  release) and machine-visible `DeprecationWarning` on deprecated symbols.
- Define the **embedding contract**: how to run PySH inside another Python
  process (entry points, lifecycle, no implicit global state).
- Add an API-surface snapshot test (e.g. golden list of public symbols and
  signatures) so accidental additions/removals fail CI.

**Watch out for**
- The plugin IPC protocol version (`#44`) and the Python `pysh.api` version
  are separate contracts; document both and their compatibility matrix.
- Avoid leaking internal types through public signatures (return/argument
  types become part of the contract).

**Acceptance Criteria**
- `docs/development/api-stability.md` with the 1.0 guarantee.
- Test asserting public symbols do not disappear without a deprecation
  cycle.
- The planned Plugin SDK v1 consumes only `pysh.api`.
- SemVer + deprecation policy published and linked from `#35`.

---

## #46 Internal Architecture Freeze & Dependency Boundary Enforcement
**Labels:** `architecture` `documentation` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #46
**Depends on:** #44 (IPC seam), #45 (public/internal split) · **Blocks:** planned Plugin SDK v1; also stabilizes the parse surface fuzzed by #49

**Description**
Companion to `#45`. Where `#45` freezes the *external* contract
(`pysh.api`, SemVer, deprecation), `#46` freezes the *internal*
architecture — module layering, dependency direction, and the
public/internal partition — so that pre-1.0 refactoring does not
destabilize the API snapshot (`#45`), the plugin IPC seam (`#44`), or the
parser surface (`#49`).

**Scope of the "freeze" (read carefully)**
"Freeze" applies to **boundaries, not implementations**. Internal code
stays free to change and be fixed; what is frozen is *who may import whom*,
*which layer owns what*, and *what is public vs internal*. A literal
code freeze would block bug fixes and is explicitly **not** the intent.

**Design & implementation**
- Define the layer map and allowed **dependency direction**, e.g.: parser
  must not depend on runtime/editor; core must not depend on feature
  plugins; the `pysh.api` layer re-exports only and is never imported by
  internals for logic. Record as an Architecture Decision Record (ADR).
- Enforce with an automated **import-direction / boundary check** in CI
  (e.g. `import-linter` or a custom AST rule) so violations fail the build,
  not code review.
- Establish a module **ownership map** and a stable seam between core and
  the `#44` IPC boundary, so plugins bind to a fixed internal contract.
- Make the public/internal partition the **single source of truth** shared
  with the `#45` API snapshot test (one definition, two consumers).

**Watch out for**
- Sequence is `#45 → #46`: the boundary definitions depend on the public
  API split (`#45`) and the IPC seam (`#44`). Do not freeze before those
  land.
- Circular imports and "convenience" cross-layer imports are the usual
  violations; the linter must run from the first day of the freeze, not be
  retrofitted.
- Keep the freeze about boundaries; resist scope creep into freezing
  function signatures of internal helpers (that is churn, not contract).

**Acceptance Criteria**
- `docs/architecture/layering.md` (or an ADR) with the layer map and
  allowed dependency direction.
- CI import-direction / boundary check fails on violation.
- Public/internal partition is consistent with the `#45` API snapshot.
- The core↔plugin seam is stable and referenced by #44 and the planned Plugin SDK v1.

---

## #47 Performance Budget & CI Regression Gates
**Labels:** `performance` `testing` `platform` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #47
**Depends on:** #36 · **Gates:** planned Advanced Completion Engine, Interactive System Dashboard, and Native Git Experience

**Description**
PySH advertises "fast". The planned Advanced Completion Engine, Native Git Experience,
and Interactive System Dashboard add startup and per-keystroke cost. Establish numeric budgets
enforced as CI regression gates.

**Budgets (initial targets, to be ratified)**
- Cold start ≤ **150 ms**
- Prompt render ≤ **20 ms**
- Completion ≤ **50 ms** (for the planned Advanced Completion Engine)
- Git prompt segment ≤ **10 ms** (for the planned Native Git Experience)
- Per-keystroke render within the `#36` editor budget

**Design & implementation**
- Benchmark harness (`pytest-benchmark` for in-process paths, `hyperfine`
  for process-level cold start), with thresholds versioned in-repo.
- CI gate fails a PR on regression beyond a set margin (e.g. > 10 %).
- **Lazy-import Pygments.** Pygments is installed by default and its
  import plus the first `get_lexer_by_name` (lexer plugin scan) costs tens
  of ms. The cold-start budget *requires* Pygments to load on first
  highlight, never on the startup path.
- **Lazy / async heavy segments.** Git, completion providers and dashboard
  collectors must be lazy-initialized and kept off the synchronous startup
  and prompt hot paths (see [Native Git Experience](#native-git-experience)).

**Watch out for**
- Benchmarks must pin the Python build and run on tier-1 platforms (`#52`);
  cold-start numbers are platform- and filesystem-sensitive.
- Import-time side effects in any module silently inflate cold start;
  guard with an import-cost test.

**Acceptance Criteria**
- Numeric thresholds per metric, versioned in the repo.
- CI blocks PRs on regression beyond the margin.
- Pygments verified absent from the import graph of the cold-start path.
- Git / completion / dashboard have separate budgets and lazy init.

---

## #48 PySH Language Specification & Conformance Suite
**Labels:** `architecture` `testing` `documentation` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #48
**Depends on:** — · **Blocks:** #49 (corpus), #54 (shared harness)
**Shares harness with:** #54

**Description**
Freeze the semantics of the `.pysh` language (operators, quoting,
redirections, heredoc/here-string, `py { ... }`, the mini rc-interpreter)
as a written spec plus a golden corpus. This is the precondition for the
"test-backed" claim at 1.0 and the *intrinsic* oracle for the correctness
cluster.

**Design & implementation**
- Formal grammar for tokenizer/parser (ABNF or equivalent), covering
  quote-aware splitting of chains (`;`, `&&`, `||`) and pipelines (`|`)
  only outside quotes, and shell-comment rules.
- Specify the **fd-handover contract** for pipelines: order of
  redirection application, inheritance, and close semantics — the exact
  behavior fuzzed by `#49`.
- **Golden corpus** with a *single shared case format* reused by `#54`:
  `input → { pysh_expected (AST / exit / stdout / stderr), ref_behavior,
  contract_ref }`. The intrinsic runner asserts `pysh_expected`.
- Exit-code contract: 127 (not found), 126 (not executable), 128+n
  (signal), and PySH-specific codes, documented and tested.

**Watch out for**
- Any change to language semantics must update the spec in the same PR
  (gate); spec drift silently invalidates both `#48` and `#54`.
- Distinguish *spec-defined* behavior from incidental current behavior;
  only freeze what is intended.

**Acceptance Criteria**
- `docs/spec/pysh-language.md` plus a corpus run in CI.
- fd-handover and exit-code contracts documented and covered.
- Semantic changes are gated on spec updates.
- Case format is the same record consumed by `#54`.

---

## #49 Parser/Tokenizer Fuzzing & Property-Based Robustness
**Labels:** `testing` `security`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #49
**Depends on:** #48 (semantics) · **Feeds:** #48, #54 (regression corpus)

**Description**
The quote-aware parser and fd-handover are core. Before 1.0 they get
coverage-guided fuzzing and property-based tests — a high-assurance
control that is cheap relative to the payoff.

**Design & implementation**
- Coverage-guided fuzzing (Atheris) on the tokenizer and the chain/pipe
  splitter; corpus seeded from the `#48` golden cases.
- Property-based tests (Hypothesis): quoting round-trips, no crash / no
  escape out of quotes, no fd leak after pipelines.
- Every discovered crash becomes a permanent regression case in the shared
  corpus (`#48`/`#54`).

**Watch out for**
- fd-leak detection needs an explicit probe (`/proc/self/fd` on Linux,
  `lsof` / `fstat` on FreeBSD); a parser that "passes" can still leak.
- Fuzzing must run against `--no-rc` safe-mode (`#43`) for reproducibility.

**Acceptance Criteria**
- No crash / unhandled exception over N million iterations.
- No descriptor leak after pipelines (verified per platform).
- Fuzz target in CI (smoke) plus a longer nightly run.
- Crashes captured as regression cases.

---

## #50 Structured Diagnostics, Audit Log & Redaction Schema
**Labels:** `architecture` `security` `observability`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #50
**Depends on:** #43 (redaction policy) · **Audits:** planned AI Assistant Layer, Remote Operations Framework, and PySH Package Manager

**Description**
Extend `--debug` / `--trace` into a **versioned event schema** plus an
audit trail for sensitive actions (AI egress, remote execution, and
package installation/signing). Implements the centralized redaction policy
defined in `#43`.

**Design & implementation**
- Stable, versioned event schema (JSON Lines); a schema version field; a
  single redaction pass applied at the emission boundary.
- Audit trail for: AI provider requests, remote execution, package
  installation, plugin loading — each with actor, action, target, decision.
- Redaction is centralized (one function), not duplicated per call site,
  so secrets cannot slip through a new emitter.

**Watch out for**
- Diagnostics must never alter command **stdout** (the existing contract);
  events go to stderr / a separate sink.
- Audit logging is opt-in, off-by-default, and must not add latency to the
  command hot path (`#47`).

**Acceptance Criteria**
- Schema versioned; any change bumps the version.
- Redaction test against known patterns (keys, passwords, tokens).
- Audit opt-in, off-by-default, zero stdout impact.
- Plugin/AI/remote/pkg actions are audited when enabled.

---

## #51 Supply-Chain Hardening: SBOM, Provenance & Signature Verification
**Labels:** `packaging` `security` `release-blocking`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #51
**Depends on:** — · **Blocks:** planned PySH Package Manager

**Description**
The planned PySH Package Manager requires package signing, but the whole distribution chain (GitHub
Releases, PyPI, `.deb`, `.rpm`, FreeBSD `.pkg`) needs SBOM, provenance and
signature verification. This contract unblocks the planned package manager and hardens PySH's own distribution.

**Design & implementation**
- Generate an **SBOM** (CycloneDX) during the build for every artifact.
- **Provenance** (SLSA / GitHub artifact attestations) for release
  artifacts; verifiable from the published release.
- Ecosystem package **signature verification** before install in
  `pkg install` (sigstore or minisign), enforced **default-deny**.
- Reproducible builds verified for the wheel and OS packages.

**Watch out for**
- The artifact-naming contract in `docs/development/packaging.md` must stay
  consistent with attestation subjects (mismatched names break
  verification).
- Trust-root distribution for `pkg` verification is itself security-
  sensitive; document key rotation.

**Acceptance Criteria**
- Every release ships SBOM + attestation.
- `pkg install` rejects a package without a valid signature (default-deny).
- Build reproducibility verified.

---

## #52 Portability & Platform Tier Contract
**Labels:** `platform` `documentation` `testing`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #52
**Depends on:** — · **Supports:** #44 (Capsicum), #54 (tier-1 CI), #36/#47 (termios/PTY)

**Description**
The planned Native File Viewer Framework and Native Git Experience claim "Debian and FreeBSD". Define an explicit platform
contract: which platforms are tier-1 (gated in CI) vs tier-2
(best-effort), and the behavior contract for termios / PTY / signals / fds.

**Design & implementation**
- Support matrix: Debian 13, FreeBSD, other Linux/Unix — support level +
  CI matrix per tier.
- Behavior contract for OS differences: termios, PTY (`secure`), signal
  handling, fd semantics; documented fallbacks.
- Anchor point for `Capsicum` (FreeBSD) used by `#44`'s OS-level option.

**Watch out for**
- FreeBSD vs Linux differ in PTY allocation, signal delivery and `/proc`
  availability (affects #49 fd-leak probes and the planned Interactive System Dashboard collectors).
- Tier-2 platforms must fail loudly and clearly, never silently misbehave.

**Acceptance Criteria**
- `docs/compatibility/platform-tiers.md`.
- CI runs the test suite on every tier-1 platform.
- OS-dependent features have an explicit fallback or a clear unsupported
  message.

---

## #53 Resource Governor & DoS Containment
**Labels:** `architecture` `security` `platform`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #53
**Depends on:** #44 (isolated process target) · **Supports:** planned Interactive System Dashboard, Plugin SDK v1, AI Assistant Layer, and Remote Operations Framework

**Description**
Limits today are point solutions (5 s command-substitution timeout,
rc-interpreter iteration cap). The planned Plugin SDK v1, AI Assistant Layer,
Interactive System Dashboard, and Remote Operations Framework need a unified governor of CPU / wallclock /
memory / fd / process budgets.

**Design & implementation**
- A common budget interface plus enforcement: `resource.setrlimit` on the
  isolated process from `#44`, wallclock timeouts, fd/process caps.
- Default budgets per task class; configurable, but with a hard ceiling
  that user config cannot exceed.
- Budget violations are contained and reported through `#50`.

**Watch out for**
- `setrlimit` granularity and semantics differ across Linux/FreeBSD
  (`#52`); wallclock enforcement needs a watchdog independent of the
  child's cooperation.
- A misbehaving child must be killed (`SIGKILL` after grace), not merely
  signaled, to guarantee containment.

**Acceptance Criteria**
- A plugin / AI / remote task exceeding budget is stopped without taking
  down the session.
- Tests force timeout / OOM / fork-bomb in isolation and verify
  containment.
- Limits documented and versioned; hard ceilings enforced over user
  config.

---

## #54 Shell Compatibility & Differential Migration Suite
**Labels:** `testing` `platform` `documentation`
**Milestone:** v1.0.0 · **Status:** filed as GitHub #54 (correctness cluster)
**Depends on:** #48 (shared harness/format), #52 (tier-1 platforms)
**Shares harness with:** #48

**Description**
Differential corpus comparing `pysh` against reference shells (`bash`,
`zsh`, `fish`) for core semantics, with divergence classified against
PySH's documented contracts. Goal: every parser/runtime change is checked
against reference behavior **and** against declared non-goals.

**Scope (corpus categories)**
quoting; redirections (`<`, `>`, `>>`, `2>`, `&>`); pipes + fd handover;
environment and local variables; command substitution (`$()` / backticks);
heredoc / here-string; exit codes (127 / 126 / 128+n and POSIX
conventions); operator ordering and conditions (`;`, `&&`, `||`).

**Oracle (the crux — three-valued, not binary)**
Each case resolves to one of:
- `match` — agrees with the reference;
- `intended-divergence` — divergence anchored in `feature-matrix.md` or
  `unsupported-constructs.md` (expected, **not** a failure); the case must
  link the contract entry (`contract_ref`);
- `regression` — divergence **not** described in any contract ⇒ a real bug
  (**CI fail**).

A naive binary differential test would flag every documented divergence as
a failure and drown the signal; the three-valued oracle is what makes this
suite protective rather than noisy.

**Design & implementation**
- Reuse the `#48` case record: `input → { pysh_expected, ref_behavior,
  contract_ref }`. Two runners over one corpus: intrinsic (`#48`) and
  differential (`#54`).
- **Pin reference-shell versions** in CI (shell behavior changes across
  versions; unpinned references make the suite non-reproducible).
- Run on tier-1 platforms (`#52`) so termios/PTY differences surface in
  results rather than hiding.

**Watch out for**
- A new `intended-divergence` requires updating `feature-matrix.md` in the
  same PR (gate); otherwise the contract and the suite drift apart.
- Interactive-only constructs need a controlled PTY harness, not just pipe
  redirection, to compare faithfully.

**Acceptance Criteria**
- Reference shells pinned by version in CI.
- Every divergence is `match`, `intended-divergence` (with `contract_ref`),
  or `regression`.
- No `regression` passes the merge gate.
- New `intended-divergence` co-updates `feature-matrix.md` (gate).
- Exit-code contract documented and covered (consistent with `#48`).
- Corpus runs on tier-1 platforms from `#52`.

---

# v1.1.0 Feature Issues

> Original scope preserved; labels, design/dependency notes added.

---

## Native File Viewer Framework
**Labels:** `enhancement` `architecture` `platform` `testing`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** #47 (perf), #52 (Debian/FreeBSD)

**Description**
Native PySH file viewing framework inspired by `bat`, `less`, `more`,
written entirely in Python and integrated with the PySH UX. Provide a
modern viewing experience without external utilities.

**Features**
Syntax highlighting; line numbers; grid and framed display modes; Markdown
rendering; JSON / YAML / TOML / XML formatting; search mode; pager mode;
UTF-8 and Unicode support; large-file support; theme support.

**Commands**
`view README.md`, `view script.py`, `view data.json`, `view config.yaml`

**Design & implementation**
- Large-file handling must be **streaming / windowed** (mmap or chunked
  reads); never load the file fully into memory. Required to meet the
  >1 GB criterion.
- Reuse the lazy-Pygments path from `#47`; the viewer is the natural first
  consumer of on-demand lexers.
- Share width/Unicode handling with the `#36` editor (single wcwidth
  implementation), not a second copy.

**Watch out for**
- Search over a 1 GB file must be incremental and cancellable; do not build
  an in-memory index of the whole file.
- Binary / invalid-UTF-8 input must degrade gracefully (hex/replacement),
  not crash the pager.

**Acceptance Criteria**
- Large files open without excessive memory use; files > 1 GB supported.
- Interactive search works.
- Correct on Debian and FreeBSD.
- Automated tests cover all major rendering modes.

---

## Advanced Completion Engine
**Labels:** `enhancement` `architecture` `testing`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** #36 (editor), #47 (≤50 ms gate)

**Description**
Replace the current completion subsystem with a context-aware engine
offering IDE-class completion quality.

**Features**
Command / path / variable / alias completion; history-assisted completion;
frequency-based ranking; context-sensitive suggestions.

**Context providers**
`git`, `docker`, `kubectl`, `uv`, `pip`, `npm`, `cargo`, `systemctl`.

**Design & implementation**
- Provider interface must be **lazy and budgeted**: each provider runs
  under the `#47` 50 ms ceiling; a provider that exceeds it is cancelled
  and yields no suggestion rather than stalling the keystroke.
- Context providers that shell out (e.g. `git`, `kubectl`) must cache and
  must never block the keystroke path synchronously (mirror the Native Git Experience rule).
- Ranking model persists frequency/recency; storage shares the config
  contract once Workspace Profiles lands, but ships standalone here.

**Watch out for**
- Provider crashes must be contained (fault isolation), not propagate to
  the editor.
- TAB behavior of existing workflows must not regress (lock with tests).

**Acceptance Criteria**
- Completion latency stays below 50 ms (enforced by `#47` gate).
- Ranking adapts to usage history.
- Interactive tests cover all supported contexts.
- No regressions in existing TAB workflows.

---

## Native Search Toolkit
**Labels:** `enhancement` `platform` `testing`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** #52

**Description**
High-performance Python-native search utilities integrated into PySH.

**Commands**
`search`, `findpy`, `where`, `whichall`

**Features**
Recursive search; regex; case-sensitive and case-insensitive; file and
extension filtering; colored output; structured output mode.

**Design & implementation**
- Walk with `os.scandir` (not `os.walk` building lists); stream results to
  the [Native File Viewer Framework](#native-file-viewer-framework) rather than collecting all matches first.
- Regex: precompile; offer a literal fast-path; guard against catastrophic
  backtracking (bound or reject pathological patterns).
- Parallelism via a bounded worker pool; ordering preserved for structured
  output.

**Watch out for**
- 100k-file repos: avoid O(files) memory; respect `.gitignore`-style
  excludes to stay competitive.
- Symlink loops and permission errors must be handled, not fatal.

**Acceptance Criteria**
- Supports repositories with 100,000+ files.
- Competitive search performance.
- Automated benchmarks included.
- Comprehensive test coverage.

---

## Structured Data Toolkit
**Labels:** `enhancement` `platform` `documentation`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** Native File Viewer Framework (shared rendering)

**Description**
First-class support for structured data formats common in developer work.

**Supported formats**
JSON, YAML, TOML, XML, CSV, INI.

**Commands**
`json file.json`, `yaml config.yaml`, `csv report.csv`, `xml data.xml`

**Features**
Pretty printing; validation; formatting; filtering; querying; conversion
between formats.

**Design & implementation**
- Reuse the Native File Viewer Framework for rendering; this issue adds parse/validate/
  query/convert, not a second pager.
- YAML/XML parsing must be **safe by default** (no arbitrary tag
  construction, no external-entity expansion / XXE). Use safe loaders only.
- Conversions are lossy across some format pairs (e.g. YAML anchors → JSON);
  document and warn rather than silently drop.

**Watch out for**
- XXE and YAML deserialization are classic RCE vectors; this ties to `#43`.
- Streaming for large structured files where the parser allows
  (CSV/JSON-lines); full-DOM parsers (XML) need size limits (`#53`).

**Acceptance Criteria**
- All supported formats validate correctly.
- Invalid input produces clear diagnostics.
- Documentation includes examples.

---

## Plugin SDK v1
**Labels:** `architecture` `enhancement` `documentation`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** #44 (isolation), #45 (API), #46 (internal seam), #53 (limits)

**Description**
Official PySH Plugin SDK and extension system, allowing third-party
developers to extend PySH without modifying core code.

**Features**
Plugin discovery, installation, removal, updates; plugin metadata;
dependency management; **isolated execution model (per #44)**.

**Commands**
`plugin install`, `plugin remove`, `plugin update`, `plugin search`

**Design & implementation**
- Execution model is **not** in-process sandboxing; it is the process
  isolation + capability grants defined in `#44`. The SDK exposes only the
  `pysh.api` surface frozen in `#45`.
- Manifest carries metadata, requested capabilities (`#44`) and resource
  class (`#53`). Version compatibility enforced against the SDK/API version
  from `#45` and the IPC protocol version from `#44`.
- Plugin loading is logged to the `#50` audit trail.

**Watch out for**
- Dependency management must not let a plugin pull arbitrary code onto the
  hot path; resolve and verify before activation (`#51` signing applies to
  ecosystem packages via the planned PySH Package Manager.
- "Security validation for plugin loading" = capability + signature checks,
  defined in `#44`/`#51`, not ad hoc.

**Acceptance Criteria**
- Stable plugin API (consumes `pysh.api` only).
- Version compatibility enforcement (API + IPC protocol).
- Security validation for plugin loading (capability + signature).
- Complete SDK documentation.

---

## Native Git Experience
**Labels:** `enhancement` `platform`
**Issue:** TBD · **Milestone:** v1.1.0 · **Depends on:** #47 (≤10 ms prompt gate), #52

**Description**
Deep Git integration directly into PySH.

**Features**
Repository detection; branch awareness; status awareness; dirty-tree
indicators; ahead/behind indicators.

**Commands**
`gst`, `gcm`, `gps`, `gpl`, `gco`

**Design & implementation**
- The prompt segment budget is **≤ 10 ms (#47)**, which **forbids spawning
  `git` on the synchronous prompt path**. `fork`/`exec` of `git` already
  approaches that ceiling, and `git status` in a large repo exceeds it by
  an order of magnitude.
- Read branch/HEAD **directly** from the repo: `.git/HEAD`, `packed-refs`,
  symbolic-ref resolution — no subprocess.
- Dirty-state and ahead/behind are expensive: compute **asynchronously**
  with a short-lived cache, or off the hot path entirely; the prompt shows
  the last known value and refreshes in the background.
- The `g*` command builtins may shell out to `git` (not on the prompt
  path); only prompt rendering is constrained.

**Watch out for**
- Worktrees, submodules and detached HEAD must be handled when reading
  refs directly.
- Cache invalidation on `cd` and after `g*` commands.

**Acceptance Criteria**
- Prompt updates automatically (async, cached).
- Works with large repositories within the 10 ms prompt budget.
- No noticeable startup delay (lazy init).
- Tested on Debian and FreeBSD.

---

# v1.2.0 Feature Issues

> Moved post-1.0: add attack surface or cost, not stability.

---

## Interactive System Dashboard
**Labels:** `enhancement` `platform`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #47 (overhead), #53 (collector budgets), #52

**Description**
Built-in real-time system monitoring dashboard.

**Command**
`dashboard`

**Features**
CPU, memory, disk, network statistics; process list; temperature; battery;
Python runtime statistics.

**Design & implementation**
- Collectors are platform-specific (`/proc`, `/sys` on Linux; `sysctl` on
  FreeBSD); abstract behind a provider interface gated by `#52`.
- Each collector runs under a `#53` budget; a slow/unavailable collector
  degrades to "n/a", never blocks the refresh loop.
- Must remain low-overhead over SSH (no busy-loop; configurable refresh).

**Watch out for**
- Temperature/battery are frequently absent (VMs, servers); handle missing
  sources gracefully.
- Long-running session: no memory growth in the refresh loop.

**Acceptance Criteria**
- Configurable refresh rate.
- Works correctly over SSH.
- Minimal CPU overhead.
- Stable under long-running sessions.

---

## AI Assistant Layer
**Labels:** `enhancement` `architecture` `security`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #43 (egress boundary), #50 (audit), #53 (limits)

**Description**
Optional AI assistance framework integrated into PySH workflows. Deferred
to v1.2 because it adds network egress and attack surface, not stability.

**Commands**
`ai explain`, `ai fix`, `ai generate`, `ai review`

**Providers**
OpenAI, Anthropic, Ollama, llama.cpp.

**Features**
Command explanation; log analysis; script generation; code review; shell
assistance.

**Design & implementation**
- Egress crosses a trust boundary reserved in `#43`: outbound payloads pass
  the centralized redaction (`#50`) before transmission; **explicit user
  consent required before any external request**.
- Provider abstraction with a clear local (`Ollama`, `llama.cpp`) vs remote
  (`OpenAI`, `Anthropic`) split; remote providers require consent, local do
  not egress.
- Every external request is recorded in the `#50` audit trail; calls run
  under a `#53` wallclock/size budget.

**Watch out for**
- Command text and logs routinely contain secrets; redaction at the
  boundary is mandatory and tested (`#50`).
- The shell must remain fully functional offline with the layer disabled.

**Acceptance Criteria**
- AI layer remains optional; PySH works fully offline when disabled.
- Provider abstraction implemented.
- User consent required before external requests.
- Outbound payloads pass redaction; requests are audited.

---

## Session Recording and Replay
**Labels:** `enhancement` `testing` `security`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #43 (redaction), #50 (schema)

**Description**
Complete session recording and replay capabilities.

**Commands**
`record start`, `record stop`, `record export`, `replay`

**Export formats**
Markdown, HTML, JSON.

**Design & implementation**
- Recording reuses the `#50` event schema where possible; secrets are
  redacted at capture time, not export time (a recording at rest must
  already be clean).
- Replay must be sandboxed/dry-run by default so replaying a session does
  not re-execute destructive commands unintentionally.

**Watch out for**
- `secure <cmd>` PTY sessions and password prompts must never be captured
  (existing sensitive-input boundary).
- HTML export must escape terminal control sequences (no injection into the
  rendered page).

**Acceptance Criteria**
- Full command history preserved (redacted).
- Replay reproduces sessions accurately.
- Export formats validated by tests.

---

## Workspace Profiles
**Labels:** `enhancement` `platform`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #45 (config contract)

**Description**
Switch between predefined development environments.

**Commands**
`profile activate`, `profile list`, `profile export`

**Example profiles**
`python`, `rust`, `java`, `nodejs`, `guardbsd`, `aeronerve`.

**Design & implementation**
- Profile = a declarative, versioned config document (no arbitrary code on
  activation; arbitrary Python stays in `~/.pyshrc.py` behind the `#43`
  trust boundary).
- PATH and env mutations are recorded so deactivation is **exactly
  reversible** (snapshot/restore, not best-effort unset).

**Watch out for**
- Activating a profile must not leak env from a previous profile; verify
  isolation.
- Reversibility under nested activation (activate A, then B, deactivate B).

**Acceptance Criteria**
- Profile activation is immediate.
- PATH modifications are reversible.
- Environment isolation verified.

---

## Remote Operations Framework
**Labels:** `enhancement` `platform` `security`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #43 (SSH key boundary), #50 (audit), #53 (parallel limits)

**Description**
Unified remote execution and administration.

**Features**
SSH execution; SCP transfers; SFTP operations; multi-host and cluster
execution.

**Commands**
`remote run`, `remote copy`, `remote sync`

**Design & implementation**
- SSH key / agent handling crosses the trust boundary reserved in `#43`;
  keys are never logged or buffered, and operations are audited (`#50`).
- Parallel/cluster execution runs under `#53` concurrency and resource
  budgets; per-host failures are isolated and reported, not fatal to the
  batch.
- Connection reuse (multiplexing) is a correctness concern under
  parallelism — bound the pool and handle half-open connections.

**Watch out for**
- Host-key verification must be enforced (no blind accept); a `known_hosts`
  policy is part of `#43`.
- Partial failures in multi-host runs need clear, structured reporting.

**Acceptance Criteria**
- SSH key support (verified host keys, no secret leakage).
- Parallel execution support under resource budgets.
- Failure reporting (per-host, structured).
- Connection-reuse optimization.

---

## PySH Package Manager
**Labels:** `architecture` `packaging` `enhancement` `security`
**Issue:** TBD · **Milestone:** v1.2.0 · **Depends on:** #45 (API), #51 (signing/SBOM), #44 (capability install)

**Description**
Dedicated package manager for PySH extensions and ecosystem components.

**Commands**
`pkg install`, `pkg remove`, `pkg search`, `pkg update`

**Features**
Repository support; version locking; dependency resolution; upgrade
management; integrity verification.

**Design & implementation**
- Integrity/signature verification is the `#51` contract applied at install
  time: **default-deny** on unsigned or unverifiable packages.
- Installed plugins are activated under the `#44` capability model; a
  package declares its requested capabilities at install for explicit
  consent.
- Reproducible installs via a lock file (pinned versions + hashes); offline
  cache keyed by hash.

**Watch out for**
- Dependency resolution must reject conflicting capability escalations;
  installing a dependency must not silently broaden granted capabilities.
- Trust-root and key-rotation handling come from `#51`.

**Acceptance Criteria**
- Reproducible installations (lock file with hashes).
- Package signing support (default-deny on failure).
- Offline cache support.
- Full documentation.

---

# Unification — post-1.0 / v1.3.0 candidate

> Scope: PySH + ECLI product unification, started only after the PySH
> v1.0.0 contract layer is stable. This is a **separate track** and must not
> be pulled into the v1.0.0 critical path; the milestone layout stays
> v1.0.0 = assurance/contract, v1.1.0 = daily-value, v1.2.0 =
> networked/extended. Full engineering design lives in
> `UNIFICATION-DESIGN.md`.

This track unifies PySH and ECLI into one coherent product line **without**
creating a god application, **without** weakening PySH execution
determinism, and **without** breaking ECLI's preview-only guarantees.

**Recommended architecture**
- one monorepo;
- shared typed kernel / services;
- two front-ends: `pysh` and `ecli`;
- unified launcher: `wb`;
- inert `CommandPlan` as the execution boundary;
- only `ExecutorService` may execute plans;
- ECLI authoring packages must not import executor code.

---

## #60 Monorepo Workspace and Package Boundary Setup
**Labels:** `architecture` `packaging` `testing`
**Milestone:** post-1.0 / v1.3.0 candidate · **Status:** new
**Depends on:** PySH `#45` / `#46` (frozen API + layering) · **Blocks:** #61, #62, #63, #64

**Description**
Create the unified repository layout and workspace structure for PySH +
ECLI. No code coupling yet — both front-ends keep building independently
inside one repo (uv workspace).

**Required scope**
- introduce a `packages/` layout;
- preserve both code histories where possible (`git filter-repo` /
  `subtree`);
- define shared package naming;
- define import boundaries (layer direction, enforced in CI);
- keep `pysh` and `ecli` runnable as independent front-ends;
- prepare the `wb` launcher package;
- add CI import-boundary checks (`import-linter`).

**Acceptance Criteria**
- Monorepo layout exists.
- Both front-ends run.
- Package ownership is documented.
- An import-boundary test exists.
- No executor import from ECLI authoring packages.

---

## #61 Shared Typed Core Contracts
**Labels:** `architecture` `runtime` `testing`
**Milestone:** post-1.0 / v1.3.0 candidate · **Status:** new
**Depends on:** #60, PySH `#48` (schema/spec), `#50` (audit schema) · **Blocks:** #62, #63, #64

**Description**
Extract the shared typed service contracts used by both PySH and ECLI into
the common core.

**Required scope**
- `CommandPlan`;
- `ExecutorService` protocol;
- `TerminalService`;
- `ConfigService`;
- `DiagnosticsService`;
- `AuditService`;
- `CapabilityBroker`.

**Hard invariant**
`CommandPlan` is inert data. It may be created, serialized, inspected,
previewed, audited, and validated, but it must not execute itself.

**Acceptance Criteria**
- Typed contracts exist.
- Schema versioning exists.
- Unknown schema versions are rejected.
- JSON round-trip tests exist.
- The executor boundary is enforced by tests.

---

## #62 Preview-Only ECLI Capability Boundary
**Labels:** `architecture` `security` `runtime` `testing`
**Milestone:** post-1.0 / v1.3.0 candidate · **Status:** new
**Depends on:** #61, PySH `#44` (capability model) · **Blocks:** #64

**Description**
Preserve ECLI's preview-only behavior inside the unified product.

**Required scope**
- default-deny capability broker;
- no ambient execution authority;
- ECLI authoring packages cannot import the executor implementation;
- plan generation and plan execution are separated;
- the audit trail records execution decisions.

**Hard invariant**
ECLI may generate a `CommandPlan`, but only `ExecutorService` may execute it.

**Acceptance Criteria**
- An `import-linter` rule blocks executor imports from ECLI authoring
  packages.
- Tests prove ECLI can preview without execution authority.
- Execution requires an explicit capability grant.
- Denied execution produces structured diagnostics.

---

## #63 Unified Terminal Ownership Model
**Labels:** `terminal` `ux` `runtime` `testing`
**Milestone:** post-1.0 / v1.3.0 candidate · **Status:** new
**Depends on:** #61, PySH `#36` (line editor) · **Blocks:** #64

**Description**
Create one terminal ownership model for line-mode PySH and full-screen
ECLI. This is the highest-risk part of the merge: curses and raw-mode must
never write to the TTY simultaneously.

**Required scope**
- one `TerminalService`;
- mutually exclusive terminal states;
- line-mode state;
- full-screen state;
- a deterministic restore path;
- signal-safe cleanup;
- no simultaneous curses / raw-mode writers.

**Acceptance Criteria**
- The PySH raw-mode editor and the ECLI full-screen UI do not write to the
  TTY directly.
- Terminal restore works after Ctrl+C.
- Terminal restore works after exceptions.
- Terminal restore works after resize.
- No screen corruption in mode-switching tests.

---

## #64 Unified `wb` Launcher and Product Entry Points
**Labels:** `enhancement` `runtime` `ux` `testing`
**Milestone:** post-1.0 / v1.3.0 candidate · **Status:** new
**Depends on:** #60, #61, #62, #63, PySH `#47` (cold-start budget), `#52` (platform tiers)

**Description**
Introduce the unified Workbench launcher while preserving the existing entry
points.

**Required scope**
- `pysh` remains the shell entry point;
- `ecli` remains the editor/workbench entry point;
- `wb` becomes the unified launcher;
- lazy import of full-screen UI dependencies (so plain `pysh` does not pay
  the curses cost — `#47`);
- the Unix executor is enabled only where supported;
- preview-only mode on unsupported executor platforms (`#52`).

**Acceptance Criteria**
- `wb pysh` launches PySH.
- `wb ecli` launches ECLI.
- `wb plan` creates inert command plans.
- `wb run` executes only through `ExecutorService`.
- Unsupported platforms fail safely into preview/diagnose mode.
- Existing `pysh` and `ecli` commands remain compatible.

---

## 5. Issue synchronization and filing rules

The v1.0.0 critical-path issues are now filed in GitHub and the numbers in
this document are canonical:

| Issue | Title |
|---|---|
| #35 | PySH v1.0.0 Readiness Audit |
| #43 | Threat Model & Security Architecture |
| #44 | Plugin Isolation & Capability Model |
| #45 | Stable Public API, SemVer & Deprecation Policy |
| #46 | Internal Architecture Freeze & Dependency Boundary Enforcement |
| #47 | Performance Budget & CI Regression Gates |
| #48 | PySH Language Specification & Conformance Suite |
| #49 | Parser/Tokenizer Fuzzing & Property-Based Robustness |
| #50 | Structured Diagnostics, Audit Log & Redaction Schema |
| #51 | Supply-Chain Hardening: SBOM, Provenance & Signature Verification |
| #52 | Portability & Platform Tier Contract |
| #53 | Resource Governor & DoS Containment |
| #54 | Shell Compatibility & Differential Migration Suite |

Filing rules:

- Do not reuse historical issue numbers for planned v1.1/v1.2 features.
  Those sections stay **TBD / unnumbered** until the corresponding GitHub
  issues are actually created.
- #43, #44, #45, and #51 form the minimum security/API/supply-chain gate.
  #46 follows #44/#45 because it freezes the boundaries they define.
- #48 and #54 share the conformance case format and should evolve together;
  #49 feeds minimized fuzz failures back into the same regression corpus.
- Future issue creation must update this roadmap in the same change so a
  roadmap identifier never points at an unrelated GitHub issue.
