<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/parser-expansion-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Parser, Expansion and Multiline Contract

This document defines the Issue #8 parser foundation. It records the current
native grammar boundary, expansion order, multiline handling, parse-error
mapping, and ownership split for future parser work.

## Scope

Issue #8 establishes a structured parser package and deterministic diagnostics
for parser-owned unsupported constructs. It does not add job control,
programmable completion, full script mode, or broad shell compatibility.

Future feature ownership remains:

| Feature area | Owner issue |
| ------------ | ----------- |
| Native glob and path expansion | Issue #9 |
| Heredoc and here-string execution | Implemented in Issue #10 |
| Job control and process groups | Issue #11 |
| Script Mode v1 execution contract | Issue #14 |
| System-shell integration policy | Issue #17 |

## Module Responsibilities

| Module | Responsibility |
| ------ | -------------- |
| `pysh.parsing.ast` | Parser value objects: `ChainOp`, `ChainElement`. |
| `pysh.parsing.errors` | Parser-local `ParseError` and `UnsupportedSyntaxError`; no dependency on `pysh.core`. |
| `pysh.parsing.lexer` | Quote state, escape handling, comment stripping, unquoted-marker detection. |
| `pysh.parsing.grammar` | Chain splitting, pipeline splitting, env assignment parsing, parser-owned unsupported syntax checks. |
| `pysh.parsing.expansion` | Variable expansion, command substitution, unsupported parameter-expansion classification. |
| `pysh.parsing.multiline` | Quote continuation, backslash-newline joining, Python block coalescing, paste splitting. |
| `pysh.parsing.heredoc` | Here-document and here-string operator parsing, body collection, and expansion policy. |
| `pysh.parsing.redirection` | Redirection specification parsing and fd application. |
| `pysh.parsing.parser` | Compatibility facade that re-exports the stable parser helper surface. |

The parser package is a shared leaf. `pysh.core`, `pysh.editor.lineedit`,
`pysh.diagnostics`, and `pysh.script_runner` may consume parser grammar, AST,
expansion and multiline helpers. The dependency is one-way: `pysh.parsing` may
not import `pysh.core`, `pysh.editor`, `pysh.prompt`, `pysh.python_layer`,
`pysh.diagnostics`, or `pysh.script_runner`.

## Processing Pipeline

Native command processing follows this order:

1. Physical input is normalized by the caller.
2. `pysh.parsing.multiline` joins supported continuations into logical input:
   quote continuation, backslash-newline, and `py { ... }` block grouping.
3. `pysh.parsing.heredoc.collect_heredoc_bodies()` collects stdin inline data.
4. `pysh.parsing.lexer.strip_comments()` removes unquoted comments from the
   command line, not from heredoc body text.
5. `pysh.parsing.grammar.validate_unsupported_syntax()` rejects parser-owned
   unsupported constructs with `UnsupportedSyntaxError`.
6. `pysh.parsing.expansion.expand_command_substitution()` expands `$(...)` and
   backtick substitution before command-chain execution.
7. `pysh.parsing.grammar.split_chain()` splits unquoted `;`, `&&`, and `||`.
8. Each chain element is split by `split_pipeline()` on unquoted `|`.
9. Each pipeline stage is tokenized with `shlex`, redirection is parsed, aliases
   are applied to the first word, and variable expansion runs on argv tokens.
10. `pysh.core.shell.PyShell` performs builtin dispatch, external command
   execution, pipeline fd management, and exit-status propagation.

## Chain, Pipeline and Redirection Rules

Operators are recognized only when outside single quotes, double quotes, and
escaped contexts.

| Construct | Native behavior |
| --------- | --------------- |
| `cmd1 ; cmd2` | Sequential command chain. |
| `cmd1 && cmd2` | Run right side only when left side exits 0. |
| `cmd1 || cmd2` | Run right side only when left side exits non-zero. |
| `cmd1 | cmd2` | Pipeline with the final stage status as the pipeline status. |
| Trailing `|` | Parse error, exit status 2. |
| `<`, `>`, `>>`, `2>`, `2>>`, `&>`, `&>>` | Native redirection. |
| `<<`, `<<-`, `<<<` | Native stdin inline-data redirection; see [heredoc-contract.md](heredoc-contract.md). |
| `2>&1` and related fd duplication | Not implemented in Issue #8. |

## Expansion Contract

Expansion is intentionally narrow and test-backed.

| Expansion | Behavior |
| --------- | -------- |
| `$NAME` | Expands from local variables first, then environment, outside single quotes. |
| `${NAME}` | Same as `$NAME`. |
| `$?` | Expands to the last PySH command status. |
| `${NAME:-default}`, `${#NAME}`, `${NAME%pat}`, etc. | Classified as unsupported parameter expansion and left literal by variable expansion. |
| `$((expr))`, `(( expr ))`, `let NAME=expr` | Parser-owned unsupported syntax; diagnostic and exit status 2. |
| `$(command)` and backticks | Supported command substitution with timeout. |
| Nested command substitution | Not part of the Issue #8 foundation. |
| `*.py`, `?`, `[...]`, `**` | Native path expansion for unquoted command arguments; not applied to heredoc or here-string content. |
| `{a,b}` and ranges | Passed literally; no brace expansion contract. |

## Multiline Contract

`pysh.parsing.multiline` owns logical-line decisions:

| Input form | Behavior |
| ---------- | -------- |
| Unterminated single quote | Continuation required until the quote closes. |
| Unterminated double quote | Continuation required until the quote closes. |
| Backslash-newline | Joined into a single logical command. |
| `py { ... }` | Coalesced as one Python block; nested blocks are rejected. |
| Heredoc opener | Collected before command execution; see [heredoc-contract.md](heredoc-contract.md). |

Interactive bracketed paste uses the same paste-splitting contract for queued
commands. Newlines inside quotes remain inside the command; they are not
treated as command boundaries.

## Parse Error Mapping

Parser-local errors are mapped at the shell boundary:

| Error source | Exit status |
| ------------ | ----------- |
| `ParseError` | 2 |
| `UnsupportedSyntaxError` | 2 |
| `shlex.ValueError` during command tokenization | 2 |
| Command not found | 127 |
| Found but cannot execute | 126 |
| General execution error | 1 |

Diagnostics are printed to stderr and must not terminate the interactive shell.

## Validation

The Issue #8 foundation is covered by:

| Contract | Evidence |
| -------- | -------- |
| Chain/pipeline grammar and parse-error mapping | `tests/test_parser_foundation.py` |
| Expansion support and unsupported expansion behavior | `tests/test_expansion_foundation.py` |
| Quote continuation, backslash-newline, Python block coalescing | `tests/test_multiline_grammar.py` |
| Existing parser behavior regression coverage | `tests/test_parser.py` |
| Exit-code boundary | `tests/test_error_exit_code_contract.py` |
| Import-boundary ratchet | `tests/test_architecture_import_boundaries.py` |
