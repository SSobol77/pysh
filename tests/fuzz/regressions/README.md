<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: tests/fuzz/regressions/README.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Permanent fuzz robustness regressions (Issue #49)

One JSON file per **real** robustness reproducer (a crash, hang, unexpected
exception, or property violation found by fuzzing a parser target). Nothing is
added speculatively: an empty directory means no such defect has been recorded.
`tests/test_fuzz_regressions.py` replays every record on every normal pytest
run and needs no fuzz engine.

Semantic divergences from `docs/spec/pysh-language.md` do **not** belong here;
they become cases in `tests/conformance/pysh-language-v1.json` (with a
`contract_ref`) so the language corpus stays the only semantic oracle.

## File name

`<sha256>.json` where `sha256` is the SHA-256 of
`target + NUL + input` and `input` is the canonical parser text encoded as
`surrogatepass` UTF-8. The name is enforced, so the same reproducer cannot be
stored twice, whichever encoding recorded it.

## Closed schema (version 1)

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `target` | full registry name, e.g. `grammar.split_chain` |
| `property` | `totality`, `determinism`, or `redirection_preserves_quoted_content` |
| `input_encoding` | `bytes-hex` (original fuzz bytes, mapped with `surrogateescape`) or `text-hex` (`str` as `surrogatepass` UTF-8) |
| `input` | lowercase hex, at most 4096 bytes |
| `contract_ref` | a `PYSH-LANG-*` anchor, or `unspecified` (spec section 11) |
| `engine` | `atheris`, `stdlib`, or `manual` |
| `seed_or_source` | how it was found (seed/iteration, artifact name, ...) |
| `fixed_in` | short commit/PR/issue reference of the fix; informational only, never compared with the current commit |

Replay one record on any platform:

```sh
uv run python scripts/fuzz_atheris.py --replay tests/fuzz/regressions/<sha256>.json
```
