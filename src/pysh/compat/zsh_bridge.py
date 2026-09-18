# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/compat/zsh_bridge.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Optional bridge for delegating transition commands to real zsh."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_ZSH_TIMEOUT_SECONDS = 30.0
ZSH_MISSING_STATUS = 127
ZSH_TIMEOUT_STATUS = 124


@dataclass(frozen=True)
class ZshResult:
    """Structured result returned by :class:`ZshBridge`."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


class ZshBridge:
    """Execute commands through ``zsh -lc`` when zsh is available."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = shutil.which(executable or "zsh")

    @property
    def available(self) -> bool:
        """Return whether a zsh executable was found on PATH."""
        return self.executable is not None

    def execute(
        self,
        command: str,
        *,
        timeout: float = DEFAULT_ZSH_TIMEOUT_SECONDS,
    ) -> ZshResult:
        """Run ``command`` through ``zsh -lc`` and capture its output."""
        if self.executable is None:
            return ZshResult(
                command=command,
                returncode=ZSH_MISSING_STATUS,
                stdout="",
                stderr="pysh: zsh: command not found\n",
                timed_out=False,
            )
        try:
            completed = subprocess.run(  # noqa: S603 - user-issued zsh command
                [self.executable, "-lc", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_timeout_stream(exc.stdout)
            stderr = _decode_timeout_stream(exc.stderr)
            stderr += f"pysh: zsh: command timed out after {timeout:g}s\n"
            return ZshResult(
                command=command,
                returncode=ZSH_TIMEOUT_STATUS,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )
        except FileNotFoundError:
            return ZshResult(
                command=command,
                returncode=ZSH_MISSING_STATUS,
                stdout="",
                stderr="pysh: zsh: command not found\n",
                timed_out=False,
            )
        except PermissionError as exc:
            return ZshResult(
                command=command,
                returncode=126,
                stdout="",
                stderr=f"pysh: zsh: {exc}\n",
                timed_out=False,
            )
        except OSError as exc:
            return ZshResult(
                command=command,
                returncode=ZSH_MISSING_STATUS,
                stdout="",
                stderr=f"pysh: zsh: {exc}\n",
                timed_out=False,
            )
        return ZshResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )


def _decode_timeout_stream(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")
