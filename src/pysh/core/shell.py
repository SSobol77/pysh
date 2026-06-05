# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Interactive shell implementation for PySH."""
from __future__ import annotations

import atexit
import locale
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import termios
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import IO

from pysh import LICENSE_NAME, __version__
from pysh.compat.mc import is_mc_environment
from pysh.compat.profile_importer import (
    analyze_compatibility_file,
    import_profile_file,
)
from pysh.compat.zsh_aliases import parse_zsh_aliases
from pysh.compat.zsh_bridge import ZshBridge
from pysh.compat.zsh_diagnostics import (
    detect_unsupported_zsh_syntax,
    is_zsh_config_path,
    zsh_config_file_diagnostic,
)
from pysh.config.api import (
    DEFAULT_CURSOR_OPTIONS,
    DEFAULT_EDITOR_OPTIONS,
    DEFAULT_PROMPT_COLOR_MODES,
    DEFAULT_PROMPT_COLORS,
    DEFAULT_PROMPT_OPTIONS,
    DEFAULT_SENSITIVE_INPUT,
    PYSHRC_PY_PATH,
    ensure_default_config,
    load_python_config,
    validate_cursor_color,
    validate_cursor_color_enabled,
    validate_editor_option,
    validate_prompt_color,
    validate_prompt_color_mode,
    validate_prompt_option,
    validate_sensitive_input,
)
from pysh.config.plugins import PLUGIN_DIR, load_plugins
from pysh.config.rc import RC_PATH, execute_rc, load_default_rc
from pysh.contracts.builtins import BUILTIN_NAMES
from pysh.core.errors import ExitCode
from pysh.core.jobs import (
    Job,
    JobStatus,
    JobTable,
    _raw_to_exit,
    has_job_control,
    make_child_preexec,
    open_tty,
    reset_child_job_control_signals,
    sigtstp_exit_status,
    tcsetpgrp_safely,
)
from pysh.core.signals import returncode_to_exit_status
from pysh.diagnostics.command_plan import plan as run_plan
from pysh.diagnostics.trace import DiagnosticStage, DiagnosticTrace
from pysh.editor.completion import Completer
from pysh.editor.highlight import colors_enabled, diagnostic
from pysh.editor.history import DEFAULT_HISTORY_PATH, HistoryManager
from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.reader import RawLineReader
from pysh.migration.script import (
    analyze_migration,
    analyze_migration_file,
    render_migration_report,
)
from pysh.parsing.heredoc import (
    HereDocBody,
    collect_heredoc_bodies,
    heredoc_line_matches,
    pending_heredoc_specs,
)
from pysh.parsing.parser import (
    ChainOp,
    ParseError,
    expand_command_substitution,
    expand_variables,
    join_backslash_continuations,
    parse_assignment,
    parse_leading_env_assignments,
    split_chain,
    split_pipeline,
    strip_comments,
    validate_unsupported_syntax,
)
from pysh.parsing.path_expansion import expand_tilde, tokenize_and_glob_expand
from pysh.parsing.redirection import RedirectionSpec, parse_redirections
from pysh.prompt.colors import color_to_hex, colorize, parse_color
from pysh.prompt.system_profile import (
    apt_check,
    apt_search,
    env_audit,
    path_audit,
    sys_info,
    which_all,
)
from pysh.prompt.terminal_style import (
    format_key_hints,
    frame_preview,
    highlight_python_preview_line,
    highlight_shell_preview_line,
    style,
    style_enabled,
)
from pysh.python_layer.runtime import (
    PythonRuntime,
    extract_block_body,
    is_block_closer,
    is_block_opener,
)
from pysh.script_runner import ScriptExit, ScriptRunner
from pysh.security.secure_runner import SecureRunner, indicator_config_from_mapping
from pysh.services.service import (
    DEFAULT_PID_ROOT,
    ServiceClient,
    ServiceError,
    format_list,
    format_status,
)


@dataclass(frozen=True)
class GitPromptInfo:
    """Minimal Git prompt metadata rendered without invoking ``git``."""

    label: str
    dirty: bool = False


@dataclass(frozen=True)
class ToolVersionSpec:
    """External tool version descriptor used by prompt rendering."""

    option: str
    executable: str
    label_prefix: str
    cache_attr: str


TOOL_VERSION_SPECS: tuple[ToolVersionSpec, ...] = (
    ToolVersionSpec("show_uv_version", "uv", "uv", "_uv_version_cache"),
    ToolVersionSpec("show_ruff_version", "ruff", "ruff", "_ruff_version_cache"),
    ToolVersionSpec("show_rust_version", "rustc", "rust", "_rust_version_cache"),
    ToolVersionSpec("show_node_version", "node", "node", "_node_version_cache"),
    ToolVersionSpec("show_npm_version", "npm", "npm", "_npm_version_cache"),
)

_UNSET = object()
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _osc_set_cursor_color(hex_color: str) -> str:
    """Return OSC 12 sequence that requests terminal cursor color."""
    return f"\x1b]12;{hex_color}\x07"


def _osc_reset_cursor_color() -> str:
    """Return OSC 112 sequence that requests terminal cursor color reset."""
    return "\x1b]112\x07"


class _ExitShell(Exception):
    """Raised by the ``exit``/``quit`` builtins to terminate the shell loop."""

    def __init__(self, code: int = 0) -> None:
        super().__init__()
        self.code = code


def _tilde_expand_spec(spec: RedirectionSpec) -> RedirectionSpec:
    """Apply tilde expansion to all file paths in a :class:`RedirectionSpec`.

    Glob expansion is intentionally NOT applied to redirection targets to
    prevent unsafe multi-target behavior (e.g., ``> *.out`` must not redirect
    to multiple files).  Only ``~`` and ``~user`` are expanded.
    """
    return RedirectionSpec(
        stdin_path=expand_tilde(spec.stdin_path) if spec.stdin_path else None,
        stdin_data=spec.stdin_data,
        stdout_path=expand_tilde(spec.stdout_path) if spec.stdout_path else None,
        stdout_append=spec.stdout_append,
        stderr_path=expand_tilde(spec.stderr_path) if spec.stderr_path else None,
        stderr_append=spec.stderr_append,
        stderr_to_stdout=spec.stderr_to_stdout,
    )


def _write_execution_stderr(
    message: str,
    spec: RedirectionSpec,
    *,
    stdout_stream: IO[bytes] | None = None,
    stderr_stream: IO[bytes] | None = None,
) -> None:
    """Write an in-process execution diagnostic through command redirection."""
    data = f"{message}\n".encode()
    if spec.stderr_to_stdout and stdout_stream is not None:
        stdout_stream.write(data)
        stdout_stream.flush()
        return
    if stderr_stream is not None:
        stderr_stream.write(data)
        stderr_stream.flush()
        return
    print(message, file=sys.stderr)


