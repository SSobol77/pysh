# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_audit_log.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #50 slice 3: opt-in persistent audit log (``--audit-log PATH``).

Distinction asserted here: command *diagnostic metadata* (redacted trace
events) may be audited; child stdout/stderr payloads and protected PTY
input are never routed into the audit file.
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from pysh.cli import main
from pysh.diagnostics.audit import AuditLogError, AuditLogSink
from pysh.diagnostics.schema import (
    DiagnosticEventClass,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
)
from pysh.diagnostics.trace import (
    DiagnosticEvent,
    DiagnosticStage,
    DiagnosticTrace,
    StructuredSinkFanOut,
    TraceOptions,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")


def _event(**fields: object) -> StructuredDiagnosticEvent:
    return StructuredDiagnosticEvent(
        schema_version=1,
        event_class=DiagnosticEventClass.RUNTIME,
        event="runtime.test",
        severity=DiagnosticSeverity.INFO,
        fields=dict(fields),  # type: ignore[arg-type]
    )


def _read_events(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    return [json.loads(line) for line in text.splitlines()]


# --- default-off ----------------------------------------------------------


def test_no_audit_file_without_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["--no-rc", "-c", "echo hi"]) == 0
    assert list(tmp_path.iterdir()) == []


def test_audit_sink_not_opened_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> AuditLogSink:
        raise AssertionError("audit opened without --audit-log")

    monkeypatch.setattr(AuditLogSink, "open", boom)
    assert main(["--no-rc", "-c", "echo hi"]) == 0


# --- creation, permissions, schema ---------------------------------------


@posix_only
def test_creates_private_file_with_schema_v1_events(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "echo hello"]) == 0
    captured = capfd.readouterr()
    assert captured.out == "hello\n"
    assert captured.err == ""
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    events = _read_events(audit)
    assert all(e["schema_version"] == 1 for e in events)
    assert events[0]["event"] == "startup.session_started"
    assert events[0]["event_class"] == "startup"
    assert events[0]["severity"] == "info"
    assert events[0]["fields"] == {"invocation_mode": "command", "no_rc": True}
    assert any(e["event"] == "runtime.execute_plan" for e in events)
    assert any(e["event"] == "parser.input" for e in events)


def test_lines_use_deterministic_encoding(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "echo hello"]) == 0
    for line in audit.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert line == json.dumps(
            obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )


@posix_only
def test_existing_file_is_appended_not_truncated(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    audit.write_text("PRIOR\n", encoding="utf-8")
    audit.chmod(0o600)
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "true"]) == 0
    assert audit.read_text(encoding="utf-8").startswith("PRIOR\n")
    first_len = len(audit.read_text(encoding="utf-8"))
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "true"]) == 0
    assert len(audit.read_text(encoding="utf-8")) > first_len


# --- exit status / stdout ------------------------------------------------


def test_exit_status_preserved(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "sh -c 'exit 7'"]) == 7


def test_child_stdout_is_not_copied_into_audit(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--audit-log", str(audit), "-c", "printf 'OUTPUT%s\\n' PAYLOAD"]) == 0
    assert capfd.readouterr().out == "OUTPUTPAYLOAD\n"
    assert "OUTPUTPAYLOAD" not in audit.read_text(encoding="utf-8")


# --- disk-level redaction ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PYSH_SECRET_TOKEN", "super-secret-value"),
        ("TOKEN", "x"),
        ("My_Api_Key", "mixed-case-secret"),
        ("PYSH_SECRET_PATTERN", "a.*b"),
    ],
)
def test_secret_never_reaches_disk(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--audit-log", str(audit), "-c", f"echo {value}"]) == 0
    assert capfd.readouterr().out.strip() == value
    raw = audit.read_bytes().decode("utf-8")
    assert "<redacted>" in raw
    if len(value) > 1:
        assert value not in raw
    for event in _read_events(audit):
        assert value not in json.dumps(event["fields"]) or len(value) == 1


def test_nested_fields_redacted_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "nested-secret-value")
    sink = AuditLogSink.open(tmp_path / "a.jsonl")
    sink.write_structured_event(
        _event(outer={"inner": ["has nested-secret-value here"], "password": "pw"})
    )
    sink.close()
    raw = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "nested-secret-value" not in raw
    assert '"pw"' not in raw
    assert "<redacted>" in raw


# --- open failures -------------------------------------------------------


