<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/compatibility/feature-matrix.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Feature Matrix

This matrix documents the current implementation status of every significant
shell feature area in PySH 0.6.x. Category definitions are in
[shell-compatibility-contract.md](shell-compatibility-contract.md).

**Columns:**

| Column | Meaning |
| ------ | ------- |
| Area | Feature domain |
| Feature | Specific construct or capability |
| Status | Supported / Partial / Unsupported / Delegated / Planned |
| Category | Native / Transition / Delegated / Planned / Unsupported / Forbidden by default |
| Evidence | Test file(s) or documentation reference |
| Owner issue | GitHub issue responsible for implementation or cleanup |

---

## Command execution

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Command execution | External command via PATH | Supported | Native | `tests/test_shell.py` | — |
| Command execution | Builtin command dispatch | Supported | Native | `tests/test_shell.py` | — |
| Command execution | Alias expansion (first word) | Supported | Native | `tests/test_shell.py` | — |
| Command execution | Temporary env assignment (`NAME=value cmd`) | Supported | Native | `tests/test_env_assignment.py` | — |
| Command execution | Sequential chain (`;`) | Supported | Native | `tests/test_parser.py` | — |
| Command execution | Conditional AND (`&&`) | Supported | Native | `tests/test_parser.py` | — |
| Command execution | Conditional OR (`\|\|`) | Supported | Native | `tests/test_parser.py` | — |

## Builtins

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Builtins | `cd`, `pwd` | Supported | Native | `tests/test_shell.py` | — |
| Builtins | `alias`, `unalias` | Supported | Native | `tests/test_shell.py`, `tests/test_unalias.py` | — |
| Builtins | `export` | Supported | Native | `tests/test_shell_export.py` | — |
| Builtins | `source` / `.` | Supported | Native | `tests/test_rc.py` | — |
| Builtins | `command` (`-v`, `-V`, exec) | Supported | Native | `tests/test_command_builtin.py` | — |
| Builtins | `secure` (PTY runner) | Supported | Native | `tests/test_secure_builtin.py` | — |
| Builtins | `pushd`, `popd`, `dirs` | Supported | Native | `tests/test_dirstack.py` | — |
| Builtins | `svc` (service control) | Supported | Native | `tests/test_service.py` | — |
| Builtins | `plan` (advisory classifier) | Supported | Native | `tests/test_command_plan.py` | — |
| Builtins | `py` (Python execution) | Supported | Native | `tests/test_python_runtime.py` | — |
| Builtins | `sys_info`, `env_audit`, `path_audit` | Supported | Native | `tests/test_system_profile.py`, `tests/test_system_info.py` | — |
| Builtins | `which_all`, `apt_check`, `apt_search` | Supported | Native | `tests/test_system_profile.py` | — |
| Builtins | `mc` (MC wrapper) | Supported | Native | `tests/test_mc_compat.py` | — |
| Builtins | `jobs`, `fg`, `bg` | Supported | Native | `tests/test_job_control.py` | #11 |
| Builtins | `exit`, `quit` | Supported | Native | `tests/test_shell.py` | — |
| Builtins | `source_zsh` | Supported | Transition | `tests/test_profile_importer.py` | — |
| Builtins | `source_zsh_profile` | Supported | Transition | `tests/test_profile_importer.py` | — |
| Builtins | `source_sh_aliases` | Supported | Transition | `tests/test_profile_importer.py` | — |
| Builtins | `compat_check` | Supported | Transition | `tests/test_profile_importer.py` | — |
| Builtins | `run_script` | Partial | Delegated | `tests/test_script_runner.py` | #14 |
| Builtins | `zsh` (explicit delegation) | Supported | Delegated | `tests/test_zsh_bridge.py` | — |
| Builtins | `zsh_fallback` | Supported | Delegated | `tests/test_zsh_transition.py` | — |
| Diagnostics | `--debug`, `--trace` stderr trace | Supported | Native | `tests/test_observability_diagnostics.py` | #13 |
| Diagnostics | Diagnostic redaction policy | Supported | Native | `tests/test_observability_diagnostics.py`, `tests/test_security_trust_model.py` | #13 |

