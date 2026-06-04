<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/architecture/source-tree.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# PySH source-tree architecture

This document describes the post-Issue #2 source tree of PySH 0.5.x.
Issue #2 relocated all runtime source from a flat `src/pysh/` layout into
domain-oriented subpackages. This document records the resulting structure,
each package's responsibility, the dependency direction, and the boundaries
between packages.

**Issue #2 scope**: relocation only. No logic was changed, extracted, or
merged during the refactor. The resulting import paths differ; the behavior
is identical.

**Issue #3 scope**: enforceable import-boundary contracts via static analysis.
Issue #3 has been implemented: `pysh.contracts` exists, import-boundary tests
run in CI, and the full contract layer is documented in
[architecture.md](architecture.md).

---

## Current source tree (`src/pysh/`)

```text
src/pysh/
├── __init__.py              ← package metadata: __version__, LICENSE_NAME
├── __main__.py              ← python -m pysh entry point
├── cli.py                   ← console script entry point; argument parsing
├── shell.py                 ← compatibility shim → pysh.core.shell (Issue #19)
├── script_runner.py         ← script transition runner (shebang dispatch)
│
├── core/
│   ├── errors.py            ← canonical ExitCode / PyShError / Diagnostic contract
│   ├── jobs.py              ← Job, JobTable, JobStatus; POSIX job-control helpers (Issue #11)
│   ├── shell.py             ← PyShell: REPL loop, command dispatch, builtins
│   └── signals.py           ← signal return-code and status helpers
│
├── parsing/
│   ├── ast.py               ← parser value objects: ChainOp, ChainElement
│   ├── errors.py            ← parser-local ParseError taxonomy
│   ├── expansion.py         ← variable and command-substitution helpers
│   ├── grammar.py           ← chain/pipeline/assignment grammar helpers
│   ├── heredoc.py           ← here-document and here-string parser model
│   ├── lexer.py             ← quote, escape and comment scanner
│   ├── multiline.py         ← continuation, Python block and paste splitting
│   ├── parser.py            ← compatibility facade for parser helpers
│   └── redirection.py       ← RedirectionSpec parser and applier
│
├── editor/
│   ├── completion.py        ← tab-completion adapter/coordinator
│   ├── highlight.py         ← ANSI color helpers; colors_enabled, paint
│   ├── history.py           ← readline/history manager
│   └── lineedit/
│       ├── autosuggest.py   ← fish-style autosuggestion engine
│       ├── buffer.py        ← LineBuffer: display-width-aware character buffer
│       ├── completion.py    ← Completion Engine v1 and raw-mode helpers
│       ├── highlight.py     ← live syntax highlighting (LineHighlighter)
│       ├── keys.py          ← KeyDecoder: terminal escape sequence parser
│       └── reader.py        ← RawLineReader: raw-mode line editing driver
│
├── prompt/
│   ├── colors.py            ← color parsing: colorize, color_to_hex, parse_color
│   └── system_profile.py   ← sys_info, env_audit, path_audit, which_all, apt_*
│
├── python_layer/
│   ├── highlighting.py      ← Pygments-based Python syntax renderer
│   ├── mode.py              ← #py interactive Python command mode
│   ├── render.py            ← PythonSyntaxRenderer facade
│   └── runtime.py           ← PythonRuntime: persistent namespace, py builtin
│
├── config/
│   ├── api.py               ← ConfigAPI: prompt/cursor/color config
│   ├── plugins.py           ← plugin directory loader (~/.pyshrc.d/)
│   └── rc.py                ← RC file loader and mini rc-interpreter
│
├── compat/
│   ├── mc.py                ← Midnight Commander environment detection
│   ├── profile_importer.py  ← static zsh/sh profile importer
│   ├── zsh_aliases.py       ← zsh alias file parser
│   └── zsh_bridge.py        ← ZshBridge: explicit zsh delegation
│
├── services/
│   ├── pyinit.py            ← PyInit service metadata parser
│   └── service.py           ← svc client: PID-file-based service control
│
├── security/
│   ├── policy.py            ← Issue #7 trust constants and predicates
│   └── secure_runner.py     ← SecureRunner: PTY bridge for sensitive commands
│
├── diagnostics/
│   ├── command_plan.py      ← plan builtin: advisory command classifier
│   ├── system_info.py       ← sys_info and env_audit helpers
│   └── trace.py             ← opt-in trace events, stages and redaction policy
│
└── contracts/               ← architecture protocol layer (Issue #3)
    ├── __init__.py          ← re-exports all protocol names
    └── protocols.py         ← typing.Protocol definitions; stdlib only
```

Current tree anchors for Issue #5/#6/#7 modules:
`core/errors.py`, `core/signals.py`, `security/policy.py`.

---

## Package responsibility table