def test_missing_parent_fails_before_execution(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "ran"
    target = tmp_path / "missing" / "audit.jsonl"
    rc = main(["--no-rc", "--audit-log", str(target), "-c", f"touch {marker}"])
    captured = capfd.readouterr()
    assert rc == 1
    assert not marker.exists()
    assert not target.parent.exists()
    assert captured.out == ""
    assert captured.err.startswith("pysh: audit-log: cannot open audit log")
    assert "Traceback" not in captured.err


def test_directory_path_rejected(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    rc = main(["--no-rc", "--audit-log", str(tmp_path), "-c", "echo hi"])
    captured = capfd.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "pysh: audit-log:" in captured.err


@posix_only
def test_symlink_rejected_and_target_untouched(tmp_path: Path) -> None:
    target = tmp_path / "target.log"
    target.write_text("KEEP\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "link.log"
    link.symlink_to(target)
    with pytest.raises(AuditLogError, match="symbolic link"):
        AuditLogSink.open(link)
    assert target.read_text(encoding="utf-8") == "KEEP\n"


@posix_only
def test_fifo_rejected_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(AuditLogError):
        AuditLogSink.open(fifo)


@posix_only
def test_device_rejected() -> None:
    with pytest.raises(AuditLogError, match="regular file"):
        AuditLogSink.open("/dev/null")


@posix_only
def test_insecure_existing_file_rejected_not_chmodded(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    audit.write_text("", encoding="utf-8")
    audit.chmod(0o644)
    with pytest.raises(AuditLogError, match="permissions"):
        AuditLogSink.open(audit)
    assert stat.S_IMODE(audit.stat().st_mode) == 0o644


# --- lifecycle / mid-run failure ----------------------------------------


@posix_only
def test_close_releases_descriptor_and_is_idempotent(tmp_path: Path) -> None:
    sink = AuditLogSink.open(tmp_path / "a.jsonl")
    fd = sink._fd
    assert fd is not None
    sink.close()
    sink.close()
    assert sink.closed
    with pytest.raises(OSError):
        os.fstat(fd)
    sink.write_structured_event(_event())  # no-op after close, no raise


def test_cli_closes_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[AuditLogSink] = []
    real_open = AuditLogSink.open.__func__  # type: ignore[attr-defined]

    def spy(cls: type[AuditLogSink], path: str) -> AuditLogSink:
        sink = real_open(cls, path)
        opened.append(sink)
        return sink

    monkeypatch.setattr(AuditLogSink, "open", classmethod(spy))
    assert main(["--no-rc", "--audit-log", str(tmp_path / "a.jsonl"), "-c", "true"]) == 0
    assert opened and opened[0].closed


@posix_only
def test_write_failure_disables_sink_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "ro.jsonl"
    path.write_text("", encoding="utf-8")
    fd = os.open(path, os.O_RDONLY)  # writes to this descriptor fail with EBADF
    sink = AuditLogSink(fd, str(path))
    sink.write_structured_event(_event())
    assert sink.failed
    assert sink.closed
    sink.write_structured_event(_event())  # terminal: no retry, no raise
    assert path.read_text(encoding="utf-8") == ""


@posix_only
def test_midrun_write_failure_contained_in_cli(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ro.jsonl"
    path.write_text("", encoding="utf-8")
    sinks: list[AuditLogSink] = []

    def fake_open(_cls: type[AuditLogSink], _p: str) -> AuditLogSink:
        sink = AuditLogSink(os.open(path, os.O_RDONLY), str(path))
        sinks.append(sink)
        return sink

    monkeypatch.setattr(AuditLogSink, "open", classmethod(fake_open))
    rc = main(["--no-rc", "--audit-log", "ignored", "-c", "sh -c 'exit 5'"])
    captured = capfd.readouterr()
    assert rc == 5
    assert captured.out == ""
    assert captured.err == ""
    assert sinks[0].failed and sinks[0].closed


def test_fan_out_isolates_failing_sink() -> None:
    received: list[str] = []

    def bad(_e: DiagnosticEvent) -> None:
        raise OSError("broken")

    trace = DiagnosticTrace(
        TraceOptions(structured_enabled=True),
        structured_sink=StructuredSinkFanOut(bad, lambda e: received.append(e.message)),
    )
    trace.emit(DiagnosticStage.INPUT, "one")
    trace.emit(DiagnosticStage.INPUT, "two")
    assert received == ["one", "two"]


def test_fan_out_preserves_order() -> None:
    order: list[str] = []
    fan = StructuredSinkFanOut(lambda _e: order.append("a"), lambda _e: order.append("b"))
    fan(DiagnosticEvent(stage=DiagnosticStage.INPUT, message="m"))
    assert order == ["a", "b"]


# --- flag combinations ---------------------------------------------------


def test_combined_with_debug(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--debug", "--audit-log", str(audit), "-c", "echo hello"]) == 0
    captured = capfd.readouterr()
    assert captured.out == "hello\n"
    assert "[PYSH_DEBUG]" in captured.err
    assert _read_events(audit)[0]["event"] == "startup.session_started"


def test_combined_with_diagnostics_json(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    audit = tmp_path / "audit.jsonl"
    assert main(["--no-rc", "--diagnostics-json", "--audit-log", str(audit), "-c", "echo hello"]) == 0
    captured = capfd.readouterr()
    assert captured.out == "hello\n"
    stderr_events = [json.loads(line) for line in captured.err.splitlines()]
    audit_events = _read_events(audit)
    assert audit_events[0]["event"] == "startup.session_started"
    assert audit_events[1:] == stderr_events


def test_debug_and_diagnostics_json_still_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--debug", "--diagnostics-json", "--audit-log", str(tmp_path / "a"), "-c", "true"])
    assert exc.value.code == 2
    assert not (tmp_path / "a").exists()


# --- protected input boundary -------------------------------------------


def test_security_layer_has_no_diagnostics_channel() -> None:
    """Structural proof: the PTY/secure path cannot reach the audit sink.

    ``pysh.security`` must not import the diagnostics package nor reference
    trace/audit objects, so protected PTY bytes have no route into events.
    """
    import pysh.security.secure_runner as secure_runner

    source = Path(secure_runner.__file__).read_text(encoding="utf-8")
    for needle in ("pysh.diagnostics", "DiagnosticTrace", "AuditLogSink", "audit"):
        assert needle not in source


def test_secure_command_records_no_protected_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    secret = "hunter2-protected-bytes"
    monkeypatch.setattr(sys, "stdin", io.StringIO(secret + "\n"))
    audit = tmp_path / "audit.jsonl"
    main(["--no-rc", "--audit-log", str(audit), "-c", "secure true"])
    capfd.readouterr()
    assert secret not in audit.read_text(encoding="utf-8")
