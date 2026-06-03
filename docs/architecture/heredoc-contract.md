<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/heredoc-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Heredoc Contract

Issue #10 adds native stdin inline-data redirection for here-documents and
here-strings. It does not add job control, completion, observability commands,
full script mode, process substitution, shell functions, arithmetic expansion,
advanced parameter expansion, or broad POSIX/bash/zsh compatibility.

## Supported syntax

| Syntax | Meaning |
| ------ | ------- |
| `cmd << WORD` | Feed following body lines to `cmd` stdin until delimiter `WORD`. |
| `cmd <<- WORD` | Same as `<<`, but strip leading tab characters from body lines and delimiter comparison. |
| `cmd <<< WORD` | Feed one expanded word plus a trailing newline to `cmd` stdin. |

Multiple heredocs on one command are supported. Stdin redirections are applied
left to right; the last stdin redirection wins.

## Body collection

For `pysh -c`, native scripts using the PySH line engine, and interactive
input, the first physical line is parsed for pending heredoc operators. PySH
does not execute the command until all required body terminators are collected.

Collection is deterministic:

1. Parse the command line for unquoted `<<`, `<<-`, and `<<<`.
2. For each `<<<`, collect the word immediately.
3. For each `<<` or `<<-`, consume following lines until the delimiter line.
4. Do not include the delimiter line in stdin data.
5. Preserve body newlines.
6. Report a parse error with status 2 when a delimiter word or terminator line
   is missing.

Heredoc content is stdin data only. It is never executed as shell code.

## Delimiter quoting

Delimiter quotes are removed for delimiter comparison.

| Delimiter form | Body policy |
| -------------- | ----------- |
| `<< EOF` | Expand `$NAME`, `${NAME}`, `$?`, and supported command substitution in the body. |
| `<< 'EOF'` | Literal body; no variable or command substitution. |
| `<< "EOF"` | Literal body; no variable or command substitution. |

Glob/path expansion is never applied to heredoc body text.

## Tab stripping

`<<- WORD` strips leading tab characters from body lines before they are stored
and from candidate delimiter lines before comparison. Spaces are not stripped.

## Here-string policy

`<<< WORD` applies the existing one-word expansion policy:

- variable expansion for `$NAME`, `${NAME}`, and `$?`;
- supported command substitution;
- quote removal for grouping;
- no glob/path expansion;
- append exactly one trailing newline.

Thus `cat <<< "*.py"` receives literal `*.py\n`, even when matching files exist.

## Redirection precedence

All stdin redirections are scanned left to right. The last stdin redirect wins:

- `cat < file << EOF ... EOF` uses the heredoc.
- `cat << EOF < file ... EOF` uses `file`.
- `cat << A << B ...` uses body `B`.

Stdout and stderr redirection behavior is unchanged.

## Error mapping

| Condition | Exit status |
| --------- | ----------- |
| Missing delimiter word after `<<`, `<<-`, or `<<<` | 2 |
| Missing heredoc terminator line | 2 |
| Malformed quoted word in command tokenization | 2 |
| Command missing after successful heredoc parsing | 127 |
| I/O error while preparing stdin payload | 1 |
| Ctrl+C during interactive heredoc collection | 130 |

Normal heredoc parse errors must not produce Python tracebacks.

## Security and trust

The parser module `pysh.parsing.heredoc` is a shared leaf. It imports only
stdlib modules and other parser helpers. It does not import `pysh.core`, the
editor, prompt, Python layer, diagnostics, script runner, or services.

Temporary stdin payloads are anonymous temporary files created by the shell
runtime immediately before spawning a child process. Handles are closed by the
parent after use. PySH does not persist heredoc bodies, log them, or execute
them as commands.

## Validation matrix

| Behavior | Evidence |
| -------- | -------- |
| `<< WORD` detection and body preservation | `tests/test_heredoc.py` |
| quoted delimiter disables body expansion | `tests/test_heredoc.py` |
| unquoted delimiter expands variables | `tests/test_heredoc.py` |
| `<<-` strips tabs only | `tests/test_heredoc.py` |
| `<<< WORD` appends newline | `tests/test_heredoc.py` |
| `<<< "*.py"` does not glob-expand | `tests/test_heredoc.py` |
| mixed stdin redirection last-wins policy | `tests/test_heredoc.py` |
| missing terminator maps to status 2 | `tests/test_heredoc.py` |
| command-not-found after body collection maps to 127 | `tests/test_heredoc.py` |
| import-boundary safety | `tests/test_architecture_import_boundaries.py` |

## Issue relationships

- Issue #8 supplies quote-aware parser and multiline foundations.
- Issue #9 supplies path/glob expansion, which is intentionally not applied to
  heredoc or here-string content.
- Issue #11 remains responsible for job control.
- Issue #14 remains responsible for full script mode.
- Issue #16 remains responsible for shell-comparison hardening.
- Issue #17 remains responsible for system-shell integration policy.
