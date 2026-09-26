<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/spec/pysh-language.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH Language Specification, Version 1

## 1. Scope and authority

This document is the normative definition of current PySH v1 command-language
semantics. In this document, **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are
normative requirements. Implementation notes explain the current mechanism but
do not independently extend the language.

Older documents under `docs/architecture/` remain subsystem and historical
design contracts. Documents under `docs/compatibility/` classify behavior
relative to other shells; they do not independently define PySH grammar. If
either conflicts with this specification, this specification governs PySH v1.

PySH is not a POSIX `sh`, bash, or zsh implementation. Similar syntax does not
imply unspecified compatibility.

## 2. Terminology and source model

- A *physical line* is source text terminated by a newline or end of input.
- A *logical input* is one or more physical lines grouped by quote continuation,
  backslash-newline, heredoc collection, or a `py { ... }` block.
- A *word* is one argv token after quote removal and supported expansion.
- A *stage* is one command in a pipeline.
- A *chain element* is one pipeline or simple command joined by a chain operator.
- *Status* is an integer command result in the range 0 through 255.

Input is Unicode text. The CLI `-c` surface and native script surface MUST apply
the same command semantics after their respective logical-input collection.
Interactive presentation, completion, history, highlighting, prompts, terminal
redraw, and paste review are not language grammar.

<a id="PYSH-LANG-SOURCE-LOGICAL"></a>
**PYSH-LANG-SOURCE-LOGICAL.** PySH MUST form logical input before parsing
operators. A trailing unescaped backslash outside quotes joins the following
physical line with one separating space. A newline within continued quotes is
preserved. Heredoc bodies and Python block bodies are collected as data/body
text, not as independent commands.

## 3. Lexical rules and grammar

The following EBNF describes the supported outer language. Whitespace means one
or more space or tab characters. The grammar describes syntactic shape;
semantic restrictions below still apply.

```ebnf
logical-input   = chain | python-block | pipeline-python-block ;
chain           = command, { chain-op, command } ;
chain-op        = ";" | "&&" | "||" | "&" ;
command         = pipeline ;
pipeline        = stage, { "|", stage } ;
stage           = { assignment, whitespace }, simple-command,
                  { whitespace, redirection } ;
simple-command  = word, { whitespace, word } ;
assignment      = name, "=", word-fragment* ;
name            = ( letter | "_" ), { letter | digit | "_" } ;
word            = word-fragment, { word-fragment } ;
word-fragment   = unquoted | single-quoted | double-quoted | escaped ;
single-quoted   = "'", { any-character-except-single-quote }, "'" ;
double-quoted   = '"', { double-quoted-character }, '"' ;
escaped         = "\\", any-character ;
redirection     = [ "0" ], "<", word
                | [ "1" ], ">", word
                | [ "1" ], ">>", word
                | "2>", word | "2>>", word
                | "&>", word | "&>>", word
                | "2>&1" | "1>&2" | ">&2"
                | "<<", delimiter | "<<-", delimiter | "<<<", word ;
python-block    = "py", whitespace, "{", newline,
                  python-source, newline, "}" ;
pipeline-python-block = stage, { "|", stage }, "|", python-block ;
```

`unquoted`, `double-quoted-character`, `delimiter`, and Python source are
defined by the lexical and semantic rules below. Heredoc body collection is
not ordinary token grammar. Python source is parsed by Python, not this EBNF.

<a id="PYSH-LANG-LEX-WORDS"></a>
**PYSH-LANG-LEX-WORDS.** Space and tab outside quotes separate words. Adjacent
quoted and unquoted fragments form one word. Quote characters group text and
are removed before argv construction. An unquoted backslash quotes the next
character. Empty quoted strings do not currently produce an argv word and are
therefore intentionally unspecified rather than a portable v1 argument form.

<a id="PYSH-LANG-QUOTE-RULES"></a>
**PYSH-LANG-QUOTE-RULES.** Single quotes preserve all enclosed characters and
suppress variable, command, tilde, and glob expansion. Double quotes preserve
word grouping, suppress tilde and glob expansion, and permit variable and
command substitution. Within double quotes, backslash quotes only `"`, `\`,
`$`, or backtick. Operators are recognized only when unquoted and unescaped.
An unclosed quote in complete command input MUST produce status 2.

<a id="PYSH-LANG-COMMENT-BOUNDARY"></a>
**PYSH-LANG-COMMENT-BOUNDARY.** An unquoted `#` starts a comment only at the
beginning of input or immediately after space or tab. It and the remainder of
that command line are removed. A quoted, escaped, or mid-word `#` is literal.
Heredoc body text and Python block source are not shell comments.

