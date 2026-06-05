# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the pysh CLI entry point."""
from __future__ import annotations

import pytest

from pysh import __version__
from pysh.cli import is_unsupported_system_shell_invocation, main


def test_version_flag_prints_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_short_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_dash_c_runs_command(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo cli-runs"])
    assert status == 0
    captured = capfd.readouterr()
    assert "cli-runs" in captured.out


@pytest.mark.parametrize(
    "argv0",
    ["sh", "/bin/sh", "dash", "/usr/bin/dash", "ash", "/bin/ash"],
)
def test_system_shell_invocation_names_are_rejected(argv0: str) -> None:
    assert is_unsupported_system_shell_invocation(argv0)


@pytest.mark.parametrize("argv0", ["pysh", "/usr/bin/pysh", "__main__.py", "python"])
def test_normal_invocation_names_are_supported(argv0: str) -> None:
    assert not is_unsupported_system_shell_invocation(argv0)


def test_busybox_sh_invocation_is_rejected() -> None:
    assert is_unsupported_system_shell_invocation("busybox", ["sh"])
    assert is_unsupported_system_shell_invocation("/bin/busybox", ["sh"])


def test_busybox_non_sh_invocation_is_not_rejected() -> None:
    assert not is_unsupported_system_shell_invocation("busybox", ["echo", "ok"])
    assert not is_unsupported_system_shell_invocation("/bin/busybox", [])


def test_main_rejects_sh_argv0(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["sh", "-c", "echo should-not-run"])

    assert main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pysh: unsupported invocation mode: sh" in captured.err
    assert "PySH is not a POSIX /bin/sh provider" in captured.err


def test_main_rejects_busybox_sh_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["busybox", "sh", "-c", "echo should-not-run"])

    assert main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pysh: unsupported invocation mode: busybox" in captured.err
    assert "PySH is not a POSIX /bin/sh provider" in captured.err
