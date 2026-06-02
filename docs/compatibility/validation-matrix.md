<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/validation-matrix.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Validation Matrix

This document defines how PySH compatibility claims are validated. A claim is
only valid when it has evidence in this matrix. Claims without current evidence
are gaps that must be resolved before the claim can be published.

---

## Validation methods

| Method | Description | When required |
| ------ | ----------- | ------------- |
| **Unit test** | `pytest` test covering a specific construct or behavior | All native features |
| **Parser golden test** | Assertion on parsed AST/token output for specific input | All parser features |
| **PTY test** | Terminal I/O test over a pseudo-terminal | Terminal/editor behavior, signal handling |
| **Migration fixture test** | Import test with a real zsh/bash/sh fixture file | Transition-layer behavior |
| **Script fixture test** | Execution test with a real script file | Script mode, `run_script` |
| **Shell comparison test** | PySH output compared to real zsh/bash/sh output | Future — compatibility hardening |
| **CI gate** | Test runs in GitHub Actions | All tests |
| **Manual acceptance test** | Human runs the feature in a real terminal | Visual/interactive features |
| **Negative test** | Test that an unsupported construct fails deterministically | All unsupported constructs |

---

## Validation by claim

### Native runtime claims

| Claim | Required evidence | Current evidence | Gap | Owner issue |
| ----- | ----------------- | ---------------- | --- | ----------- |
| Sequential execution (`;`) works correctly | Unit test, parser golden | `tests/test_parser.py` | None | — |
| Conditional AND (`&&`) works correctly | Unit test, parser golden | `tests/test_parser.py` | None | — |
| Conditional OR (`\|\|`) works correctly | Unit test, parser golden | `tests/test_parser.py` | None | — |
| Pipelines connect correctly without deadlock | Unit test | `tests/test_shell.py` | None | — |
| Redirection (`<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>`) works | Unit test | `tests/test_redirection.py` | None | — |
| Command substitution `$(...)` and backtick works | Unit test | `tests/test_substitution.py` | None | — |
| Single/double quoting semantics are correct | Parser golden, unit test | `tests/test_parser.py` | None | — |
| Backslash escapes are correct | Parser golden | `tests/test_parser.py` | None | — |
| `$VAR` and `${VAR}` expansion works | Parser golden | `tests/test_parser.py` | None | — |
| Temporary env assignment works | Unit test | `tests/test_env_assignment.py` | None | — |
| Canonical exit codes (0/1/2/126/127/130) are defined and enforced | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| `$?` expands to last command exit status | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| External command exit code propagated exactly | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| Command-not-found → 127 | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| Cannot-execute → 126 | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| Builtin misuse → 2 | Unit test | `tests/test_error_exit_code_contract.py` | None | #5 |
| SIGINT → 130 | Unit test (`signal_exit_code`) | `tests/test_error_exit_code_contract.py` | Process-level flaky test deferred | #6 |
| Comments (`#`) work correctly | Unit test | `tests/test_comments.py` | None | — |
| Aliases are expanded correctly | Unit test | `tests/test_shell.py` | None | — |
| `unalias` works | Unit test | `tests/test_unalias.py` | None | — |
| `export` works | Unit test | `tests/test_shell_export.py` | None | — |
| `cd`, `pwd` work | Unit test | `tests/test_shell.py` | None | — |
| `pushd`/`popd`/`dirs` work | Unit test | `tests/test_dirstack.py` | None | — |
| `command` builtin (-v, -V, exec) works | Unit test | `tests/test_command_builtin.py` | None | — |
| `source`/`.` execute rc files | Unit test | `tests/test_rc.py` | None | — |
| `plan` advisory classifier works | Unit test | `tests/test_command_plan.py` | None | — |
| `secure` PTY runner works | Unit test, PTY test | `tests/test_secure_builtin.py`, `tests/test_secure_runner.py` | None | — |
| `svc` service control works | Unit test | `tests/test_service.py` | None | — |
| Multiline paste handling works | PTY test | `tests/test_multiline_paste.py` | None | — |
| History persists across sessions | Unit test | `tests/test_history.py` | None | — |
| Tab completion (alias/builtin/filesystem) | Unit test | `tests/test_completion.py` | Programmatic completion | #12 |
| Python `py` one-line execution | Unit test | `tests/test_python_runtime.py` | None | — |
| Python `py { ... }` blocks | Unit test | `tests/test_python_runtime.py` | None | — |
| `#py` interactive Python mode | Unit test | `tests/test_python_mode.py` | None | — |
| `~/.pyshrc` loading | Unit test | `tests/test_rc.py` | None | — |
| Plugin loading (`~/.pyshrc.d/`) | Unit test | `tests/test_plugins.py` | None | — |
| `~/.pyshrc.py` Python config | Unit test | `tests/test_pyshrc_py.py` | None | — |
| Mini rc-interpreter (if/for/while) | Unit test | `tests/test_rc_interpreter.py` | None | — |
| Highlighting works in editor | Unit test | `tests/test_lineedit_highlight.py` | PTY validation | Manual |
| Autosuggestion works | Unit test | `tests/test_lineedit_autosuggest.py` | PTY validation | Manual |
| Raw-mode editor key handling | Unit test, PTY | `tests/test_lineedit_reader_pty.py` | None | — |

