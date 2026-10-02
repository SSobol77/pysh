# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_isolated_plugin_diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #50: isolated-plugin lifecycle/capability events as structured diagnostics."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from pysh.diagnostics.audit import AuditLogSink
from pysh.diagnostics.jsonl import JsonlDiagnosticSink
from pysh.diagnostics.schema import (
    DiagnosticEventClass,
    DiagnosticResult,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
)
from pysh.plugins.isolated.capabilities import Capability, parse_capability
from pysh.plugins.isolated.diagnostics import (
    make_structured_plugin_event_sink,
    structured_event_from_isolated_plugin_event,
)
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.manifest import (
    IsolatedPluginManifest,
    validate_isolated_plugin_manifest,
)
from pysh.plugins.isolated.runtime import IsolatedPluginRuntime, IsolatedPluginState

FIXTURE = Path(__file__).parent / "fixtures" / "isolated_plugin.py"
SECRET = "plugin-super-secret"


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


def _event(kind: IsolatedPluginEventKind, **kwargs: object) -> IsolatedPluginEvent:
    return IsolatedPluginEvent(kind=kind, plugin_name="demo-plugin", **kwargs)  # type: ignore[arg-type]


# --- A. adapter mapping -----------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "name", "severity", "result"),
    [
        (IsolatedPluginEventKind.SPAWN, "plugin.spawn", DiagnosticSeverity.INFO, DiagnosticResult.SUCCESS),
        (IsolatedPluginEventKind.HANDSHAKE, "plugin.handshake", DiagnosticSeverity.INFO, DiagnosticResult.SUCCESS),
        (IsolatedPluginEventKind.RUNNING, "plugin.running", DiagnosticSeverity.INFO, DiagnosticResult.SUCCESS),
        (IsolatedPluginEventKind.STOPPED, "plugin.stopped", DiagnosticSeverity.INFO, DiagnosticResult.SUCCESS),
    ],
)
def test_lifecycle_mapping(
    kind: IsolatedPluginEventKind,
    name: str,
    severity: DiagnosticSeverity,
    result: DiagnosticResult,
) -> None:
    mapped = structured_event_from_isolated_plugin_event(_event(kind))

    assert mapped.event_class is DiagnosticEventClass.PLUGIN
    assert mapped.event == name
    assert mapped.severity is severity
    assert mapped.result is result
    assert mapped.actor == "demo-plugin"
    assert mapped.action is None
    assert mapped.target is None


def test_failure_mapping_preserves_reason_code() -> None:
    mapped = structured_event_from_isolated_plugin_event(
        _event(IsolatedPluginEventKind.FAILURE, reason_code="handshake_failed")
    )

    assert mapped.event == "plugin.failure"
    assert mapped.event_class is DiagnosticEventClass.PLUGIN
    assert mapped.severity is DiagnosticSeverity.ERROR
    assert mapped.result is DiagnosticResult.FAILURE
    assert mapped.reason_code == "handshake_failed"


def test_forced_stop_asserts_no_result() -> None:
    mapped = structured_event_from_isolated_plugin_event(
        _event(IsolatedPluginEventKind.STOPPED, reason_code="forced")
    )

    assert mapped.severity is DiagnosticSeverity.WARNING
    assert mapped.result is None
    assert mapped.reason_code == "forced"


def test_denied_mapping_is_security_event_with_operation_action() -> None:
    mapped = structured_event_from_isolated_plugin_event(
        _event(
            IsolatedPluginEventKind.DENIED,
            operation="request.environment",
            reason_code="capability_denied",
        )
    )

    assert mapped.event_class is DiagnosticEventClass.SECURITY
    assert mapped.event == "security.capability_denied"
    assert mapped.severity is DiagnosticSeverity.WARNING
    assert mapped.actor == "demo-plugin"
    assert mapped.action == "request.environment"
    assert mapped.result is DiagnosticResult.DENIED
    assert mapped.reason_code == "capability_denied"


def test_grant_mapping_carries_bounded_capability_labels() -> None:
    mapped = structured_event_from_isolated_plugin_event(
        _event(
            IsolatedPluginEventKind.GRANTED,
            requested_capabilities=("command:report", "env.read:HOME"),
            granted_capabilities=("command:report",),
        )
    )

    assert mapped.event_class is DiagnosticEventClass.SECURITY
    assert mapped.event == "security.capability_granted"
    assert mapped.severity is DiagnosticSeverity.INFO
    assert mapped.actor == "demo-plugin"
    assert mapped.action == "capability_grant"
    assert mapped.result is DiagnosticResult.SUCCESS
    assert dict(mapped.fields) == {
        "requested_capabilities": ("command:report", "env.read:HOME"),
        "granted_capabilities": ("command:report",),
    }