## 4. Commands, chains, and pipelines

<a id="PYSH-LANG-CHAIN-SEQUENCE"></a>
**PYSH-LANG-CHAIN-SEQUENCE.** `A ; B` MUST execute `A` then `B`. The resulting
status is the most recently executed element's status.

<a id="PYSH-LANG-CHAIN-CONDITIONAL"></a>
**PYSH-LANG-CHAIN-CONDITIONAL.** `A && B` executes `B` only when `A` returns 0.
`A || B` executes `B` only when `A` returns nonzero. Decisions use the most
recently executed status, and skipped elements do not replace it. The chain
status is the status of the last element actually executed.

<a id="PYSH-LANG-CHAIN-BACKGROUND"></a>
**PYSH-LANG-CHAIN-BACKGROUND.** `A &` starts an external command or pipeline as
a background job and reports success when launch succeeds; following elements
remain eligible to execute. A bare `&` is a status-2 syntax error. Builtins run
in process and do not become asynchronous merely because `&` follows them.
Job identifiers and launch PIDs are not stable language output.

<a id="PYSH-LANG-PIPE-STATUS"></a>
**PYSH-LANG-PIPE-STATUS.** An unquoted `|` connects the stdout of each stage to
the stdin of the next. Stages execute in isolated child processes. The pipeline
status MUST be the final stage's status; PySH v1 has no `pipefail` mode.
Quoted or escaped pipes are word data. An empty or dangling stage MUST produce
status 2.

Python inline stages (`py CODE`) and a final collected `py { ... }` block MAY
participate in pipelines. A Python stage in a pipeline executes in its isolated
child and therefore MUST NOT persist namespace changes into the parent session.

## 5. Redirections

<a id="PYSH-LANG-REDIR-FILES"></a>
**PYSH-LANG-REDIR-FILES.** PySH supports `<`, `0<`, `>`, `1>`, `>>`, `1>>`,
`2>`, `2>>`, `&>`, and `&>>`. Input opens a file for reading; `>` truncates;
`>>` appends. `&>` and `&>>` first redirect fd 1 and then duplicate fd 2 from
fd 1. Operators may be adjacent to their target. A missing target is a status-2
syntax error. Tilde expansion applies to file targets; glob expansion does not.

<a id="PYSH-LANG-REDIR-FD-DUP"></a>
**PYSH-LANG-REDIR-FD-DUP.** PySH supports exactly `2>&1`, `1>&2`, and `>&2`
for descriptor duplication. Duplication copies the source descriptor's current
destination at that point; it is not a permanent link to later changes.
Arbitrary descriptor numbers, descriptor closing (`>&-`), and input duplication
(`<&`) are unsupported in v1.

<a id="PYSH-LANG-REDIR-ORDER"></a>
**PYSH-LANG-REDIR-ORDER.** Redirection actions MUST be applied from left to
right. Thus `cmd >out 2>&1` sends both streams to `out`, whereas
`cmd 2>&1 >out` leaves stderr at the destination stdout had before `>out` and
sends only stdout to `out`. Multiple input or output redirections are likewise
ordered; the last action for a descriptor determines its final destination.

Redirection applies to external commands, builtins, plugins, and supported
Python execution. Open/setup failure returns status 1 unless a more specific
established status applies.

## 6. Variables and expansion

<a id="PYSH-LANG-EXP-ORDER"></a>
**PYSH-LANG-EXP-ORDER.** For ordinary shell stages, processing order is:
logical-input collection; heredoc collection; comment removal; unsupported
syntax validation; command substitution; chain and pipeline splitting; alias
expansion; variable expansion; redirection parsing; quote removal/tokenization;
tilde expansion; glob expansion; execution. Python block bodies are protected
from shell word expansion. Here-input follows its separate rules below.

<a id="PYSH-LANG-EXP-VARIABLE"></a>
**PYSH-LANG-EXP-VARIABLE.** `$NAME` and `${NAME}` expand first from PySH local
variables and then from the process environment; an unset name expands to the
empty string. `$?` expands to the last PySH status. Expansion is active
unquoted and inside double quotes, and suppressed inside single quotes.
Bare `NAME=value` assignments update the session-local variable map. Leading
assignments before a command modify that command's child environment without
mutating the parent process environment.

Advanced parameter expansions such as `${NAME:-default}`, `${#NAME}`, and
`${NAME%pattern}` are unsupported and remain literal under the current parser.
Arithmetic expansion `$((...))`, arithmetic commands `((...))`, and `let` are
recognized as unsupported syntax and return status 2.