### Transition-layer claims

| Claim | Required evidence | Current evidence | Gap | Owner issue |
| ----- | ----------------- | ---------------- | --- | ----------- |
| `source_zsh` imports aliases, skips unsupported | Migration fixture test | `tests/test_profile_importer.py` | None | — |
| `source_zsh_profile` imports aliases/exports/vars | Migration fixture test | `tests/test_profile_importer.py` | None | — |
| `source_sh_aliases` imports bash/sh entries | Migration fixture test | `tests/test_profile_importer.py` | None | — |
| Unsupported zsh constructs are skipped and counted | Unit test | `tests/test_profile_importer.py` | None | — |
| `compat_check` classifies constructs correctly | Unit test | `tests/test_profile_importer.py` | None | — |
| Static import never executes code | Unit test (no subprocess calls in importer) | `tests/test_profile_importer.py` | None | — |

### Delegated behavior claims

| Claim | Required evidence | Current evidence | Gap | Owner issue |
| ----- | ----------------- | ---------------- | --- | ----------- |
| `zsh COMMAND` delegates to `zsh -lc` | Unit test with real zsh | `tests/test_zsh_bridge.py` | None | — |
| `zsh COMMAND` returns 127 when zsh is absent | Unit test | `tests/test_zsh_bridge.py` | None | — |
| `run_script` delegates bash/zsh/sh shebangs | Script fixture test | `tests/test_script_runner.py` | Full script mode contract | #14 |
| `zsh_fallback on` enables delegation | Unit test | `tests/test_zsh_transition.py` | None | — |
| `zsh_fallback off` disables delegation | Unit test | `tests/test_zsh_transition.py` | None | — |
| Fallback is off by default | Unit test | `tests/test_zsh_transition.py` | None | — |

### Negative / unsupported-construct claims

| Claim | Required evidence | Current evidence | Gap | Owner issue |
| ----- | ----------------- | ---------------- | --- | ----------- |
| PySH is not a `/bin/sh` replacement | Documentation, no symlink test | `docs/compatibility/posix-sh-scope.md` | CI check for symlink absence | #17 |
| PySH is not zsh-compatible | Documentation, no zsh grammar test | `docs/compatibility/zsh-scope.md` | Shell comparison tests | #16 |
| Glob patterns pass literally | Unit test confirming no expansion | `docs/compatibility/feature-matrix.md` | Explicit negative unit test | #9 |
| Heredocs produce error/not-silently-broken | Negative unit test | Gap | Negative test needed | #10 |
| Job control is absent (no `&` background) | Negative unit test | Gap | Negative test needed | #11 |
| Shell functions are absent | Negative unit test | Gap | Negative test needed | — |

---

## CI gate coverage

| Gate | Current status | Gap |
| ---- | -------------- | --- |
| `uv run ruff check src tests` | Active in CI | None |
| `uv run pytest -q` (full suite) | Active in CI | None |
| Import-boundary test | Active (Issue #3) | None |
| Public API snapshot | Active (Issue #3) | None |
| Cold-start budget | Active (Issue #3) | None |
| Compatibility docs existence check | Active (Issue #4) | None |
| Feature matrix broad-claim audit | Active (Issue #4) | None |
| Shell comparison tests | Not yet | Issue #16 |
| Negative construct tests (glob, heredoc, job) | Partial | Issues #9, #10, #11 |
| FreeBSD validation | Not yet | Issue #18 |

---

## Gap resolution ownership

| Gap | Owner issue | Priority |
| --- | ----------- | -------- |
| Negative unit tests for unsupported constructs | #9, #10, #11 | High |
| Shell comparison tests (PySH vs real zsh/bash) | #16 | Medium |
| Script mode full contract validation | #14 | High |
| POSIX sh script fixture tests | #17 | Medium |
| FreeBSD terminal and PTY validation | #18 | Low (deferred) |
| Programmable completion validation | #12 | Medium |

---

## Manual acceptance tests

Some behaviors require human verification in a real terminal. These are
acceptance gates, not automated tests.

| Feature | Test procedure | Last verified |
| ------- | -------------- | ------------- |
| Bracketed paste replay | Paste multi-line content in interactive shell; verify each line executes correctly | Per release |
| Autosuggestion rendering | Type partial command; verify suggestion appears in correct color; press → to accept | Per release |
| Syntax highlighting | Type valid and invalid syntax; verify colors change correctly | Per release |
| Cursor color (OSC 12) | Configure cursor color in `~/.pyshrc.py`; verify terminal cursor changes | Per release |
| `secure sudo -v` PTY ring | Run `secure sudo -v` and type password; verify ring indicator appears without revealing length | Per release |
| `zsh_fallback on` delegation | Enable fallback; type a zsh-specific construct; verify it runs in zsh | Per release |
| `mc` integration | Launch `mc`; verify PySH resumes correctly on exit | Per release |
