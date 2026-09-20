# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/core/shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Interactive shell implementation for PySH."""
from __future__ import annotations

import atexit
import locale
import os
import pwd
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import termios
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from copy import deepcopy
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
from pysh.config.alias_packs import BUILTIN_ALIAS_PACKS, alias_pack_names
from pysh.config.api import (
    DEFAULT_COMPLETION_OPTIONS,
    DEFAULT_CURSOR_OPTIONS,
    DEFAULT_EDITOR_OPTIONS,
    DEFAULT_HISTORY_OPTIONS,
    DEFAULT_PROMPT_COLOR_MODES,
    DEFAULT_PROMPT_COLORS,
    DEFAULT_PROMPT_OPTIONS,
    DEFAULT_SENSITIVE_INPUT,
    PYSHRC_PY_PATH,
    ensure_default_config,
    load_python_config,
    validate_completion_option,
    validate_cursor_color,
    validate_cursor_color_enabled,
    validate_editor_option,
    validate_highlight_color,
    validate_history_option,
    validate_prompt_color,
    validate_prompt_color_mode,
    validate_prompt_option,
    validate_sensitive_input,
)
from pysh.config.diagnostics import safe_value_repr
from pysh.config.plugins import PLUGIN_DIR, load_plugins
from pysh.config.profiles import profile_names, resolve_profiles
from pysh.config.rc import RC_PATH, execute_rc, load_default_rc
from pysh.config.runtime import (
    apply_declarative_config,
    ensure_default_toml_config,
    load_declarative_config,
    load_plugin_configs,
)
from pysh.config.startup import DEFAULT_STARTUP_POLICY, StartupPolicy
from pysh.config.themes import resolve_themes, theme_names
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
from pysh.editor.history import DEFAULT_HISTORY_PATH, HistoryEngine, HistoryManager
from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.highlight import (
    DEFAULT_HIGHLIGHT_COLORS,
    DEFAULT_SCHEME,
    ColorScheme,
    LineHighlighter,
)
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
from pysh.parsing.redirection import (
    RedirectionActionKind,
    RedirectionSpec,
    parse_redirections,
)
from pysh.plugins.manager import PluginManager
from pysh.prompt.colors import (
    color_to_hex,
    colorize,
    parse_color,
    sgr_ansi16,
    sgr_reset,
    sgr_truecolor,
)
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
    timeout_seconds: float = 0.2


@dataclass(frozen=True)
class _ResolvedStage:
    """One pipeline stage resolved before any process is started."""

    kind: str
    argv: tuple[str, ...]
    spec: RedirectionSpec
    env_overrides: dict[str, str] | None = None
    python_source: str | None = None


TOOL_VERSION_SPECS: tuple[ToolVersionSpec, ...] = (
    ToolVersionSpec("show_uv_version", "uv", "uv", "_uv_version_cache"),
    ToolVersionSpec("show_ruff_version", "ruff", "ruff", "_ruff_version_cache"),
    ToolVersionSpec("show_rust_version", "rustc", "rust", "_rust_version_cache"),
    ToolVersionSpec("show_node_version", "node", "node", "_node_version_cache"),
    ToolVersionSpec("show_npm_version", "npm", "npm", "_npm_version_cache"),
    # Issue #32 (Shell Integrations Pack): I32-A added detection/cache, I32-B
    # wired these into DEFAULT_PROMPT_OPTIONS/PROMPT_OPTION_TYPES (all default
    # False). pip gets a wider timeout (I32-B.1): a real ``pip --version`` can
    # cost more than 0.2s (interpreter startup for the Python environment pip
    # belongs to, which may differ from PySH's own interpreter), so detection
    # stays executable-based rather than switching to importlib.metadata.
    ToolVersionSpec("show_pip_version", "pip", "pip", "_pip_version_cache", timeout_seconds=0.5),
    ToolVersionSpec("show_docker_version", "docker", "docker", "_docker_version_cache"),
    ToolVersionSpec("show_kubectl_version", "kubectl", "kubectl", "_kubectl_version_cache"),
    ToolVersionSpec("show_ecli_version", "ecli", "ecli", "_ecli_version_cache"),
    ToolVersionSpec("show_guardbsd_version", "guardbsd", "guardbsd", "_guardbsd_version_cache"),
    ToolVersionSpec("show_aeronerve_version", "aeronerve", "aeronerve", "_aeronerve_version_cache"),
)

_UNSET = object()
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|.)")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_KUBECONFIG_MAX_BYTES = 64 * 1024
_KUBE_CURRENT_CONTEXT_RE = re.compile(r'^current-context:\s*([^\s#]+)\s*(?:#.*)?$')
_GIT_BARE_CONFIG_MAX_BYTES = 64 * 1024


def _osc_set_cursor_color(hex_color: str) -> str:
    """Return OSC 12 sequence that requests terminal cursor color."""
    return f"\x1b]12;{hex_color}\x07"


def _osc_reset_cursor_color() -> str:
    """Return OSC 112 sequence that requests terminal cursor color reset."""
    return "\x1b]112\x07"


def _sanitize_prompt_value(value: str) -> str:
    """Remove terminal controls from untrusted prompt segment values."""
    cleaned = _ANSI_ESCAPE_RE.sub("", value)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    return cleaned.strip()


def _format_command_duration(seconds: float) -> str:
    """Return a deterministic prompt label for command duration seconds."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    total = int(seconds)
    minutes, remainder = divmod(total, 60)
    return f"{minutes}m{remainder:02d}s"


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
    expanded = RedirectionSpec(
        stdin_path=expand_tilde(spec.stdin_path) if spec.stdin_path else None,
        stdin_data=spec.stdin_data,
        stdout_path=expand_tilde(spec.stdout_path) if spec.stdout_path else None,
        stdout_append=spec.stdout_append,
        stderr_path=expand_tilde(spec.stderr_path) if spec.stderr_path else None,
        stderr_append=spec.stderr_append,
        stderr_to_stdout=spec.stderr_to_stdout,
    )
    expanded.actions = [
        type(action)(
            action.fd,
            action.kind,
            path=expand_tilde(action.path) if action.path else None,
            append=action.append,
            source_fd=action.source_fd,
            data=action.data,
        )
        for action in spec.actions
    ]
    return expanded


@contextmanager
def _redirect_standard_fds(
    spec: RedirectionSpec,
    *,
    stdin_fd: int | None = None,
    stdout_fd: int | None = None,
) -> object:
    """Apply ordered redirections to fd 0/1/2 and restore them on return."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = {fd: os.dup(fd) for fd in (0, 1, 2)}
    opened: list[int] = []
    original_streams = (sys.stdin, sys.stdout, sys.stderr)
    redirected_streams: list[IO[str]] = []
    try:
        if stdin_fd is not None:
            os.dup2(stdin_fd, 0)
        if stdout_fd is not None:
            os.dup2(stdout_fd, 1)
        for action in spec.actions:
            if action.kind is RedirectionActionKind.DUP:
                assert action.source_fd is not None
                os.dup2(action.source_fd, action.fd)
                continue
            if action.kind is RedirectionActionKind.DATA:
                temp = tempfile.TemporaryFile("w+b")
                temp.write(action.data or b"")
                temp.seek(0)
                duplicate = os.dup(temp.fileno())
                temp.close()
                opened.append(duplicate)
                os.dup2(duplicate, action.fd)
                continue
            assert action.path is not None
            if action.kind is RedirectionActionKind.READ:
                flags = os.O_RDONLY
                mode = 0
            else:
                flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if action.append else os.O_TRUNC)
                mode = 0o666
            opened_fd = os.open(action.path, flags, mode)
            opened.append(opened_fd)
            os.dup2(opened_fd, action.fd)
        encoding = locale.getpreferredencoding(False) or "utf-8"
        redirected_stdin = os.fdopen(os.dup(0), "r", encoding=encoding, errors="replace")
        redirected_stdout = os.fdopen(os.dup(1), "w", encoding=encoding, errors="replace", buffering=1)
        redirected_stderr = os.fdopen(os.dup(2), "w", encoding=encoding, errors="replace", buffering=1)
        redirected_streams.extend((redirected_stdin, redirected_stdout, redirected_stderr))
        sys.stdin = redirected_stdin
        sys.stdout = redirected_stdout
        sys.stderr = redirected_stderr
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdin, sys.stdout, sys.stderr = original_streams
        for stream in redirected_streams:
            stream.close()
        for fd, duplicate in saved.items():
            os.dup2(duplicate, fd)
            os.close(duplicate)
        for opened_fd in opened:
            try:
                os.close(opened_fd)
            except OSError:
                pass


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


