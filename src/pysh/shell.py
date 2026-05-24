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

import locale
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import IO

from pysh import __version__
from pysh.completion import Completer
from pysh.highlighting import colors_enabled, diagnostic
from pysh.history import DEFAULT_HISTORY_PATH, HistoryManager
from pysh.parser import (
    ChainOp,
    expand_command_substitution,
    expand_variables,
    parse_assignment,
    split_chain,
    split_pipeline,
)
from pysh.plugins import PLUGIN_DIR, load_plugins
from pysh.rc import RC_PATH, execute_rc, load_default_rc
from pysh.redirection import RedirectionSpec, parse_redirections
from pysh.service import (
    DEFAULT_PID_ROOT,
    ServiceClient,
    ServiceError,
    format_list,
    format_status,
)


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
        }
    )

    HISTORY_PATH: Path = DEFAULT_HISTORY_PATH

    # ------------------------------------------------------------ construction
    def __init__(
        self,
        *,
        pid_root: Path | None = None,
        service_client: ServiceClient | None = None,
    ) -> None:
        self.local_vars: dict[str, str] = {}
        self.aliases: dict[str, str] = dict(self.DEFAULT_ALIASES)
        self.last_status: int = 0
        self.dir_stack: list[Path] = []
        self.completer = Completer(lambda: list(self.aliases.keys()))
        self.history = HistoryManager(self.HISTORY_PATH)
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
        try:
            while True:
                try:
                    line = input(self._prompt())
                except EOFError:
                    print()
                    return 0
                except KeyboardInterrupt:
                    print()
                    continue
                if not line.strip():
                    continue
                try:
                    self.last_status = self.execute(line)
                except _ExitShell as exit_signal:
                    return exit_signal.code
        finally:
            self._save_history()

    # --------------------------------------------------------------- execute
    def execute(self, line: str) -> int:
        """Execute one shell line. Returns the exit status of the last command."""
        line = line.rstrip("\n").rstrip("\r")
        if not line.strip():
            return 0

        # Apply command substitution before anything else so the substituted
        # text participates in chain splitting, alias expansion, etc.
        line = expand_command_substitution(line)

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
        return self._run_pipeline(stages)

    def _run_simple(self, stage: str) -> int:
        clean, spec = parse_redirections(stage)
        try:
            argv = shlex.split(clean, posix=True)
        except ValueError as exc:
            print(f"pysh: parse error: {exc}", file=sys.stderr)
            return 2
        if not argv:
            return 0
        if argv[0] in self.BUILTINS:
            return self._dispatch_builtin(argv)
        return self._run_external(argv, spec)

    def _run_pipeline(self, stages: list[str]) -> int:
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

    def _run_external(self, argv: list[str], spec: RedirectionSpec) -> int:
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
        handlers: dict[str, callable] = {
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
            else:
                if token in self.local_vars:
                    os.environ[token] = self.local_vars[token]
                else:
                    os.environ.setdefault(token, "")
        return 0

    def _builtin_source(self, args: list[str]) -> int:
        if not args:
            print("source: filename argument required", file=sys.stderr)
            return 2
        target = Path(os.path.expanduser(args[0]))
        return execute_rc(target, self.execute, quiet_missing=False)

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
        return 0

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

    # ------------------------------------------------------------- presentation
    def _prompt(self) -> str:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
        cwd = Path.cwd()
        try:
            rel = cwd.relative_to(Path.home())
            cwd_str = "~" if str(rel) == "." else "~/" + str(rel)
        except ValueError:
            cwd_str = str(cwd)
        icon = self._prompt_icon()
        return f"{icon} {user}:{cwd_str}$ "

    @staticmethod
    def _prompt_icon() -> str:
        encoding = (locale.getpreferredencoding(False) or "").lower()
        if "utf" in encoding:
            return "\U0001f40d"  # snake emoji
        return "$"

    def _print_banner(self) -> None:
        py_version = ".".join(str(p) for p in sys.version_info[:3])
        use_color = colors_enabled()
        if "utf" in (locale.getpreferredencoding(False) or "").lower():
            line1 = f"\U0001f40d PySH {__version__} | Python {py_version}"
        else:
            line1 = f"PySH {__version__} | Python {py_version}"
        print(diagnostic(line1, "info", enabled=use_color))
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
