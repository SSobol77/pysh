# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/shell.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Interactive shell implementation for PySH."""
from __future__ import annotations

import atexit
import locale
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import termios
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import IO

from pysh import LICENSE_NAME, __version__
from pysh.colors import color_to_hex, colorize, parse_color
from pysh.command_plan import plan as run_plan
from pysh.completion import Completer
from pysh.config_api import (
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
from pysh.highlighting import colors_enabled, diagnostic
from pysh.history import DEFAULT_HISTORY_PATH, HistoryManager
from pysh.lineedit.autosuggest import AutoSuggester
from pysh.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.lineedit.reader import RawLineReader
from pysh.parser import (
    ChainOp,
    expand_command_substitution,
    expand_variables,
    parse_assignment,
    split_chain,
    split_pipeline,
    strip_comments,
)
from pysh.plugins import PLUGIN_DIR, load_plugins
from pysh.profile_importer import (
    analyze_compatibility_file,
    import_profile_file,
)
from pysh.python_runtime import (
    PythonRuntime,
    extract_block_body,
    is_block_closer,
    is_block_opener,
)
from pysh.rc import RC_PATH, execute_rc, load_default_rc
from pysh.redirection import RedirectionSpec, parse_redirections
from pysh.script_runner import ScriptRunner
from pysh.secure_runner import SecureRunner, indicator_config_from_mapping
from pysh.service import (
    DEFAULT_PID_ROOT,
    ServiceClient,
    ServiceError,
    format_list,
    format_status,
)
from pysh.system_profile import (
    apt_check,
    apt_search,
    env_audit,
    path_audit,
    sys_info,
    which_all,
)
from pysh.zsh_aliases import parse_zsh_aliases
from pysh.zsh_bridge import ZshBridge


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


class PyShell:
    """Python-first interactive shell with full Unix command support."""

    DEFAULT_ALIASES: dict[str, str] = {
        "ls": "ls --color=auto -F",
        "ll": "ls --color=auto -laF",
        "grep": "grep --color=auto",
        "df": "df -h",
        "free": "free -h",
    }

    BUILTINS: frozenset[str] = frozenset(
        {
            "cd",
            "pwd",
            "alias",
            "unalias",
            "export",
            "source",
            ".",
            "exit",
            "quit",
            "pushd",
            "popd",
            "dirs",
            "svc",
            "source_zsh",
            "source_zsh_profile",
            "source_sh_aliases",
            "run_script",
            "compat_check",
            "zsh",
            "zsh_fallback",
            "py",
            "sys_info",
            "env_audit",
            "path_audit",
            "which_all",
            "apt_check",
            "apt_search",
            "plan",
            "secure",
        }
    )

    HISTORY_PATH: Path = DEFAULT_HISTORY_PATH

    # ------------------------------------------------------------ construction
    def __init__(
        self,
        *,
        pid_root: Path | None = None,
        service_client: ServiceClient | None = None,
        zsh_bridge: ZshBridge | None = None,
        script_runner: ScriptRunner | None = None,
    ) -> None:
        self.local_vars: dict[str, str] = {}
        self.aliases: dict[str, str] = dict(self.DEFAULT_ALIASES)
        self.last_status: int = 0
        self.dir_stack: list[Path] = []
        self.prompt_options: dict[str, object] = dict(DEFAULT_PROMPT_OPTIONS)
        self.prompt_colors: dict[str, str] = dict(DEFAULT_PROMPT_COLORS)
        self.prompt_color_modes: dict[str, object] = dict(DEFAULT_PROMPT_COLOR_MODES)
        self.editor_options: dict[str, object] = dict(DEFAULT_EDITOR_OPTIONS)
        self.cursor_options: dict[str, object] = dict(DEFAULT_CURSOR_OPTIONS)
        self._cursor_color_applied = False
        # Read only by the explicit secure <cmd> PTY wrapper. Normal command
        # execution, prompt rendering and line editing do not consult it.
        self.sensitive_input: dict[str, object] = dict(DEFAULT_SENSITIVE_INPUT)
        for spec in TOOL_VERSION_SPECS:
            setattr(self, spec.cache_attr, _UNSET)
        self.completer = Completer(lambda: list(self.aliases.keys()))
        self.history = HistoryManager(self.HISTORY_PATH)
        self.autosuggester = AutoSuggester()
        self.line_highlighter = LineHighlighter(self.BUILTINS)
        self.line_reader = RawLineReader()
        self.zsh_bridge = zsh_bridge if zsh_bridge is not None else ZshBridge()
        self.zsh_fallback_enabled = os.environ.get("PYSH_ZSH_FALLBACK") == "1"
        self.python_runtime = PythonRuntime()
        self.script_runner = (
            script_runner if script_runner is not None else ScriptRunner(self.execute)
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
        load_default_rc(self.execute)
        load_plugins(self.execute, directory=PLUGIN_DIR)
        # Python-native configuration runs last so that ~/.pyshrc.py has the
        # final word over the legacy shell-syntax layers. Created on first
        # launch so the file is discoverable; the generated body is inert.
        if ensure_default_config():
            print(f"pysh: created {PYSHRC_PY_PATH}")
        load_python_config(self)
        self._apply_cursor_color()
        try:
            while True:
                try:
                    info_line = self._prompt_info_line()
                    if info_line:
                        sys.stdout.write(info_line + "\n")
                        sys.stdout.flush()
                    line = self._read_interactive_line()
                except EOFError:
                    print()
                    return 0
                except KeyboardInterrupt:
                    print()
                    continue
                if not line.strip():
                    continue
                if is_block_opener(line):
                    collected = self._collect_block_interactive(line)
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

    def _collect_block_interactive(self, opener: str) -> str | None:
        """Read continuation lines until the ``py { ... }`` block closes.

        Returns the joined multi-line block text, or ``None`` if collection
        was cancelled by the user (Ctrl+C or EOF).
        """
        collected: list[str] = [opener]
        while True:
            try:
                cont = input(self._continuation_prompt())
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

    @staticmethod
    def _continuation_prompt() -> str:
        return "py> "

    # --------------------------------------------------------------- execute
    def execute(self, line: str) -> int:
        """Execute one shell line. Returns the exit status of the last command."""
        line = line.rstrip("\n").rstrip("\r")
        # ``#py`` must be checked *before* strip_comments() because a bare ``#``
        # at the start of a token-boundary is otherwise treated as a comment.
        if line.strip() == "#py":
            return self._enter_python_mode()
        line = strip_comments(line)
        if not line.strip():
            return 0

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

        chain = split_chain(line)
        status = 0
        run_next = True
        for elem in chain:
            if run_next:
                status = self._run_chain_element(elem.command)
                self.last_status = status
            if elem.operator is ChainOp.AND:
                run_next = status == 0
            elif elem.operator is ChainOp.OR:
                run_next = status != 0
            else:
                run_next = True
        return status

    # ------------------------------------------------------------- internals
    def _run_chain_element(self, command: str) -> int:
        stages = split_pipeline(command)
        if not stages:
            return 0
        # Alias expansion is applied per simple command (i.e. per pipe stage).
        stages = [self._expand_alias(s) for s in stages]
        # Variable expansion happens after alias expansion so that alias
        # bodies behave like literal text but user variables in arguments
        # are still substituted.
        stages = [expand_variables(s, self.local_vars) for s in stages]
        if len(stages) == 1:
            return self._run_simple(stages[0])
        return self._run_pipeline(stages, original_command=command)

    def _run_simple(self, stage: str) -> int:
        clean, spec = parse_redirections(stage)
        try:
            argv = shlex.split(clean, posix=True)
        except ValueError as exc:
            if self.zsh_fallback_enabled:
                return self._run_zsh_fallback(stage)
            print(f"pysh: parse error: {exc}", file=sys.stderr)
            return 2
        if not argv:
            return 0
        if argv[0] in self.BUILTINS:
            return self._dispatch_builtin(argv)
        return self._run_external(argv, spec, original_stage=stage)

    def _run_pipeline(self, stages: list[str], *, original_command: str) -> int:
        parsed: list[tuple[list[str], RedirectionSpec]] = []
        for s in stages:
            clean, spec = parse_redirections(s)
            try:
                argv = shlex.split(clean, posix=True)
            except ValueError as exc:
                print(f"pysh: parse error: {exc}", file=sys.stderr)
                return 2
            if not argv:
                print("pysh: syntax error near unexpected '|'", file=sys.stderr)
                return 2
            parsed.append((argv, spec))

        procs: list[subprocess.Popen[bytes]] = []
        opened: list[IO[bytes]] = []
        prev_out: IO[bytes] | None = None
        try:
            for i, (argv, spec) in enumerate(parsed):
                is_first = i == 0
                is_last = i == len(parsed) - 1

                stdin_arg: IO[bytes] | int | None
                if spec.stdin_path:
                    f = open(spec.stdin_path, "rb")
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
                if spec.stderr_to_stdout:
                    stderr_arg = subprocess.STDOUT
                elif spec.stderr_path:
                    f = open(spec.stderr_path, "ab" if spec.stderr_append else "wb")
                    opened.append(f)
                    stderr_arg = f
                else:
                    stderr_arg = None

                try:
                    proc = subprocess.Popen(  # noqa: S603 - user-issued command
                        argv,
                        stdin=stdin_arg,
                        stdout=stdout_arg,
                        stderr=stderr_arg,
                    )
                except FileNotFoundError:
                    if self.zsh_fallback_enabled and argv[0] not in self.BUILTINS:
                        if prev_out is not None:
                            prev_out.close()
                        for p in procs:
                            p.terminate()
                            p.wait()
                        return self._run_zsh_fallback(original_command)
                    print(f"pysh: {argv[0]}: command not found", file=sys.stderr)
                    if prev_out is not None:
                        prev_out.close()
                    for p in procs:
                        p.terminate()
                        p.wait()
                    return 127

                # The parent must close the read end of the previous pipe so
                # that the child receives EOF after the upstream stage exits.
                if prev_out is not None:
                    prev_out.close()
                prev_out = proc.stdout
                procs.append(proc)

            try:
                results = [p.wait() for p in procs]
            except KeyboardInterrupt:
                for p in procs:
                    p.terminate()
                results = [p.wait() for p in procs]
                return 130
            return results[-1] if results else 0
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
    ) -> int:
        stdin_f: IO[bytes] | None = None
        stdout_f: IO[bytes] | None = None
        stderr_f: IO[bytes] | None = None
        stderr_arg: IO[bytes] | int | None
        try:
            if spec.stdin_path:
                stdin_f = open(spec.stdin_path, "rb")
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
                    stdin=stdin_f,
                    stdout=stdout_f,
                    stderr=stderr_arg,
                )
            except FileNotFoundError:
                if self.zsh_fallback_enabled and original_stage is not None:
                    return self._run_zsh_fallback(original_stage)
                print(f"pysh: {argv[0]}: command not found", file=sys.stderr)
                return 127
            except PermissionError as exc:
                print(f"pysh: {argv[0]}: {exc}", file=sys.stderr)
                return 126
            try:
                return proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                proc.wait()
                return 130
        except OSError as exc:
            print(f"pysh: {exc}", file=sys.stderr)
            return 1
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
            "which_all": self._builtin_which_all,
            "apt_check": self._builtin_apt_check,
            "apt_search": self._builtin_apt_search,
            "plan": self._builtin_plan,
            "secure": self._builtin_secure,
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

    def _builtin_source(self, args: list[str]) -> int:
        if not args:
            print("source: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
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
        return self.script_runner.run(target, args[1:])

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
        from pysh.python_mode import PythonCommandMode  # noqa: PLC0415
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
                    completer=self.completer,
                )
            except (OSError, termios.error):
                return input(self._prompt())
        return input(self._prompt())

    def _should_use_raw_editor(self) -> bool:
        """Return True when the configured editor may use raw TTY mode."""
        mode = str(self.editor_options.get("line_editor", "auto"))
        if mode == "readline":
            return False
        if not self._stdio_is_tty():
            return False
        if mode == "auto" and not colors_enabled():
            return False
        return mode in {"auto", "basic"}

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

        return " ".join(segments)

    def _prompt_info_line(self) -> str:
        """Return the two-line prompt informational line, or ``""`` for single."""
        options = self.prompt_options
        if options.get("prompt_layout", "two_line") != "two_line":
            return ""
        return self._prompt_body(options)

    def _prompt(self) -> str:
        """Return the newline-free prompt string passed to ``input()``.

        ``single`` renders the full historical inline prompt body followed by
        the configured symbol. ``two_line`` returns only the command-line
        prompt; the informational line is printed separately before readline.
        """
        options = self.prompt_options
        symbol = str(options.get("symbol", ">"))
        rendered_symbol = self._color_prompt_segment(symbol, "symbol")
        if options.get("prompt_layout", "two_line") == "single":
            return self._prompt_body(options) + rendered_symbol + " "
        return rendered_symbol + " "

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

    def _print_banner(self) -> None:
        from pysh.system_info import get_system_summary  # noqa: PLC0415
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
