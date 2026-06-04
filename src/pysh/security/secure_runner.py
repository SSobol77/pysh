# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Explicit PTY runner for ``secure <cmd>``.

This module is intentionally separate from the normal external-command path.
It forwards terminal bytes through a child PTY only when the user explicitly
invokes the ``secure`` builtin. It must not parse password prompts, use
stdin-based sudo password modes, log PTY input, store forwarded bytes, or
expose password length.
"""
from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import IO

from pysh.prompt.colors import colorize, parse_color

_HELPER_ENV = "PYSH_SECURE_RUNNER_HELPER"
_HELPER_CONFIG_ENV = "PYSH_SECURE_RUNNER_CONFIG"


@dataclass(frozen=True)
class SensitiveIndicatorConfig:
    """Runtime configuration for the fixed sensitive-input indicator."""

    enabled: bool
    symbol: str
    idle_color: str
    active_color: str
    mode: str
    slots: int
    vga: bool


class KeypressIndicator:
    """Pure formatter for the fixed sensitive-input keypress indicator."""

    def __init__(self, config: SensitiveIndicatorConfig, *, colors: bool) -> None:
        self.config = config
        self.colors = colors
        self._active_slot: int | None = None

    def show_idle(self) -> str:
        """Return the idle indicator rendering."""
        if self.config.mode == "ring":
            self.reset()
            return self.render()
        return self._render_symbol(self.config.idle_color)

    def show_active(self) -> str:
        """Return the active indicator rendering."""
        if self.config.mode == "ring":
            return self.keypress()
        return self._render_symbol(self.config.active_color)

    def render(self) -> str:
        """Return the current fixed-width indicator rendering."""
        if not self.config.enabled:
            return ""
        if self.config.mode != "ring":
            color = (
                self.config.active_color
                if self._active_slot is not None
                else self.config.idle_color
            )
            return self._render_symbol(color)
        parts = []
        for slot in range(self.config.slots):
            color = (
                self.config.active_color
                if slot == self._active_slot
                else self.config.idle_color
            )
            parts.append(self._render_symbol(color))
        return " ".join(parts)

    def keypress(self) -> str:
        """Advance volatile activity state and return the updated rendering."""
        if not self.config.enabled:
            return ""
        if self.config.mode == "ring":
            if self._active_slot is None:
                self._active_slot = 0
            else:
                self._active_slot = (self._active_slot + 1) % self.config.slots
            return self.render()
        self._active_slot = 0
        return self._render_symbol(self.config.active_color)

    def reset(self) -> None:
        """Reset volatile sensitive-phase activity state."""
        self._active_slot = None

    def erase(self) -> str:
        """Return a control sequence that erases the full indicator width."""
        return "\b \b" * self.visible_width()

    def visible_width(self) -> int:
        """Return the number of terminal columns occupied by the indicator."""
        if not self.config.enabled:
            return 0
        if self.config.mode == "ring":
            return self.config.slots + max(0, self.config.slots - 1)
        return 1

    def _render_symbol(self, color: str) -> str:
        if not self.config.enabled:
            return ""
        return colorize(
            self.config.symbol,
            parse_color(color),
            enabled=self.colors,
            vga=self.config.vga,
        )


def colors_enabled_for_fd(fd: int, env: dict[str, str] | None = None) -> bool:
    """Return True when ANSI color is safe on ``fd``."""
    env = os.environ if env is None else env
    if "NO_COLOR" in env:
        return False
    term = env.get("TERM", "")
    if not term or term == "dumb":
        return False
    try:
        return os.isatty(fd)
    except OSError:
        return False


def indicator_config_from_mapping(
    values: dict[str, object],
    *,
    vga: bool = True,
) -> SensitiveIndicatorConfig:
    """Build a runtime indicator config from validated shell storage."""
    return SensitiveIndicatorConfig(
        enabled=bool(values.get("enabled", False)),
        symbol=str(values.get("symbol", "*")),
        idle_color=str(values.get("idle_color", "white")),
        active_color=str(values.get("active_color", "lime")),
        mode=str(values.get("mode", "ring")),
        slots=int(values.get("slots", 5)),
        vga=vga,
    )


class SecureRunner:
    """Run an explicitly requested command behind a PTY bridge."""

    def __init__(
        self,
        config: SensitiveIndicatorConfig,
        *,
        input_fd: int | None = None,
        output_fd: int | None = None,
        env: dict[str, str] | None = None,
        blink_delay: float = 0.03,
        _direct_fork: bool = False,
        _colors_override: bool | None = None,
    ) -> None:
        self.config = config
        self.input_fd = input_fd
        self.output_fd = output_fd
        self.env = env
        self.blink_delay = blink_delay
        self._direct_fork = _direct_fork
        self._colors_override = _colors_override

    def run(self, argv: list[str]) -> int:
        """Run ``argv`` behind a PTY and return the child exit status."""
        if not argv:
            return 2
        if not self._direct_fork and os.environ.get(_HELPER_ENV) != "1":
            return self._run_via_helper(argv)
        return self._run_direct(argv)

    def _run_via_helper(self, argv: list[str]) -> int:
        """Run the PTY bridge in a helper process to isolate fork from PySH."""
        fallback_input: IO[bytes] | None = None
        if self.input_fd is not None:
            in_fd = self.input_fd
        else:
            try:
                in_fd = sys.stdin.fileno()
            except (AttributeError, OSError):
                fallback_input = open(os.devnull, "rb")
                in_fd = fallback_input.fileno()
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        helper_env = dict(os.environ)
        helper_env[_HELPER_ENV] = "1"
        helper_env[_HELPER_CONFIG_ENV] = json.dumps(
            {
                "config": {
                    "enabled": self.config.enabled,
                    "symbol": self.config.symbol,
                    "idle_color": self.config.idle_color,
                    "active_color": self.config.active_color,
                    "mode": self.config.mode,
                    "slots": self.config.slots,
                    "vga": self.config.vga,
                },
                "input_fd": in_fd,
                "output_fd": out_fd,
                "blink_delay": self.blink_delay,
                "colors": colors_enabled_for_fd(out_fd, self.env),
                "env": self.env,
            },
        )
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pysh.security.secure_runner", "--", *argv],
                env=helper_env,
                pass_fds=(in_fd, out_fd),
                close_fds=True,
            )
            try:
                return proc.wait()
            except KeyboardInterrupt:
                proc.send_signal(signal.SIGINT)
                return proc.wait()
        finally:
            if fallback_input is not None:
                fallback_input.close()

    def _run_direct(self, argv: list[str]) -> int:
        fallback_input: IO[bytes] | None = None
        if self.input_fd is not None:
            in_fd = self.input_fd
        else:
            try:
                in_fd = sys.stdin.fileno()
            except (AttributeError, OSError):
                fallback_input = open(os.devnull, "rb")
                in_fd = fallback_input.fileno()
        out_fd = self.output_fd if self.output_fd is not None else sys.stdout.fileno()
        colors = (
            self._colors_override
            if self._colors_override is not None
            else colors_enabled_for_fd(out_fd, self.env)
        )
        indicator = KeypressIndicator(self.config, colors=colors)
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()
        if pid == 0:
            self._child_exec(argv, master_fd, slave_fd)

        os.close(slave_fd)
        old_state: list[int | bytes] | None = None
        restore_input = False
        try:
            if os.isatty(in_fd):
                old_state = termios.tcgetattr(in_fd)
                tty.setraw(in_fd)
                restore_input = True
            return self._parent_bridge(pid, master_fd, in_fd, out_fd, indicator)
        finally:
            if restore_input and old_state is not None:
                termios.tcsetattr(in_fd, termios.TCSADRAIN, old_state)
            try:
                os.close(master_fd)
            except OSError:
                pass
            if fallback_input is not None:
                fallback_input.close()

    @staticmethod
    def _child_exec(argv: list[str], master_fd: int, slave_fd: int) -> None:
        try:
            os.setsid()
            if hasattr(termios, "TIOCSCTTY"):
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(master_fd)
            if slave_fd > 2:
                os.close(slave_fd)
            try:
                os.execvp(argv[0], argv)
            except FileNotFoundError:
                os.write(2, f"secure: {argv[0]}: command not found\r\n".encode())
                os._exit(127)
            except PermissionError as exc:
                os.write(2, f"secure: {argv[0]}: {exc}\r\n".encode())
                os._exit(126)
            except OSError as exc:
                os.write(2, f"secure: {argv[0]}: {exc}\r\n".encode())
                os._exit(126)
        except BaseException:
            os._exit(126)

    def _parent_bridge(
        self,
        pid: int,
        master_fd: int,
        in_fd: int,
        out_fd: int,
        indicator: KeypressIndicator,
    ) -> int:
        visible = False
        stdin_open = True
        input_enabled = self._input_selectable(in_fd)
        status: int | None = None
        try:
            while True:
                echo_disabled = self._echo_disabled(master_fd)
                visible = self._sync_indicator(out_fd, indicator, visible, echo_disabled)
                read_fds = [master_fd]
                if input_enabled and stdin_open:
                    read_fds.append(in_fd)
                ready, _, _ = select.select(read_fds, [], [], 0.05)
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    if visible:
                        self._write_text(out_fd, indicator.erase())
                        visible = False
                    os.write(out_fd, data)
                    if self._echo_disabled(master_fd):
                        visible = self._sync_indicator(out_fd, indicator, visible, True)
                if input_enabled and stdin_open and in_fd in ready:
                    try:
                        data = os.read(in_fd, 4096)
                    except OSError:
                        stdin_open = False
                        data = b""
                    if not data:
                        stdin_open = False
                        try:
                            os.write(master_fd, b"\x04")
                        except OSError:
                            pass
                    else:
                        if self._echo_disabled(master_fd):
                            for _ in data:
                                visible = self._blink(out_fd, indicator, visible)
                        try:
                            os.write(master_fd, data)
                        except OSError:
                            stdin_open = False
                status = self._wait_nonblocking(pid)
                if status is not None:
                    self._drain_master(master_fd, out_fd, indicator, visible)
                    indicator.reset()
                    visible = False
                    break
        except KeyboardInterrupt:
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            status = self._wait_blocking(pid)
        finally:
            if visible:
                self._write_text(out_fd, indicator.erase())
            indicator.reset()
        if status is None:
            status = self._wait_blocking(pid)
        return self._status_to_returncode(status)

    @staticmethod
    def _input_selectable(fd: int) -> bool:
        try:
            os.fstat(fd)
        except OSError:
            return False
        return True

    @staticmethod
    def _echo_disabled(master_fd: int) -> bool:
        try:
            attrs = termios.tcgetattr(master_fd)
        except termios.error:
            return False
        return not bool(attrs[3] & termios.ECHO)

    def _sync_indicator(
        self,
        out_fd: int,
        indicator: KeypressIndicator,
        visible: bool,
        echo_disabled: bool,
    ) -> bool:
        if not self.config.enabled:
            return False
        if echo_disabled and not visible:
            self._write_text(out_fd, indicator.render())
            return True
        if not echo_disabled and visible:
            self._write_text(out_fd, indicator.erase())
            indicator.reset()
            return False
        return visible

    def _blink(
        self,
        out_fd: int,
        indicator: KeypressIndicator,
        visible: bool,
    ) -> bool:
        if not self.config.enabled:
            return False
        if visible:
            self._write_text(out_fd, indicator.erase())
        if self.config.mode == "single-blink":
            self._write_text(out_fd, indicator.show_active())
        else:
            self._write_text(out_fd, indicator.keypress())
        if self.config.mode == "single-blink" and self.blink_delay > 0:
            time.sleep(self.blink_delay)
        if self.config.mode == "single-blink":
            self._write_text(out_fd, indicator.erase())
            indicator.reset()
            self._write_text(out_fd, indicator.show_idle())
        return True

    @staticmethod
    def _wait_nonblocking(pid: int) -> int | None:
        try:
            waited_pid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return 0
        if waited_pid == 0:
            return None
        return status

    @staticmethod
    def _drain_master(
        master_fd: int,
        out_fd: int,
        indicator: KeypressIndicator,
        visible: bool,
    ) -> None:
        while True:
            ready, _, _ = select.select([master_fd], [], [], 0)
            if not ready:
                return
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                return
            if not data:
                return
            if visible:
                os.write(out_fd, indicator.erase().encode("utf-8", errors="replace"))
                visible = False
            os.write(out_fd, data)

    @staticmethod
    def _wait_blocking(pid: int) -> int:
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            return 0
        return status

    @staticmethod
    def _status_to_returncode(status: int) -> int:
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return 128 + os.WTERMSIG(status)
        return 1

    @staticmethod
    def _write_text(fd: int, text: str) -> None:
        if text:
            os.write(fd, text.encode("utf-8", errors="replace"))


def _run_helper(argv: list[str]) -> int:
    """Entry point used by the isolated secure-runner helper subprocess."""
    try:
        raw = os.environ[_HELPER_CONFIG_ENV]
        payload = json.loads(raw)
        config_values = payload["config"]
        config = SensitiveIndicatorConfig(
            enabled=bool(config_values["enabled"]),
            symbol=str(config_values["symbol"]),
            idle_color=str(config_values["idle_color"]),
            active_color=str(config_values["active_color"]),
            mode=str(config_values["mode"]),
            slots=int(config_values["slots"]),
            vga=bool(config_values["vga"]),
        )
        runner = SecureRunner(
            config,
            input_fd=int(payload["input_fd"]),
            output_fd=int(payload["output_fd"]),
            env=payload.get("env"),
            blink_delay=float(payload["blink_delay"]),
            _direct_fork=True,
            _colors_override=bool(payload["colors"]),
        )
        return runner.run(argv)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print("secure: helper configuration error", file=sys.stderr)
        return 126


def main() -> int:
    """Run the secure-runner helper process."""
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if os.environ.get(_HELPER_ENV) != "1":
        print("secure: helper mode required", file=sys.stderr)
        return 126
    return _run_helper(args)


if __name__ == "__main__":
    raise SystemExit(main())