def test_every_event_kind_has_a_mapping() -> None:
    for kind in IsolatedPluginEventKind:
        mapped = structured_event_from_isolated_plugin_event(_event(kind))
        assert isinstance(mapped, StructuredDiagnosticEvent)


# --- C. redaction ------------------------------------------------------------


def _run_once(manifest: IsolatedPluginManifest, destinations: tuple[object, ...], **kwargs: object) -> None:
    def fan_out(event: StructuredDiagnosticEvent) -> None:
        for destination in destinations:
            destination.write_structured_event(event)  # type: ignore[attr-defined]

    runtime = IsolatedPluginRuntime(
        manifest,
        event_sink=make_structured_plugin_event_sink(fan_out),
        **kwargs,  # type: ignore[arg-type]
    )
    try:
        runtime.start()
        runtime.serve_once()
    finally:
        runtime.close()


def test_environment_decision_events_exclude_value_but_keep_name(tmp_path: Path) -> None:
    stream = io.StringIO()
    audit_path = tmp_path / "audit.jsonl"
    audit = AuditLogSink.open(audit_path)
    declaration = "env.read:SECRET_TOKEN"
    for granted in (frozenset[Capability](), _grants(declaration)):
        _run_once(
            _manifest("request_environment", "SECRET_TOKEN", capabilities=(declaration,)),
            (JsonlDiagnosticSink(stream), audit),
            granted_capabilities=granted,
            broker_environment={"SECRET_TOKEN": SECRET},
        )
    audit.close()

    for output in (stream.getvalue(), audit_path.read_text(encoding="utf-8")):
        assert SECRET not in output  # the value is payload
        assert declaration in output  # the declared NAME is authorization metadata


def test_filesystem_decision_events_exclude_file_contents(tmp_path: Path) -> None:
    file_secret = "plugin-file-super-secret"
    secret_file = tmp_path / "data.txt"
    secret_file.write_text(file_secret, encoding="utf-8")
    declaration = f"fs.read:{tmp_path}"
    assert parse_capability(declaration) in _grants(declaration)  # label embeds the root
    stream = io.StringIO()
    audit_path = tmp_path / "audit.jsonl"
    audit = AuditLogSink.open(audit_path)
    for granted in (frozenset[Capability](), _grants(declaration)):
        _run_once(
            _manifest("request_read", str(secret_file), capabilities=(declaration,)),
            (JsonlDiagnosticSink(stream), audit),
            granted_capabilities=granted,
        )
    audit.close()

    for output in (stream.getvalue(), audit_path.read_text(encoding="utf-8")):
        assert file_secret not in output  # file contents are payload
        # The canonical declaration may carry the declared root: authorization metadata.
        assert declaration in output
        # The IPC request payload (the specific file requested) is not copied.
        assert str(secret_file) not in output


def test_command_decision_events_exclude_argv_and_output(
    capfd: pytest.CaptureFixture[str],
) -> None:
    argument = "ultra-secret-command-argument"
    output_marker = "ultra-secret-command-output"
    received: list[str] = []

    def handler(argv: list[str]) -> int:
        received.extend(argv)
        print(output_marker)
        print(output_marker, file=sys.stderr)
        return 0

    declaration = "command:report"
    stream = io.StringIO()
    _run_once(
        _manifest("report_args", argument, capabilities=(declaration,)),
        (JsonlDiagnosticSink(stream),),
        granted_capabilities=_grants(declaration),
        command_handlers={"report": handler},
    )

    assert received == [argument]  # the real request reached the handler
    captured = capfd.readouterr()
    assert output_marker in captured.out + captured.err  # handler output really happened
    output = stream.getvalue()
    assert declaration in output  # the declaration is authorization metadata
    assert argument not in output
    assert output_marker not in output


def test_grant_event_serializes_through_canonical_jsonl_schema() -> None:
    stream = io.StringIO()
    sink = JsonlDiagnosticSink(stream)
    event_sink = make_structured_plugin_event_sink(sink.write_structured_event)

    event_sink(
        _event(
            IsolatedPluginEventKind.GRANTED,
            requested_capabilities=("env.read:API_TOKEN",),
            granted_capabilities=("env.read:API_TOKEN",),
        )
    )

    line = json.loads(stream.getvalue())
    assert line["schema_version"] == 1
    assert line["fields"]["granted_capabilities"] == ["env.read:API_TOKEN"]


# --- D. real runtime -> sink -> JSONL / audit --------------------------------


def _jsonl(text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in text.splitlines()]


