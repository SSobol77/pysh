<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/development/fuzzing.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski
-->

# Parser/Tokenizer Fuzzing and Property-Based Robustness

Issue #49 gives the quote-aware parser, the tokenizer helpers, and the
pipeline file-descriptor handover mechanical robustness evidence. This page
documents the harness, the evidence model per platform, and the maintainer
workflow for findings.

Status: the portable evidence and the scheduled workflow are implemented and
wired into CI. PR #73 has passed the native Debian 13 and native FreeBSD 14.4
Tier-1 platform-reference jobs, which run the portable evidence. FreeBSD
coverage is portable deterministic evidence only; Atheris coverage-guided
fuzzing remains Linux x86_64 only.

## Authority

Issue #48 (`docs/spec/pysh-language.md` and
`tests/conformance/pysh-language-v1.json`) is the only normative language
oracle. Fuzzing asserts **intrinsic robustness** only: no crash, no unhandled
exception, no hang, deterministic results, no escape from quotes, no descriptor
leak. It never defines semantics. A semantic divergence found by fuzzing becomes
a case in the #48 corpus, not a second oracle here.

## Two evidence classes

| Class | Engine | Platforms | Where it runs |
| --- | --- | --- | --- |
| Portable deterministic evidence | Python standard library only | Debian 13 and FreeBSD 14.4 (Tier 1), any CPython `>=3.13` host | every PR, via `scripts/check_fuzz_evidence.sh` |
| Coverage-guided evidence | Atheris (libFuzzer) | **Linux x86_64 only** | scheduled/manual `fuzz-nightly.yml` |

FreeBSD has no Atheris distribution usable by this repository. FreeBSD
therefore runs the portable class in full and makes **no coverage-guided
claim**. Atheris availability is not a platform-support criterion; it never
downgrades a Tier-1 platform.

Atheris is a development dependency (`[dependency-groups] fuzz` in
`pyproject.toml`, guarded to Linux x86_64). It is not a runtime dependency and
nothing under `src/` imports it. Hypothesis is not used.

## Architecture

```text
tests/fuzz_support/targets.py     registry of pure targets + registered rejections
tests/fuzz_support/properties.py  totality, determinism, quote/redirection properties
tests/fuzz_support/engines.py     deterministic stdlib generator (seed, iteration) -> case
tests/fuzz_support/corpus.py      #48 corpus -> seeds/mutations (no second corpus)
tests/fuzz_support/driver.py      engine-independent driver: bytes->str, seeds, regression records
tests/fuzz_support/repro.py       canonical failure report (hex input, sha256, replay command)
tests/fuzz_support/fdprobe.py     portable os.fstat descriptor probe
tests/fuzz_support/execution.py   deterministic fault injection and child accounting
scripts/fuzz_atheris.py           CLI: replay, seed materialization, Atheris engine adapter
tests/fuzz/regressions/           permanent regression records (see its README)
```

### Target registry

Each target names one production callable and the exact exception classes (and
message patterns) it may raise. Anything not registered is a failure. List the
current targets:

```sh
uv run python scripts/fuzz_atheris.py --list-targets
```

### Input domain and bytes → str mapping

Parsers receive `str`, never bytes. Engine bytes are mapped with one canonical,
lossless, injective function: UTF-8 with `surrogateescape`. Every byte value,
including invalid UTF-8, survives and can be recovered. The deterministic
generator produces `str` directly from `random.Random(f"{version}:{seed}:{iteration}")`,
which is stable across platforms, so any case replays in O(1) from
`(seed, iteration)`. Generated words use a `zq` prefix and never contain `/`,
so `~word`, `$word` and glob patterns cannot name a real account, variable or
host path.

### Expected rejection vs defect

* **expected rejection**: a registered exception (class and message pattern) for
  that target; a normal outcome.
* **parser defect**: any other exception, a property violation, a
  nondeterministic result, or a hang.
* **harness defect**: `HarnessError`, or an engine finding the portable replay
  cannot reproduce. Never counted as a pass, never silenced.

Findings are never hidden by filtering the input domain.

### Safe/no-rc behavior and hermetic containment

Targets run with an empty temporary cwd, a cleared environment with a pinned
`HOME`, a fake command-substitution runner, and subprocess tripwires that raise
`HarnessError` if a real process is ever reached. Tokenizer glob expansion is
confined to the temporary cwd. No user rc/config is read and no fuzz input is
ever executed or handed to a shell. Shell-execution robustness cases use a
`NO_RC_STARTUP_POLICY` shell and only structured, known-safe command cases.

### Portable descriptor probe

Descriptor evidence uses a bounded `os.fstat` scan limited by
`min(soft RLIMIT_NOFILE, 4096)`. It does not read `/proc/self/fd` or `/dev/fd`
(on FreeBSD `/dev/fd` lists only 0–2 unless `fdescfs` is mounted, so such a
probe can pass vacuously). `EBADF` means closed; any other error is a probe
failure and is never converted into "no leak". Failures are injected
deterministically into `os.fork/pipe/dup/dup2/open`; real descriptors are
exhausted only in one bounded child with a lowered *soft* limit.

## Normal PR evidence

```sh
PYSH_PYTEST="uv run python -m pytest" sh scripts/check_fuzz_evidence.sh
```

The script is the single repository-owned entry point and owns the file list:

* `tests/test_parser_properties.py`: deterministic property harness
* `tests/test_fuzz_corpus.py`: #48-corpus seed/mutation adapter
* `tests/test_fuzz_driver.py`: driver, byte mapping, engine-independent replay
* `tests/test_fuzz_regressions.py`: permanent regression replay
* `tests/test_fd_robustness.py`: portable fd/pipeline/redirection robustness
* `tests/test_fuzz_contract.py`: CI/documentation contract for this evidence

