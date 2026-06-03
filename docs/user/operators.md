<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/operators.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

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

A trailing pipe is a parse error and returns status 2:

```sh
echo hello |
```

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
| `<< WORD`  | Read stdin from following heredoc body. |
| `<<- WORD` | Read stdin from body with leading tabs stripped. |
| `<<< WORD` | Read stdin from one expanded word plus newline. |

Examples:

```sh
echo hello > out.txt
echo again >> out.txt
python3.13 -c "import sys; print('err', file=sys.stderr)" 2> err.log
ls -la &> listing.log
```

Redirection paths are parsed outside quotes. Redirection operators inside
quotes remain literal arguments.

Heredocs and here-strings are stdin redirections. Unquoted heredoc delimiters
enable `$NAME`, `${NAME}`, `$?`, and supported command substitution in body
text; quoted delimiters make the body literal. Glob/path expansion is not
applied to heredoc body text or here-string content. For `<<-`, only leading
tab characters are stripped; spaces are preserved. When multiple stdin
redirections are present, PySH applies them left to right and the last stdin
redirection wins.

```sh
cat << EOF
hello
EOF

cat << 'EOF'
$HOME stays literal
EOF

cat <<- EOF
	leading tab stripped
	EOF

cat <<< "*.py"
```

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

## Line continuation

A backslash immediately before a newline joins the physical lines into one
logical command:

```sh
echo hello \
world
```

The command above is parsed as `echo hello world`.

## Known limitations

PySH does not implement the full POSIX, bash or zsh grammar. Current
non-goals include job control operators, process substitution, brace
expansion, shell arrays and multiline shell functions.
