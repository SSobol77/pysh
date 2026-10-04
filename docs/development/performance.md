<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/performance.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Performance Contract and Regression Gates

This document is the normative human-readable performance contract established
by Issue #47. The canonical machine-readable values are in
[`performance.toml`](../../performance.toml), and the standard-library harness
is [`scripts/benchmark_performance.py`](../../scripts/benchmark_performance.py).
Documentation, policy, harness scenarios, and CI jobs must change together.

The contract freezes measurable boundaries, not implementations. A compliant
optimization may replace internal code provided behavior, security, public API,
and Issue #46 dependency boundaries remain valid.

## Versioned budgets

All measurements use milliseconds and median aggregation. The CI threshold is
the nominal budget plus the profile's explicit 20% infrastructure-noise
margin. The JSON report records both `within_nominal_budget` and the gating
status so the margin cannot silently redefine the nominal target.

| Benchmark ID | Scope | Samples / warmups | Nominal budget | CI threshold | Status of Issue #47 target |
| ------------ | ----- | ----------------- | -------------- | ------------ | -------------------------- |
| `cold_start` | Fresh process | 9 / 2 | 175 ms | 210 ms | Initial 150 ms revised with measured evidence |
| `prompt_render` | In process | 31 / 5 | 20 ms | 24 ms | Ratified |
| `git_context` | In process | 31 / 5 | 10 ms | 12 ms | Ratified |
| `completion_core` | In process | 31 / 5 | 50 ms | 60 ms | Ratified |
| `keystroke_render` | In process | 51 / 10 | 2 ms | 2.4 ms | Derived and ratified from the stabilized editor |

Every benchmark is release-blocking for both current validation profiles:

- `linux-python3-13`: Debian/Linux development and GitHub
  `ubuntu-latest`, Python 3.13;
- `freebsd-14-4-python3-13`: real FreeBSD 14.4 VM, Python 3.13.

These are performance validation profiles, not final support-tier decisions.
Issue #52 may formalize or reclassify tiers without changing the benchmark
schema.

## Benchmark definitions

### Fresh-process cold start

Each warmup and measured sample launches a new process:

```text
<current Python> -m pysh --no-rc -c ""
```

The timer is in the parent and includes Python process creation, module import,
CLI parsing, `PyShell` construction, dispatch of an empty command, and process
exit. Standard streams use `/dev/null`; the child receives a fixed minimal
environment, `PYTHONNOUSERSITE=1`, and the strict `--no-rc` policy. It performs
no user config/plugin discovery and no external command execution. The `uv`
launcher used to start the harness is outside each sample.

“Cold” means a fresh process under normal host page-cache conditions. The
harness does not require root access, clear filesystem caches, or claim a
power-cycle/cold-storage measurement.

The original 150 ms target was not reached on the Debian 13 development host:

- fresh Python no-op median: approximately 16.9 ms;
- `import pysh.cli` median: approximately 154.5 ms;
- full safe empty-command medians: approximately 155–164 ms;
- an exploratory 15-sample run observed a 164.374 ms median and a
  164.298–266.362 ms range.

The nominal budget is therefore 175 ms. This is an explicit target revision,
not a larger CI margin. It leaves limited headroom over the repeatable median
while still rejecting material import/runtime regressions. The existing 2.0 s
import test is not this benchmark; it remains a conservative eager-import
hygiene alarm.

### Base prompt rendering

`prompt_render` constructs `PyShell` outside the timed samples using the
no-user-config startup policy. Each sample computes both the default two-line
information block and command prompt. It keeps base identity, current-directory,
Python-version, status, and formatting work, while explicitly disabling Git,
Kubernetes, cloud/SSH, virtualenv, external tool-version, and plugin providers.
Color capability is fixed off and the working directory is a temporary fixture.

This isolates deterministic prompt computation from context collection and
external subprocess startup. Optional tool-version providers remain bounded and
session-cached in normal runtime, but they are not part of this base benchmark.

### Git context

`git_context` creates a temporary repository metadata fixture with a fixed
`HEAD`, then measures `PyShell._read_git_prompt_info`. The timer includes path
resolution, bounded parent lookup, `HEAD` parsing, and conservative dirty-state
metadata checks. It never invokes `git`, never touches the PySH checkout, and
does not scan the worktree.

### Completion

`completion_core` exercises the canonical `CompletionEngine.complete` path at
command position with a normal prefix, 128 controlled builtins, 128 aliases,
and 256 executable candidates in a temporary `PATH` directory. Warmup populates
the bounded PATH cache; measured samples cover parsing, in-memory prefix
matching, candidate construction, deduplication, and ranking.