| Package | Responsibility | Owns | Must not own |
| ------- | -------------- | ---- | ------------ |
| `pysh` | Package identity and version metadata | `__version__`, `__author__`, `LICENSE_NAME` | Runtime logic, imports |
| `pysh.__main__` | `python -m pysh` execution shim | Module-level `main()` call | Argument parsing, shell logic |
| `pysh.cli` | Console script entry point | Argument parsing, `--version`, `-c` flag, interactive REPL start | Shell execution, builtin dispatch |
| `pysh.core` | Main shell runtime | `PyShell` class, canonical exit/error contract, signal status helpers, builtin dispatch, pipeline execution | Parser primitives, editor rendering, config loading |
| `pysh.parsing` | Quote-aware text parsing and expansion helpers | Parser AST values, parse errors, lexical scanning, chain splitting, pipeline splitting, paste command splitting, multiline continuation, heredoc collection, variable/command substitution helpers, `RedirectionSpec`, redirection parsing and application | Shell state, command dispatch, editor rendering |
| `pysh.editor` | Interactive line editor (coordinator) | `Completer`, `HistoryManager`, `colors_enabled`, `diagnostic`, ANSI `paint` helper | Shell state, prompt rendering |
| `pysh.editor.lineedit` | Raw-mode terminal line editing engine | `RawLineReader`, `LineBuffer`, `LineHighlighter`, `AutoSuggester`, `KeyDecoder`, Completion Engine v1 | Higher-level shell concepts, history persistence |
| `pysh.prompt` | Prompt segment rendering | `colorize`, `color_to_hex`, `parse_color`, two-line prompt assembly, `system_profile` Debian helpers | Shell state, RC parsing |
| `pysh.python_layer` | Python command execution layer | `PythonRuntime` (persistent namespace), `py` builtin logic, `#py` interactive mode, Python syntax highlighting, `iter_logical_lines`, block detection | Shell builtins outside the Python layer, config loading |
| `pysh.config` | Configuration and startup | RC file execution, mini rc-interpreter, plugin directory loader, `ConfigAPI` (prompt/cursor/color settings) | Runtime command dispatch, builtin logic |
| `pysh.compat` | Transition and compatibility helpers | Zsh bridge (`ZshBridge`), zsh/sh alias file parser, static profile importer, MC environment detection | Core shell execution, prompt rendering |
| `pysh.services` | Service management | `svc` builtin client, PID-file-based service control, PyInit metadata parser | Shell REPL, command dispatch |
| `pysh.security` | Security-sensitive command execution | Trust constants/predicates, `SecureRunner` PTY bridge, fixed-size ring indicator, `indicator_config_from_mapping` | General command dispatch, shell state |
| `pysh.diagnostics` | Advisory diagnostics | `plan` builtin command classifier, opt-in trace event model, diagnostic redaction | Policy enforcement, runtime execution |
| `pysh.shell` | Compatibility shim (scheduled removal) | Re-export of `PyShell` from `pysh.core.shell` | Any new logic — shim only |
| `pysh.script_runner` | Script transition runner | `ScriptRunner`, shebang detection, interpreter delegation, native PySH line-by-line execution | Interactive REPL state |

---

## Module responsibility table

