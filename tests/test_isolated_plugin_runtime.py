# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_isolated_plugin_runtime.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Process, broker, and failure-containment tests for Issue #44."""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from pysh.plugins.isolated.capabilities import Capability, parse_capability
from pysh.plugins.isolated.errors import LifecycleError
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.manifest import (
    IsolatedPluginManifest,
    validate_isolated_plugin_manifest,
)
from pysh.plugins.isolated.runtime import (
    BASELINE_CHILD_ENVIRONMENT,
    IsolatedPluginRuntime,
    IsolatedPluginState,
    IsolatedResourceLimits,
)

FIXTURE = Path(__file__).parent / "fixtures" / "isolated_plugin.py"


def _manifest(
    mode: str = "normal",
    *arguments: str,
    capabilities: tuple[str, ...] = (),
) -> IsolatedPluginManifest:
    return validate_isolated_plugin_manifest(
        {
            "manifest_version": 1,
            "name": "fixture-plugin",
            "plugin_version": "1.0",
            "protocol_version": 1,
            "entrypoint": [
                str(Path(sys.executable).resolve()),
                str(FIXTURE.resolve()),
                "fixture-plugin",
                "1.0",
                mode,
                *arguments,
            ],
            "requested_capabilities": list(capabilities),
            "resource_class": "test",
        }
    )


def _grants(*declarations: str) -> frozenset[Capability]:
    return frozenset(parse_capability(item) for item in declarations)


def test_spawn_handshake_running_shutdown_and_cwd_cleanup() -> None:
    runtime = IsolatedPluginRuntime(_manifest(), handshake_timeout=1.0, shutdown_timeout=0.5)

    runtime.start()
    working_directory = runtime.working_directory

    assert runtime.state is IsolatedPluginState.RUNNING
    assert runtime.process_id is not None
    assert working_directory is not None and working_directory.is_dir()
    assert stat.S_IMODE(working_directory.stat().st_mode) == 0o700
    assert runtime.shutdown()
    assert runtime.state is IsolatedPluginState.STOPPED
    assert not working_directory.exists()


def test_default_deny_rejects_parent_environment_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSH_TEST_SECRET", "must-not-cross-ipc")
    manifest = _manifest(
        "request_environment",
        "PYSH_TEST_SECRET",
        capabilities=("env.read:PYSH_TEST_SECRET",),
    )
    runtime = IsolatedPluginRuntime(manifest, broker_environment=os.environ)
    try:
        runtime.start()
        result = runtime.serve_once()

        assert not result.ok
        assert result.error_code == "capability_denied"
    finally:
        runtime.close()