<a id="PYSH-LANG-EXP-PATH"></a>
**PYSH-LANG-EXP-PATH.** An unquoted leading `~` undergoes user-home expansion.
Unquoted `*`, `?`, bracket expressions, and recursive `**` undergo filesystem
glob expansion after variable expansion. Results are lexicographically sorted.
Wildcard components do not match leading-dot names unless the pattern component
begins with `.`. A pattern with no match remains literal. Quoting or escaping
the relevant metacharacter suppresses expansion. Brace expansion is unsupported
and brace text remains literal.

<a id="PYSH-LANG-SUBST-COMMAND"></a>
**PYSH-LANG-SUBST-COMMAND.** `$(command)` and backtick command substitution run
through `/bin/sh -c`, capture stdout, remove all trailing newline characters,
and insert the remaining text before chain splitting. Substitution is active
unquoted and within double quotes, and suppressed within single quotes. Each
substitution is bounded by the implementation timeout (currently five seconds);
timeout or launch failure diagnoses the event and substitutes an empty string.

The `/bin/sh` language inside substitution is an explicit delegated language,
not PySH grammar. Nested/pathological substitution, substitution stderr text,
and malformed unmatched substitution delimiters are not portable v1 contracts;
unmatched forms currently remain literal.

## 7. Heredocs and here-strings

<a id="PYSH-LANG-HEREDOC-COLLECT"></a>
**PYSH-LANG-HEREDOC-COLLECT.** `<< WORD` and `<<- WORD` collect following
physical lines until a line equal to the quote-removed delimiter. The delimiter
line is excluded; each body line retains a trailing newline. Missing delimiter
word or terminator MUST return status 2. Multiple heredocs are collected and
applied left to right. They are stdin data and MUST NOT execute as commands.

<a id="PYSH-LANG-HEREDOC-EXPAND"></a>
**PYSH-LANG-HEREDOC-EXPAND.** An unquoted delimiter enables supported variable
and command substitution in body text. A single- or double-quoted delimiter
makes the body literal. Glob and tilde expansion MUST NOT apply to body text.
For `<<-`, leading tab characters are removed from stored body lines and before
delimiter comparison; leading spaces are preserved.

<a id="PYSH-LANG-HERESTRING-INPUT"></a>
**PYSH-LANG-HERESTRING-INPUT.** `<<< WORD` supplies the quote-removed word followed by
exactly one newline on stdin. Supported variable and command substitution apply;
glob and tilde expansion do not. As with every stdin redirection, ordered later
stdin actions override it.

## 8. Python execution

<a id="PYSH-LANG-PY-INLINE"></a>
**PYSH-LANG-PY-INLINE.** `py CODE` compiles and executes `CODE` as Python in a
session-persistent namespace shared with `py { ... }`. Python syntax or runtime
failure returns 1 and MUST NOT terminate the shell. Successful execution returns
0. A bare `py` invokes the builtin's existing usage behavior rather than an
empty inline program.

<a id="PYSH-LANG-PY-BLOCK"></a>
**PYSH-LANG-PY-BLOCK.** A block opener is a logical line containing `py {`
with optional surrounding whitespace and an optional trailing shell comment.
The closer is a line containing only `}` with optional whitespace. The body is
dedented and parsed as Python. Nested PySH block openers are unsupported. A bare
or unterminated opener returns status 2 at the command/script boundary. A final
pipeline stage may be a collected Python block and receives pipeline stdin.
Python braces inside the body are Python syntax and do not close the PySH block.

The separate interactive `#py` editor mode is a user-interface execution
surface, not part of the v1 command grammar.

## 9. Native script mode and startup

<a id="PYSH-LANG-SCRIPT-EXECUTION"></a>
**PYSH-LANG-SCRIPT-EXECUTION.** `pysh FILE [ARGS...]` executes readable `FILE`
as native PySH regardless of filename suffix. Blank and comment-only logical
lines do not replace the current script status. Without `exit`, the script
returns the last executed command's status. `exit N` terminates immediately
with `N`. A status-2 parse/usage failure stops the script unless the logical
line contains `&&` or `||`, in which case normal chain handling determines the
line status and execution may continue. Other nonzero statuses do not imply
`set -e` behavior.

<a id="PYSH-LANG-SCRIPT-PARAMETERS"></a>
**PYSH-LANG-SCRIPT-PARAMETERS.** In native script mode, `$0` is the script path;
`$1`, `$2`, and later numeric parameters are arguments; `$#` is the argument
count; and `$@` and `$*` are the same space-joined string in v1. They do not
implement POSIX `"$@"` multi-word preservation. Braced forms are supported.