| Module | Primary responsibility |
| ------ | ---------------------- |
| `pysh.core.errors` | Canonical `ExitCode`, `PyShError`, and `Diagnostic` contract |
| `pysh.core.shell` | `PyShell` class: all builtin methods, REPL loop, pipeline and redirection execution, signal handling, Ctrl+C/Ctrl+D |
| `pysh.core.signals` | Signal return-code helpers and signal status helpers |
| `pysh.parsing.ast` | `ChainOp`, `ChainElement`: parser value objects |
| `pysh.parsing.errors` | `ParseError`, `UnsupportedSyntaxError`: parser-local diagnostics |
| `pysh.parsing.lexer` | Quote state, escape handling, comments, unquoted-marker detection |
| `pysh.parsing.grammar` | `split_chain`, `split_pipeline`, assignment parsing, unsupported syntax validation |
| `pysh.parsing.heredoc` | Here-document and here-string operator model, body collection, delimiter policy, and expansion policy |
| `pysh.parsing.expansion` | `$NAME`, `${NAME}`, `$?`, command substitution, unsupported parameter-expansion classification |
| `pysh.parsing.multiline` | Quote continuation, backslash-newline joining, Python block coalescing, paste command splitting |
| `pysh.parsing.parser` | Compatibility facade that re-exports the parser helper surface |
| `pysh.parsing.redirection` | `RedirectionSpec` dataclass; `parse_redirections`; file descriptor open/close |
| `pysh.contracts.builtins` | Canonical builtin-name data consumed by shell and completion |
| `pysh.editor.completion` | `Completer`: readline/raw-mode adapter over Completion Engine v1 |
| `pysh.editor.highlight` | `colors_enabled`, `diagnostic`, ANSI `paint`; terminal capability detection |
| `pysh.editor.history` | `HistoryManager`: `~/.pysh_history` persistence; readline integration |
| `pysh.editor.lineedit.reader` | `RawLineReader`: raw terminal mode, character loop, paste detection |
| `pysh.editor.lineedit.buffer` | `LineBuffer`: cursor management, display-width accounting |
| `pysh.editor.lineedit.highlight` | `LineHighlighter`: live token coloring; `ColorScheme` |
| `pysh.editor.lineedit.autosuggest` | `AutoSuggester`: history-backed ghost-text suggestions |
| `pysh.editor.lineedit.keys` | `KeyDecoder`: ANSI escape sequence decoding; `Key`, `KeyEvent` |
| `pysh.editor.lineedit.completion` | `CompletionEngine`, `CompletionContext`, `CompletionCandidate`, `CompletionResult`, `apply_single_completion`: PySH-native completion |
| `pysh.prompt.colors` | `colorize`, `color_to_hex`, `parse_color`: VGA + truecolor; `NO_COLOR` awareness |
| `pysh.prompt.system_profile` | `sys_info`, `env_audit`, `path_audit`, `which_all`, `apt_check`, `apt_search` |
| `pysh.python_layer.runtime` | `PythonRuntime`: `exec`/`eval` in persistent namespace; `py` builtin, multiline block logic |
| `pysh.python_layer.mode` | `#py` interactive Python command mode: REPL loop, directives, source buffer |
| `pysh.python_layer.highlighting` | `PythonSyntaxRenderer`, Pygments integration, `pygments_available` |
| `pysh.python_layer.render` | `PythonSyntaxRenderer` facade; rendering entry point |
| `pysh.config.rc` | `execute_rc`, `load_default_rc`: mini rc-interpreter, `if`/`for`/`while` |
| `pysh.config.plugins` | `load_plugins`: `~/.pyshrc.d/*.pysh` lexicographic loader |
| `pysh.config.api` | `ConfigAPI`: prompt segment, cursor color, ANSI scheme configuration |
| `pysh.compat.zsh_bridge` | `ZshBridge`: `zsh -lc` delegation, fallback mode |
| `pysh.compat.zsh_aliases` | `parse_zsh_aliases`: static alias file parser |
| `pysh.compat.profile_importer` | Static zsh/sh/bash profile importer: aliases, exports, assignments |
| `pysh.compat.mc` | `is_mc_environment`: Midnight Commander integration detection |
| `pysh.services.service` | `svc` client: `list`, `status`, `start`, `stop`, `restart` via PID files |
| `pysh.services.pyinit` | `ServiceMetadata`, `ServiceMetadataError`: PyInit `.service` file parser |
| `pysh.security.policy` | Trust constants and predicates for the Issue #7 security model |
| `pysh.security.secure_runner` | `SecureRunner`: PTY bridge; `indicator_config_from_mapping` |
| `pysh.diagnostics.command_plan` | `plan` function: advisory classifier for `plan <cmd>` builtin |
| `pysh.diagnostics.system_info` | System information helpers used by `sys_info` and `env_audit` |
| `pysh.diagnostics.trace` | `DiagnosticTrace`, canonical stages and redaction helpers for opt-in stderr trace output |
| `pysh.script_runner` | `ScriptRunner`, `ScriptType`: shebang dispatch and native line execution |

---

## Dependency direction

The following diagram shows the primary import relationships established by
Issue #2. Arrows indicate "imports from". Leaf packages do not import from
higher layers.

```text
pysh.__main__
    ↓
pysh.cli
    ↓
pysh.core.shell
    ├── pysh.parsing          (parser, redirection)
    ├── pysh.editor           (completion, highlight, history)
    │   └── pysh.editor.lineedit  (reader, buffer, highlight, autosuggest, keys)
    │       └── pysh.parsing  (split_paste_commands)
    ├── pysh.prompt           (colors, system_profile)
    ├── pysh.python_layer     (runtime, mode, render, highlighting)
    │   └── pysh.editor.lineedit  (lineedit primitives used by #py mode)
    ├── pysh.config           (api, rc, plugins)
    │   └── pysh.editor.lineedit.buffer  (_display_width)
    │   └── pysh.prompt.colors
    ├── pysh.compat           (mc, profile_importer, zsh_aliases, zsh_bridge)
    ├── pysh.services         (service, pyinit)
    ├── pysh.security         (secure_runner)
    │   └── pysh.prompt.colors
    ├── pysh.diagnostics      (command_plan, system_info)
    │   └── pysh.parsing
    └── pysh.script_runner
        └── pysh.parsing
```

**Key observations**:

- `pysh.core.shell` is the single fan-in point. All other packages are
  imported by core rather than importing core.
