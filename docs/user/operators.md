<!--
SPDX-License-Identifier: GPL-3.0-or-later

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/operators.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (c) 2026 Siergej Sobolewski

Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# Operators

PySH implements a small quote-aware operator set. Operators inside single or
double quotes are treated as literal text.

## Command chains

| Operator | Syntax          | Behavior                                      |
| -------- | --------------- | --------------------------------------------- |
| `;`      | `cmd1 ; cmd2`   | Run both commands in sequence.                |
| `&&`     | `cmd1 && cmd2`  | Run `cmd2` only if `cmd1` returns 0.          |
| `||`     | `cmd1 || cmd2`  | Run `cmd2` only if `cmd1` returns non-zero.   |

Examples:

```sh
echo first; echo second
false && echo skipped
false || echo recovered
```

## Pipelines

Syntax: `cmd1 | cmd2`

Purpose: Connect stdout from one command to stdin of the next using an OS
pipe.

Example:

```sh
printf 'a\nb\nc\n' | head -2
```

The pipeline return status is the final stage's status. PySH closes parent
pipe handles after spawning children to avoid EOF deadlocks.

## Redirection

| Syntax     | Behavior                              |
| ---------- | ------------------------------------- |
| `< file`   | Read stdin from `file`.               |
| `> file`   | Write stdout to `file`, truncating.   |
| `>> file`  | Write stdout to `file`, appending.    |
| `2> file`  | Write stderr to `file`, truncating.   |
| `2>> file` | Write stderr to `file`, appending.    |
| `&> file`  | Write stdout and stderr to `file`.    |
| `&>> file` | Append stdout and stderr to `file`.   |

Examples:

```sh
echo hello > out.txt
echo again >> out.txt
python3.13 -c "import sys; print('err', file=sys.stderr)" 2> err.log
ls -la &> listing.log
```

Redirection paths are parsed outside quotes. Redirection operators inside
quotes remain literal arguments.

## Command substitution

Syntax:

```sh
$(command)
`command`
```

Purpose: Run a command and substitute its stdout into the current command
line before chain splitting, alias expansion and variable expansion.

Examples:

```sh
echo "Kernel: $(uname -r)"
echo "Date: `date '+%Y-%m-%d'`"
echo 'Literal: $(date)'
```

Substitution is evaluated inside double quotes and suppressed inside single
quotes. Each substitution has a 5-second timeout by default. On timeout or
substitution error, PySH reports the issue and substitutes an empty string.

## Quoting behavior

PySH tracks single quotes, double quotes and backslash escapes while parsing
operators. This preserves literal operator characters inside quoted strings:

```sh
echo "a | b ; c && d"
echo 'literal $(date)'
```

Variable expansion is suppressed inside single quotes and active inside
double quotes.

## Known limitations

PySH does not implement the full POSIX, bash or zsh grammar. Known
non-goals for 0.2.2 include job control operators, here-documents,
process substitution, brace expansion, native glob expansion, shell arrays
and multiline shell functions.