It needs no Atheris, network, `/proc`, `/dev/fd` or user configuration, and is
finite (a few seconds locally). `tests/test_fuzz_atheris_smoke.py` is
engine-specific, skips cleanly without Atheris, and is deliberately **not** in
this script.

CI wiring: the `platform-debian` and `platform-freebsd` jobs in
`.github/workflows/ci.yml` each run the script once. On FreeBSD it runs in the
normal (privileged VM) context: none of its tests depend on unprivileged
hard-limit semantics (they only lower a child's *soft* `RLIMIT_NOFILE`), so
only the Issue #53 resource-governor evidence uses the `pyshci` account. The
Linux `test` job also runs these files as part of the full suite.

## Scheduled coverage-guided fuzzing

`.github/workflows/fuzz-nightly.yml` runs on `schedule` and `workflow_dispatch`
only (never on `pull_request`/`push`), Linux x86_64, CPython 3.13,
`permissions: contents: read`. It runs one matrix job per target, each with a
hard wall-clock budget:

| Setting | Value |
| --- | --- |
| Targets | `grammar.split_chain`, `grammar.split_pipeline`, `redirection.parse_redirections`, `path_expansion.tokenize_and_glob_expand`, `lexer.scan_quote_state`, `block_syntax.split_unquoted_pipe_stages`, `heredoc.parse_heredoc_specs`, `heredoc.collect_heredoc_bodies`, `multiline.split_paste_commands`, `expansion.expand_variables` |
| Budget per target | 300 s by default; `workflow_dispatch` input `seconds`, validated to 30–1800 |
| Engine bound | `--max-total-time` plus a 60 s grace, after which the engine process group is killed; job `timeout-minutes: 40` |
| Per-input limits | 256 bytes, 5 s hang timeout, 1024 MB RSS |

The seed corpus is materialized by the engine at run time from the #48 corpus
plus `tests/fuzz/regressions/` into a private temporary directory that is
removed afterwards. No corpus is checked in; the seed count is discovered, not
hard-coded.

Reproduce a nightly run locally (Linux x86_64):

```sh
uv run --group fuzz python scripts/fuzz_atheris.py --target grammar.split_chain --max-total-time 30
```

Exit codes: `0` clean, `1` reproduced finding, `2` usage/schema error, `3`
engine unavailable, `4` engine exceeded its hard bound, `5` finding not
reproduced by the portable replay (harness/engine suspect).

### Failure artifacts

On any failure the workflow uploads `fuzz-finding-<target>` containing the
libFuzzer artifact (`crash-*`, `timeout-*`, `oom-*`), `report.txt` (the engine's
output and the sanitized reproduction report: target, property, input hex,
SHA-256, exception, traceback fingerprint, Python/platform), and
`context.txt` (target, budget, commit, uname, Python version). Retention is 14
days. The workflow never commits, pushes, opens issues or pull requests, and
dumps neither the environment nor secrets.

## Replay on any platform

```sh
# a permanent regression record
uv run python scripts/fuzz_atheris.py --replay tests/fuzz/regressions/REPLACE_WITH_SHA256.json
# an engine artifact downloaded from CI
uv run python scripts/fuzz_atheris.py --target grammar.split_chain --input-file crash-REPLACE_WITH_HASH
# one input from a report
uv run python scripts/fuzz_atheris.py --target grammar.split_chain --encoding bytes-hex --input-hex REPLACE_WITH_HEX
```

Replace the `REPLACE_WITH_SHA256`, `REPLACE_WITH_HASH` and `REPLACE_WITH_HEX`
tokens with the real file name, artifact name or hex input before running the
command; they are not valid values as written.

## Regression records

One JSON file per **real** reproducer in `tests/fuzz/regressions/`, named by the
canonical SHA-256 of `target + NUL + input`, in a closed schema documented in
that directory's `README.md`. `tests/test_fuzz_regressions.py` replays every
record on every normal pytest run on every platform. An empty directory means
no such defect has been recorded; nothing is added speculatively.

## Finding and minimization workflow

1. Scheduled fuzzing fails and uploads a finding artifact.
2. A maintainer downloads it and replays it with the portable tooling above
   (`--input-file`). A finding that does not reproduce is a harness/engine
   suspect, not a pass.
3. The maintainer minimizes the input (for example with `libFuzzer`
   `-minimize_crash=1` or by hand) and reviews the minimized case.
4. Classify: expected rejection (register it in `targets.py` with a precise
   pattern), production defect, harness defect, or contract ambiguity (resolve
   in the #48 spec/corpus first).
5. For a production defect: write the failing regression record first, fix
   production code, and keep the record. A semantic divergence becomes a #48
   corpus case with a `contract_ref` instead.
6. Normal CI replays the record on every platform forever.

Automation never converts a crash artifact into committed source; a maintainer
reviews and commits every record.

## Known limitations

* Coverage-guided fuzzing is Linux x86_64 only; FreeBSD gets deterministic
  generation, corpus and regression replay, and fd/pipeline robustness only.
* Targets are pure text-processing functions. Shell execution paths are covered
  by structured cases with injected faults, not arbitrary fuzz bytes.
* The interactive editor and PTY paths are not fuzzed here.
* The descriptor probe cannot see descriptors numbered at or above its scan cap
  (4096) or exhaust real descriptors outside the one bounded child.
* FreeBSD 14.4 runs the portable deterministic evidence natively (passed in
  PR #73) but has no coverage-guided Atheris evidence; the two are not
  equivalent.