def test_runtime_startup_and_grant_lifecycle_reaches_jsonl() -> None:
    stream = io.StringIO()
    sink = JsonlDiagnosticSink(stream)
    declaration = "env.read:VISIBLE"
    runtime = IsolatedPluginRuntime(
        _manifest("request_environment", "VISIBLE", capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
        broker_environment={"VISIBLE": "allowed"},
        event_sink=make_structured_plugin_event_sink(sink.write_structured_event),
    )
    try:
        runtime.start()
        assert runtime.serve_once().ok
    finally:
        runtime.close()

    events = _jsonl(stream.getvalue())
    assert [item["event"] for item in events] == [
        "plugin.spawn",
        "security.capability_granted",
        "plugin.handshake",
        "plugin.running",
        "plugin.stopped",
    ]
    granted = events[1]
    assert granted["actor"] == "fixture-plugin"
    assert granted["action"] == "capability_grant"
    assert granted["result"] == "success"
    assert granted["fields"] == {
        "requested_capabilities": [declaration],
        "granted_capabilities": [declaration],
    }
    assert "allowed" not in stream.getvalue()


def test_runtime_denial_reaches_audit_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit = AuditLogSink.open(audit_path)
    declaration = "env.read:SECRET_TOKEN"
    runtime = IsolatedPluginRuntime(
        _manifest("request_environment", "SECRET_TOKEN", capabilities=(declaration,)),
        broker_environment={"SECRET_TOKEN": SECRET},
        event_sink=make_structured_plugin_event_sink(audit.write_structured_event),
    )
    try:
        runtime.start()
        result = runtime.serve_once()
        assert not result.ok
    finally:
        runtime.close()
        audit.close()

    content = audit_path.read_text(encoding="utf-8")
    assert SECRET not in content
    assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600
    events = _jsonl(content)
    denied = [item for item in events if item["event"] == "security.capability_denied"]
    assert len(denied) == 1
    assert denied[0]["event_class"] == "security"
    assert denied[0]["result"] == "denied"
    assert denied[0]["reason_code"] == "capability_denied"
    assert denied[0]["action"] == "request.environment"
    granted = [item for item in events if item["event"] == "security.capability_granted"]
    assert len(granted) == 1
    assert granted[0]["fields"]["granted_capabilities"] == []


def test_runtime_failure_reaches_jsonl() -> None:
    stream = io.StringIO()
    sink = JsonlDiagnosticSink(stream)
    runtime = IsolatedPluginRuntime(
        _manifest("malformed_handshake"),
        handshake_timeout=0.5,
        event_sink=make_structured_plugin_event_sink(sink.write_structured_event),
    )
    with pytest.raises(Exception, match="handshake"):
        runtime.start()

    events = _jsonl(stream.getvalue())
    failures = [item for item in events if item["event"] == "plugin.failure"]
    assert len(failures) == 1
    assert failures[0]["severity"] == "error"
    assert failures[0]["result"] == "failure"
    assert failures[0]["reason_code"] == "handshake_failed"
    assert runtime.state is IsolatedPluginState.FAILED


# --- E. failure isolation -----------------------------------------------------


def test_sink_failure_does_not_replace_runtime_result() -> None:
    def broken_sink(_event: StructuredDiagnosticEvent) -> None:
        raise OSError("disk full")

    declaration = "env.read:VISIBLE"
    runtime = IsolatedPluginRuntime(
        _manifest("request_environment", "VISIBLE", capabilities=(declaration,)),
        granted_capabilities=_grants(declaration),
        broker_environment={"VISIBLE": "allowed"},
        event_sink=make_structured_plugin_event_sink(broken_sink),
    )
    try:
        runtime.start()
        result = runtime.serve_once()

        assert runtime.state is IsolatedPluginState.RUNNING
        assert result.ok
        assert result.payload == {"present": True, "value": "allowed"}
    finally:
        runtime.close()
    assert runtime.state is IsolatedPluginState.STOPPED


def test_malformed_mapping_is_contained_but_programming_errors_propagate() -> None:
    delivered: list[StructuredDiagnosticEvent] = []
    contained = make_structured_plugin_event_sink(delivered.append)
    # Empty plugin name makes schema validation raise ValueError: contained.
    contained(IsolatedPluginEvent(kind=IsolatedPluginEventKind.SPAWN, plugin_name=""))
    assert delivered == []

    def buggy(_event: StructuredDiagnosticEvent) -> None:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        make_structured_plugin_event_sink(buggy)(_event(IsolatedPluginEventKind.SPAWN))


def test_audit_write_failure_mid_run_does_not_break_plugin_runtime(tmp_path: Path) -> None:
    audit = AuditLogSink.open(tmp_path / "audit.jsonl")
    os.close(audit._fd)  # type: ignore[arg-type]  # simulate a descriptor failure mid-session
    runtime = IsolatedPluginRuntime(
        _manifest(),
        event_sink=make_structured_plugin_event_sink(audit.write_structured_event),
    )
    try:
        runtime.start()
        assert runtime.state is IsolatedPluginState.RUNNING
    finally:
        runtime.close()
    assert audit.failed