class PyShell:
    """Python-first interactive shell with full Unix command support."""

    DEFAULT_ALIASES: dict[str, str] = {
        "ls": "ls --color=auto -F",
        "ll": "ls --color=auto -laF",
        "grep": "grep --color=auto",
        "df": "df -h",
        "free": "free -h",
    }

    BUILTINS: frozenset[str] = BUILTIN_NAMES

    HISTORY_PATH: Path = DEFAULT_HISTORY_PATH

    # ------------------------------------------------------------ construction
    def __init__(
        self,
        *,
        pid_root: Path | None = None,
        service_client: ServiceClient | None = None,
        zsh_bridge: ZshBridge | None = None,
        script_runner: ScriptRunner | None = None,
        trace: DiagnosticTrace | None = None,
    ) -> None:
        self.local_vars: dict[str, str] = {}
        self.aliases: dict[str, str] = dict(self.DEFAULT_ALIASES)
        self.last_status: int = 0
        self.trace = trace if trace is not None else DiagnosticTrace()
        self.script_name: str = ""
        self.script_args: list[str] = []
        self._script_context: tuple[Path, int] | None = None
        self.pending_multiline_paste: str | None = None
        self._executing_paste: bool = False
        self.dir_stack: list[Path] = []
        self.job_table: JobTable = JobTable()
        self._tty_fd: int | None = None
        self.prompt_options: dict[str, object] = dict(DEFAULT_PROMPT_OPTIONS)
        self.prompt_colors: dict[str, str] = dict(DEFAULT_PROMPT_COLORS)
        self.prompt_color_modes: dict[str, object] = dict(DEFAULT_PROMPT_COLOR_MODES)
        self.editor_options: dict[str, object] = dict(DEFAULT_EDITOR_OPTIONS)
        self.cursor_options: dict[str, object] = dict(DEFAULT_CURSOR_OPTIONS)
        self._cursor_color_applied = False
        self._mc_auto_warning_emitted = False
        # Read only by the explicit secure <cmd> PTY wrapper. Normal command
        # execution, prompt rendering and line editing do not consult it.
        self.sensitive_input: dict[str, object] = dict(DEFAULT_SENSITIVE_INPUT)
        for spec in TOOL_VERSION_SPECS:
            setattr(self, spec.cache_attr, _UNSET)
        self.completer = Completer(
            lambda: list(self.aliases.keys()),
            get_locals=lambda: dict(self.local_vars),
            get_job_ids=lambda: [job.job_id for job in self.job_table.all_jobs() if job.is_alive()],
        )
        self.history = HistoryManager(self.HISTORY_PATH)
        self.autosuggester = AutoSuggester()
        self.line_highlighter = LineHighlighter(self.BUILTINS)
        self.line_reader = RawLineReader()
        self.zsh_bridge = zsh_bridge if zsh_bridge is not None else ZshBridge()
        self.zsh_fallback_enabled = os.environ.get("PYSH_ZSH_FALLBACK") == "1"
        self.python_runtime = PythonRuntime()
        self.script_runner = (
            script_runner if script_runner is not None else ScriptRunner(
                self._execute_script_line,
                before_execute=self._before_script_line,
            )
        )
        if service_client is not None:
            self.service_client = service_client
        else:
            self.service_client = ServiceClient(
                pid_root if pid_root is not None else DEFAULT_PID_ROOT,
            )

    # ------------------------------------------------------------------- run
    def run(self) -> int:
        """Start the interactive shell loop."""
        self._print_banner()
        self._setup_readline()
        self._export_interactive_shell_vars()
        load_default_rc(self.execute)
        load_plugins(self.execute, directory=PLUGIN_DIR)
        # Python-native configuration runs last so that ~/.pyshrc.py has the
        # final word over the legacy shell-syntax layers. Created on first
        # launch so the file is discoverable; the generated body is inert.
        if ensure_default_config():
            print(f"pysh: created {PYSHRC_PY_PATH}")
        load_python_config(self)
        self._apply_cursor_color()
        # Job control: open /dev/tty and set SIGTSTP to SIG_IGN so the shell
        # itself is never suspended by Ctrl+Z; the foreground child resets it.
        if self._stdio_is_tty():
            self._tty_fd = open_tty()
            if has_job_control():
                try:
                    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
                except OSError:
                    pass
        try:
            while True:
                # Reap completed background jobs before showing the prompt.
                self._reap_and_notify_jobs()
                try:
                    info_line = self._prompt_info_line()
                    if self._should_use_raw_editor() and self.line_reader.has_queued_commands():
                        info_line = ""
                    if info_line and not is_mc_environment():
                        sys.stdout.write(info_line + "\n")
                        sys.stdout.flush()
                    line = self._read_interactive_line()
                except EOFError:
                    print()
                    return 0
                except KeyboardInterrupt:
                    print()
                    if self.pending_multiline_paste is not None:
                        self.pending_multiline_paste = None
                        self.line_reader.clear_command_queue()
                        self._executing_paste = False
                        enabled = style_enabled()
                        print(style("paste_cancel: pending multiline paste discarded", "warning", enabled=enabled))
                    else:
                        self.line_reader.clear_command_queue()
                    self.last_status = ExitCode.SIGINT
                    continue
                if self.pending_multiline_paste is not None:
                    if not line.strip():
                        try:
                            self.last_status = self._builtin_paste_run([])
                        except _ExitShell as exit_signal:
                            return exit_signal.code
                        continue
                    if self._pending_paste_command_allowed(line):
                        try:
                            self.last_status = self.execute(line)
                            self.history.add(line)
                        except _ExitShell as exit_signal:
                            return exit_signal.code
                        continue
                    print(
                        style(
                            "pysh: pending multiline paste exists; use paste_run or paste_cancel first",
                            "error",
                            enabled=style_enabled(),
                        ),
                        file=sys.stderr,
                    )
                    self.last_status = ExitCode.BUILTIN_MISUSE
                    continue
                if not line.strip():
                    continue
                if is_block_opener(line):
                    collected = self._collect_block_interactive(line)
                    if collected is None:
                        continue
                    line = collected
                elif pending_heredoc_specs(line):
                    collected = self._collect_heredoc_interactive(line)
                    if collected is None:
                        continue
                    line = collected
                try:
                    self.last_status = self.execute(line)
                    self.history.add(line)
                except _ExitShell as exit_signal:
                    return exit_signal.code
        finally:
            self._reset_cursor_color()
            self._save_history()
            # Clean up tty fd and restore SIGTSTP.
            if self._tty_fd is not None:
                try:
                    os.close(self._tty_fd)
                except OSError:
                    pass
                self._tty_fd = None
            if has_job_control():
                try:
                    signal.signal(signal.SIGTSTP, signal.SIG_DFL)
                except OSError:
                    pass

    def _collect_block_interactive(self, opener: str) -> str | None:
        """Read continuation lines until the ``py { ... }`` block closes.

        Returns the joined multi-line block text, or ``None`` if collection
        was cancelled by the user (Ctrl+C or EOF).
        """
        collected: list[str] = [opener]
        try:
            while True:
                try:
                    cont = self._read_multiline_interactive_line(self._continuation_prompt())
                except EOFError:
                    print()
                    print("pysh: py: unterminated block", file=sys.stderr)
                    self.last_status = 1
                    return None
                except KeyboardInterrupt:
                    print()
                    self.last_status = 130
                    return None
                if is_block_opener(cont):
                    print("pysh: py: nested py { ... } blocks are not supported", file=sys.stderr)
                    self.last_status = 1
                    return None
                collected.append(cont)
                if is_block_closer(cont):
                    return "\n".join(collected)
        finally:
            collected.clear()

    def _collect_heredoc_interactive(self, command_line: str) -> str | None:
        """Read heredoc body lines until all pending delimiters are seen."""
        try:
            specs = pending_heredoc_specs(command_line)
        except ParseError as exc:
            print(f"pysh: parse error: {exc}", file=sys.stderr)
            self.last_status = ExitCode.BUILTIN_MISUSE
            return None
        collected: list[str] = [command_line]
        try:
            for spec in specs:
                while True:
                    try:
                        line = self._read_multiline_interactive_line(self._heredoc_prompt())
                    except EOFError:
                        print()
                        print(
                            f"pysh: parse error: missing heredoc terminator: {spec.delimiter}",
                            file=sys.stderr,
                        )
                        self.last_status = ExitCode.BUILTIN_MISUSE
                        return None
                    except KeyboardInterrupt:
                        print()
                        self.last_status = ExitCode.SIGINT
                        return None
                    collected.append(line)
                    if heredoc_line_matches(line, spec):
                        break
            return "\n".join(collected)
        finally:
            collected.clear()

    def _read_multiline_interactive_line(self, prompt: str) -> str:
        """Read one collector-owned continuation line through the active editor."""
        if self._should_use_raw_editor():
            options = SimpleNamespace(autosuggest=False, syntax_highlight=False)
            try:
                return self.line_reader.read_line(
                    prompt,
                    history=[],
                    suggester=self.autosuggester,
                    highlighter=self.line_highlighter,
                    scheme=DEFAULT_SCHEME,
                    options=options,
                    echo_queued=False,
                )
            except (OSError, termios.error):
                return input(prompt)
        return input(prompt)

    @staticmethod
    def _continuation_prompt() -> str:
        return "py> "

    @staticmethod
    def _heredoc_prompt() -> str:
        return "heredoc> "

    # --------------------------------------------------------------- execute
    def run_script_file(
        self,
        path: Path,
        args: list[str],
        *,
        native_only: bool = False,
    ) -> int:
        """Run a script file with script positional parameters installed."""
        previous_name = self.script_name
        previous_args = list(self.script_args)
        previous_context = self._script_context
        self.script_name = str(path)
        self.script_args = list(args)
        self._script_context = None
        try:
            status = self.script_runner.run(path, args, native_only=native_only)
            self.last_status = status
            return status
        finally:
            self.script_name = previous_name
            self.script_args = previous_args
            self._script_context = previous_context

    def _before_script_line(self, path: Path, line_number: int, command: str) -> None:
        self._script_context = (path, line_number)
        self.trace.emit(
            DiagnosticStage.INPUT,
            "script line",
            file=str(path),
            line=line_number,
            command=command,
        )

    def _execute_script_line(self, line: str) -> int:
        try:
            return self.execute(line)
        except _ExitShell as exc:
            raise ScriptExit(exc.code) from exc

    def _capture_multiline_paste(self, payload: str) -> list[str]:
        """Store sanitized bracketed multiline paste for explicit user action."""
        enabled = style_enabled()
        diagnostics: list[str] = []
        if self.pending_multiline_paste is not None:
            diagnostics.append(
                style("pysh: previous pending paste replaced", "warning", enabled=enabled)
            )
        self.pending_multiline_paste = payload
        count = self._pending_multiline_paste_line_count()
        diagnostics.append(
            style(
                f"pysh: multiline paste captured ({count} lines). Review below.",
                "warning",
                enabled=enabled,
            )
        )
        diagnostics.extend(
            self._format_pending_paste_preview(
                payload,
                title="paste",
                max_lines=20,
                enabled=enabled,
                highlighter=self._make_paste_line_highlighter(payload, enabled=enabled),
            )
        )
        diagnostics.append(
            format_key_hints(
                [
                    ("Enter", "run"),
                    ("Ctrl+C", "cancel"),
                    ("paste_show", "inspect"),
                    ("paste_cancel", "discard"),
                ],
                enabled=enabled,
            )
        )
        return diagnostics

    @staticmethod
    def _format_pending_paste_preview(
        payload: str,
        *,
        title: str,
        max_lines: int | None = 20,
        enabled: bool = False,
        highlighter: Callable[[str, int], str] | None = None,
    ) -> list[str]:
        """Return a numbered, optionally styled and highlighted preview."""
        return frame_preview(
            payload,
            title,
            enabled=enabled,
            max_lines=max_lines,
            line_highlighter=highlighter,
        )

    def _pending_multiline_paste_line_count(self) -> int:
        """Return the user-visible line count for the pending paste payload."""
        if self.pending_multiline_paste is None:
            return 0
        return len(self.pending_multiline_paste.splitlines()) or 1

    def _make_paste_line_highlighter(
        self,
        payload: str,
        *,
        enabled: bool,
    ) -> Callable[[str, int], str] | None:
        """Return a per-line syntax highlighter for paste preview, or None.

        Detects payload type (shell, Python block, heredoc) and returns a
        closure that highlights each line accordingly.

        Shell lines use the safe shell highlighter from terminal_style (not
        the editor.highlight pipeline, which uses dark-blue for variables and
        can render as black blocks on dark-theme terminals).  Python block
        lines use the lightweight Python highlighter in terminal_style.
        """
        if not enabled:
            return None
        lines = payload.splitlines() or [""]
        n = len(lines)
        is_py = n >= 2 and is_block_opener(lines[0]) and is_block_closer(lines[-1])
        has_heredoc = n >= 2 and "<<" in lines[0]
        heredoc_term = self._heredoc_terminator_from_opener(lines[0]) if has_heredoc else ""

        def highlighter(ln: str, idx: int) -> str:
            if is_py:
                if idx == 0 or idx == n - 1:
                    return highlight_shell_preview_line(ln, enabled=True)
                return highlight_python_preview_line(ln, enabled=True)
            if has_heredoc:
                if idx == 0:
                    return highlight_shell_preview_line(ln, enabled=True)
                if heredoc_term and ln.strip() == heredoc_term:
                    return f"\033[90m{ln}\033[0m"  # muted gray terminator line
                return ln  # heredoc body: plain text, no styling needed
            return highlight_shell_preview_line(ln, enabled=True)

        return highlighter

    @staticmethod
    def _heredoc_terminator_from_opener(opener: str) -> str:
        """Extract the heredoc terminator word from an opener line.

        Handles ``<<'EOF'``, ``<<EOF``, ``<<-EOF``, ``<<"EOF"``, and
        ``<<< word`` forms.  Returns empty string if not parseable.
        """
        m = re.search(r"<<[-]?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", opener)
        return m.group(1) if m else ""

    @staticmethod
    def _pending_paste_command_allowed(line: str) -> bool:
        """Return whether *line* may run while multiline paste is pending."""
        try:
            argv = shlex.split(line, posix=True)
        except ValueError:
            return False
        return bool(argv) and argv[0] in {"paste_show", "paste_run", "paste_cancel"}

    def execute(self, line: str) -> int:
        """Execute one shell line. Returns the exit status of the last command."""
        line = line.rstrip("\n").rstrip("\r")
        trace_fields: dict[str, object] = {"line": line}
        if self._script_context is not None:
            script_file, script_line = self._script_context
            trace_fields["file"] = str(script_file)
            trace_fields["script_line"] = script_line
        self.trace.emit(DiagnosticStage.INPUT, "received line", **trace_fields)
        line = join_backslash_continuations(line)
        # ``#py`` must be checked *before* strip_comments() because a bare ``#``
        # at the start of a token-boundary is otherwise treated as a comment.
        if line.strip() == "#py":
            return self._enter_python_mode()
        if self._is_python_block_text(line):
            return self._run_python_block(line)
        direct_migration_status = self._execute_inline_migrate_if_needed(line)
        if direct_migration_status is not None:
            return direct_migration_status
        try:
            line, heredoc_bodies = collect_heredoc_bodies(
                line,
                self.local_vars,
                special_vars=self._special_vars(),
            )
        except ParseError as exc:
            self.trace.error(
                "heredoc parse error",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        self.trace.emit(DiagnosticStage.HEREDOC, "collected heredocs", count=len(heredoc_bodies))
        line = strip_comments(line)
        if not line.strip():
            return 0
        zsh_diagnostic = detect_unsupported_zsh_syntax(line)
        if zsh_diagnostic is not None:
            print(zsh_diagnostic.message, file=sys.stderr)
            print(zsh_diagnostic.hint, file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        try:
            validate_unsupported_syntax(line)
        except ParseError as exc:
            self.trace.error(
                "unsupported syntax",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE

        # Multi-line ``py { ... }`` block: execute its body in the persistent
        # Python runtime context. We accept either a fully collected block
        # text (joined by ``\n``) or a bare ``py {`` line which is a usage
        # error in single-line execution mode.
        if self._is_python_block_text(line):
            return self._run_python_block(line)
        if is_block_opener(line.strip()) and "\n" not in line:
            print(
                "pysh: py: unterminated py { ... } block",
                file=sys.stderr,
            )
            return 2

        # Apply command substitution before anything else so the substituted
        # text participates in chain splitting, alias expansion, etc.
        line = expand_command_substitution(line)

        py_code = self._extract_direct_py_code(line)
        if py_code is not None:
            return self._run_python_code(py_code)

        # Bare ``NAME=value`` assignment.
        if self._is_bare_assignment(line):
            return self._assign_local(line)

        try:
            chain = split_chain(line)
        except ParseError as exc:
            self.trace.error(
                "split chain failed",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        self.trace.emit(DiagnosticStage.PARSE, "split chain", elements=len(chain))
        status = 0
        run_next = True
        for elem in chain:
            if run_next:
                is_background = elem.operator is ChainOp.BACKGROUND
                status = self._run_chain_element(
                    elem.command, heredoc_bodies, background=is_background
                )
                self.last_status = status
            if elem.operator is ChainOp.AND:
                run_next = status == 0
            elif elem.operator is ChainOp.OR:
                run_next = status != 0
            else:
                # SEMI, BACKGROUND, or None: always run next element.
                run_next = True
        return status

    # ------------------------------------------------------------- internals
    def _run_chain_element(
        self,
        command: str,
        heredoc_bodies: list[HereDocBody] | None = None,
        *,
        background: bool = False,
    ) -> int:
        try:
            stages = split_pipeline(command)
        except ParseError as exc:
            self.trace.error(
                "split pipeline failed",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        if not stages:
            return 0
        self.trace.emit(DiagnosticStage.PARSE, "split pipeline", stages=len(stages))
        # Alias expansion is applied per simple command (i.e. per pipe stage).
        stages = [self._expand_alias(s) for s in stages]
        # Variable expansion happens after alias expansion so that alias
        # bodies behave like literal text but user variables in arguments
        # are still substituted.  $? is passed as a special variable so it
        # expands to the last command exit status (Issue #5).
        _sv = self._special_vars()
        stages = [expand_variables(s, self.local_vars, special_vars=_sv) for s in stages]
        self.trace.emit(DiagnosticStage.EXPAND, "expanded variables", stages=len(stages))
        if len(stages) == 1:
            return self._run_simple(stages[0], heredoc_bodies, background=background)
        if not heredoc_bodies:
            return self._run_pipeline(stages, original_command=command, background=background)
        return self._run_pipeline(
            stages,
            original_command=command,
            heredoc_bodies=heredoc_bodies,
            background=background,
        )

    def _run_simple(
        self,
        stage: str,
        heredoc_bodies: list[HereDocBody] | None = None,
        *,
        background: bool = False,
    ) -> int:
        try:
            clean, spec = parse_redirections(stage, heredoc_bodies)
        except ParseError as exc:
            self.trace.error(
                "parse redirections failed",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        self.trace.emit(
            DiagnosticStage.REDIRECT,
            "parsed redirections",
            stdin=bool(spec.stdin_path or spec.stdin_data),
            stdout=bool(spec.stdout_path),
            stderr=bool(spec.stderr_path or spec.stderr_to_stdout),
        )
        # Tilde expansion on redirection targets (glob expansion is not applied
        # to redirection targets to avoid unsafe multi-target behavior).
        spec = _tilde_expand_spec(spec)
        try:
            argv = tokenize_and_glob_expand(clean, cwd=Path(os.getcwd()))
        except ValueError as exc:
            if self.zsh_fallback_enabled:
                return self._run_zsh_fallback(stage)
            self.trace.error(
                "path expansion failed",
                detail=str(exc),
                code=ExitCode.BUILTIN_MISUSE,
            )
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return 2
        if not argv:
            return 0
        self.trace.emit(DiagnosticStage.PATH_EXPAND, "tokenized argv", argc=len(argv))
        self.trace.emit(DiagnosticStage.EXECUTE_PLAN, "argv prepared", argv=argv)
        env_overrides, cmd_argv = parse_leading_env_assignments(argv)
        if not cmd_argv:
            # All tokens are assignments with no command: update local vars.
            for name, value in env_overrides.items():
                self.local_vars[name] = value
            return 0
        if cmd_argv[0] in self.BUILTINS:
            # Builtins run in-process; background flag has no effect for builtins.
            self.trace.emit(
                DiagnosticStage.RESOLVE,
                "command resolved",
                command=cmd_argv[0],
                kind="builtin",
            )
            status = self._dispatch_builtin(cmd_argv)
            self.trace.emit(DiagnosticStage.EXECUTE_PLAN, "command finished", status=status)
            return status
        resolved_path = shutil.which(cmd_argv[0])
        self.trace.emit(
            DiagnosticStage.RESOLVE,
            "command resolved",
            command=cmd_argv[0],
            kind="external" if resolved_path is not None else "missing",
            path=resolved_path or "",
        )
        status = self._run_external(
            cmd_argv,
            spec,
            original_stage=stage,
            env_overrides=env_overrides if env_overrides else None,
            background=background,
        )
        self.trace.emit(DiagnosticStage.EXECUTE_PLAN, "command finished", status=status)
        return status

    def _run_pipeline(
        self,
        stages: list[str],
        *,
        original_command: str,
        heredoc_bodies: list[HereDocBody] | None = None,
        background: bool = False,
    ) -> int:
        parsed: list[tuple[list[str], RedirectionSpec, dict[str, str] | None]] = []
        remaining_heredocs = heredoc_bodies if heredoc_bodies is not None else []
        for s in stages:
            try:
                clean, spec = parse_redirections(s, remaining_heredocs)
            except ParseError as exc:
                print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
                return ExitCode.BUILTIN_MISUSE
            spec = _tilde_expand_spec(spec)
            try:
                argv = tokenize_and_glob_expand(clean, cwd=Path(os.getcwd()))
            except ValueError as exc:
                print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
                return 2
            if not argv:
                print("pysh: syntax error near unexpected '|'", file=sys.stderr)
                return 2
            env_overrides, argv = parse_leading_env_assignments(argv)
            if not argv:
                print("pysh: syntax error: assignment without command before '|'", file=sys.stderr)
                return 2
            parsed.append((argv, spec, env_overrides if env_overrides else None))

        procs: list[subprocess.Popen[bytes]] = []
        opened: list[IO[bytes]] = []
        prev_out: IO[bytes] | None = None
        pipeline_pgid: int | None = None
        jc_available = has_job_control()

        try:
            for i, (argv, spec, env_overrides) in enumerate(parsed):
                is_first = i == 0
                is_last = i == len(parsed) - 1

                child_env: dict[str, str] | None = None
                if env_overrides:
                    child_env = dict(os.environ)
                    child_env.update(env_overrides)

                stdin_arg: IO[bytes] | int | None
                if spec.stdin_path:
                    f = open(spec.stdin_path, "rb")
                    opened.append(f)
                    stdin_arg = f
                elif spec.stdin_data is not None:
                    f = tempfile.TemporaryFile("w+b")
                    f.write(spec.stdin_data)
                    f.seek(0)
                    opened.append(f)
                    stdin_arg = f
                elif is_first:
                    stdin_arg = None
                else:
                    stdin_arg = prev_out

                stdout_arg: IO[bytes] | int | None
                if spec.stdout_path:
                    f = open(spec.stdout_path, "ab" if spec.stdout_append else "wb")
                    opened.append(f)
                    stdout_arg = f
                elif is_last:
                    stdout_arg = None
                else:
                    stdout_arg = subprocess.PIPE

                stderr_arg: IO[bytes] | int | None
                diagnostic_stdout: IO[bytes] | None = None
                diagnostic_stderr: IO[bytes] | None = None
                if spec.stderr_to_stdout:
                    stderr_arg = subprocess.STDOUT
                    diagnostic_stdout = stdout_arg if hasattr(stdout_arg, "write") else None
                elif spec.stderr_path:
                    f = open(spec.stderr_path, "ab" if spec.stderr_append else "wb")
                    opened.append(f)
                    stderr_arg = f
                    diagnostic_stderr = f
                else:
                    stderr_arg = None

                # Build preexec_fn for process-group assignment.
                preexec_fn: Callable[[], None] | None = None
                if jc_available:
                    if is_first:
                        preexec_fn = make_child_preexec
                    else:
                        # Subsequent stages join the first process's group.
                        _target_pgid = pipeline_pgid
                        def _join_pgid(pgid: int = _target_pgid) -> None:  # type: ignore[assignment]
                            os.setpgid(0, pgid)
                            reset_child_job_control_signals()
                        preexec_fn = _join_pgid

                try:
                    proc = subprocess.Popen(  # noqa: S603 - user-issued command
                        argv,
                        env=child_env,
                        stdin=stdin_arg,
                        stdout=stdout_arg,
                        stderr=stderr_arg,
                        preexec_fn=preexec_fn,
                    )
                except FileNotFoundError:
                    if self.zsh_fallback_enabled and argv[0] not in self.BUILTINS:
                        if prev_out is not None:
                            prev_out.close()
                        for p in procs:
                            p.terminate()
                            p.wait()
                        return self._run_zsh_fallback(original_command)
                    self.trace.error(
                        "command not found",
                        command=argv[0],
                        code=ExitCode.COMMAND_NOT_FOUND,
                    )
                    _write_execution_stderr(
                        f"pysh: {argv[0]}: command not found",
                        spec,
                        stdout_stream=diagnostic_stdout,
                        stderr_stream=diagnostic_stderr,
                    )
                    if prev_out is not None:
                        prev_out.close()
                    for p in procs:
                        p.terminate()
                        p.wait()
                    return ExitCode.COMMAND_NOT_FOUND

                if is_first and jc_available:
                    pipeline_pgid = proc.pid
                if jc_available and pipeline_pgid is not None:
                    try:
                        os.setpgid(proc.pid, pipeline_pgid)
                    except OSError:
                        pass

                # The parent must close the read end of the previous pipe so
                # that the child receives EOF after the upstream stage exits.
                if prev_out is not None:
                    prev_out.close()
                prev_out = proc.stdout
                procs.append(proc)

            if not procs:
                return ExitCode.SUCCESS

            pids = [p.pid for p in procs]
            pgid = pipeline_pgid or (procs[0].pid if procs else 0)

            if background:
                # Register as background job; do not wait.
                job = self.job_table.add_job(
                    pgid, original_command, pids, background=True
                )
                print(f"[{job.job_id}] {pids[-1]}", flush=True)
                return ExitCode.SUCCESS

            # Foreground pipeline: give terminal, wait, restore terminal.
            tty_fd = self._tty_fd
            if tty_fd is not None and pgid:
                if not tcsetpgrp_safely(tty_fd, pgid):
                    tty_fd = None

            try:
                results = [p.wait() for p in procs]
            except KeyboardInterrupt:
                for p in procs:
                    try:
                        p.terminate()
                    except OSError:
                        pass
                results = [p.wait() for p in procs]
                return ExitCode.SIGINT
            finally:
                if tty_fd is not None:
                    tcsetpgrp_safely(tty_fd, os.getpgrp())

            return returncode_to_exit_status(results[-1]) if results else ExitCode.SUCCESS
        finally:
            for f in opened:
                try:
                    f.close()
                except OSError:
                    pass
            if prev_out is not None:
                try:
                    prev_out.close()
                except OSError:
                    pass

    def _run_external(
        self,
        argv: list[str],
        spec: RedirectionSpec,
        *,
        original_stage: str | None = None,
        env_overrides: dict[str, str] | None = None,
        background: bool = False,
    ) -> int:
        child_env: dict[str, str] | None = None
        if env_overrides:
            child_env = dict(os.environ)
            child_env.update(env_overrides)
        stdin_f: IO[bytes] | None = None
        stdout_f: IO[bytes] | None = None
        stderr_f: IO[bytes] | None = None
        stderr_arg: IO[bytes] | int | None

        jc_available = has_job_control()
        preexec_fn: Callable[[], None] | None = make_child_preexec if jc_available else None

        try:
            if spec.stdin_path:
                stdin_f = open(spec.stdin_path, "rb")
            elif spec.stdin_data is not None:
                stdin_f = tempfile.TemporaryFile("w+b")
                stdin_f.write(spec.stdin_data)
                stdin_f.seek(0)
            if spec.stdout_path:
                stdout_f = open(spec.stdout_path, "ab" if spec.stdout_append else "wb")
            if spec.stderr_to_stdout:
                stderr_arg = subprocess.STDOUT
            elif spec.stderr_path:
                stderr_f = open(spec.stderr_path, "ab" if spec.stderr_append else "wb")
                stderr_arg = stderr_f
            else:
                stderr_arg = None
            try:
                proc = subprocess.Popen(  # noqa: S603 - user-issued command
                    argv,
                    env=child_env,
                    stdin=stdin_f,
                    stdout=stdout_f,
                    stderr=stderr_arg,
                    preexec_fn=preexec_fn,
                )
            except FileNotFoundError:
                if self.zsh_fallback_enabled and original_stage is not None:
                    return self._run_zsh_fallback(original_stage)
                self.trace.error(
                    "command not found",
                    command=argv[0],
                    code=ExitCode.COMMAND_NOT_FOUND,
                )
                _write_execution_stderr(
                    f"pysh: {argv[0]}: command not found",
                    spec,
                    stdout_stream=stdout_f,
                    stderr_stream=stderr_f,
                )
                return ExitCode.COMMAND_NOT_FOUND
            except PermissionError as exc:
                self.trace.error(
                    "command not executable",
                    command=argv[0],
                    code=ExitCode.CANNOT_EXECUTE,
                )
                print(f"pysh: {argv[0]}: {exc}", file=sys.stderr)
                return ExitCode.CANNOT_EXECUTE

            pgid = proc.pid
            cmd_text = original_stage or " ".join(argv)
            if jc_available:
                try:
                    os.setpgid(proc.pid, pgid)
                except OSError:
                    pass

            if background:
                # Register as background job; return immediately.
                job = self.job_table.add_job(pgid, cmd_text, [proc.pid], background=True)
                print(f"[{job.job_id}] {proc.pid}", flush=True)
                return ExitCode.SUCCESS

            # Foreground: give terminal to child's process group.
            tty_fd = self._tty_fd
            if tty_fd is not None:
                if not tcsetpgrp_safely(tty_fd, pgid):
                    tty_fd = None

            try:
                if jc_available and hasattr(os, "WUNTRACED"):
                    # Use os.waitpid with WUNTRACED to detect Ctrl+Z stops.
                    # Falls back to proc.wait() when pid is unavailable
                    # (e.g., test environments that mock subprocess.Popen).
                    try:
                        _, raw_status = os.waitpid(proc.pid, os.WUNTRACED)
                    except ChildProcessError:
                        # pid not a real child (mock or already reaped).
                        try:
                            return returncode_to_exit_status(proc.wait())
                        except KeyboardInterrupt:
                            proc.terminate()
                            proc.wait()
                            return ExitCode.SIGINT
                    except (TypeError, ValueError, OSError):
                        # proc.pid not usable as a pid (e.g., mock object).
                        try:
                            return returncode_to_exit_status(proc.wait())
                        except KeyboardInterrupt:
                            proc.terminate()
                            proc.wait()
                            return ExitCode.SIGINT
                    except KeyboardInterrupt:
                        try:
                            os.killpg(pgid, signal.SIGINT)
                        except OSError:
                            pass
                        try:
                            os.waitpid(proc.pid, 0)
                        except OSError:
                            pass
                        return ExitCode.SIGINT
                    if hasattr(os, "WIFSTOPPED") and os.WIFSTOPPED(raw_status):
                        # Child stopped by Ctrl+Z (SIGTSTP).
                        job = self.job_table.add_job(
                            pgid, cmd_text, [proc.pid], background=False
                        )
                        self.job_table.mark_stopped(job.job_id)
                        print(
                            f"\n[{job.job_id}]+ Stopped     {cmd_text}",
                            file=sys.stderr,
                        )
                        return sigtstp_exit_status()
                    return _raw_to_exit(raw_status)
                else:
                    try:
                        return returncode_to_exit_status(proc.wait())
                    except KeyboardInterrupt:
                        proc.terminate()
                        proc.wait()
                        return ExitCode.SIGINT
            finally:
                if tty_fd is not None:
                    tcsetpgrp_safely(tty_fd, os.getpgrp())
        except OSError as exc:
            print(f"pysh: {exc}", file=sys.stderr)
            return ExitCode.GENERAL_ERROR
        finally:
            for f in (stdin_f, stdout_f, stderr_f):
                if f is not None:
                    try:
                        f.close()
                    except OSError:
                        pass

    # ------------------------------------------------------------- builtins
    def _dispatch_builtin(self, argv: list[str]) -> int:
        name = argv[0]
        args = argv[1:]
        handlers: dict[str, Callable[[list[str]], int]] = {
            "cd": self._builtin_cd,
            "pwd": self._builtin_pwd,
            "alias": self._builtin_alias,
            "unalias": self._builtin_unalias,
            "export": self._builtin_export,
            "source": self._builtin_source,
            ".": self._builtin_source,
            "exit": self._builtin_exit,
            "quit": self._builtin_exit,
            "pushd": self._builtin_pushd,
            "popd": self._builtin_popd,
            "dirs": self._builtin_dirs,
            "jobs": self._builtin_jobs,
            "fg": self._builtin_fg,
            "bg": self._builtin_bg,
            "svc": self._builtin_svc,
            "source_zsh": self._builtin_source_zsh,
            "source_zsh_profile": self._builtin_source_zsh_profile,
            "source_sh_aliases": self._builtin_source_sh_aliases,
            "run_script": self._builtin_run_script,
            "compat_check": self._builtin_compat_check,
            "zsh": self._builtin_zsh,
            "zsh_fallback": self._builtin_zsh_fallback,
            "py": self._builtin_py,
            "sys_info": self._builtin_sys_info,
            "env_audit": self._builtin_env_audit,
            "path_audit": self._builtin_path_audit,
            "paste_show": self._builtin_paste_show,
            "paste_cancel": self._builtin_paste_cancel,
            "paste_run": self._builtin_paste_run,
            "which_all": self._builtin_which_all,
            "apt_check": self._builtin_apt_check,
            "apt_search": self._builtin_apt_search,
            "plan": self._builtin_plan,
            "secure": self._builtin_secure,
            "mc": self._builtin_mc,
            "command": self._builtin_command,
            "migrate": self._builtin_migrate,
        }
        handler = handlers.get(name)
        if handler is None:
            print(f"pysh: {name}: not a builtin", file=sys.stderr)
            return 1
        return handler(args)

    def _builtin_cd(self, args: list[str]) -> int:
        target = args[0] if args else str(Path.home())
        target = os.path.expanduser(target)
        try:
            os.chdir(target)
            return 0
        except OSError as exc:
            print(f"cd: {exc}", file=sys.stderr)
            return 1

    def _builtin_pwd(self, _args: list[str]) -> int:
        print(os.getcwd())
        return 0

    def _builtin_alias(self, args: list[str]) -> int:
        if not args:
            for name in sorted(self.aliases):
                print(f"alias {name}={shlex.quote(self.aliases[name])}")
            return 0
        status = 0
        for token in args:
            assignment = parse_assignment(token)
            if assignment:
                name, raw = assignment
                value = self._unquote_value(raw)
                self.aliases[name] = value
            elif token in self.aliases:
                print(f"alias {token}={shlex.quote(self.aliases[token])}")
            else:
                print(f"alias: {token}: not found", file=sys.stderr)
                status = 1
        return status

    def _builtin_unalias(self, args: list[str]) -> int:
        if not args:
            print("unalias: usage: unalias name [name ...]", file=sys.stderr)
            return 2
        status = 0
        for name in args:
            if name in self.aliases:
                del self.aliases[name]
            else:
                print(f"unalias: {name}: not found", file=sys.stderr)
                status = 1
        return status

    def _builtin_export(self, args: list[str]) -> int:
        if not args:
            for key in sorted(os.environ):
                print(f"export {key}={shlex.quote(os.environ[key])}")
            return 0
        for token in args:
            assignment = parse_assignment(token)
            if assignment:
                name, raw = assignment
                value = self._unquote_value(raw)
                os.environ[name] = value
                # Keep local_vars in sync so that ${NAME} expansion sees it.
                self.local_vars[name] = value
                if name == "PYSH_ZSH_FALLBACK":
                    self.zsh_fallback_enabled = value == "1"
            else:
                if token in self.local_vars:
                    os.environ[token] = self.local_vars[token]
                    if token == "PYSH_ZSH_FALLBACK":
                        self.zsh_fallback_enabled = self.local_vars[token] == "1"
                else:
                    os.environ.setdefault(token, "")
        return 0

    def _builtin_command(self, args: list[str]) -> int:
        """Run or resolve a command with alias expansion suppressed."""
        if not args:
            print("command: usage: command [-v|-V] name [args ...]", file=sys.stderr)
            return 2

        if args[0] in {"-v", "-V"}:
            if len(args) == 1:
                print(f"command: {args[0]}: name argument required", file=sys.stderr)
                return 2
            verbose = args[0] == "-V"
            status = 0
            for name in args[1:]:
                if not self._print_command_resolution(name, verbose=verbose):
                    if verbose:
                        print(f"pysh: command: {name}: not found", file=sys.stderr)
                    status = 1
            return status

        if args[0].startswith("-"):
            print(f"command: unsupported option: {args[0]}", file=sys.stderr)
            return 2

        name = args[0]
        if name == "command":
            return self._builtin_command(args[1:])
        if name in self.BUILTINS:
            return self._dispatch_builtin(args)
        return self._run_external(args, RedirectionSpec(), original_stage=" ".join(args))

    def _print_command_resolution(self, name: str, *, verbose: bool) -> bool:
        """Print POSIX-style command resolution details for ``command -v/-V``."""
        if name in self.BUILTINS:
            print(f"{name} is a PySH builtin" if verbose else name)
            return True
        alias = self.aliases.get(name)
        if alias is not None:
            if verbose:
                print(f"{name} is an alias for {shlex.quote(alias)}")
            else:
                print(f"alias {name}={shlex.quote(alias)}")
            return True
        path = shutil.which(name)
        if path is not None:
            print(f"{name} is {path}" if verbose else path)
            return True
        return False

    def _builtin_source(self, args: list[str]) -> int:
        if not args:
            print("source: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        if is_zsh_config_path(str(target)):
            diagnostic_info = zsh_config_file_diagnostic(str(target))
            print(diagnostic_info.message, file=sys.stderr)
            print(diagnostic_info.hint, file=sys.stderr)
            return 2
        return execute_rc(target, self.execute, quiet_missing=False)

    def _builtin_source_zsh(self, args: list[str]) -> int:
        if not args:
            print("source_zsh: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"source_zsh: {target}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"source_zsh: {target}: {exc}", file=sys.stderr)
            return 1
        result = parse_zsh_aliases(text)
        self.aliases.update(result.aliases)
        for diagnostic_info in result.diagnostics:
            print(
                f"source_zsh: {target}:{diagnostic_info.line_number}: "
                f"malformed alias: {diagnostic_info.message}",
                file=sys.stderr,
            )
        print(f"imported={result.imported} skipped={result.skipped} file={target}")
        return 0

    def _builtin_source_zsh_profile(self, args: list[str]) -> int:
        if not args:
            print("source_zsh_profile: filename argument required", file=sys.stderr)
            return 2
        return self._import_static_profile("source_zsh_profile", Path(os.path.expanduser(args[0])))

    def _builtin_source_sh_aliases(self, args: list[str]) -> int:
        if not args:
            print("source_sh_aliases: filename argument required", file=sys.stderr)
            return 2
        return self._import_static_profile("source_sh_aliases", Path(os.path.expanduser(args[0])))

    def _builtin_run_script(self, args: list[str]) -> int:
        if not args:
            print("run_script: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        return self.run_script_file(target, args[1:], native_only=False)

    def _builtin_paste_show(self, args: list[str]) -> int:
        if args:
            print("paste_show: usage: paste_show", file=sys.stderr)
            return 2
        if self.pending_multiline_paste is None:
            print("paste_show: no pending multiline paste")
            return 2
        enabled = style_enabled()
        payload = self.pending_multiline_paste
        for line in self._format_pending_paste_preview(
            payload,
            title="paste",
            max_lines=None,
            enabled=enabled,
            highlighter=self._make_paste_line_highlighter(payload, enabled=enabled),
        ):
            print(line)
        return 0

    def _builtin_paste_cancel(self, args: list[str]) -> int:
        if args:
            print("paste_cancel: usage: paste_cancel", file=sys.stderr)
            return 2
        if self.pending_multiline_paste is None:
            print("paste_cancel: no pending multiline paste")
            return 2
        self.pending_multiline_paste = None
        self.line_reader.clear_command_queue()
        self._executing_paste = False
        enabled = style_enabled()
        print(style("paste_cancel: pending multiline paste discarded", "warning", enabled=enabled))
        return 0

    def _builtin_paste_run(self, args: list[str]) -> int:
        if args:
            print("paste_run: usage: paste_run", file=sys.stderr)
            return 2
        if self.pending_multiline_paste is None:
            print("paste_run: no pending multiline paste")
            return 2
        payload = self.pending_multiline_paste
        self.pending_multiline_paste = None
        enabled = style_enabled()
        for line in self._format_pending_paste_preview(
            payload,
            title="paste_run",
            max_lines=None,
            enabled=enabled,
            highlighter=self._make_paste_line_highlighter(payload, enabled=enabled),
        ):
            print(line)
        previous_context = self._script_context
        self._script_context = None
        self._executing_paste = True
        try:
            status = self.script_runner.run_native_text(payload, name="<paste>")
            self.last_status = status
            return status
        finally:
            self.pending_multiline_paste = None
            self.line_reader.clear_command_queue()
            self._executing_paste = False
            self._script_context = previous_context

    def _builtin_compat_check(self, args: list[str]) -> int:
        if not args:
            print("compat_check: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        try:
            report = analyze_compatibility_file(target)
        except FileNotFoundError:
            print(f"compat_check: {target}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"compat_check: {target}: {exc}", file=sys.stderr)
            return 1

        print(f"file={target}")
        print(
            f"supported={report.supported} delegated={report.delegated} "
            f"skipped={report.skipped} risky={report.risky}"
        )
        for finding in report.findings:
            print(
                f"line={finding.line_number} kind={finding.kind} "
                f"action={finding.action.value}"
            )
        return 2 if report.risky else 0

    def _execute_inline_migrate_if_needed(self, line: str) -> int | None:
        """Run ``migrate`` before normal shell expansion can execute input."""
        stripped = line.strip()
        if not (stripped == "migrate" or stripped.startswith("migrate ")):
            return None
        try:
            argv = shlex.split(stripped, posix=True)
        except ValueError as exc:
            print(f"migrate: parse error: {exc}", file=sys.stderr)
            return 2
        if not argv or argv[0] != "migrate":
            return None
        return self._builtin_migrate(argv[1:])

    def _builtin_migrate(self, args: list[str]) -> int:
        if not args:
            print("migrate: usage: migrate FILE | migrate --text TEXT", file=sys.stderr)
            return 2
        if args[0] in {"--text", "-c"}:
            if len(args) < 2:
                print("migrate: --text requires shell content", file=sys.stderr)
                return 2
            text = " ".join(args[1:])
            report = analyze_migration(text, source="<inline>")
            print(render_migration_report(report))
            return 0
        if args[0].startswith("-"):
            print(f"migrate: unsupported option: {args[0]}", file=sys.stderr)
            return 2
        if len(args) != 1 and args[0].startswith("$("):
            args = [" ".join(args)]
        if len(args) != 1:
            print("migrate: usage: migrate FILE | migrate --text TEXT", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        try:
            report = analyze_migration_file(target)
        except FileNotFoundError:
            print(f"migrate: {target}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"migrate: {target}: {exc}", file=sys.stderr)
            return 1
        print(render_migration_report(report))
        return 0

    def _builtin_zsh(self, args: list[str]) -> int:
        if not args:
            print("zsh: command argument required", file=sys.stderr)
            return 2
        return self._run_zsh_command(" ".join(args))

    def _builtin_zsh_fallback(self, args: list[str]) -> int:
        if len(args) != 1 or args[0] not in {"on", "off"}:
            print("zsh_fallback: usage: zsh_fallback {on|off}", file=sys.stderr)
            return 2
        self.zsh_fallback_enabled = args[0] == "on"
        self.local_vars["PYSH_ZSH_FALLBACK"] = "1" if self.zsh_fallback_enabled else "0"
        return 0

    def _builtin_py(self, args: list[str]) -> int:
        if not args:
            print("py: code argument required", file=sys.stderr)
            return 2
        return self._run_python_code(" ".join(args))

    # ---------------------------------------------------------- system profile
    def _builtin_sys_info(self, _args: list[str]) -> int:
        return sys_info()

    def _builtin_env_audit(self, _args: list[str]) -> int:
        return env_audit()

    def _builtin_path_audit(self, _args: list[str]) -> int:
        return path_audit()

    def _builtin_which_all(self, args: list[str]) -> int:
        if not args:
            print("which_all: usage: which_all <command>", file=sys.stderr)
            return 2
        return which_all(args[0])

    def _builtin_apt_check(self, _args: list[str]) -> int:
        return apt_check()

    def _builtin_apt_search(self, args: list[str]) -> int:
        if not args:
            print("apt_search: usage: apt_search <query>", file=sys.stderr)
            return 2
        return apt_search(" ".join(args))

    # ---------------------------------------------------------- command planning
    def _builtin_plan(self, args: list[str]) -> int:
        return run_plan(args, builtins=self.BUILTINS)

    def _builtin_secure(self, args: list[str]) -> int:
        if not args:
            print("secure: usage: secure <command> [args ...]", file=sys.stderr)
            return 2
        config = indicator_config_from_mapping(
            self.sensitive_input,
            vga=bool(self.prompt_color_modes.get("vga", True)),
        )
        return SecureRunner(config).run(args)

    def _builtin_mc(self, args: list[str]) -> int:
        """Launch Midnight Commander with PySH-aware subshell policy."""
        mc_path = shutil.which("mc")
        if mc_path is None:
            print("mc: external Midnight Commander executable not found", file=sys.stderr)
            return 127

        mode = str(self.editor_options.get("mc_integration", "auto"))
        mc_args = list(args)
        if mode in {"auto", "safe"}:
            mc_args = self._mc_safe_args(mc_args)
            if self._should_warn_for_mc_auto(args, mode):
                print(
                    "pysh mc: MC does not support PySH as a live Ctrl+O subshell; "
                    "launching with subshell disabled (-u). Ctrl+O will only show "
                    "the previous screen, not an active PySH prompt.",
                    file=sys.stderr,
                )
                self._mc_auto_warning_emitted = True
        elif mode not in {"off", "subshell"}:
            print(f"mc: invalid mc_integration mode: {mode}", file=sys.stderr)
            return 2

        return self._run_external(
            [mc_path, *mc_args],
            RedirectionSpec(),
            original_stage=" ".join(["mc", *args]),
        )

    @staticmethod
    def _mc_args_disable_subshell(args: list[str]) -> bool:
        """Return True when MC args already request no concurrent subshell."""
        return any(arg in {"-u", "--nosubshell"} for arg in args)

    def _should_warn_for_mc_auto(self, args: list[str], mode: str) -> bool:
        """Return True when auto mode should emit the MC no-subshell warning."""
        return (
            mode == "auto"
            and bool(self.editor_options.get("mc_warning_enabled", True))
            and not self._mc_auto_warning_emitted
            and not self._mc_args_disable_subshell(args)
        )

    @classmethod
    def _mc_safe_args(cls, args: list[str]) -> list[str]:
        """Return MC argv with concurrent subshell disabled deterministically."""
        filtered = [arg for arg in args if arg not in {"-U", "--subshell"}]
        if cls._mc_args_disable_subshell(filtered):
            return filtered
        return ["-u", *filtered]

    def _builtin_exit(self, args: list[str]) -> int:
        code = 0
        if args:
            try:
                code = int(args[0])
            except ValueError:
                print(f"exit: {args[0]}: numeric argument required", file=sys.stderr)
                code = 2
        raise _ExitShell(code)

    # ---------------------------------------------------------- directory stack
    def _builtin_pushd(self, args: list[str]) -> int:
        if not args:
            print("pushd: usage: pushd <directory>", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        if not target.is_dir():
            print(f"pushd: {args[0]}: not a directory", file=sys.stderr)
            return 1
        current = Path.cwd()
        try:
            os.chdir(target)
        except OSError as exc:
            print(f"pushd: {exc}", file=sys.stderr)
            return 1
        self.dir_stack.append(current)
        self._builtin_dirs([])
        return 0

    def _builtin_popd(self, _args: list[str]) -> int:
        if not self.dir_stack:
            print("popd: directory stack empty", file=sys.stderr)
            return 1
        target = self.dir_stack.pop()
        try:
            os.chdir(target)
        except OSError as exc:
            print(f"popd: {exc}", file=sys.stderr)
            return 1
        self._builtin_dirs([])
        return 0

    def _builtin_dirs(self, _args: list[str]) -> int:
        entries = [self._format_path(Path.cwd())]
        for entry in reversed(self.dir_stack):
            entries.append(self._format_path(entry))
        print(" ".join(entries))
        return 0

    @staticmethod
    def _format_path(path: Path) -> str:
        home = Path.home()
        try:
            rel = path.relative_to(home)
            if str(rel) == ".":
                return "~"
            return "~/" + str(rel)
        except ValueError:
            return str(path)

    # ----------------------------------------------------------------- job control
    def _builtin_jobs(self, _args: list[str]) -> int:
        """List tracked background and stopped jobs."""
        self._reap_and_notify_jobs()
        output = self.job_table.format_jobs()
        if output:
            print(output)
        # Done jobs are removed after being displayed once.
        self.job_table.remove_done()
        return 0

    def _builtin_fg(self, args: list[str]) -> int:
        """Bring a job to the foreground."""
        if not args:
            job = self.job_table.get_current_job()
            if job is None:
                print("fg: no current job", file=sys.stderr)
                return 1
        else:
            job = self._resolve_job_arg(args, "fg")
            if job is None:
                return 1
        print(job.command_text)

        tty_fd = self._tty_fd
        if tty_fd is not None and job.pgid > 0:
            if not tcsetpgrp_safely(tty_fd, job.pgid):
                tty_fd = None

        if job.status == JobStatus.STOPPED and job.pgid > 0:
            try:
                os.killpg(job.pgid, signal.SIGCONT)
            except OSError:
                pass
        self.job_table.mark_running(job.job_id)

        try:
            return self._wait_for_job(job)
        finally:
            if tty_fd is not None:
                tcsetpgrp_safely(tty_fd, os.getpgrp())

    def _builtin_bg(self, args: list[str]) -> int:
        """Resume a stopped job in the background."""
        if not args:
            job = self.job_table.get_current_job()
            if job is None:
                print("bg: no current job", file=sys.stderr)
                return 1
        else:
            job = self._resolve_job_arg(args, "bg")
            if job is None:
                return 1
        if job.status != JobStatus.STOPPED:
            print(f"bg: [{job.job_id}] job is not stopped", file=sys.stderr)
            return 1
        if job.pgid > 0:
            try:
                os.killpg(job.pgid, signal.SIGCONT)
            except OSError as exc:
                print(f"bg: [{job.job_id}] {exc}", file=sys.stderr)
                return 1
        self.job_table.mark_running(job.job_id)
        job.background = True
        print(f"[{job.job_id}]+ {job.command_text} &", flush=True)
        return 0

    def _resolve_job_arg(self, args: list[str], builtin: str) -> Job | None:
        """Return the job referenced by ``args``, or the current job if no args.

        Returns None on lookup failure; the caller handles the error message.
        """
        if not args:
            return self.job_table.get_current_job()
        raw = args[0]
        if raw.startswith("%"):
            raw = raw[1:]
        try:
            job_id = int(raw)
        except ValueError:
            print(f"{builtin}: {args[0]}: no such job", file=sys.stderr)
            return None
        job = self.job_table.get_job(job_id)
        if job is None:
            print(f"{builtin}: {job_id}: no such job", file=sys.stderr)
        return job

    def _wait_for_job(self, job: Job) -> int:
        """Wait for *job* to finish or stop.  Returns PySH exit status."""
        exit_status = 0
        try:
            for pid in list(job.pids):
                try:
                    _, raw_status = os.waitpid(pid, getattr(os, "WUNTRACED", 0))
                except ChildProcessError:
                    continue
                if hasattr(os, "WIFSTOPPED") and os.WIFSTOPPED(raw_status):
                    self.job_table.mark_stopped(job.job_id)
                    print(
                        f"\n[{job.job_id}]+ Stopped     {job.command_text}",
                        file=sys.stderr,
                    )
                    return sigtstp_exit_status()
                exit_status = _raw_to_exit(raw_status)
        except KeyboardInterrupt:
            if job.pgid > 0:
                try:
                    os.killpg(job.pgid, signal.SIGINT)
                except OSError:
                    pass
            for pid in list(job.pids):
                try:
                    os.waitpid(pid, 0)
                except OSError:
                    pass
            self.job_table.mark_done(job.job_id, ExitCode.SIGINT)
            return ExitCode.SIGINT
        self.job_table.mark_done(job.job_id, exit_status)
        return exit_status

    def _reap_and_notify_jobs(self) -> None:
        """Non-blocking reap of completed background jobs with notifications."""
        reaped = self.job_table.reap_background_jobs()
        for job, status in reaped:
            label = "Done" if status == 0 else f"Done({status})"
            print(f"[{job.job_id}]  {label:<12}{job.command_text}", file=sys.stderr)

    # ----------------------------------------------------------------- svc
    def _builtin_svc(self, args: list[str]) -> int:
        if not args:
            print("svc: usage: svc {list|status|start|stop|restart} [name]", file=sys.stderr)
            return 2
        action = args[0]
        rest = args[1:]
        try:
            if action == "list":
                print(format_list(self.service_client.list_services()))
                return 0
            if action in {"status", "stop", "restart", "start"}:
                if not rest:
                    print(f"svc: {action}: service name required", file=sys.stderr)
                    return 2
                name = rest[0]
                if action == "status":
                    print(format_status(self.service_client.status(name)))
                    return 0
                if action == "stop":
                    status = self.service_client.stop(name)
                    print(format_status(status))
                    return 0
                if action == "restart":
                    status = self.service_client.restart(name)
                    print(format_status(status))
                    return 0
                status = self.service_client.start(name)
                print(format_status(status))
                return 0
            print(f"svc: {action}: unknown action", file=sys.stderr)
            return 2
        except ServiceError as exc:
            print(f"svc: {exc}", file=sys.stderr)
            return 1

    # ------------------------------------------------------------- helpers
    def _import_static_profile(self, command: str, target: Path) -> int:
        try:
            result = import_profile_file(target)
        except FileNotFoundError:
            print(f"{command}: {target}: file not found", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"{command}: {target}: {exc}", file=sys.stderr)
            return 1

        self.aliases.update(result.aliases)
        for name, value in result.variables.items():
            self.local_vars[name] = value
            if name == "PYSH_ZSH_FALLBACK":
                self.zsh_fallback_enabled = value == "1"
        for name, value in result.exports.items():
            os.environ[name] = value
            self.local_vars[name] = value
            if name == "PYSH_ZSH_FALLBACK":
                self.zsh_fallback_enabled = value == "1"
        print(
            f"aliases={len(result.aliases)} exports={len(result.exports)} "
            f"vars={len(result.variables)} skipped={result.skipped} file={target}"
        )
        return 0

    def _is_bare_assignment(self, line: str) -> bool:
        stripped = line.strip()
        if not parse_assignment(stripped):
            return False
        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError:
            return False
        return len(tokens) == 1

    def _assign_local(self, line: str) -> int:
        assignment = parse_assignment(line.strip())
        assert assignment is not None
        name, raw = assignment
        expanded = expand_variables(raw, self.local_vars)
        value = self._unquote_value(expanded)
        self.local_vars[name] = value
        if name == "PYSH_ZSH_FALLBACK":
            self.zsh_fallback_enabled = value == "1"
        return 0

    def _enter_python_mode(self) -> int:
        """Start an interactive Python command mode session.

        Imported lazily to keep shell startup fast and avoid circular imports.
        ``PythonCommandMode`` creates its own runtime so Python-mode variables
        are independent from the ``py``-builtin runtime.
        """
        from pysh.python_layer.mode import PythonCommandMode  # noqa: PLC0415
        mode = PythonCommandMode(cwd_provider=Path.cwd)
        return mode.run()

    def _run_zsh_command(self, command: str) -> int:
        result = self.zsh_bridge.execute(command)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    def _run_zsh_fallback(self, command: str) -> int:
        return self._run_zsh_command(command)

    def _run_python_code(self, code: str) -> int:
        return self.python_runtime.execute(code)

    def _run_python_block(self, text: str) -> int:
        try:
            body = extract_block_body(text)
        except ValueError as exc:
            print(f"pysh: py: {exc}", file=sys.stderr)
            return 2
        return self.python_runtime.execute_block(body)

    def _special_vars(self) -> dict[str, str]:
        special = {"?": str(self.last_status)}
        if self.script_name:
            special["0"] = self.script_name
            special["#"] = str(len(self.script_args))
            joined_args = " ".join(self.script_args)
            special["@"] = joined_args
            special["*"] = joined_args
            for index, value in enumerate(self.script_args, start=1):
                special[str(index)] = value
        return special

    @staticmethod
    def _is_python_block_text(text: str) -> bool:
        if "\n" not in text:
            return False
        lines = text.split("\n")
        if not is_block_opener(lines[0]):
            return False
        return is_block_closer(lines[-1])

    @staticmethod
    def _extract_direct_py_code(line: str) -> str | None:
        stripped = line.lstrip()
        if stripped == "py":
            return None
        if not stripped.startswith("py") or len(stripped) == 2:
            return None
        if stripped[2] not in " \t":
            return None
        return stripped[3:].lstrip()

    def _unquote_value(self, raw: str) -> str:
        try:
            parts = shlex.split(raw, posix=True)
        except ValueError:
            return raw
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return " ".join(parts)

    def _paste_error_label(self) -> str:
        return "parse error (paste)" if self._executing_paste else "parse error"

    def _expand_alias(self, command: str) -> str:
        leading_ws = len(command) - len(command.lstrip())
        body = command[leading_ws:]
        first, rest = self._split_first_word(body)
        if not first:
            return command
        try:
            parts = shlex.split(first, posix=True)
        except ValueError:
            return command
        if not parts:
            return command
        name = parts[0]
        if name not in self.aliases:
            return command
        return command[:leading_ws] + self.aliases[name] + rest

    @staticmethod
    def _split_first_word(text: str) -> tuple[str, str]:
        in_single = False
        in_double = False
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if in_single:
                if c == "'":
                    in_single = False
                i += 1
                continue
            if in_double:
                if c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\", "$", "`"):
                    i += 2
                    continue
                if c == '"':
                    in_double = False
                i += 1
                continue
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "'":
                in_single = True
                i += 1
                continue
            if c == '"':
                in_double = True
                i += 1
                continue
            if c in " \t":
                break
            i += 1
        return text[:i], text[i:]

    # ----------------------------------------------- python config surface
    # These methods implement the ConfigurableShell protocol consumed by
    # config_api.ShellConfigAPI. They are the only mutation points exposed to
    # ~/.pyshrc.py and mirror the semantics of the equivalent builtins.
    def register_alias(self, name: str, value: str) -> None:
        """Register or replace an alias (ConfigurableShell contract)."""
        self.aliases[name] = value

    def set_environment(self, name: str, value: str) -> None:
        """Export an environment variable and mirror it into local vars.

        Mirrors the behaviour of the ``export NAME=value`` builtin so that
        ``$NAME`` / ``${NAME}`` expansion sees the value immediately.
        """
        os.environ[name] = value
        self.local_vars[name] = value
        if name == "PYSH_ZSH_FALLBACK":
            self.zsh_fallback_enabled = value == "1"

    def set_prompt_option(self, name: str, value: object) -> None:
        """Set a validated prompt option (ConfigurableShell contract).

        Validation is enforced here as well as in the public API so the
        contract holds for any direct caller. Raises ``ValueError`` (via
        ``ConfigError``) on an unknown name or wrong value type.
        """
        validate_prompt_option(name, value)
        self.prompt_options[name] = value

    def set_editor_option(self, name: str, value: object) -> None:
        """Set a validated line editor option (ConfigurableShell contract)."""
        validate_editor_option(name, value)
        self.editor_options[name] = value

    def set_mc_integration(self, value: str) -> None:
        """Set Midnight Commander integration mode (ConfigurableShell contract)."""
        validate_editor_option("mc_integration", value)
        self.editor_options["mc_integration"] = value

    def set_mc_warning_enabled(self, value: bool) -> None:
        """Enable or disable MC auto-mode warning (ConfigurableShell contract)."""
        validate_editor_option("mc_warning_enabled", value)
        self.editor_options["mc_warning_enabled"] = value

    def set_prompt_color(self, segment: str, color: str) -> None:
        """Set a validated prompt segment color (ConfigurableShell contract)."""
        validate_prompt_color(segment, color)
        self.prompt_colors[segment] = color

    def set_prompt_color_mode(self, name: str, value: object) -> None:
        """Set a validated prompt color mode (ConfigurableShell contract)."""
        validate_prompt_color_mode(name, value)
        self.prompt_color_modes[name] = value

    def set_cursor_color_enabled(self, value: bool) -> None:
        """Set validated terminal cursor color enable state."""
        validate_cursor_color_enabled(value)
        self.cursor_options["enabled"] = value

    def set_cursor_color(self, color: str) -> None:
        """Set validated terminal cursor color as canonical uppercase hex."""
        validate_cursor_color(color)
        self.cursor_options["color"] = color_to_hex(color)

    def set_sensitive_input_indicator(self, name: str, value: object) -> None:
        """Store a validated sensitive-input option (ConfigurableShell contract).

        Only the explicit ``secure <cmd>`` builtin reads this storage. The
        REPL, raw line editor, prompt rendering, and normal external-command
        path do not consult it. PySH never intercepts, counts, stores or logs
        password bytes for ordinary commands; those are owned by the child
        process and the terminal. See ``docs/security-sensitive-input.md``.
        """
        validate_sensitive_input(name, value)
        self.sensitive_input[name] = value

    def _apply_cursor_color(self) -> None:
        """Apply configured terminal cursor color when the terminal gate allows it."""
        if self._cursor_color_applied:
            return
        if not bool(self.cursor_options.get("enabled", False)):
            return
        if not self._cursor_color_terminal_enabled():
            return
        color = color_to_hex(str(self.cursor_options.get("color", "orange")))
        try:
            sys.stdout.write(_osc_set_cursor_color(color))
            sys.stdout.flush()
        except (OSError, ValueError):
            return
        self._cursor_color_applied = True
        atexit.register(self._reset_cursor_color)

    def _reset_cursor_color(self) -> None:
        """Reset terminal cursor color if this shell applied it."""
        if not self._cursor_color_applied:
            return
        try:
            sys.stdout.write(_osc_reset_cursor_color())
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        self._cursor_color_applied = False

    @staticmethod
    def _cursor_color_terminal_enabled() -> bool:
        if "NO_COLOR" in os.environ:
            return False
        term = os.environ.get("TERM", "")
        if not term or term == "dumb":
            return False
        try:
            return sys.stdout.isatty()
        except (AttributeError, ValueError):
            return False

    # ------------------------------------------------------------- presentation
    def _read_interactive_line(self) -> str:
        """Read one interactive command line via raw editor or readline."""
        if self._should_use_raw_editor():
            options = self._resolved_editor_options()
            try:
                return self.line_reader.read_line(
                    self._prompt(),
                    history=self.history.entries(),
                    suggester=self.autosuggester,
                    highlighter=self.line_highlighter,
                    scheme=DEFAULT_SCHEME,
                    options=options,
                    on_multiline_paste=self._capture_multiline_paste,
                    completer=self.completer,
                    paste_pending=self.pending_multiline_paste is not None,
                )
            except (OSError, termios.error):
                return input(self._prompt())
        return input(self._prompt())

    def _should_use_raw_editor(self) -> bool:
        """Return True when the configured editor may use raw TTY mode.

        Returns False in Midnight Commander environments (mc-safe mode) so
        that PySH uses ``input()`` instead of the ANSI-repainting raw editor.
        This prevents cursor-placement corruption when MC manages the terminal.

        Crucially, this check is intentionally independent of colors_enabled()
        and NO_COLOR.  Color preferences must never affect bracketed-paste mode,
        paste staging, or execution behaviour.  Only terminal capability (TERM
        not dumb/empty, stdin/stdout are TTYs) determines raw-editor eligibility.
        """
        mode = str(self.editor_options.get("line_editor", "auto"))
        if mode == "readline":
            return False
        if not self._stdio_is_tty():
            return False
        if is_mc_environment():
            return False
        if mode == "auto" and not self._raw_editor_terminal_capable():
            return False
        return mode in {"auto", "basic"}

    @staticmethod
    def _raw_editor_terminal_capable() -> bool:
        """Return True when TERM indicates a VT-style capable terminal.

        Dumb terminals and unset TERM cannot handle the ANSI cursor sequences
        the raw editor emits.  NO_COLOR and color-related variables are
        intentionally not consulted here.
        """
        term = os.environ.get("TERM", "")
        return bool(term) and term != "dumb"

    def _resolved_editor_options(self) -> SimpleNamespace:
        mode = str(self.editor_options.get("line_editor", "auto"))
        if mode == "basic":
            return SimpleNamespace(autosuggest=False, syntax_highlight=False)
        return SimpleNamespace(
            autosuggest=bool(self.editor_options.get("autosuggest", True)),
            syntax_highlight=bool(self.editor_options.get("syntax_highlight", True)),
        )

    @staticmethod
    def _stdio_is_tty() -> bool:
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except ValueError:
            return False

    def _prompt_body(self, options: dict[str, object]) -> str:
        """Build the informational portion shared by both prompt layouts.

        Order: optional virtualenv, icon, identity/current-directory, optional
        Git segment, optional Python version, optional tool versions, and
        optional non-zero last status. The returned string contains no trailing
        symbol and no newline, so it can be used safely either inline or as a
        separate info line before readline receives the command-line prompt.
        """
        segments: list[str] = []

        if bool(options.get("show_virtualenv", False)):
            virtualenv = self._prompt_virtualenv()
            if virtualenv:
                segments.append(self._color_prompt_segment(f"({virtualenv})", "venv"))

        segments.append(self._color_prompt_segment(self._prompt_icon(), "icon"))

        identity_segments = self._prompt_identity_segments(options)
        show_cwd = bool(options.get("show_cwd", True))
        cwd_str = self._prompt_cwd_with_style(options) if show_cwd else ""
        if identity_segments and cwd_str:
            identity = "".join(
                self._color_prompt_segment(text, role) for text, role in identity_segments
            )
            segments.append(f"{identity}:{self._color_prompt_segment(cwd_str, 'cwd')}")
        elif identity_segments:
            segments.append(
                "".join(
                    self._color_prompt_segment(text, role) for text, role in identity_segments
                )
            )
        elif cwd_str:
            segments.append(self._color_prompt_segment(cwd_str, "cwd"))

        git_segment = self._prompt_git_segment(options)
        if git_segment:
            segments.append(self._color_prompt_segment(git_segment, "git"))

        if bool(options.get("show_python_version", False)):
            py = ".".join(str(p) for p in sys.version_info[:2])
            segments.append(self._color_prompt_segment(f"py{py}", "python"))

        for spec in TOOL_VERSION_SPECS:
            if bool(options.get(spec.option, False)):
                version = self._detect_tool_version(spec)
                if version:
                    segments.append(self._color_prompt_segment(version, spec.label_prefix))

        if bool(options.get("show_last_status", False)) and self.last_status != 0:
            segments.append(self._color_prompt_segment(f"[{self.last_status}]", "status"))

        if self.pending_multiline_paste is not None:
            lines = self._pending_multiline_paste_line_count()
            segments.append(self._color_prompt_segment(f"[paste:{lines}]", "status"))

        return " ".join(segments)

    def _prompt_info_line(self) -> str:
        """Return the framed info block for the two_line layout, or ``""`` for single.

        For ``two_line`` returns two lines joined by ``\\n``; the caller writes
        both before passing the command-line prompt to readline.
        """
        options = self.prompt_options
        if options.get("prompt_layout", "two_line") != "two_line":
            return ""
        return self._build_framed_info_lines(options)

    def _build_framed_info_lines(self, options: dict[str, object]) -> str:
        """Build the framed two-line info block for the two_line prompt layout.

        Line 1: ``┌─{venv} {icon} {user@host} ─ [{cwd}] ─ {git} ─ {status}``
        Line 2: ``│  {py} · {uv} · ...``  (omitted when no tool segments active)

        ASCII fallback (non-UTF-8 locale): ``+-`` / ``|`` / `` · `` separators.
        """
        use_unicode = self._unicode_capable()
        sep = " ─ " if use_unicode else " - "       # ─
        prefix1 = "┌─" if use_unicode else "+-"  # ┌─
        prefix2 = "│  " if use_unicode else "|  "     # │

        # Identity group: venv + icon + user@host, space-joined.
        id_parts: list[str] = []
        if bool(options.get("show_virtualenv", False)):
            venv = self._prompt_virtualenv()
            if venv:
                id_parts.append(self._color_prompt_segment(f"({venv})", "venv"))
        id_parts.append(self._color_prompt_segment(self._prompt_icon(), "icon"))
        identity_segs = self._prompt_identity_segments(options)
        if identity_segs:
            id_parts.append(
                "".join(
                    self._color_prompt_segment(text, role)
                    for text, role in identity_segs
                )
            )

        # Line 1: identity ─ [cwd] ─ git ─ status
        line1_segs: list[str] = [" ".join(id_parts)]

        if bool(options.get("show_cwd", True)):
            cwd_str = self._prompt_cwd_with_style(options)
            if cwd_str:
                line1_segs.append(
                    self._color_prompt_segment(f"[{cwd_str}]", "cwd")
                )

        git_seg = self._prompt_git_segment(options)
        if git_seg:
            line1_segs.append(self._color_prompt_segment(git_seg, "git"))

        if bool(options.get("show_last_status", False)) and self.last_status != 0:
            line1_segs.append(
                self._color_prompt_segment(f"[{self.last_status}]", "status")
            )

        if self.pending_multiline_paste is not None:
            count = self._pending_multiline_paste_line_count()
            line1_segs.append(
                self._color_prompt_segment(f"[paste:{count}]", "status")
            )

        line1 = prefix1 + sep.join(line1_segs)

        # Line 2: tool versions, dot-separated (omitted if none are active).
        tool_parts: list[str] = []

        if bool(options.get("show_python_version", False)):
            py = ".".join(str(p) for p in sys.version_info[:2])
            tool_parts.append(self._color_prompt_segment(f"py{py}", "python"))

        for spec in TOOL_VERSION_SPECS:
            if bool(options.get(spec.option, False)):
                version = self._detect_tool_version(spec)
                if version:
                    tool_parts.append(
                        self._color_prompt_segment(version, spec.label_prefix)
                    )

        if tool_parts:
            line2 = prefix2 + " · ".join(tool_parts)  # ·
            return f"{line1}\n{line2}"

        return line1

    def _prompt(self) -> str:
        """Return the newline-free prompt string passed to ``input()``.

        ``single`` renders the full historical inline prompt body followed by
        the configured symbol. ``two_line`` returns the framed closing line
        (``└─❯ `` / ``└─> `` / `` `- > ``); the informational block is
        printed separately before readline.
        """
        options = self.prompt_options
        symbol = str(options.get("symbol", ">"))
        rendered_symbol = self._color_prompt_segment(symbol, "symbol")
        if options.get("prompt_layout", "two_line") == "single":
            return self._prompt_body(options) + rendered_symbol + " "
        # two_line: framed closing line
        use_unicode = self._unicode_capable()
        if use_unicode:
            close_prefix = "└─"  # └─
            cmd_char = "❯" if symbol == ">" else symbol  # ❯
            return f"{close_prefix}{self._color_prompt_segment(cmd_char, 'symbol')} "
        return f"`- {rendered_symbol} "

    @staticmethod
    def _prompt_identity(options: dict[str, object]) -> str:
        """Build the ``user`` / ``host`` / ``user@host`` identity segment."""
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
        show_user = bool(options.get("show_user", True))
        show_host = bool(options.get("show_host", False))
        if show_user and show_host:
            return f"{user}@{socket.gethostname()}"
        if show_host:
            return socket.gethostname()
        if show_user:
            return user
        return ""

    @staticmethod
    def _prompt_identity_segments(options: dict[str, object]) -> list[tuple[str, str | None]]:
        """Build color-aware identity segments."""
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
        show_user = bool(options.get("show_user", True))
        show_host = bool(options.get("show_host", False))
        host = socket.gethostname()
        if show_user and show_host:
            return [(user, "user"), ("@", None), (host, "host")]
        if show_host:
            return [(host, "host")]
        if show_user:
            return [(user, "user")]
        return []

    def _color_prompt_segment(self, text: str, segment: str | None) -> str:
        """Apply configured prompt color to one rendered segment."""
        if segment is None or not text:
            return text
        color = self.prompt_colors.get(segment)
        rgb = parse_color(color) if color is not None else None
        return colorize(
            text,
            rgb,
            enabled=self._prompt_colors_enabled(),
            vga=bool(self.prompt_color_modes.get("vga", True)),
        )

    def _prompt_colors_enabled(self) -> bool:
        """Return True when prompt color output is allowed."""
        return colors_enabled()

    def _prompt_cwd_with_style(self, options: dict[str, object]) -> str:
        """Return the current directory using the configured prompt style."""
        return self._prompt_cwd(str(options.get("cwd_style", "full")))

    @staticmethod
    def _prompt_cwd(style: str = "full") -> str:
        """Return the current directory formatted for prompt display.

        ``full`` keeps the absolute path, ``home`` collapses ``$HOME`` to
        ``~`` and ``basename`` shows only the final path component. The
        configuration API validates the option value, but this method remains
        defensive and falls back to the default ``full`` style.
        """
        cwd = Path.cwd()
        if style == "full":
            return str(cwd)
        if style == "basename":
            if cwd == Path(cwd.anchor):
                return cwd.anchor
            return cwd.name or str(cwd)

        try:
            rel = cwd.relative_to(Path.home())
            return "~" if str(rel) == "." else "~/" + str(rel)
        except ValueError:
            return str(cwd)

    @staticmethod
    def _prompt_virtualenv() -> str | None:
        """Return the active virtualenv name, if ``VIRTUAL_ENV`` is set."""
        raw = os.environ.get("VIRTUAL_ENV")
        if not raw:
            return None
        name = Path(raw).name
        return name or None

    def _detect_tool_version(self, spec: ToolVersionSpec) -> str:
        """Return a cached rendered label for one external tool version."""
        cached = getattr(self, spec.cache_attr)
        if cached is not _UNSET:
            return cached

        value = ""
        if shutil.which(spec.executable) is not None:
            try:
                proc = subprocess.run(  # noqa: S603,S607 - explicit argv, bounded timeout.
                    [spec.executable, "--version"],
                    timeout=0.2,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    out = proc.stdout or proc.stderr or ""
                    match = _VERSION_RE.search(out)
                    if match is not None:
                        value = f"{spec.label_prefix}{match.group(1)}"
            except (OSError, subprocess.SubprocessError):
                value = ""

        setattr(self, spec.cache_attr, value)
        return value

    def _prompt_git_segment(self, options: dict[str, object]) -> str | None:
        """Return the Git prompt segment without invoking ``git``."""
        if not bool(options.get("show_git_branch", False)):
            return None
        info = self._read_git_prompt_info(Path.cwd())
        if info is None:
            return None
        dirty = "*" if bool(options.get("show_git_dirty", False)) and info.dirty else ""
        return f"git:{info.label}{dirty}"

    @classmethod
    def _read_git_prompt_info(cls, start: Path) -> GitPromptInfo | None:
        """Discover Git branch metadata by walking up from ``start``.

        Supports both normal repositories where ``.git`` is a directory and
        worktrees/submodules where ``.git`` is a file containing
        ``gitdir: <path>``. Detached HEADs are shown as ``detached-<hash>``.
        """
        git_dir = cls._find_git_dir(start)
        if git_dir is None:
            return None
        head_path = git_dir / "HEAD"
        try:
            head = head_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not head:
            return None
        if head.startswith("ref:"):
            ref = head[4:].strip()
            if not ref.startswith("refs/heads/"):
                return None
            label = ref.removeprefix("refs/heads/")
            if not label:
                return None
            return GitPromptInfo(label=label, dirty=cls._is_git_dirty_conservative(git_dir))
        if len(head) >= 7 and all(ch in "0123456789abcdefABCDEF" for ch in head):
            label = f"detached-{head[:7].lower()}"
            return GitPromptInfo(label=label, dirty=cls._is_git_dirty_conservative(git_dir))
        return None

    @classmethod
    def _find_git_dir(cls, start: Path) -> Path | None:
        """Return the repository git-dir for ``start`` or one of its parents."""
        current = start.resolve()
        while True:
            dotgit = current / ".git"
            if dotgit.is_dir():
                return dotgit
            if dotgit.is_file():
                git_dir = cls._read_gitdir_file(dotgit)
                if git_dir is not None:
                    return git_dir
            if current.parent == current:
                return None
            current = current.parent

    @staticmethod
    def _read_gitdir_file(path: Path) -> Path | None:
        """Parse a worktree/submodule ``.git`` file."""
        try:
            line = path.read_text(encoding="utf-8").splitlines()[0].strip()
        except (IndexError, OSError):
            return None
        prefix = "gitdir:"
        if not line.lower().startswith(prefix):
            return None
        raw = line[len(prefix) :].strip()
        if not raw:
            return None
        git_dir = Path(raw)
        if not git_dir.is_absolute():
            git_dir = (path.parent / git_dir).resolve()
        return git_dir if git_dir.is_dir() else None

    @staticmethod
    def _is_git_dirty_conservative(git_dir: Path) -> bool:
        """Detect only obvious non-clean Git states without false positives.

        A full dirty check would require reimplementing substantial Git index
        logic or invoking ``git status``. PySH intentionally does neither in
        the prompt path. This method marks only unambiguous states that are
        represented by Git metadata files/directories. If the repository state
        is uncertain, it returns ``False`` and omits the dirty marker.
        """
        obvious_files = (
            "index.lock",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "BISECT_LOG",
        )
        if any((git_dir / name).exists() for name in obvious_files):
            return True
        return (git_dir / "rebase-apply").exists() or (git_dir / "rebase-merge").exists()

    @staticmethod
    def _prompt_icon() -> str:
        encoding = (locale.getpreferredencoding(False) or "").lower()
        if "utf" in encoding:
            return "\U0001f40d"  # snake emoji
        return "$"

    @staticmethod
    def _unicode_capable() -> bool:
        """Return True when the locale encoding supports Unicode output."""
        encoding = (locale.getpreferredencoding(False) or "").lower()
        return "utf" in encoding

    def _print_banner(self) -> None:
        from pysh.diagnostics.system_info import get_system_summary  # noqa: PLC0415
        py_version = ".".join(str(p) for p in sys.version_info[:3])
        use_color = colors_enabled()
        snake = "\U0001f40d " if "utf" in (locale.getpreferredencoding(False) or "").lower() else ""
        line1 = f"{snake}PySH {__version__} | Python {py_version} | {LICENSE_NAME}"
        print(diagnostic(line1, "info", enabled=use_color))
        try:
            print(get_system_summary().format_compact())
        except Exception:  # noqa: BLE001 - banner must never crash PySH
            pass
        print("Type 'exit' or press Ctrl+D to quit.")
        if RC_PATH.exists():
            print(f"Loading {RC_PATH}")

    # ----------------------------------------------------------------- readline
    def _setup_readline(self) -> None:
        self.history.load()
        self.history.bind_reverse_search()
        self.completer.install()

    def _save_history(self) -> None:
        self.history.save()

    def _export_interactive_shell_vars(self) -> None:
        """Set SHELL, PYSH_SHELL, and PYSH_INTERACTIVE when running interactively.

        These exports let Midnight Commander and other tools that read ``$SHELL``
        launch PySH as their subshell.  They are only set when stdin and stdout
        are both TTYs so non-interactive invocations (scripts, ``-c`` mode) are
        unaffected.
        """
        if not self._stdio_is_tty():
            return
        path = self._resolve_pysh_path()
        for name, value in (
            ("SHELL", path),
            ("PYSH_SHELL", path),
            ("PYSH_INTERACTIVE", "1"),
        ):
            os.environ[name] = value
            self.local_vars[name] = value

    @staticmethod
    def _resolve_pysh_path() -> str:
        """Return the absolute path of the running PySH executable.

        Resolution order:
        1. ``shutil.which("pysh")`` — follows ``$PATH``, works after pip install.
        2. ``sys.argv[0]`` — works when invoked as a script or from a venv.
        3. ``sys.executable`` — fallback; points to the Python interpreter.
        """
        found = shutil.which("pysh")
        if found:
            return found
        argv0 = sys.argv[0] if sys.argv else ""
        if argv0 and os.path.isfile(argv0):
            return os.path.abspath(argv0)
        return sys.executable
