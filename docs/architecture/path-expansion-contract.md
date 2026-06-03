<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/path-expansion-contract.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Path and Glob Expansion Contract (Issue #9)

This document defines the native path and glob expansion contract for
PySH 0.5.x.  All claims are backed by tests in `tests/test_path_expansion.py`.

---

## Scope

Issue #9 implements native glob and path expansion.  It does not implement:

- Heredocs or here-strings — Issue #10.
- Job control, `&` background, `jobs`, `fg`, `bg` — Issue #11.
- Completion engine — Issue #12.
- Brace expansion (`{a,b}`) — unsupported; passes literal to commands.
- Process substitution (`<(cmd)`, `>(cmd)`) — unsupported.
- Arithmetic expansion — unsupported; `$((expr))` and `(( expr ))` are rejected with a parse diagnostic (Issue #8).
- Advanced parameter expansion — unsupported; only `$NAME`, `${NAME}`, and `$?` are supported. Issue #8 added deterministic unsupported/literal behavior for advanced forms such as `${NAME:-default}`.
- Shell functions — unsupported.

---

## Expansion order

PySH expands command lines in this order:

| Step | Operation | Where implemented |
|------|-----------|-------------------|
| 1 | Command substitution (`$(...)`, backticks) | `pysh.parsing.expansion` — `execute()` |
| 2 | Variable expansion (`$NAME`, `${NAME}`, `$?`) | `pysh.parsing.expansion` — `_run_chain_element()` |
| 3 | Tilde expansion (`~`, `~/path`, `~user`) | `pysh.parsing.path_expansion` — `tokenize_and_glob_expand()` |
| 4 | Glob/path expansion (`*`, `?`, `[...]`, `**`) | `pysh.parsing.path_expansion` — `tokenize_and_glob_expand()` |
| 5 | Redirection application / external execution | `pysh.core.shell` |

Steps 3 and 4 are applied AFTER variable expansion.  This means that if
`$X` expands to `*.py`, the resulting `*.py` is eligible for glob expansion.
This differs from some shells where variable expansion results are not
glob-expanded; the behavior is documented and tested.

---

## Supported glob syntax

| Pattern | Description | Example |
|---------|-------------|---------|
| `*` | Any sequence of characters (not crossing `/`, not matching leading `.`) | `*.py` |
| `?` | Any single character (not matching leading `.`) | `?.txt` |
| `[abc]` | One character from the set | `[ab].txt` |
| `[a-z]` | One character from the range | `[a-z].py` |
| `**` | Any sequence of characters including `/` (recursive) | `**/*.py` |

`**` recursive glob is enabled by default
(`PathExpansionOptions.recursive_globstar = True`).

---

## Tilde expansion

| Pattern | Result |
|---------|--------|
| `~` | Current user's home directory |
| `~/path` | `<home>/path` |
| `~user` | Named user's home directory (via `os.path.expanduser`) |
| `"~"` or `'~'` | Literal `~` (no expansion inside quotes) |
| `\~` | Literal `~` (backslash-escaped) |

Tilde expansion is applied only to tokens that start with an **unquoted** `~`.
Tilde expansion is also applied to redirection targets (`> ~/file`).

---

## Dotfile policy

`*` does **not** match names beginning with `.`.  This matches common Unix
shell convention.  Python's `glob.glob` follows this convention in Python
3.13+.

To match dotfiles, use a pattern that explicitly begins with `.`:

- `.*` matches all dotfiles in the current directory.
- `.*.py` matches dotfiles ending in `.py`.

This behavior is tested in `tests/test_path_expansion.py::TestExpandPathWord`.

---

## No-match policy

When a glob pattern matches **no filesystem entries**, the original literal
pattern is returned unchanged.  This is `NoMatchPolicy.LITERAL` (the default).

Examples:

- `echo *.xyz` where no `.xyz` files exist → prints literal `*.xyz`
- `echo no-such-*.txt` → prints literal `no-such-*.txt`

Alternative policies (`NoMatchPolicy.EMPTY`, `NoMatchPolicy.ERROR`) are
available in `PathExpansionOptions` for programmatic callers.

---

## Sorting policy

Glob expansion results are sorted lexicographically by default
(`PathExpansionOptions.sort = True`).  This ensures deterministic argv order
independent of filesystem traversal order.

---

## Quoting and escaping

| Input | Glob expansion? | Tilde expansion? |
|-------|:---------------:|:----------------:|
| `*.py` (unquoted) | Yes | — |
| `"*.py"` (double-quoted) | No — literal | No |
| `'*.py'` (single-quoted) | No — literal | No |
| `\*.py` (backslash-escaped `*`) | No — literal | — |
| `~` (unquoted) | — | Yes |
| `"~"` (double-quoted) | — | No — literal |
| `'~'` (single-quoted) | — | No — literal |
| `\~` (backslash-escaped) | — | No — literal |

Double quotes suppress glob expansion but still allow variable expansion
(which happens upstream in step 2 before `tokenize_and_glob_expand` is called).

---

## Redirection target policy

Tilde expansion IS applied to redirection targets:

```
echo hello > ~/output.txt   # writes to $HOME/output.txt
```

Glob expansion is NOT applied to redirection targets.  A redirection target
like `> *.out` is treated as the literal filename `*.out`.  This prevents
accidental multi-target redirections which would be unsafe.

---

## Brace expansion

Brace expansion (`{a,b,c}`, `{1..5}`) is **not supported** in Issue #9.
Brace patterns are passed as literal arguments to external commands.  This
matches the documented behavior in `docs/compatibility/feature-matrix.md`.

---

## Security and trust considerations

Glob expansion is applied only to **command arguments**, using the user's
current working directory.  It does not:

- Execute code.
- Mutate shell state.
- Expand inside subprocess arguments (subprocess receives the final expanded argv).
- Apply to redirection targets (avoiding multi-file redirect risks).

Glob expansion results are deterministic for a given filesystem state.

---

## Implementation module

`src/pysh/parsing/path_expansion.py` — stdlib only, no pysh implementation imports.

Public API:

| Symbol | Type | Description |
|--------|------|-------------|
| `NoMatchPolicy` | `StrEnum` | `LITERAL` / `ERROR` / `EMPTY` |
| `PathExpansionOptions` | `dataclass` | `no_match`, `recursive_globstar`, `sort` |
| `has_glob_metacharacters(word)` | `bool` | True if word contains `*`, `?`, or `[` |
| `expand_tilde(word)` | `str` | Expand leading `~` or `~user` |
| `expand_path_word(word, *, cwd, options)` | `list[str]` | Tilde + glob expand one word |
| `expand_path_words(words, *, cwd, options)` | `list[str]` | Expand a list of words |
| `tokenize_and_glob_expand(text, *, cwd, options)` | `list[str]` | Quote-aware tokenize + expand |

---

## Validation matrix

| Claim | Test file | Test | Status |
|-------|-----------|------|--------|
| `*` expands to matching files | `test_path_expansion.py` | `TestExpandPathWord::test_star_matches_py_files` | PASS |
| `?` matches one char | `test_path_expansion.py` | `test_question_mark_matches_one_char` | PASS |
| `[abc]` character class | `test_path_expansion.py` | `test_bracket_class_matches` | PASS |
| `**` recursive glob | `test_path_expansion.py` | `test_recursive_globstar` | PASS |
| `*` does not match dotfiles | `test_path_expansion.py` | `test_star_does_not_match_dotfiles_by_default` | PASS |
| `.*.py` matches dotfiles | `test_path_expansion.py` | `test_explicit_dot_pattern_matches_dotfiles` | PASS |
| No-match → literal | `test_path_expansion.py` | `test_no_match_returns_literal` | PASS |
| Results sorted | `test_path_expansion.py` | `test_results_sorted_by_default` | PASS |
| Single-quoted glob literal | `test_path_expansion.py` | `TestTokenizeAndGlobExpand::test_single_quoted_glob_remains_literal` | PASS |
| Double-quoted glob literal | `test_path_expansion.py` | `test_double_quoted_glob_remains_literal` | PASS |
| `\*` literal | `test_path_expansion.py` | `test_backslash_escaped_star_remains_literal` | PASS |
| `~` expands to home | `test_path_expansion.py` | `TestExpandTilde` | PASS |
| `"~"` stays literal | `test_path_expansion.py` | `test_tilde_in_double_quotes_stays_literal` | PASS |
| Shell argv glob expansion | `test_path_expansion.py` | `TestShellGlobIntegration` | PASS |
| `> ~/file` tilde expanded | `test_path_expansion.py` | `TestRedirectionTargets::test_tilde_expanded_in_stdout_redirect` | PASS |
| `> *.out` stays literal | `test_path_expansion.py` | `test_glob_in_redirect_target_stays_literal` | PASS |
| Brace expansion stays literal | `test_path_expansion.py` | `test_echo_brace_expansion_stays_literal` | PASS |
| Variable then glob expansion | `test_path_expansion.py` | `TestRegression::test_variable_then_glob_expansion` | PASS |
| Quoted glob unchanged (regression) | `test_path_expansion.py` | `test_existing_glob_patterns_as_literals_via_double_quote` | PASS |

---

## Relation to other issues

| Issue | Relation |
|-------|----------|
| Issue #8 | Parser foundation: `expand_variables` and grammar that feeds into `tokenize_and_glob_expand` |
| Issue #9 | This document |
| Issue #10 | Heredocs and here-strings (not in scope for path expansion) |
| Issue #11 | Job control (not in scope; process-group ownership separate) |
| Issue #14 | Script mode: path expansion applies the same rules in script execution |
| Issue #16 | Shell comparison hardening: will validate glob behavior against real zsh/bash |
| Issue #17 | POSIX sh scope: PySH does not claim full POSIX glob compatibility |