<a id="PYSH-LANG-SCRIPT-SHEBANG"></a>
**PYSH-LANG-SCRIPT-SHEBANG.** Direct native script mode ignores a first line
beginning with `#!`; it does not dispatch that interpreter. The explicit
`run_script` transition builtin may delegate bash/sh/zsh shebangs using argv
execution, but delegated syntax is not PySH language semantics.

<a id="PYSH-LANG-STARTUP-BOUNDARY"></a>
**PYSH-LANG-STARTUP-BOUNDARY.** `--no-rc` MUST disable user configuration and
plugin discovery for command and script execution. Native script mode MUST NOT
source foreign shell profiles. Configuration is trusted executable input and
may affect normal sessions, but configuration-file grammar, plugin behavior,
and interactive startup presentation are outside this language specification.

## 10. Status and failures

<a id="PYSH-LANG-EXIT-STATUS"></a>
**PYSH-LANG-EXIT-STATUS.** PySH reserves these established meanings: 0 success;
1 general execution/runtime failure; 2 syntax or builtin usage failure; 126
command found but not executable; and 127 command not found. A normal external
exit status is propagated. Exact OS error wording is not normative.

<a id="PYSH-LANG-EXIT-SIGNAL"></a>
**PYSH-LANG-EXIT-SIGNAL.** A child terminated by signal number `N` maps to
`128 + N`. SIGINT therefore maps to 130. Parent-side keyboard interruption of
a foreground child or pipeline also returns 130 after cleanup.

<a id="PYSH-LANG-ERROR-UNSUPPORTED"></a>
**PYSH-LANG-ERROR-UNSUPPORTED.** Recognized unsupported shell control flow
(`if`, `for`, `while`, `case`, functions), arithmetic syntax, process
substitution, and parser-owned malformed operator forms MUST fail without being
silently delegated. Parser/unsupported-syntax failures return 2 and MUST NOT
terminate a continuing interactive shell.

## 11. Supported, unsupported, and unspecified boundary

Behavior attached to a `PYSH-LANG-*` contract above and exercised by the v1
corpus is **supported**. Syntax explicitly rejected or described as outside v1
is **unsupported**. The following are **unspecified** and MUST NOT be relied on:

- exact internal exception types, traceback frames, temporary-file paths, and
  nondeterministic OS diagnostic wording;
- timing, scheduling, background PID/job-number text, and pipeline interleaving;
- host PATH ordering, executable-resolution accidents, locale, hostname, user,
  terminal rendering, prompt/editor state, and plugin-produced behavior;
- empty-quoted argv elements, pathological nested substitution, and constructs
  not assigned a normative contract above.

Unsupported syntax includes full POSIX control flow, shell functions, arrays,
brace expansion semantics, process substitution, arithmetic expansion, general
fd manipulation, `set -e/-u/-x`, and implicit bash/zsh fallback. Literal
pass-through of brace or advanced parameter text does not make those features
supported.

## 12. Semantic change procedure

Any intentional language change MUST update, in one reviewed change:

1. the affected normative contract(s) in this specification;
2. positive and negative cases in the versioned conformance corpus;
3. implementation and focused/regression tests when runtime behavior changes;
4. compatibility/reference metadata when behavior relative to other shells changes.

Changing runtime semantics without the spec and corpus is invalid. Changing the
spec without executable conformance evidence is invalid. Contract identifiers
SHOULD remain stable when meaning is refined compatibly; an incompatible meaning
MUST receive a new identifier and language/corpus version as appropriate.

## 13. Conformance corpus mapping

The canonical corpus is `tests/conformance/pysh-language-v1.json`. Its
`schema_version` is **1** and its language version is `1`. Every case names one
contract ID, execution surface, structured PySH expectation, and structured
future reference-shell classification. `scripts/run_language_conformance.py`
validates the closed schema, resolves every contract ID against explicit anchors
in this document, provisions isolated deterministic fixtures, and executes only
PySH. It MUST NOT execute reference shells.

Corpus placeholders are fixed, non-executable string substitutions:
`{{FIXTURE_BIN}}`, `{{NOEXEC}}`, `{{WORK}}`, and `{{HOME}}`. They refer only to
runner-created temporary resources. The corpus cannot select commands or supply
runner argv metadata. The `command` surface means `pysh --no-rc -c INPUT`; the
`script` surface means a temporary native script invoked with `--no-rc`.

The corpus is the intrinsic correctness oracle for later robustness and
differential suites. Reference behavior metadata is descriptive only in v1;
capturing or executing bash/zsh/sh reference behavior belongs to later work.