## Aliases

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Aliases | Define: `alias NAME=value` | Supported | Native | `tests/test_shell.py` | — |
| Aliases | Display: `alias`, `alias NAME` | Supported | Native | `tests/test_shell.py` | — |
| Aliases | Expand on first word of pipeline stage | Supported | Native | `tests/test_shell.py` | — |
| Aliases | Remove: `unalias NAME` | Supported | Native | `tests/test_unalias.py` | — |
| Aliases | Recursive/chained alias expansion | Unsupported | Unsupported | — | — |

## Variables

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Variables | Local assignment: `NAME=value` | Supported | Native | `tests/test_env_assignment.py` | — |
| Variables | Simple expansion: `$NAME` | Supported | Native | `tests/test_parser.py` | — |
| Variables | Braced expansion: `${NAME}` | Supported | Native | `tests/test_parser.py` | — |
| Variables | `$?` last exit status (special parameter) | Supported | Native | `tests/test_error_exit_code_contract.py` | #5 |
| Variables | Default value: `${NAME:-default}` | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Variables | Length: `${#NAME}` | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Variables | Substring/pattern expansion | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Variables | Script positional params (`$0`, `$1`, `$#`, `$@`, `$*`) | Supported | Native | `tests/test_script_mode.py` | #14 |
| Variables | Other POSIX special params (`$$`, `$!`) | Unsupported | Unsupported | — | — |

## Environment exports

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Environment | `export NAME=value` | Supported | Native | `tests/test_shell_export.py` | — |
| Environment | `export NAME` (from local var) | Supported | Native | `tests/test_shell_export.py` | — |
| Environment | Display: `export` (no args) | Supported | Native | `tests/test_shell_export.py` | — |
| Environment | Temporary assignment: `NAME=val cmd` | Supported | Native | `tests/test_env_assignment.py` | — |

## Quoting

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Quoting | Single quotes: literal `'...'` | Supported | Native | `tests/test_parser.py` | — |
| Quoting | Double quotes: partial expansion `"..."` | Supported | Native | `tests/test_parser.py` | — |
| Quoting | ANSI C quoting: `$'...'` | Unsupported | Unsupported | — | — |
| Quoting | Locale quoting: `$"..."` | Unsupported | Unsupported | — | — |

