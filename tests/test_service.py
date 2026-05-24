# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the svc service client."""
from __future__ import annotations

import signal
from pathlib import Path

import pytest

from pysh.service import (
    ServiceClient,
    ServiceController,
    ServiceError,
    format_list,
    format_status,
)
from pysh.shell import PyShell


def _write_pid(root: Path, name: str, pid: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{name}.pid"
    p.write_text(f"{pid}\n", encoding="utf-8")
    return p


def test_status_returns_dead_when_no_pid_file(tmp_path: Path) -> None:
    client = ServiceClient(tmp_path, alive_check=lambda _pid: True)
    status = client.status("missing")
    assert status.pid is None
    assert status.active is False


def test_status_returns_active_when_pid_alive(tmp_path: Path) -> None:
    _write_pid(tmp_path, "alpha", 4242)
    client = ServiceClient(tmp_path, alive_check=lambda _pid: True)
    status = client.status("alpha")
    assert status.pid == 4242
    assert status.active is True


def test_status_returns_dead_when_pid_not_alive(tmp_path: Path) -> None:
    _write_pid(tmp_path, "beta", 4242)
    client = ServiceClient(tmp_path, alive_check=lambda _pid: False)
    status = client.status("beta")
    assert status.pid == 4242
    assert status.active is False


def test_list_services_returns_all_pid_files(tmp_path: Path) -> None:
    _write_pid(tmp_path, "alpha", 1)
    _write_pid(tmp_path, "beta", 2)
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")
    client = ServiceClient(tmp_path, alive_check=lambda _pid: True)
    names = sorted(s.name for s in client.list_services())
    assert names == ["alpha", "beta"]


def test_list_services_empty_when_root_missing(tmp_path: Path) -> None:
    client = ServiceClient(tmp_path / "nope")
    assert client.list_services() == []


def test_stop_signals_pid(tmp_path: Path) -> None:
    _write_pid(tmp_path, "gamma", 999)
    signals: list[tuple[int, int]] = []
    client = ServiceClient(
        tmp_path,
        alive_check=lambda _pid: True,
        signaler=lambda pid, sig: signals.append((pid, sig)),
    )
    client.stop("gamma")
    assert signals == [(999, signal.SIGTERM)]


def test_stop_no_pid_file_raises(tmp_path: Path) -> None:
    client = ServiceClient(tmp_path)
    with pytest.raises(ServiceError):
        client.stop("nothing")


def test_restart_without_controller_raises(tmp_path: Path) -> None:
    _write_pid(tmp_path, "delta", 555)
    client = ServiceClient(
        tmp_path,
        alive_check=lambda _pid: True,
        signaler=lambda _pid, _sig: None,
    )
    with pytest.raises(ServiceError) as exc:
        client.restart("delta")
    assert "supervision" in str(exc.value)


def test_restart_with_controller_succeeds(tmp_path: Path) -> None:
    _write_pid(tmp_path, "eps", 111)
    starts: list[str] = []

    class FakeController(ServiceController):
        def start(self, name: str) -> None:
            starts.append(name)

    client = ServiceClient(
        tmp_path,
        alive_check=lambda _pid: True,
        signaler=lambda _pid, _sig: None,
        controller=FakeController(),
    )
    client.restart("eps")
    assert starts == ["eps"]


def test_start_without_controller_is_unsupported(tmp_path: Path) -> None:
    client = ServiceClient(tmp_path)
    with pytest.raises(ServiceError) as exc:
        client.start("anything")
    assert "control interface" in str(exc.value)


def test_format_status_includes_state_and_pid(tmp_path: Path) -> None:
    _write_pid(tmp_path, "alpha", 12)
    client = ServiceClient(tmp_path, alive_check=lambda _pid: True)
    line = format_status(client.status("alpha"))
    assert "alpha" in line
    assert "active" in line
    assert "12" in line


def test_format_list_handles_empty(tmp_path: Path) -> None:
    client = ServiceClient(tmp_path / "absent")
    assert "no services" in format_list(client.list_services())


# ------------------------------------------------------ integration with shell
def test_svc_list_via_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pid(tmp_path, "alpha", 1)
    client = ServiceClient(tmp_path, alive_check=lambda _pid: True)
    shell = PyShell(service_client=client)
    assert shell.execute("svc list") == 0
    captured = capsys.readouterr()
    assert "alpha" in captured.out


def test_svc_start_reports_unsupported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shell = PyShell(service_client=ServiceClient(tmp_path))
    status = shell.execute("svc start anything")
    assert status == 1
    captured = capsys.readouterr()
    assert "control interface" in captured.err


def test_svc_usage_when_no_args(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    shell = PyShell(service_client=ServiceClient(tmp_path))
    assert shell.execute("svc") == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err


def test_svc_unknown_action(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    shell = PyShell(service_client=ServiceClient(tmp_path))
    assert shell.execute("svc reboot") == 2
    captured = capsys.readouterr()
    assert "unknown action" in captured.err