- `pysh.parsing` is a shared leaf: it is used by `core`, `editor.lineedit`,
  `diagnostics`, and `script_runner` — all without circularity.
- `pysh.editor.lineedit` is also shared: used by `core`, `python_layer`, and
  `config`. This reflects the editor engine serving multiple consumers.
- `pysh.prompt.colors` is used by `core`, `config`, and `security`.
- No circular imports exist as of the Issue #2 relocation.

---

## Public entrypoints

| Entrypoint | Module | Mechanism |
| ---------- | ------ | --------- |
| `pysh` CLI command | `pysh.cli:main` | `pyproject.toml` `[project.scripts]` |
| `python -m pysh` | `pysh.__main__` | Module `__main__.py` calls `pysh.cli:main` |

Both paths converge on `pysh.cli.main`, which constructs `pysh.core.shell.PyShell`
and enters the REPL or executes a `-c` command string.

---

## Internal package boundaries

Issue #3 turned the post-Issue #2 boundary model into active quality gates.
The current enforcement split is:

| Rule | Status |
| ---- | ------ |
| Import graph must not contain cycles | Hard gate in `tests/test_architecture_import_boundaries.py` |
| `pysh.contracts` must remain stdlib-only and isolated from implementation packages | Hard gate in `tests/test_architecture_import_boundaries.py` |
| Package `__init__.py` files must remain side-effect minimal | Hard gate in `tests/test_architecture_import_boundaries.py` |
| Cross-domain imports outside permitted fan-in/entrypoint paths | Ratcheted with documented known violations |
| `pysh.diagnostics` must remain advisory and must not execute commands | Architectural contract; covered by code review and focused tests |
| `pysh.editor.lineedit` must remain a self-contained editing engine | Architectural contract; cross-domain imports are ratcheted |

---

## Compatibility shim policy

`pysh.shell` is a single-line compatibility shim created by Issue #2:

```python
from pysh.core.shell import PyShell
__all__ = ["PyShell"]
```

It exists to avoid breaking any external code that imports from `pysh.shell`
directly. It carries no logic. Scheduled for removal as part of GitHub Issue
#19. No new code should import from `pysh.shell`.

---

## Legacy bytecode artifacts

Issue #2 moved `src/pysh/lineedit/` to `src/pysh/editor/lineedit/`. Python
bytecode caches (`__pycache__/`) from the pre-Issue #2 module path may still
exist at `src/pysh/lineedit/__pycache__/`. These are stale artifacts with no
effect on runtime behavior; they will be eliminated by the next
`git clean -xdf` or `find . -type d -name __pycache__ -exec rm -rf {} +`
maintenance pass. The source files themselves have been relocated by git.

---

## What is intentionally not part of Issue #2

Issue #2 is a **pure relocation refactor**. The following work is explicitly
deferred:

- No logic was changed, extracted, simplified, or merged.
- No import-boundary contracts were enforced.
- No circular imports were introduced or fixed (none exist).
- No new public APIs were created.
- No new packages were added beyond the domain subdirectory structure.
- The compatibility shim `pysh.shell` was created as a consequence, not a goal.

---

## Validation gates

The following quality gates apply to the post-Issue #2 source tree and must
pass before any commit on this branch:

| Gate | Command |
| ---- | ------- |
| Static analysis (lint + type-aware checks) | `uv run ruff check src tests` |
| Unit and integration tests | `uv run pytest -q` |
| Version banner | `uv run python -m pysh --version` |
| Entry point | `uv run pysh --version` |
| Inline execution | `uv run pysh -c 'echo hello'` |

All gates must show PASS before a release tag is applied.

---

## Architecture work status

| Issue | Scope | Status |
| ----- | ----- | ------ |
| Issue #2 | Source tree relocation into domain subpackages | **Completed** — this document |
| Issue #3 | Import-boundary contracts, protocol layer, ratchet, public API snapshot, cold-start budget | **Completed** — see [architecture.md](architecture.md) |
| Issue #6 | Signal-handling architecture: deterministic signal exit codes, terminal restoration, `returncode_to_exit_status()`. `pysh.security → pysh.prompt` violation retained — cleanup deferred to Issue #19. | Completed |
| Issue #7 | Security and trust model: execution surfaces, static import policy, sensitive input boundary, trust predicates | Completed |
| Issue #8 | Parser/expansion/multiline foundation; classifies `pysh.parsing` as a shared leaf for editor, diagnostics and script runner consumers | Implemented pending commit |
| Issue #14 | Script/config mode cleanup: resolves `pysh.config → pysh.python_layer` and finalizes script semantics | Open |
| Issue #19 | Remove the `pysh.shell` compatibility shim after all callers are updated | Open |

The import-boundary ratchet and cycle tests run in CI as of Issue #3.
New cross-package violations fail automatically.