Plugin/network providers are excluded. Completion remains TAB-triggered;
ordinary printable-key handling does not call it. Filesystem candidate
collection is deterministic and confined to the temporary fixture.

### Printable-key render preparation

`keystroke_render` passes one ordinary printable event through
`RawLineReader._handle_event`, including `LineBuffer` mutation and history
autosuggestion, then performs the real syntax-highlighting, display-width,
row/cursor, and redraw-string computation. Output is captured in memory, so the
timer excludes human latency, terminal scheduling, and kernel TTY write time.

The measured Debian median was approximately 0.036–0.042 ms. A 2 ms nominal
budget was selected as a conservative bound that still catches new synchronous
providers or materially heavier redraw computation.

## Sampling and variance policy

- No gate uses a single timing sample.
- In-process scenarios run explicit untimed warmups.
- Cold-start warmups are also fresh processes and are excluded from results.
- The measured sample counts are odd and at least nine for process startup and
  31 for microbenchmarks.
- Median is the sole gating aggregate. Raw samples are retained in JSON.
- One isolated outlier does not fail a stable median; a sustained median beyond
  the effective threshold does.
- Garbage collection is disabled only around measured in-process iterations to
  reduce unrelated collection jitter, then restored.
- The 20% CI margin is profile data, not an excuse to raise nominal budgets.

Local workstation results are development evidence only. Controlled CI history
is required before treating a result as a platform baseline.

## Import and hot-path hygiene

`tests/test_import_time_budget.py` retains its independent 2.0 s import guard.
Focused Issue #47 tests additionally verify in fresh processes that bare
`import pysh` and `import pysh.api` do not load Pygments, readline/curses,
editor, core, configuration, diagnostics, Python execution, or isolated-plugin
runtime modules.

Current hot-path findings:

- Pygments is imported only by the Python command-mode rendering module, not by
  bare package/API imports or the ordinary shell-line highlighter.
- Git prompt collection uses bounded filesystem metadata and no Git subprocess.
- Git is absent from non-prompt startup and ordinary printable-key processing.
- Completion and plugin completion providers are called by TAB completion, not
  by ordinary printable-key handling.
- User configuration, plugin discovery, and startup hooks are disabled in the
  cold-start scenario.
- Optional tool-version prompt providers use bounded subprocess timeouts and
  session caches; the pure prompt benchmark excludes them explicitly.

No runtime optimization was necessary for the four ratified microbenchmarks.
The cold-start revision avoids a broad pre-1.0 lazy-import rewrite solely to
recover a small, host-specific difference from 150 ms.

## Running locally

Run the complete contract:

```bash
uv run python scripts/benchmark_performance.py \
  --output /tmp/pysh-performance.json
```

Run one fixed benchmark:

```bash
uv run python scripts/benchmark_performance.py \
  --benchmark completion_core \
  --output /tmp/pysh-completion-performance.json
```

The process exits `0` when all selected release-blocking measurements are at or
below their effective thresholds, `1` for a measured regression, and `2` for
policy, scenario, or output errors. Benchmark configuration cannot provide an
arbitrary command; all scenarios are fixed in the reviewed harness.

## Structured evidence and CI

JSON records the schema version, UTC generation time, selected profile,
non-sensitive runner context, Python version/implementation, OS/release,
machine architecture, logical CPU count, CI Git SHA when valid, raw samples,
aggregate, nominal budget, margin, effective threshold, and PASS/FAIL status.
It never records environment contents, hostnames, usernames, home paths,
tokens, or benchmark fixture paths.

Pull-request CI has two independent gating jobs:

- Linux writes `artifacts/performance/linux-python3-13.json` and uploads the
  `performance-linux-python3-13` artifact.
- A real `vmactions/freebsd-vm@v1` FreeBSD 14.4 VM writes
  `artifacts/performance/freebsd-14.4-python3-13.json` and uploads the
  `performance-freebsd-14.4-python3-13` artifact.

Artifact upload uses `always()` so a budget failure remains diagnosable. The
benchmark step's non-zero status still fails the job; no performance job uses
`continue-on-error`. Both jobs have finite timeouts and explicit Python 3.13.

## Budget change policy

Raising a release-blocking budget is not a normal regression fix. It requires:

1. repeatable raw measurement evidence and relevant runner context;
2. bottleneck analysis and an explanation of attempted safe optimization;
3. explicit architecture/performance review;
4. synchronized policy, documentation, harness-test, and CI evidence updates;
5. changelog/release-contract consideration when a public performance claim is
   affected.

Investigation and safe optimization come first. Infrastructure changes belong
in a reviewed profile/margin change; product regressions belong in the
implementation, not behind an arbitrarily increased threshold.