## Escapes

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Escapes | Backslash outside quotes | Supported | Native | `tests/test_parser.py` | — |
| Escapes | Backslash inside double quotes (`\"`, `\\`, `\$`, `` \` ``) | Supported | Native | `tests/test_parser.py` | — |
| Escapes | Line continuation (`\<newline>`) | Supported | Native | `tests/test_multiline_grammar.py` | #8 |

## Operators

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Operators | `;` (sequence) | Supported | Native | `tests/test_parser.py` | — |
| Operators | `&&` (conditional AND) | Supported | Native | `tests/test_parser.py` | — |
| Operators | `\|\|` (conditional OR) | Supported | Native | `tests/test_parser.py` | — |
| Operators | `\|` (pipe) | Supported | Native | `tests/test_parser.py` | — |
| Operators | Trailing pipe parse error | Supported | Native | `tests/test_parser_foundation.py` | #8 |
| Operators | `&` (background execution) | Supported | Native | `tests/test_job_control.py` | #11 |

## Pipelines

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Pipelines | Two-stage pipeline | Supported | Native | `tests/test_shell.py` | — |
| Pipelines | Multi-stage pipeline | Supported | Native | `tests/test_shell.py` | — |
| Pipelines | Correct fd handover (no deadlock) | Supported | Native | `tests/test_shell.py` | — |
| Pipelines | Pipeline exit status (last stage) | Supported | Native | `tests/test_shell.py` | — |
| Pipelines | `pipefail` semantics | Unsupported | Unsupported | — | — |

## Redirection

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Redirection | `< file` (stdin) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `> file` (stdout truncate) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `>> file` (stdout append) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `2> file` (stderr truncate) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `2>> file` (stderr append) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `&> file` (stdout+stderr truncate) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | `&>> file` (stdout+stderr append) | Supported | Native | `tests/test_redirection.py` | — |
| Redirection | Fd duplication: `2>&1` | Unsupported | Unsupported | — | — |
| Redirection | `/dev/null` shorthand | Supported | Native | — | — |

## Command substitution

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Command substitution | `$(command)` | Supported | Native | `tests/test_substitution.py` | — |
| Command substitution | `` `command` `` | Supported | Native | `tests/test_substitution.py` | — |
| Command substitution | Inside double quotes | Supported | Native | `tests/test_substitution.py` | — |
| Command substitution | Suppressed inside single quotes | Supported | Native | `tests/test_substitution.py` | — |
| Command substitution | 5-second timeout | Supported | Native | `tests/test_substitution.py` | — |
| Command substitution | Nested `$(...)` | Unsupported | Unsupported | — | — |

## Comments

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Comments | `#` after whitespace (unquoted) | Supported | Native | `tests/test_comments.py` | — |
| Comments | `#` mid-token is literal | Supported | Native | `tests/test_comments.py` | — |
| Comments | `#` inside quotes is literal | Supported | Native | `tests/test_comments.py` | — |

## Temporary environment assignment

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Temp env assignment | `NAME=value cmd` (external) | Supported | Native | `tests/test_env_assignment.py` | — |
| Temp env assignment | Multiple assignments before cmd | Supported | Native | `tests/test_env_assignment.py` | — |
| Temp env assignment | `NAME=value builtin` | Partial | Native | `tests/test_env_assignment.py` | #8 |

## Multiline paste

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Multiline paste | Bracketed paste mode | Supported | Native | `tests/test_multiline_paste.py` | — |
| Multiline paste | Compact paste replay queue | Supported | Native | `tests/test_multiline_paste.py` | — |

## Python runtime `py`

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Python runtime | `py <code>` one-line execution | Supported | Native | `tests/test_python_runtime.py` | — |
| Python runtime | Persistent namespace across invocations | Supported | Native | `tests/test_python_runtime.py` | — |
| Python runtime | Exception reporting (no shell death) | Supported | Native | `tests/test_python_runtime.py` | — |

## Python block `py { ... }`

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Python block | `py {` / `}` multiline block | Supported | Native | `tests/test_python_runtime.py` | — |
| Python block | Shared namespace with `py` | Supported | Native | `tests/test_python_runtime.py` | — |
| Python block | Nested blocks rejected deterministically | Supported | Native | `tests/test_python_runtime.py` | — |
| Python block | Unterminated block returns non-zero | Supported | Native | `tests/test_python_runtime.py` | — |

## Source / rc loading

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Source/rc | `~/.pyshrc` on interactive start | Supported | Native | `tests/test_rc.py` | — |
| Source/rc | `~/.pyshrc.d/*.pysh` plugins | Supported | Native | `tests/test_plugins.py` | — |
| Source/rc | `source FILE` / `. FILE` | Supported | Native | `tests/test_rc.py` | — |
| Source/rc | `~/.pyshrc.py` (Python config) | Supported | Native | `tests/test_pyshrc_py.py` | — |
| Source/rc | Mini rc-interpreter (`if`/`for`/`while`) | Supported | Native | `tests/test_rc_interpreter.py` | — |

## Directory stack

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Directory stack | `pushd DIRECTORY` | Supported | Native | `tests/test_dirstack.py` | — |
| Directory stack | `popd` | Supported | Native | `tests/test_dirstack.py` | — |
| Directory stack | `dirs` | Supported | Native | `tests/test_dirstack.py` | — |
| Directory stack | `pushd +N` (rotate by index) | Unsupported | Planned | — | — |

## Completion

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Completion | Alias completion at command position | Supported | Native | `tests/test_completion.py`, `tests/test_completion_engine.py` | #12 |
| Completion | Builtin completion at command position | Supported | Native | `tests/test_completion.py`, `tests/test_completion_engine.py` | #12 |
| Completion | External executable completion from PATH | Supported | Native | `tests/test_completion_engine.py` | #12 |
| Completion | Filesystem path completion | Supported | Native | `tests/test_completion_engine.py` | #12 |
| Completion | Directory-only completion after `cd`/`pushd` | Supported | Native | `tests/test_completion_engine.py` | #12 |
| Completion | Variable-name completion after `$` / `${` | Supported | Native | `tests/test_completion_engine.py` | #12 |
| Completion | Job-ID completion after `fg` / `bg` | Supported | Native | `tests/test_completion_engine.py` | #12 |
| Completion | Programmable bash/zsh/fish completion scripts | Unsupported | Unsupported | `docs/architecture/completion-engine-contract.md` | — |

## History

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| History | Persistent history (`~/.pysh_history`) | Supported | Native | `tests/test_history.py` | — |
| History | Ctrl+R incremental search | Supported | Native | `tests/test_multiline_paste.py`, `tests/test_history.py` | — |
| History | Deduplication of consecutive entries | Supported | Native | `tests/test_history.py` | — |
| History | `history` builtin / `fc` | Unsupported | Planned | — | — |

## Globbing

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Globbing | `*` path expansion | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | `?` single-char expansion | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | `[...]` character class | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | `**` recursive glob | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | Tilde expansion (`~`, `~/path`, `~user`) | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | No-match returns literal pattern | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | `*` does not match dotfiles by default | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | Quoted glob patterns remain literal | Supported | Native | `tests/test_path_expansion.py` | #9 |
| Globbing | Brace expansion (`{a,b}`) | Unsupported | Unsupported | — | — |
| Globbing | zsh extended glob | Unsupported | Unsupported | — | — |

## Heredocs

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Heredocs | `<< DELIM` heredoc syntax | Supported | Native | `tests/test_heredoc.py` | #10 |
| Heredocs | `<<- DELIM` (strip leading tabs) | Supported | Native | `tests/test_heredoc.py` | #10 |
| Heredocs | `<<< word` here-string | Supported | Native | `tests/test_heredoc.py` | #10 |
| Heredocs | Quoted delimiter disables body expansion | Supported | Native | `tests/test_heredoc.py` | #10 |
| Heredocs | No glob expansion in body or here-string content | Supported | Native | `tests/test_heredoc.py` | #10 |

## Functions

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Functions | Shell function definition (`function f() { ... }`) | Unsupported | Unsupported | — | — |
| Functions | POSIX function definition (`f() { ... }`) | Unsupported | Unsupported | — | — |
| Functions | Function export (`export -f`) | Unsupported | Unsupported | — | — |
| Functions | Local variables (`local NAME`) | Unsupported | Unsupported | — | — |

## Arithmetic expansion

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Arithmetic | `$((expr))` arithmetic substitution | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Arithmetic | `(( expr ))` arithmetic command | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Arithmetic | `let NAME=expr` | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Arithmetic | Note: Python blocks (`py { ... }`) cover arithmetic needs via Python | Supported | Native | `tests/test_python_runtime.py` | — |

## Parameter expansion

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Parameter expansion | `$NAME`, `${NAME}` | Supported | Native | `tests/test_parser.py` | — |
| Parameter expansion | `${NAME:-default}` (default value) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${NAME:=default}` (assign default) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${NAME:?error}` (error if unset) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${#NAME}` (string length) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${NAME#pattern}` (prefix strip) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${NAME%pattern}` (suffix strip) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |
| Parameter expansion | `${NAME/old/new}` (substitution) | Unsupported | Unsupported | `tests/test_expansion_foundation.py` | — |

## Arrays

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Arrays | Indexed array (`arr=(a b c)`) | Unsupported | Unsupported | — | — |
| Arrays | Associative array (`declare -A`) | Unsupported | Unsupported | — | — |
| Arrays | Array expansion (`"${arr[@]}"`) | Unsupported | Unsupported | — | — |
| Arrays | Note: Python lists via `py { ... }` cover array needs | Supported | Native | `tests/test_python_runtime.py` | — |

## Security and trust model

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Security | Foreign profile execution by default | Unsupported | Forbidden by default | `tests/test_security_trust_model.py` | #7 |
| Security | Static profile import (no execution) | Supported | Transition | `tests/test_security_trust_model.py` | #7 |
| Security | Explicit delegation (`zsh`, `run_script`, `zsh_fallback on`) | Supported | Delegated | `tests/test_security_trust_model.py` | #7 |
| Security | `zsh_fallback` off by default | Supported | Delegated | `tests/test_security_trust_model.py` | #7 |
| Security | Normal command does not use PTY bridge | Supported | Native | `tests/test_security_trust_model.py` | #7 |
| Security | `secure <cmd>` explicit PTY bridge opt-in | Supported | Native | `tests/test_secure_runner.py` | #7 |
| Security | `env_audit` redacts sensitive variable names | Supported | Native | `tests/test_security_trust_model.py` | #7 |
| Security | `apt_check` / `apt_search` use no sudo | Supported | Native | `tests/test_security_trust_model.py` | #7 |
| Security | `plan` does not execute target command | Supported | Native | `tests/test_security_trust_model.py` | #7 |
| Security | Python runtime sandboxing | Unsupported | Unsupported | `tests/test_security_trust_model.py` | #7 |
| Security | Privilege separation / capability confinement | Unsupported | Unsupported | `docs/architecture/security-trust-model.md` | #7 |

## Signal handling

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Signal handling | Ctrl+C cancels line editor input; `$?=130` | Supported | Native | `tests/test_signal_handling.py` | #6 |
| Signal handling | Ctrl+C interrupts foreground child; `$?=130` | Supported | Native | `tests/test_signal_handling.py` | #6 |
| Signal handling | Signal-killed child: `$? = 128 + signum` | Supported | Native | `tests/test_signal_handling.py` | #6 |
| Signal handling | `py` builtin `KeyboardInterrupt` → `$?=130` | Supported | Native | `tests/test_signal_handling.py` | #6 |
| Signal handling | Terminal state restored after Ctrl+C | Supported | Native | `tests/test_lineedit_reader_pty.py` | #6 |
| Signal handling | Bracketed paste disabled after Ctrl+C | Supported | Native | `src/pysh/editor/lineedit/reader.py` | #6 |
| Signal handling | SIGTSTP job suspend/resume | Supported | Native | `tests/test_job_control.py` | #11 |

## Traps

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Traps | `trap 'cmd' SIGNAL` | Unsupported | Unsupported | — | — |
| Traps | `trap 'cmd' EXIT` | Unsupported | Unsupported | — | — |
| Traps | `trap '' SIGNAL` (ignore signal) | Unsupported | Unsupported | — | — |

## Job control

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Job control | Background execution (`cmd &`) | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | `jobs` | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | `bg` | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | `fg` | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | TTY suspend key (SIGTSTP) / Ctrl+Z | Supported | Native | `tests/test_job_control.py`, `docs/architecture/job-control-contract.md` | #11 |
| Job control | Process-group isolation (foreground/background) | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | Background job reaping before prompt | Supported | Native | `tests/test_job_control.py` | #11 |
| Job control | `wait` builtin | Unsupported | Planned | — | — |
| Job control | `disown` | Unsupported | Unsupported | — | — |

## Process substitution

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Process substitution | `<(cmd)` input substitution | Unsupported | Unsupported | — | — |
| Process substitution | `>(cmd)` output substitution | Unsupported | Unsupported | — | — |

## Brace expansion

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Brace expansion | `{a,b,c}` word list | Unsupported | Unsupported | — | — |
| Brace expansion | `{1..5}` range | Unsupported | Unsupported | — | — |

## zsh profile import

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| zsh import | `source_zsh FILE` (alias-only) | Supported | Transition | `tests/test_profile_importer.py` | — |
| zsh import | `source_zsh_profile FILE` (alias/export/var) | Supported | Transition | `tests/test_profile_importer.py` | — |
| zsh import | Skips: `autoload`, `compinit`, `eval`, functions, arrays | Supported | Transition | `tests/test_profile_importer.py` | — |
| zsh import | Counts imported vs skipped | Supported | Transition | `tests/test_profile_importer.py` | — |
| zsh import | Full profile execution (`source ~/.zshrc`) | Unsupported | Forbidden by default | — | #7 |

## bash / sh alias import

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| bash/sh import | `source_sh_aliases FILE` | Supported | Transition | `tests/test_profile_importer.py` | — |
| bash/sh import | Supports aliases, exports, simple assignments | Supported | Transition | `tests/test_profile_importer.py` | — |
| bash/sh import | Skips bash-specific syntax | Supported | Transition | `tests/test_profile_importer.py` | — |
| bash/sh import | Full bash profile execution | Unsupported | Forbidden by default | — | #7 |

## Explicit zsh delegation

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| zsh delegation | `zsh COMMAND` | Supported | Delegated | `tests/test_zsh_bridge.py` | — |
| zsh delegation | Returns 127 when zsh is not installed | Supported | Delegated | `tests/test_zsh_bridge.py` | — |
| zsh delegation | Exit status forwarded | Supported | Delegated | `tests/test_zsh_bridge.py` | — |
| zsh delegation | `compat_check FILE` (static report) | Supported | Transition | `tests/test_profile_importer.py` | — |
| zsh delegation | `run_script FILE [args]` (shebang dispatch) | Supported | Delegated | `tests/test_script_runner.py` | #14 |

## Fallback mode

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Fallback | `zsh_fallback on` / `off` | Supported | Delegated | `tests/test_zsh_transition.py` | — |
| Fallback | `PYSH_ZSH_FALLBACK=1` env var | Supported | Delegated | `tests/test_zsh_transition.py` | — |
| Fallback | Off by default | Supported | Delegated | `tests/test_zsh_transition.py` | — |
| Fallback | Does not hide native command failures | Supported | Delegated | `tests/test_zsh_transition.py` | — |

## Script mode

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| Script mode | Run shebang scripts via `run_script` | Supported | Delegated | `tests/test_script_runner.py` | #14 |
| Script mode | Run native PySH scripts via `pysh script.pysh` | Supported | Native | `tests/test_script_mode.py` | #14 |
| Script mode | Run native PySH scripts via `python -m pysh script.pysh` | Supported | Native | `tests/test_script_mode.py` | #14 |
| Script mode | Run no-shebang scripts line-by-line | Supported | Native | `tests/test_script_runner.py`, `tests/test_script_mode.py` | #14 |
| Script mode | Shebang header ignored in native PySH mode | Supported | Native | `tests/test_script_mode.py` | #14 |
| Script mode | Error propagation in scripts | Supported | Native | `tests/test_script_mode.py` | #14 |
| Script mode | `set -e` / `set -x` / `set -u` POSIX strict modes | Unsupported | Unsupported | — | #14 |

## `/bin/sh` provider status

| Area | Feature | Status | Category | Evidence | Owner issue |
| ---- | ------- | ------ | -------- | -------- | ----------- |
| `/bin/sh` | PySH as `/bin/sh` symlink target | Unsupported | Unsupported | — | #17 |
| `/bin/sh` | System script compatibility | Unsupported | Unsupported | — | #17 |
| `/bin/sh` | POSIX sh grammar compliance | Unsupported | Unsupported | — | — |
| `/bin/sh` | System shell integration policy | Planned | Planned | — | #17 |