def test_explicit_environment_grant_returns_only_named_value() -> None:
    declaration = "env.read:VISIBLE"
    manifest = _manifest("request_environment", "VISIBLE", capabilities=(declaration,))
    runtime = IsolatedPluginRuntime(
        manifest,
        granted_capabilities=_grants(declaration),
        broker_environment={"VISIBLE": "allowed", "HIDDEN": "not-returned"},
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert result.ok
        assert result.payload == {"present": True, "value": "allowed"}
    finally:
        runtime.close()


def test_child_process_environment_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/sensitive/home")
    monkeypatch.setenv("PATH", "/sensitive/path")
    monkeypatch.setenv("PYSH_TEST_SECRET", "must-not-be-inherited")
    reports: list[str] = []
    declaration = "command:report"
    manifest = _manifest("environment_probe", capabilities=(declaration,))
    runtime = IsolatedPluginRuntime(
        manifest,
        granted_capabilities=_grants(declaration),
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
    )
    try:
        runtime.start()
        assert runtime.serve_once().ok
    finally:
        runtime.close()

    child_environment = json.loads(reports[0])
    assert child_environment["PYTHONNOUSERSITE"] == "1"
    assert child_environment["PYTHONUTF8"] == "1"
    assert "HOME" not in child_environment
    assert "PATH" not in child_environment
    assert "PYSH_TEST_SECRET" not in child_environment
    assert set(BASELINE_CHILD_ENVIRONMENT).issubset(child_environment)


def test_child_uses_dedicated_working_directory() -> None:
    reports: list[str] = []
    declaration = "command:report"
    runtime = IsolatedPluginRuntime(
        _manifest("cwd_probe", capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
    )
    try:
        runtime.start()
        dedicated = runtime.working_directory
        assert runtime.serve_once().ok
        assert dedicated is not None
        assert Path(reports[0]) == dedicated
        assert dedicated != Path.cwd()
    finally:
        runtime.close()


def test_unrelated_inheritable_parent_fd_is_closed_in_child(tmp_path: Path) -> None:
    reports: list[str] = []
    extra_fd = os.open(tmp_path / "parent-only", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(extra_fd, True)
    declaration = "command:report"
    runtime = IsolatedPluginRuntime(
        _manifest("fd_probe", str(extra_fd), capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
    )
    try:
        runtime.start()
        assert runtime.serve_once().ok
        assert reports == ["closed"]
    finally:
        runtime.close()
        os.close(extra_fd)


def test_history_read_through_broker_is_denied_by_default(tmp_path: Path) -> None:
    history = tmp_path / ".pysh_history"
    history.write_text("private-history\n", encoding="utf-8")
    declaration = f"fs.read:{tmp_path}"
    runtime = IsolatedPluginRuntime(
        _manifest("request_read", str(history), capabilities=(declaration,))
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert not result.ok
        assert result.error_code == "capability_denied"
        assert history.read_text(encoding="utf-8") == "private-history\n"
    finally:
        runtime.close()


def test_portable_isolation_does_not_claim_same_uid_filesystem_confinement(
    tmp_path: Path,
) -> None:
    """Document direct host authority outside the portable broker contract."""
    secret = tmp_path / "direct-syscall-secret"
    secret.write_text("not-returned-over-ipc", encoding="utf-8")
    declaration = "command:report"
    reports: list[str] = []
    runtime = IsolatedPluginRuntime(
        _manifest("direct_file_probe", str(secret), capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
    )
    try:
        runtime.start()
        assert runtime.serve_once().ok
    finally:
        runtime.close()

    assert reports == ["accessible"]


def test_allowed_filesystem_read_succeeds(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "data.txt"
    target.write_text("allowed-data", encoding="utf-8")
    declaration = f"fs.read:{allowed}"
    runtime = IsolatedPluginRuntime(
        _manifest("request_read", str(target), capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert result.ok
        assert result.payload == {"data": "allowed-data"}
    finally:
        runtime.close()


def test_allowed_filesystem_write_succeeds(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "created.txt"
    declaration = f"fs.write:{allowed}"
    runtime = IsolatedPluginRuntime(
        _manifest(
            "request_write",
            str(target),
            "written-data",
            capabilities=(declaration,),
        ),
        granted_capabilities=_grants(declaration),
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert result.ok
        assert result.payload == {"characters_written": len("written-data")}
        assert target.read_text(encoding="utf-8") == "written-data"
    finally:
        runtime.close()


@pytest.mark.parametrize("escape_kind", ["parent", "prefix", "symlink"])
def test_filesystem_scope_rejects_traversal_prefix_and_symlink_escape(
    tmp_path: Path,
    escape_kind: str,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    if escape_kind == "parent":
        attempted = allowed / ".." / "secret.txt"
    elif escape_kind == "prefix":
        lookalike = tmp_path / "allowed-other"
        lookalike.mkdir()
        attempted = lookalike / "secret.txt"
        attempted.write_text("secret", encoding="utf-8")
    else:
        attempted = allowed / "link"
        attempted.symlink_to(secret)
    declaration = f"fs.read:{allowed}"
    runtime = IsolatedPluginRuntime(
        _manifest("request_read", str(attempted), capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert not result.ok
        assert result.error_code == "capability_denied"
    finally:
        runtime.close()


def test_declared_but_ungranted_network_request_is_denied() -> None:
    declaration = "network.connect:example.com:443"
    runtime = IsolatedPluginRuntime(
        _manifest("request_network", "example.com", "443", capabilities=(declaration,))
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert not result.ok
        assert result.error_code == "capability_denied"
    finally:
        runtime.close()


def test_explicit_network_grant_does_not_expose_a_raw_socket() -> None:
    declaration = "network.connect:example.com:443"
    runtime = IsolatedPluginRuntime(
        _manifest("request_network", "example.com", "443", capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert not result.ok
        assert result.error_code == "operation_unavailable"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "mode",
    [
        "malformed_handshake",
        "oversized_handshake",
        "unknown_handshake",
        "version_mismatch",
        "identity_mismatch",
    ],
)
def test_handshake_violations_terminate_and_are_contained(mode: str) -> None:
    runtime = IsolatedPluginRuntime(_manifest(mode), handshake_timeout=0.5)

    with pytest.raises(LifecycleError, match="handshake"):
        runtime.start()

    assert runtime.state is IsolatedPluginState.FAILED
    assert runtime.working_directory is None


@pytest.mark.parametrize("mode", ["malformed_running", "oversized_running", "unknown_running"])
def test_running_protocol_violations_terminate_and_are_contained(mode: str) -> None:
    runtime = IsolatedPluginRuntime(_manifest(mode), request_timeout=0.5)
    runtime.start()

    with pytest.raises(LifecycleError, match="request"):
        runtime.serve_once()

    assert runtime.state is IsolatedPluginState.FAILED


def test_plugin_crash_does_not_terminate_parent_session() -> None:
    runtime = IsolatedPluginRuntime(_manifest("crash"), request_timeout=0.5)
    runtime.start()

    with pytest.raises(LifecycleError):
        runtime.serve_once()

    assert runtime.state is IsolatedPluginState.FAILED
    assert 6 * 7 == 42


def test_handshake_and_request_hangs_are_bounded() -> None:
    handshake_runtime = IsolatedPluginRuntime(
        _manifest("hang_handshake"),
        handshake_timeout=0.05,
        shutdown_timeout=0.05,
    )
    started = time.monotonic()
    with pytest.raises(LifecycleError):
        handshake_runtime.start()
    assert time.monotonic() - started < 2.0

    request_runtime = IsolatedPluginRuntime(
        _manifest("hang_after_ready"),
        request_timeout=0.05,
        shutdown_timeout=0.05,
    )
    request_runtime.start()
    started = time.monotonic()
    with pytest.raises(LifecycleError):
        request_runtime.serve_once()
    assert time.monotonic() - started < 2.0


def test_shutdown_hang_uses_forced_termination() -> None:
    runtime = IsolatedPluginRuntime(
        _manifest("hang_shutdown"),
        shutdown_timeout=0.05,
    )
    runtime.start()

    started = time.monotonic()
    assert not runtime.shutdown()

    assert time.monotonic() - started < 2.0
    assert runtime.state is IsolatedPluginState.STOPPED


def test_events_expose_identity_grants_denials_and_failures_without_values() -> None:
    events: list[IsolatedPluginEvent] = []
    declaration = "env.read:SECRET_NAME"
    runtime = IsolatedPluginRuntime(
        _manifest("request_environment", "SECRET_NAME", capabilities=(declaration,)),
        event_sink=events.append,
    )
    try:
        runtime.start()
        result = runtime.serve_once()
        assert not result.ok
    finally:
        runtime.close()

    assert [event.kind for event in events[:3]] == [
        IsolatedPluginEventKind.SPAWN,
        IsolatedPluginEventKind.HANDSHAKE,
        IsolatedPluginEventKind.RUNNING,
    ]
    assert any(event.kind is IsolatedPluginEventKind.DENIED for event in events)
    assert events[0].requested_capabilities == (declaration,)
    assert events[0].granted_capabilities == ()
    assert all("must-not" not in repr(event) for event in events)


def test_resource_limit_seam_fails_closed_until_issue_53() -> None:
    runtime = IsolatedPluginRuntime(
        _manifest(),
        resource_limits=IsolatedResourceLimits(memory_bytes=1024),
    )

    with pytest.raises(LifecycleError, match="Issue #53"):
        runtime.start()

    assert runtime.state is IsolatedPluginState.NEW