def _mapping_items(value: object) -> tuple[tuple[str, object], ...]:
    """Return string-keyed mapping items for config application helpers."""
    if not isinstance(value, dict):
        return ()
    return tuple((str(key), item) for key, item in value.items())


def _append_mapping_diff(
    lines: list[str],
    prefix: str,
    defaults: dict[str, object],
    current: dict[str, object],
) -> None:
    """Append changed mapping keys using redacted value formatting."""
    for key in sorted(set(defaults) | set(current)):
        default_missing = key not in defaults
        current_missing = key not in current
        if current_missing:
            value: object = "<unset>"
        else:
            value = current[key]
        if not default_missing and not current_missing and defaults[key] == value:
            continue
        lines.append(f"{prefix}.{key}={safe_value_repr(key, value)}")


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
        startup_policy: StartupPolicy = DEFAULT_STARTUP_POLICY,
    ) -> None:
        self.local_vars: dict[str, str] = {}
        self.aliases: dict[str, str] = dict(self.DEFAULT_ALIASES)
        self.last_status: int = 0
        self.trace = trace if trace is not None else DiagnosticTrace()
        self.startup_policy = startup_policy
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
        self.highlight_colors: dict[str, str] = dict(DEFAULT_HIGHLIGHT_COLORS)
        self.prompt_color_modes: dict[str, object] = dict(DEFAULT_PROMPT_COLOR_MODES)
        self.editor_options: dict[str, object] = dict(DEFAULT_EDITOR_OPTIONS)
        self.completion_options: dict[str, object] = dict(DEFAULT_COMPLETION_OPTIONS)
        self.cursor_options: dict[str, object] = dict(DEFAULT_CURSOR_OPTIONS)
        self.active_profile = "default"
        self.active_theme = "default"
        self.config_profiles: dict[str, dict[str, object]] = resolve_profiles({})[0]
        self.config_themes: dict[str, dict[str, object]] = resolve_themes({})[0]
        self.config_diagnostics: list[object] = []
        self.config_loaded_paths: list[Path] = []
        self.plugin_configs: dict[str, dict[str, object]] = {}
        self._startup_hooks: list[Callable[[], None]] = []
        self._cursor_color_applied = False
        self._mc_auto_warning_emitted = False
        # Read only by the explicit secure <cmd> PTY wrapper. Normal command
        # execution, prompt rendering and line editing do not consult it.
        self.sensitive_input: dict[str, object] = dict(DEFAULT_SENSITIVE_INPUT)
        for spec in TOOL_VERSION_SPECS:
            setattr(self, spec.cache_attr, _UNSET)
        self._last_command_duration: float | None = None
        self._k8s_context_cache_key: tuple[tuple[str, int, int] | tuple[str, str], ...] | None = None
        self._k8s_context_cache_value: str | None = None
        self.plugin_manager = PluginManager(builtin_names=self.BUILTINS)
        self.completer = Completer(
            lambda: list(self.aliases.keys()),
            get_locals=lambda: dict(self.local_vars),
            get_job_ids=lambda: [job.job_id for job in self.job_table.all_jobs() if job.is_alive()],
            get_plugin_commands=lambda: self.plugin_manager.command_names(),
            complete_plugin_command=self.plugin_manager.complete_command,
            get_options=lambda: dict(self.completion_options),
        )
        self.history = HistoryManager(self.HISTORY_PATH)
        self.history_options: dict[str, object] = dict(DEFAULT_HISTORY_OPTIONS)
        self._session_id: str = uuid.uuid4().hex[:16]
        self.history_engine = HistoryEngine(
            self.HISTORY_PATH,
            session_id=self._session_id,
            max_length=int(self.history_options.get("max_length", 10_000)),  # type: ignore[arg-type]
            dedup_mode=str(self.history_options.get("dedup_mode", "consecutive")),
            ignore_space_prefix=bool(self.history_options.get("ignore_space_prefix", True)),
            ignore_patterns=list(self.history_options.get("ignore_patterns", [])),  # type: ignore[arg-type]
        )
        self._last_execute_parse_ok: bool = True
        self._venv_restore_environment: dict[str, str | None] | None = None
        self._venv_restore_locals: dict[str, str | None] | None = None
        self.autosuggester = AutoSuggester(self.completer.raw_completion)
        self.line_highlighter = LineHighlighter(
            self.BUILTINS,
            aliases=lambda: self.aliases.keys(),
        )
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
        if self.startup_policy.load_user_configuration:
            self._load_user_startup_configuration()
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
                        self.line_reader.clear_editor_state()
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
                    pending_action = self._pending_paste_command(line)
                    if pending_action == "exit":
                        self._discard_pending_paste_for_exit()
                        try:
                            self.last_status = self.execute(line)
                            if self._last_execute_parse_ok:
                                self.history_engine.add(line, raw_line=line)
                        except _ExitShell as exit_signal:
                            return exit_signal.code
                        continue
                    if pending_action == "clear":
                        # PYSH-0.9.0-BUG-024: `clear` while a paste is staged
                        # must actually clear the screen. Re-printing the full
                        # staged-paste preview here would immediately redraw
                        # everything `clear` just erased. The staged payload
                        # is preserved untouched; the next prompt's existing
                        # `[paste:N]` indicator communicates that it is still
                        # pending, and paste_show/paste_edit/paste_run/
                        # paste_cancel remain available as always.
                        self.last_status = self.execute(line)
                        if self._last_execute_parse_ok:
                            self.history_engine.add(line, raw_line=line)
                        continue
                    if pending_action == "paste":
                        try:
                            self.last_status = self.execute(line)
                            if self._last_execute_parse_ok:
                                self.history_engine.add(line, raw_line=line)
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
                    if self._last_execute_parse_ok:
                        self.history_engine.add(line, raw_line=line)
                except _ExitShell as exit_signal:
                    return exit_signal.code
        finally:
            self.plugin_manager.run_shutdown_hooks()
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

    def _load_user_startup_configuration(self) -> None:
        """Load all user-controlled interactive startup layers in order."""
        load_default_rc(self.execute)
        load_plugins(self.execute, directory=PLUGIN_DIR)
        if ensure_default_toml_config():
            print("pysh: created declarative config")
        declarative_config = apply_declarative_config(self)
        self.config_profiles = declarative_config.profiles
        self.config_themes = declarative_config.themes
        self.config_diagnostics = list(declarative_config.diagnostics)
        self.config_loaded_paths = list(declarative_config.loaded_paths)
        # Python-native configuration runs last so that ~/.pyshrc.py has the
        # final word over the legacy shell-syntax layers. Created on first
        # launch so the file is discoverable; the generated body is inert.
        if ensure_default_config():
            print(f"pysh: created {PYSHRC_PY_PATH}")
        load_python_config(self)
        self.plugin_manager.discover_and_load()
        self._run_user_startup_hooks()
        self.plugin_manager.run_startup_hooks()

    def run_batch(self, lines: IO[str]) -> int:
        """Execute logical lines from non-interactive stdin without presentation.

        Batch input deliberately does not initialize the interactive editor,
        banner, prompt engine, or user startup hooks. It is therefore safe for
        pipelines and automation and has the same last-command status contract
        as native script mode.
        """
        from pysh.parsing.multiline import iter_logical_lines  # noqa: PLC0415

        status = 0
        try:
            for logical_line in iter_logical_lines(lines):
                if not logical_line.strip():
                    continue
                status = self.execute(logical_line)
        except ValueError as exc:
            print(f"pysh: stdin: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        return status

    def _collect_block_interactive(self, opener: str) -> str | None:
        """Read continuation lines until the ``py { ... }`` block closes.

        Returns the joined multi-line block text, or ``None`` if collection
        was cancelled by the user (Ctrl+C or EOF).
        """
        collected: list[str] = [opener]
        self.line_reader.enter_multiline_mode(opener=opener)
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
            self.line_reader.clear_editor_state()

    def _collect_heredoc_interactive(self, command_line: str) -> str | None:
        """Read heredoc body lines until all pending delimiters are seen."""
        try:
            specs = pending_heredoc_specs(command_line)
        except ParseError as exc:
            print(f"pysh: parse error: {exc}", file=sys.stderr)
            self.last_status = ExitCode.BUILTIN_MISUSE
            return None
        collected: list[str] = [command_line]
        self.line_reader.enter_heredoc_mode(
            opener=command_line,
            delimiters=[spec.delimiter for spec in specs],
        )
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
            self.line_reader.clear_editor_state()

    def _read_multiline_interactive_line(self, prompt: str, *, initial_text: str = "") -> str:
        """Read one collector-owned continuation line through the active editor.

        *initial_text* pre-fills the line buffer (e.g. for ``paste_edit``
        editing an existing staged line) and is ignored by the ``input()``
        fallback, which has no concept of a pre-filled buffer.
        """
        if self._should_use_raw_editor():
            options = SimpleNamespace(autosuggest=False, syntax_highlight=False)
            try:
                return self.line_reader.read_line(
                    prompt,
                    history=[],
                    suggester=self.autosuggester,
                    highlighter=self.line_highlighter,
                    scheme=self._highlight_color_scheme(),
                    options=options,
                    echo_queued=False,
                    initial_text=initial_text,
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
        self.line_reader.enter_paste_mode(payload)
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
                    ("paste_edit", "edit"),
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
    def _pending_paste_command(line: str) -> str | None:
        """Classify commands allowed while multiline paste is pending."""
        try:
            argv = shlex.split(line, posix=True)
        except ValueError:
            return None
        if not argv:
            return None
        if argv[0] in {"paste_show", "paste_run", "paste_cancel", "paste_edit"}:
            return "paste"
        if argv[0] == "clear":
            return "clear"
        if argv[0] in {"exit", "quit"}:
            return "exit"
        return None

    def _print_pending_paste_hint(self) -> None:
        """Re-render the pending paste state after a safe UI command."""
        payload = self.pending_multiline_paste
        if payload is None:
            return
        enabled = style_enabled()
        count = self._pending_multiline_paste_line_count()
        print(
            style(
                f"pysh: pending multiline paste retained ({count} lines). Review below.",
                "warning",
                enabled=enabled,
            )
        )
        for preview_line in self._format_pending_paste_preview(
            payload,
            title="paste",
            max_lines=20,
            enabled=enabled,
            highlighter=self._make_paste_line_highlighter(payload, enabled=enabled),
        ):
            print(preview_line)
        print(
            format_key_hints(
                [
                    ("Enter", "run"),
                    ("Ctrl+C", "cancel"),
                    ("paste_edit", "edit"),
                    ("paste_show", "inspect"),
                    ("paste_cancel", "discard"),
                ],
                enabled=enabled,
            )
        )

    def _discard_pending_paste_for_exit(self) -> None:
        """Drop pending paste before dispatching exit/quit."""
        self.pending_multiline_paste = None
        self.line_reader.clear_command_queue()
        self.line_reader.clear_editor_state()
        self._executing_paste = False
        enabled = style_enabled()
        print(style("paste_cancel: pending multiline paste discarded", "warning", enabled=enabled))

    def execute(self, line: str) -> int:
        """Execute one shell line and record bounded prompt duration metadata."""
        if not line.strip():
            self._last_command_duration = None
            return self._execute_impl(line)
        start = time.perf_counter()
        try:
            return self._execute_impl(line)
        finally:
            self._last_command_duration = time.perf_counter() - start

    def _execute_impl(self, line: str) -> int:
        """Execute one shell line. Returns the exit status of the last command."""
        self._last_execute_parse_ok = True
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
        if self._is_pipeline_python_block(line):
            return self._run_python_block_pipeline(line)
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
            self._last_execute_parse_ok = False
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
            self._last_execute_parse_ok = False
            print(zsh_diagnostic.message, file=sys.stderr)
            print(zsh_diagnostic.hint, file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        try:
            validate_unsupported_syntax(line)
        except ParseError as exc:
            self._last_execute_parse_ok = False
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
            return self._run_direct_python(line, py_code)

        # Bare ``NAME=value`` assignment.
        if self._is_bare_assignment(line):
            return self._assign_local(line)

        try:
            chain = split_chain(line)
        except ParseError as exc:
            self._last_execute_parse_ok = False
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
            stages = self._split_pipeline_stages(command)
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
        # Alias and variable expansion apply to shell stages, never to the
        # source body of a collected Python block stage.
        stages = [
            stage if self._is_python_block_stage(stage) else self._expand_alias(stage)
            for stage in stages
        ]
        # Variable expansion happens after alias expansion so that alias
        # bodies behave like literal text but user variables in arguments
        # are still substituted.  $? is passed as a special variable so it
        # expands to the last command exit status (Issue #5).
        _sv = self._special_vars()
        stages = [
            stage
            if self._is_python_block_stage(stage)
            else expand_variables(stage, self.local_vars, special_vars=_sv)
            for stage in stages
        ]
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

    @staticmethod
    def _is_pipeline_python_block(command: str) -> bool:
        """Return True for a collected pipeline whose final stage is ``py {``."""
        lines = command.splitlines()
        if len(lines) < 2 or lines[-1].strip() != "}":
            return False
        try:
            stages = split_pipeline(lines[0])
        except ParseError:
            return False
        return len(stages) > 1 and stages[-1].strip() == "py {"

    @staticmethod
    def _is_python_block_stage(stage: str) -> bool:
        lines = stage.strip().splitlines()
        return len(lines) >= 2 and lines[0].strip() == "py {" and lines[-1].strip() == "}"

    def _run_python_block_pipeline(self, command: str) -> int:
        """Execute a collected Python-block pipeline without expanding its body."""
        lines = command.splitlines()
        first_line = strip_comments(lines[0])
        zsh_diagnostic = detect_unsupported_zsh_syntax(first_line)
        if zsh_diagnostic is not None:
            print(zsh_diagnostic.message, file=sys.stderr)
            print(zsh_diagnostic.hint, file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        try:
            validate_unsupported_syntax(first_line)
        except ParseError as exc:
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        expanded_first_line = expand_command_substitution(first_line)
        protected = "\n".join([expanded_first_line, *lines[1:]])
        return self._run_chain_element(protected)

    @classmethod
    def _split_pipeline_stages(cls, command: str) -> list[str]:
        """Split a pipeline while preserving a collected Python block body."""
        if not cls._is_pipeline_python_block(command):
            return split_pipeline(command)
        lines = command.splitlines()
        stages = split_pipeline(lines[0])
        stages[-1] = "\n".join([stages[-1], *lines[1:]])
        return stages

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
            try:
                redirection = _redirect_standard_fds(spec) if not spec.is_empty() else nullcontext()
                with redirection:
                    status = self._dispatch_builtin(cmd_argv)
            except OSError as exc:
                print(f"pysh: {exc}", file=sys.stderr)
                return ExitCode.GENERAL_ERROR
            self.trace.emit(DiagnosticStage.EXECUTE_PLAN, "command finished", status=status)
            return status
        if self.plugin_manager.has_command(cmd_argv[0]):
            self.trace.emit(
                DiagnosticStage.RESOLVE,
                "command resolved",
                command=cmd_argv[0],
                kind="plugin",
            )
            try:
                redirection = _redirect_standard_fds(spec) if not spec.is_empty() else nullcontext()
                with redirection:
                    status = self.plugin_manager.run_command(cmd_argv[0], cmd_argv[1:])
            except OSError as exc:
                print(f"pysh: {exc}", file=sys.stderr)
                return ExitCode.GENERAL_ERROR
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
        if status == ExitCode.COMMAND_NOT_FOUND and self._looks_like_python_source(cmd_argv[0]):
            print("hint: Python code requires the 'py' prefix:", file=sys.stderr)
            print("      pysh -c 'py print(\"hello\")'", file=sys.stderr)
        self.trace.emit(DiagnosticStage.EXECUTE_PLAN, "command finished", status=status)
        return status

    @staticmethod
    def _looks_like_python_source(command: str) -> bool:
        """Return True for common Python statements misused as shell commands."""
        return bool(
            re.match(
                r"^(?:print\s*\(|import\b|from\b|def\b|class\b|raise\b)",
                command,
            )
        )

    def _run_pipeline(
        self,
        stages: list[str],
        *,
        original_command: str,
        heredoc_bodies: list[HereDocBody] | None = None,
        background: bool = False,
    ) -> int:
        """Resolve every stage, then execute it through one pipeline contract."""
        resolved: list[_ResolvedStage] = []
        remaining_heredocs = heredoc_bodies if heredoc_bodies is not None else []
        for source in stages:
            stage = self._resolve_execution_stage(source, remaining_heredocs)
            if isinstance(stage, int):
                return stage
            resolved.append(stage)
        if self.zsh_fallback_enabled:
            missing_external = next(
                (
                    stage.argv[0]
                    for stage in resolved
                    if stage.kind == "external" and shutil.which(stage.argv[0]) is None
                ),
                None,
            )
            if missing_external is not None:
                return self._run_zsh_fallback(original_command)
        return self._execute_resolved_pipeline(
            resolved,
            original_command=original_command,
            background=background,
        )

    def _resolve_execution_stage(
        self,
        source: str,
        heredoc_bodies: list[HereDocBody],
    ) -> _ResolvedStage | int:
        """Parse and classify one pipeline stage without executing it."""
        stripped = source.strip()
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].strip() == "py {" and lines[-1].strip() == "}":
            return _ResolvedStage(
                "python-block",
                ("py",),
                RedirectionSpec(),
                python_source="\n".join(lines[1:-1]),
            )
        try:
            clean, spec = parse_redirections(source, heredoc_bodies)
        except ParseError as exc:
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        spec = _tilde_expand_spec(spec)
        python_source = self._extract_direct_py_code(clean)
        if python_source is not None:
            return _ResolvedStage(
                "python-inline",
                ("py",),
                spec,
                python_source=python_source,
            )
        try:
            argv = tokenize_and_glob_expand(clean, cwd=Path(os.getcwd()))
        except ValueError as exc:
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        if not argv:
            print("pysh: syntax error near unexpected '|'", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        env_overrides, command_argv = parse_leading_env_assignments(argv)
        if not command_argv:
            print("pysh: syntax error: assignment without command before '|'", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        name = command_argv[0]
        if name in self.BUILTINS:
            kind = "builtin"
        elif self.plugin_manager.has_command(name):
            kind = "plugin"
        else:
            kind = "external"
        return _ResolvedStage(
            kind,
            tuple(command_argv),
            spec,
            env_overrides if env_overrides else None,
        )

    def _execute_resolved_pipeline(
        self,
        stages: list[_ResolvedStage],
        *,
        original_command: str,
        background: bool,
    ) -> int:
        """Fork isolated stages connected by OS pipes and return the last status."""
        pids: list[int] = []
        previous_read: int | None = None
        pipeline_pgid: int | None = None
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            for index, stage in enumerate(stages):
                is_last = index == len(stages) - 1
                next_read: int | None = None
                next_write: int | None = None
                if not is_last:
                    next_read, next_write = os.pipe()
                pid = os.fork()
                if pid == 0:
                    try:
                        os.setpgid(0, pipeline_pgid or 0)
                        reset_child_job_control_signals()
                    except OSError:
                        pass
                    try:
                        with _redirect_standard_fds(
                            stage.spec,
                            stdin_fd=previous_read,
                            stdout_fd=next_write,
                        ):
                            for fd in (previous_read, next_read, next_write):
                                if fd is not None and fd > 2:
                                    try:
                                        os.close(fd)
                                    except OSError:
                                        pass
                            status = self._execute_isolated_stage(stage)
                            sys.stdout.flush()
                            sys.stderr.flush()
                    except BaseException as exc:  # noqa: BLE001 - child boundary
                        print(f"pysh: pipeline: {exc}", file=sys.stderr)
                        status = ExitCode.GENERAL_ERROR
                    os._exit(int(status))

                if pipeline_pgid is None:
                    pipeline_pgid = pid
                try:
                    os.setpgid(pid, pipeline_pgid)
                except OSError:
                    pass
                pids.append(pid)
                if previous_read is not None:
                    os.close(previous_read)
                if next_write is not None:
                    os.close(next_write)
                previous_read = next_read

            if background:
                assert pipeline_pgid is not None
                job = self.job_table.add_job(
                    pipeline_pgid,
                    original_command,
                    pids,
                    background=True,
                )
                print(f"[{job.job_id}] {pids[-1]}", flush=True)
                return ExitCode.SUCCESS

            raw_statuses: dict[int, int] = {}
            tty_fd = self._tty_fd
            if tty_fd is not None and pipeline_pgid is not None:
                if not tcsetpgrp_safely(tty_fd, pipeline_pgid):
                    tty_fd = None
            try:
                for pid in pids:
                    _, raw_statuses[pid] = os.waitpid(pid, 0)
            except KeyboardInterrupt:
                if pipeline_pgid is not None:
                    try:
                        os.killpg(pipeline_pgid, signal.SIGINT)
                    except OSError:
                        pass
                for pid in pids:
                    if pid not in raw_statuses:
                        try:
                            _, raw_statuses[pid] = os.waitpid(pid, 0)
                        except OSError:
                            pass
                return ExitCode.SIGINT
            finally:
                if tty_fd is not None:
                    tcsetpgrp_safely(tty_fd, os.getpgrp())
            return _raw_to_exit(raw_statuses[pids[-1]])
        except OSError as exc:
            print(f"pysh: pipeline: {exc}", file=sys.stderr)
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            return ExitCode.GENERAL_ERROR
        finally:
            if previous_read is not None:
                try:
                    os.close(previous_read)
                except OSError:
                    pass

    def _execute_isolated_stage(self, stage: _ResolvedStage) -> int:
        """Execute one already-resolved stage in its isolated child process."""
        if stage.env_overrides:
            os.environ.update(stage.env_overrides)
        if stage.kind == "builtin":
            try:
                return self._dispatch_builtin(list(stage.argv))
            except _ExitShell as exc:
                return exc.code
        if stage.kind == "plugin":
            return self.plugin_manager.run_command(stage.argv[0], list(stage.argv[1:]))
        if stage.kind == "python-inline":
            return self._run_python_code(stage.python_source or "")
        if stage.kind == "python-block":
            return self.python_runtime.execute_block(stage.python_source or "")
        try:
            os.execvpe(stage.argv[0], stage.argv, dict(os.environ))
        except FileNotFoundError:
            print(f"pysh: {stage.argv[0]}: command not found", file=sys.stderr)
            return ExitCode.COMMAND_NOT_FOUND
        except PermissionError as exc:
            print(f"pysh: {stage.argv[0]}: {exc}", file=sys.stderr)
            return ExitCode.CANNOT_EXECUTE
        except OSError as exc:
            print(f"pysh: {stage.argv[0]}: {exc}", file=sys.stderr)
            return ExitCode.GENERAL_ERROR

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
            if not spec.actions and spec.stdin_path:
                stdin_f = open(spec.stdin_path, "rb")
            elif not spec.actions and spec.stdin_data is not None:
                stdin_f = tempfile.TemporaryFile("w+b")
                stdin_f.write(spec.stdin_data)
                stdin_f.seek(0)
            if not spec.actions and spec.stdout_path:
                stdout_f = open(spec.stdout_path, "ab" if spec.stdout_append else "wb")
            if spec.actions:
                stderr_arg = None
            elif spec.stderr_to_stdout:
                stderr_arg = subprocess.STDOUT
            elif spec.stderr_path:
                stderr_f = open(spec.stderr_path, "ab" if spec.stderr_append else "wb")
                stderr_arg = stderr_f
            else:
                stderr_arg = None
            try:
                redirection = _redirect_standard_fds(spec) if spec.actions else nullcontext()
                with redirection:
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
                message = f"pysh: {argv[0]}: command not found"
                if any(action.fd != 0 for action in spec.actions):
                    with _redirect_standard_fds(spec):
                        print(message, file=sys.stderr)
                else:
                    _write_execution_stderr(
                        message,
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
            "config_check": self._builtin_config_check,
            "config_reset": self._builtin_config_reset,
            "config_profile": self._builtin_config_profile,
            "config_theme": self._builtin_config_theme,
            "deactivate": self._builtin_deactivate,
            "config_alias_pack": self._builtin_config_alias_pack,
            "zsh": self._builtin_zsh,
            "zsh_fallback": self._builtin_zsh_fallback,
            "py": self._builtin_py,
            "sys_info": self._builtin_sys_info,
            "env_audit": self._builtin_env_audit,
            "path_audit": self._builtin_path_audit,
            "paste_show": self._builtin_paste_show,
            "paste_cancel": self._builtin_paste_cancel,
            "paste_run": self._builtin_paste_run,
            "paste_edit": self._builtin_paste_edit,
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
                self._set_exported_environment(name, value, notify_plugins=True)
            else:
                if token in self.local_vars:
                    self._set_exported_environment(
                        token,
                        self.local_vars[token],
                        notify_plugins=True,
                    )
                else:
                    if token not in os.environ:
                        self._set_exported_environment(token, "", notify_plugins=True)
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
        if self.plugin_manager.has_command(name):
            return self.plugin_manager.run_command(name, args[1:])
        return self._run_external(args, RedirectionSpec(), original_stage=" ".join(args))

    def _print_command_resolution(self, name: str, *, verbose: bool) -> bool:
        """Print POSIX-style command resolution details for ``command -v/-V``."""
        if name in self.BUILTINS:
            print(f"{name} is a PySH builtin" if verbose else name)
            return True
        if self.plugin_manager.has_command(name):
            print(f"{name} is a PySH plugin command" if verbose else name)
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
        venv_root = self._validated_venv_activation_target(target)
        if venv_root is not None:
            return self._activate_virtualenv(venv_root)
        if target.name == "activate" and target.parent.name == "bin":
            print(f"source: {target}: invalid Python virtual environment", file=sys.stderr)
            return 1
        if is_zsh_config_path(str(target)):
            diagnostic_info = zsh_config_file_diagnostic(str(target))
            print(diagnostic_info.message, file=sys.stderr)
            print(diagnostic_info.hint, file=sys.stderr)
            return 2
        return execute_rc(target, self.execute, quiet_missing=False)

    @staticmethod
    def _validated_venv_activation_target(target: Path) -> Path | None:
        """Return the validated virtualenv root for a ``bin/activate`` target."""
        try:
            resolved = target.resolve(strict=True)
        except OSError:
            return None
        if resolved.name != "activate" or resolved.parent.name != "bin":
            return None
        root = resolved.parent.parent
        python = root / "bin" / "python"
        if not (root / "pyvenv.cfg").is_file() or not python.is_file():
            return None
        if not os.access(python, os.X_OK):
            return None
        return root

    def _activate_virtualenv(self, root: Path) -> int:
        """Activate ``root`` transactionally without interpreting foreign code."""
        if self._venv_restore_environment is None:
            self._venv_restore_environment = {
                name: os.environ.get(name)
                for name in ("PATH", "PYTHONHOME", "VIRTUAL_ENV")
            }
            self._venv_restore_locals = {
                name: self.local_vars.get(name)
                for name in ("PATH", "PYTHONHOME", "VIRTUAL_ENV")
            }
        else:
            self._restore_virtualenv_environment(clear_snapshot=False)

        base_path = os.environ.get("PATH", "")
        bin_path = str(root / "bin")
        path_parts = [part for part in base_path.split(os.pathsep) if part != bin_path]
        new_path = os.pathsep.join([bin_path, *path_parts])
        self._set_exported_environment("PATH", new_path, notify_plugins=True)
        self._set_exported_environment("VIRTUAL_ENV", str(root), notify_plugins=True)
        self._unset_exported_environment("PYTHONHOME", notify_plugins=True)
        return 0

    def _builtin_deactivate(self, _args: list[str]) -> int:
        """Restore the exact environment captured before native activation."""
        if self._venv_restore_environment is None:
            return 0
        self._restore_virtualenv_environment(clear_snapshot=True)
        return 0

    def _restore_virtualenv_environment(self, *, clear_snapshot: bool) -> None:
        snapshot = self._venv_restore_environment
        if snapshot is None:
            return
        for name, value in snapshot.items():
            if value is None:
                self._unset_exported_environment(name, notify_plugins=True)
            else:
                self._set_exported_environment(name, value, notify_plugins=True)
        local_snapshot = self._venv_restore_locals or {}
        for name, value in local_snapshot.items():
            if value is None:
                self.local_vars.pop(name, None)
            else:
                self.local_vars[name] = value
        if clear_snapshot:
            self._venv_restore_environment = None
            self._venv_restore_locals = None

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
        self.line_reader.clear_editor_state()
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
            self.line_reader.clear_editor_state()
            self._executing_paste = False
            self._script_context = previous_context

    def _builtin_paste_edit(self, args: list[str]) -> int:
        """Edit the staged multiline paste line-by-line before it is run.

        Each existing line is opened in the raw editor pre-filled with its
        current text; accepting a line (Enter) never executes it. The
        canonical ``self.pending_multiline_paste`` payload is replaced only
        after every line has been accepted, so an interrupted edit (Ctrl+C
        or EOF) leaves the original staged payload byte-for-byte intact.
        """
        if args:
            print("paste_edit: usage: paste_edit", file=sys.stderr)
            return 2
        if self.pending_multiline_paste is None:
            print("paste_edit: no pending multiline paste")
            return 2
        original = self.pending_multiline_paste
        trailing_newline = original.endswith("\n")
        original_lines = original.splitlines()
        total = len(original_lines)
        enabled = style_enabled()
        edited_lines: list[str] = []
        for index, original_line in enumerate(original_lines, start=1):
            prompt = f"paste[{index}/{total}]> "
            try:
                edited_lines.append(
                    self._read_multiline_interactive_line(prompt, initial_text=original_line)
                )
            except EOFError:
                print()
                print(
                    style(
                        "paste_edit: edit aborted at end of input; original payload preserved",
                        "warning",
                        enabled=enabled,
                    )
                )
                return ExitCode.GENERAL_ERROR
            except KeyboardInterrupt:
                print()
                print(
                    style(
                        "paste_edit: edit cancelled; original payload preserved",
                        "warning",
                        enabled=enabled,
                    )
                )
                return ExitCode.SIGINT
        updated_payload = "\n".join(edited_lines)
        if trailing_newline:
            updated_payload += "\n"
        self.pending_multiline_paste = updated_payload
        self.line_reader.enter_paste_mode(updated_payload)
        print(
            style(
                f"paste_edit: staged paste updated ({total} lines).",
                "warning",
                enabled=enabled,
            )
        )
        return 0

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

    def _builtin_config_check(self, args: list[str]) -> int:
        if len(args) > 1 or (args and args[0] not in {"--validate", "--diff", "--locations"}):
            print("usage: config_check [--validate|--diff|--locations]", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        mode = args[0] if args else ""
        config = load_declarative_config()
        plugin_cfgs = load_plugin_configs()
        plugin_diags = [diag for pc in plugin_cfgs.values() for diag in pc.diagnostics]
        has_errors = any(d.severity == "error" for d in config.diagnostics) or any(
            d.severity == "error" for d in plugin_diags
        )
        if mode == "--locations":
            if config.loaded_paths:
                for path in config.loaded_paths:
                    print(f"loaded: {path}")
            else:
                print("loaded: <none>")
            for pc in sorted(plugin_cfgs.values(), key=lambda p: str(p.path)):
                print(f"plugin: {pc.path}")
            return 1 if has_errors else 0
        if mode == "--diff":
            for line in self._config_diff_lines():
                print(line)
            return 1 if has_errors else 0
        all_diags = list(config.diagnostics) + plugin_diags
        for diagnostic_item in all_diags:
            print(diagnostic_item.format(), file=sys.stderr)
        if mode == "--validate":
            if has_errors:
                return 1
            print("pysh: config: valid")
            return 0
        print(f"profile: {self.active_profile}")
        print(f"theme: {self.active_theme}")
        print(f"loaded files: {len(config.loaded_paths)}")
        print(f"plugin config files: {len(plugin_cfgs)}")
        print(f"diagnostics: {len(all_diags)}")
        return 1 if has_errors else 0

    def _config_diff_lines(self) -> list[str]:
        """Return runtime configuration differences from built-in defaults."""
        lines: list[str] = []
        if self.active_profile != "default":
            lines.append(f"profile.active={self.active_profile!r}")
        if self.active_theme != "default":
            lines.append(f"theme.active={self.active_theme!r}")
        _append_mapping_diff(lines, "prompt", DEFAULT_PROMPT_OPTIONS, self.prompt_options)
        _append_mapping_diff(lines, "editor", DEFAULT_EDITOR_OPTIONS, self.editor_options)
        _append_mapping_diff(lines, "completion", DEFAULT_COMPLETION_OPTIONS, self.completion_options)
        _append_mapping_diff(lines, "history", DEFAULT_HISTORY_OPTIONS, self.history_options)
        _append_mapping_diff(lines, "colors.prompt", DEFAULT_PROMPT_COLORS, self.prompt_colors)
        _append_mapping_diff(lines, "colors.highlight", DEFAULT_HIGHLIGHT_COLORS, self.highlight_colors)
        _append_mapping_diff(lines, "colors.mode", DEFAULT_PROMPT_COLOR_MODES, self.prompt_color_modes)
        _append_mapping_diff(lines, "cursor", DEFAULT_CURSOR_OPTIONS, self.cursor_options)
        _append_mapping_diff(lines, "aliases", self.DEFAULT_ALIASES, self.aliases)
        return lines

    def _builtin_config_reset(self, args: list[str]) -> int:
        if len(args) > 1:
            print("usage: config_reset [target]", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        target = args[0] if args else "all"
        try:
            self.reset_config(target)
        except ValueError as exc:
            print(f"pysh: config_reset: {exc}", file=sys.stderr)
            return 1
        return 0

    def _builtin_config_profile(self, args: list[str]) -> int:
        if not args or args[0] not in {"list", "show", "use"}:
            print("usage: config_profile list|show NAME|use NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        action = args[0]
        if action == "list":
            if len(args) != 1:
                print("usage: config_profile list", file=sys.stderr)
                return ExitCode.BUILTIN_MISUSE
            for name in self.get_profiles():
                marker = "*" if name == self.active_profile else " "
                print(f"{marker} {name}")
            return 0
        if len(args) != 2:
            print(f"usage: config_profile {action} NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        name = args[1]
        if name not in self.config_profiles:
            print(f"pysh: config_profile: unknown profile: {name}", file=sys.stderr)
            return 1
        if action == "show":
            print(f"profile: {name}")
            for key, value in sorted(self.config_profiles[name].items()):
                print(f"{key}: {value!r}")
            return 0
        self.set_profile(name)
        return 0

    def _builtin_config_theme(self, args: list[str]) -> int:
        if not args or args[0] not in {"list", "show", "preview", "use"}:
            print("usage: config_theme list|show NAME|preview NAME|use NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        action = args[0]
        if action == "list":
            if len(args) != 1:
                print("usage: config_theme list", file=sys.stderr)
                return ExitCode.BUILTIN_MISUSE
            for name in self.get_themes():
                marker = "*" if name == self.active_theme else " "
                print(f"{marker} {name}")
            return 0
        if len(args) != 2:
            print(f"usage: config_theme {action} NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        name = args[1]
        if name not in self.config_themes:
            print(f"pysh: config_theme: unknown theme: {name}", file=sys.stderr)
            return 1
        if action == "show":
            print(f"theme: {name}")
            for key, value in sorted(self.config_themes[name].items()):
                print(f"{key}: {value!r}")
            return 0
        if action == "preview":
            print(self.preview_theme(name))
            return 0
        self.set_theme(name)
        return 0

    def _builtin_config_alias_pack(self, args: list[str]) -> int:
        if not args or args[0] not in {"list", "show", "load"}:
            print("usage: config_alias_pack list|show NAME|load NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        action = args[0]
        if action == "list":
            if len(args) != 1:
                print("usage: config_alias_pack list", file=sys.stderr)
                return ExitCode.BUILTIN_MISUSE
            for name in self.get_alias_packs():
                print(name)
            return 0
        if len(args) != 2:
            print(f"usage: config_alias_pack {action} NAME", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        name = args[1]
        pack = BUILTIN_ALIAS_PACKS.get(name)
        if pack is None:
            print(f"pysh: config_alias_pack: unknown alias pack: {name}", file=sys.stderr)
            return 1
        if action == "show":
            for alias_name, value in sorted(pack.items()):
                print(f"{alias_name}={value!r}")
            return 0
        self.load_alias_pack(name)
        return 0

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
        return run_plan(
            args,
            builtins=self.BUILTINS,
            plugin_commands=self.plugin_manager.command_names(),
        )

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
            self._set_exported_environment(name, value, notify_plugins=True)
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

    def _run_direct_python(self, line: str, code: str) -> int:
        """Execute direct Python with optional trailing shell redirections."""
        try:
            clean, spec = parse_redirections(line)
        except ParseError as exc:
            print(f"pysh: {self._paste_error_label()}: {exc}", file=sys.stderr)
            return ExitCode.BUILTIN_MISUSE
        if spec.is_empty():
            return self._run_python_code(code)
        clean_code = self._extract_direct_py_code(clean)
        if clean_code is None:
            return self._run_python_code(code)
        try:
            with _redirect_standard_fds(_tilde_expand_spec(spec)):
                return self._run_python_code(clean_code)
        except OSError as exc:
            print(f"pysh: {exc}", file=sys.stderr)
            return ExitCode.GENERAL_ERROR

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
        if lines[0].strip() != "py {":
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
        self._set_exported_environment(name, value, notify_plugins=True)

    def _set_exported_environment(
        self,
        name: str,
        value: str,
        *,
        notify_plugins: bool,
    ) -> None:
        """Set an exported variable through the central mutation path."""
        old = os.environ.get(name)
        os.environ[name] = value
        self.local_vars[name] = value
        if name == "PYSH_ZSH_FALLBACK":
            self.zsh_fallback_enabled = value == "1"
        if notify_plugins and old != value:
            self.plugin_manager.notify_env_change(name, old, value)

    def _unset_exported_environment(self, name: str, *, notify_plugins: bool) -> None:
        """Unset one exported variable through the central mutation path."""
        old = os.environ.pop(name, None)
        self.local_vars.pop(name, None)
        if notify_plugins and old is not None:
            self.plugin_manager.notify_env_change(name, old, None)

    def enable_plugin(self, name: str) -> None:
        """Record explicit intent to load a trusted Python plugin."""
        self.plugin_manager.enable_plugin(name)

    def disable_plugin(self, name: str) -> None:
        """Remove explicit intent to load a trusted Python plugin."""
        self.plugin_manager.disable_plugin(name)

    def enable_project_plugins(self) -> None:
        """Allow explicitly enabled project-local plugins to execute."""
        self.plugin_manager.enable_project_plugins()

    def list_plugins(self) -> list[str]:
        """Return plugin names known from config/discovery state."""
        return self.plugin_manager.list_plugins()

    def is_plugin_enabled(self, name: str) -> bool:
        """Return whether a plugin name is explicitly enabled."""
        return self.plugin_manager.is_plugin_enabled(name)

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

    def set_highlight_color(self, role: str, color: str) -> None:
        """Set a validated live-input highlight color."""
        validate_highlight_color(role, color)
        self.highlight_colors[role] = color

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

    def set_history_option(self, name: str, value: object) -> None:
        """Set a validated history engine option (ConfigurableShell contract)."""
        validate_history_option(name, value)
        self.history_options[name] = value
        self.history_engine.set_option(name, value)

    def set_completion_option(self, name: str, value: object) -> None:
        """Set a validated completion option."""
        validate_completion_option(name, value)
        self.completion_options[name] = value

    def set_profile(self, name: str) -> None:
        """Apply a named profile to runtime configuration state."""
        if name not in self.config_profiles:
            raise ValueError(f"unknown profile: {name}")
        profile = self.config_profiles[name]
        self.active_profile = name
        theme = profile.get("theme")
        if isinstance(theme, str) and theme in self.config_themes:
            self.set_theme(theme)
        for key, value in _mapping_items(profile.get("prompt")):
            self.set_prompt_option(key, value)
        for key, value in _mapping_items(profile.get("editor")):
            self.set_editor_option(key, value)
        for key, value in _mapping_items(profile.get("completion")):
            self.set_completion_option(key, value)
        for key, value in _mapping_items(profile.get("history")):
            self.set_history_option(key, value)

    def get_profiles(self) -> list[str]:
        """Return known profile names."""
        return profile_names(self.config_profiles)

    def set_theme(self, name: str) -> None:
        """Apply a named theme to runtime color state."""
        if name not in self.config_themes:
            raise ValueError(f"unknown theme: {name}")
        theme = self.config_themes[name]
        self.active_theme = name
        colors = theme.get("colors")
        if not isinstance(colors, dict):
            return
        for key, value in _mapping_items(colors.get("prompt")):
            if isinstance(value, str):
                self.set_prompt_color(key, value)
        for key, value in _mapping_items(colors.get("highlight")):
            if isinstance(value, str):
                self.set_highlight_color(key, value)

    def get_themes(self) -> list[str]:
        """Return known theme names."""
        return theme_names(self.config_themes)

    def preview_theme(self, name: str) -> str:
        """Return a non-executing theme preview."""
        if name not in self.config_themes:
            raise ValueError(f"unknown theme: {name}")
        return "\n".join(
            (
                f"theme: {name}",
                "prompt: user@host [~/project] git:main",
                "status: ok / error",
                "highlight: builtin alias path string comment paste reverse_search",
            )
        )

    def load_alias_pack(self, name: str) -> None:
        """Load a built-in alias pack without executing alias values."""
        pack = BUILTIN_ALIAS_PACKS.get(name)
        if pack is None:
            raise ValueError(f"unknown alias pack: {name}")
        for alias_name, value in pack.items():
            self.register_alias(alias_name, value)

    def get_alias_packs(self) -> list[str]:
        """Return known alias-pack names."""
        return alias_pack_names()

    def get_plugin_config(self, name: str) -> dict[str, object]:
        """Return a copy of the loaded plugin TOML configuration for *name*.

        Returns an empty dict when no plugin config file was found for *name*.
        The returned value is always a fresh copy; callers may not mutate
        internal state through it.
        """
        return deepcopy(self.plugin_configs.get(name, {}))

    def register_startup_hook(self, fn: Callable[[], None]) -> None:
        """Register a trusted Python startup hook from ``~/.pyshrc.py``."""
        if not callable(fn):
            raise ValueError("startup hook must be callable")
        self._startup_hooks.append(fn)

    def _run_user_startup_hooks(self) -> None:
        """Run user startup hooks without preventing later hooks."""
        for hook in tuple(self._startup_hooks):
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 - startup hooks are trusted user code
                print(f"pysh: config: startup hook failed: {exc}", file=sys.stderr)

    def reset_config(self, target: str = "all") -> None:
        """Reset runtime configuration state without writing user files."""
        valid = {
            "all",
            "prompt",
            "editor",
            "history",
            "completion",
            "colors",
            "highlight",
            "cursor",
            "aliases",
        }
        if target not in valid:
            raise ValueError(f"unknown config reset target: {target}")
        if target == "all":
            self.active_profile = "default"
            self.active_theme = "default"
        if target in {"all", "prompt"}:
            self.prompt_options = dict(DEFAULT_PROMPT_OPTIONS)
        if target in {"all", "editor"}:
            self.editor_options = dict(DEFAULT_EDITOR_OPTIONS)
        if target in {"all", "completion"}:
            self.completion_options = dict(DEFAULT_COMPLETION_OPTIONS)
        if target in {"all", "history"}:
            self.history_options = dict(DEFAULT_HISTORY_OPTIONS)
            for key, value in self.history_options.items():
                self.history_engine.set_option(key, value)
        if target in {"all", "colors"}:
            self.prompt_colors = dict(DEFAULT_PROMPT_COLORS)
            self.prompt_color_modes = dict(DEFAULT_PROMPT_COLOR_MODES)
        if target in {"all", "highlight"}:
            self.highlight_colors = dict(DEFAULT_HIGHLIGHT_COLORS)
        if target in {"all", "cursor"}:
            self.cursor_options = dict(DEFAULT_CURSOR_OPTIONS)
        if target in {"all", "aliases"}:
            self.aliases = dict(self.DEFAULT_ALIASES)

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
                    history=self.history_engine.entries(),
                    suggester=self.autosuggester,
                    highlighter=self.line_highlighter,
                    scheme=self._highlight_color_scheme(),
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

    def _highlight_color_scheme(self) -> ColorScheme:
        """Return the configured live-input color scheme."""
        try:
            values: dict[str, str] = {}
            vga = bool(self.prompt_color_modes.get("vga", True))
            for role, default_color in DEFAULT_HIGHLIGHT_COLORS.items():
                rgb = parse_color(self.highlight_colors.get(role, default_color))
                values[role] = sgr_ansi16(rgb) if vga else sgr_truecolor(rgb)
            return ColorScheme(**values, reset=sgr_reset())
        except ValueError:
            return DEFAULT_SCHEME

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

        for value in self.plugin_manager.prompt_segments("before_cwd"):
            segments.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

        git_segment = self._prompt_git_segment(options)
        if git_segment:
            segments.append(self._color_prompt_segment(git_segment, "git"))

        for value in self.plugin_manager.prompt_segments("after_git"):
            segments.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

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

        for text, role in self._prompt_context_segments(options):
            segments.append(self._color_prompt_segment(text, role))

        for value in self.plugin_manager.prompt_segments("end"):
            segments.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

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

        for value in self.plugin_manager.prompt_segments("before_cwd"):
            line1_segs.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

        git_seg = self._prompt_git_segment(options)
        if git_seg:
            line1_segs.append(self._color_prompt_segment(git_seg, "git"))

        for value in self.plugin_manager.prompt_segments("after_git"):
            line1_segs.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

        if bool(options.get("show_last_status", False)) and self.last_status != 0:
            line1_segs.append(
                self._color_prompt_segment(f"[{self.last_status}]", "status")
            )

        for text, role in self._prompt_context_segments(options):
            line1_segs.append(self._color_prompt_segment(text, role))

        for value in self.plugin_manager.prompt_segments("end"):
            line1_segs.append(self._color_prompt_segment(_sanitize_prompt_value(value), None))

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
        user = PyShell._effective_username()
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
        user = PyShell._effective_username()
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

    @staticmethod
    def _effective_username() -> str:
        """Return the passwd name for the effective process identity."""
        try:
            return pwd.getpwuid(os.geteuid()).pw_name
        except (KeyError, OSError):
            return str(os.geteuid())

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
                    timeout=spec.timeout_seconds,
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

    def _prompt_context_segments(self, options: dict[str, object]) -> list[tuple[str, str]]:
        """Return optional non-tool context prompt segments."""
        segments: list[tuple[str, str]] = []
        for provider in (
            self._prompt_duration_segment,
            self._prompt_ssh_segment,
            self._prompt_aws_segment,
            self._prompt_k8s_segment,
        ):
            try:
                segment = provider(options)
            except (OSError, ValueError):
                segment = None
            if segment is not None:
                segments.append(segment)
        return segments

    def _prompt_duration_segment(self, options: dict[str, object]) -> tuple[str, str] | None:
        """Return the last command duration segment when above threshold."""
        if not bool(options.get("show_command_duration", False)):
            return None
        duration = self._last_command_duration
        if duration is None:
            return None
        threshold = options.get("command_duration_threshold", 0.5)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            return None
        if duration < threshold:
            return None
        return _format_command_duration(duration), "duration"

    @staticmethod
    def _prompt_ssh_segment(options: dict[str, object]) -> tuple[str, str] | None:
        """Return an SSH marker for interactive remote sessions."""
        if not bool(options.get("show_ssh_indicator", False)):
            return None
        if not any(os.environ.get(name) for name in ("SSH_CLIENT", "SSH_TTY", "SSH_CONNECTION")):
            return None
        marker = _sanitize_prompt_value("ssh")
        return (marker, "ssh") if marker else None

    @staticmethod
    def _prompt_aws_segment(options: dict[str, object]) -> tuple[str, str] | None:
        """Return the configured AWS profile segment without invoking AWS tools."""
        if not bool(options.get("show_aws_profile", False)):
            return None
        raw = os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE")
        if not raw:
            return None
        profile = _sanitize_prompt_value(raw)
        return (f"aws:{profile}", "aws") if profile else None

    def _prompt_k8s_segment(self, options: dict[str, object]) -> tuple[str, str] | None:
        """Return Kubernetes current-context from bounded stdlib config parsing."""
        if not bool(options.get("show_k8s_context", False)):
            return None
        context = self._read_k8s_context()
        return (f"k8s:{context}", "k8s") if context else None

    def _read_k8s_context(self) -> str | None:
        """Return the first configured Kubernetes current-context, or None."""
        paths = self._kubeconfig_paths()
        signature = self._kubeconfig_signature(paths)
        if signature == self._k8s_context_cache_key:
            return self._k8s_context_cache_value
        value: str | None = None
        for path in paths:
            value = self._read_k8s_context_file(path)
            if value:
                break
        self._k8s_context_cache_key = signature
        self._k8s_context_cache_value = value
        return value

    @staticmethod
    def _kubeconfig_paths() -> tuple[Path, ...]:
        raw = os.environ.get("KUBECONFIG")
        if raw:
            return tuple(Path(part).expanduser() for part in raw.split(os.pathsep) if part)
        return (Path("~/.kube/config").expanduser(),)

    @staticmethod
    def _kubeconfig_signature(paths: tuple[Path, ...]) -> tuple[tuple[str, int, int] | tuple[str, str], ...]:
        signature: list[tuple[str, int, int] | tuple[str, str]] = []
        for path in paths:
            try:
                stat_result = path.stat()
            except OSError:
                signature.append((str(path), "missing"))
                continue
            signature.append((str(path), stat_result.st_size, stat_result.st_mtime_ns))
        return tuple(signature)

    @staticmethod
    def _read_k8s_context_file(path: Path) -> str | None:
        try:
            stat_result = path.stat()
        except OSError:
            return None
        if not path.is_file() or stat_result.st_size > _KUBECONFIG_MAX_BYTES:
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if "\n---" in text or text.lstrip().startswith("---"):
            return None
        matches: list[str] = []
        for line in text.splitlines():
            if line.startswith((" ", "\t")):
                continue
            match = _KUBE_CURRENT_CONTEXT_RE.match(line.strip())
            if match is None:
                continue
            raw = match.group(1).strip().strip("'\"")
            context = _sanitize_prompt_value(raw)
            if context:
                matches.append(context)
        if len(matches) != 1:
            return None
        return matches[0]

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
            return cls._read_bare_git_prompt_info(start)
        return cls._read_git_prompt_info_from_dir(git_dir)

    @classmethod
    def _read_git_prompt_info_from_dir(cls, git_dir: Path) -> GitPromptInfo | None:
        """Read prompt metadata from a concrete Git metadata directory."""
        try:
            head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
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
        try:
            current = start.resolve()
        except OSError:
            return None
        while True:
            dotgit = current / ".git"
            try:
                if dotgit.is_dir():
                    return dotgit
                if dotgit.is_file():
                    git_dir = cls._read_gitdir_file(dotgit)
                    if git_dir is not None:
                        return git_dir
            except OSError:
                return None
            if current.parent == current:
                return None
            current = current.parent

    @classmethod
    def _read_bare_git_prompt_info(cls, start: Path) -> GitPromptInfo | None:
        """Detect a bare repository using a bounded strong-signal check."""
        try:
            current = start.resolve()
        except OSError:
            return None
        while True:
            if cls._is_bare_git_dir(current):
                return cls._read_git_prompt_info_from_dir(current)
            if current.parent == current:
                return None
            current = current.parent

    @staticmethod
    def _is_bare_git_dir(path: Path) -> bool:
        """Return True only for strong, bounded bare Git repository evidence."""
        try:
            config_stat = (path / "config").stat()
        except OSError:
            return False
        if config_stat.st_size > _GIT_BARE_CONFIG_MAX_BYTES:
            return False
        try:
            if not (path / "HEAD").is_file():
                return False
            if not (path / "objects").is_dir():
                return False
            if not (path / "refs").is_dir():
                return False
            config = (path / "config").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        in_core = False
        for raw_line in config.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_core = line.casefold() == "[core]"
                continue
            if in_core and re.fullmatch(r"bare\s*=\s*true", line, re.IGNORECASE):
                return True
        return False

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
        try:
            if any((git_dir / name).exists() for name in obvious_files):
                return True
            return (git_dir / "rebase-apply").exists() or (git_dir / "rebase-merge").exists()
        except OSError:
            return False

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
        self.history_engine.load()
        self.history.populate_from_entries(self.history_engine.entries())
        self.history.disable_auto_history()
        self.history.bind_reverse_search()
        self.completer.install()

    def _save_history(self) -> None:
        self.history_engine.save()

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
