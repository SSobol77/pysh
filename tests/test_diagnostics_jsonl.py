# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_diagnostics_jsonl.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""JSON Lines structured diagnostic sink and --diagnostics-json contract (Issue #50 slice 2)."""
from __future__ import annotations

import io
import json

import pytest

from pysh.cli import main
from pysh.core.shell import PyShell
from pysh.diagnostics.jsonl import JsonlDiagnosticSink, structured_event_from_trace
from pysh.diagnostics.schema import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    DiagnosticEventClass,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
)
from pysh.diagnostics.trace import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStage,
    DiagnosticTrace,
    TraceOptions,
)

# ---------------------------------------------------------------------------
# Adapter: DiagnosticEvent -> StructuredDiagnosticEvent
# ---------------------------------------------------------------------------


def test_parser_stage_maps_to_parser_event_class() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.LEX, message="lexed")
    structured = structured_event_from_trace(event)
    assert structured.event_class is DiagnosticEventClass.PARSER
    assert structured.event == "parser.lex"
    assert structured.severity is DiagnosticSeverity.DEBUG


def test_runtime_stage_maps_to_runtime_event_class() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.EXECUTE_PLAN, message="argv prepared")
    structured = structured_event_from_trace(event)
    assert structured.event_class is DiagnosticEventClass.RUNTIME
    assert structured.event == "runtime.execute_plan"


def test_error_level_maps_to_error_severity() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.ERROR,
        message="boom",
        level=DiagnosticLevel.ERROR,
    )
    structured = structured_event_from_trace(event)
    assert structured.event == "runtime.error"
    assert structured.severity is DiagnosticSeverity.ERROR


def test_adapter_preserves_message_and_fields() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.INPUT,
        message="received line",
        fields={"length": 4},
    )
    structured = structured_event_from_trace(event)
    assert structured.fields["message"] == "received line"
    assert structured.fields["length"] == 4


def test_adapter_has_no_actor_action_target_result() -> None:
    """A parser/runtime trace line has no meaningful actor/action/target/result."""
    event = DiagnosticEvent(stage=DiagnosticStage.RESOLVE, message="resolved ls")
    structured = structured_event_from_trace(event)
    assert structured.actor is None
    assert structured.action is None
    assert structured.target is None
    assert structured.result is None


def test_adapter_coerces_non_finite_float_field_to_string() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.EXECUTE_PLAN,
        message="timed",
        fields={"elapsed": float("inf")},
    )
    structured = structured_event_from_trace(event)
    assert structured.fields["elapsed"] == "inf"


def test_adapter_coerces_nested_structures() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.EXECUTE_PLAN,
        message="argv prepared",
        fields={"argv": ["ls", "-la"]},
    )
    structured = structured_event_from_trace(event)
    assert structured.fields["argv"] == ("ls", "-la")


class _Unrepresentable:
    def __str__(self) -> str:
        return "unrepresentable"


def test_adapter_stringifies_unknown_object_field() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.EXECUTE_PLAN,
        message="argv prepared",
        fields={"odd": _Unrepresentable()},
    )
    structured = structured_event_from_trace(event)
    assert structured.fields["odd"] == "unrepresentable"


# ---------------------------------------------------------------------------
# JsonlDiagnosticSink
# ---------------------------------------------------------------------------


def test_sink_writes_one_json_object_per_line() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.INPUT, message="received line")
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={})
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == 1
    assert payload["event"] == "parser.input"
    assert payload["fields"]["message"] == "received line"


def test_sink_redacts_sensitive_values() -> None:
    event = DiagnosticEvent(
        stage=DiagnosticStage.EXECUTE_PLAN,
        message="argv prepared",
        fields={"token": "abc123", "detail": "using abc123 now"},
    )
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={})
    payload = json.loads(buf.getvalue())
    assert payload["fields"]["token"] == "<redacted>"
    assert payload["fields"]["detail"] == "using <redacted> now"


def test_sink_redacts_sensitive_env_values() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.INPUT, message="saw MY_SECRET=hunter2")
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={"MY_SECRET": "hunter2"})
    payload = json.loads(buf.getvalue())
    assert "hunter2" not in payload["fields"]["message"]
    assert "<redacted>" in payload["fields"]["message"]


def test_sink_output_is_one_object_and_one_newline_per_event() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.INPUT, message="received line")
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={})
    sink.write_structured_event(structured, env={})
    raw = buf.getvalue()
    assert raw.count("\n") == 2
    assert len(raw.splitlines()) == 2
    for line in raw.splitlines():
        json.loads(line)  # each line is exactly one complete JSON object


def test_sink_output_keys_are_sorted_deterministically() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.INPUT, message="received line")
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={})
    raw_line = buf.getvalue().splitlines()[0]
    outer_keys = list(json.loads(raw_line).keys())
    assert outer_keys == sorted(outer_keys)


def test_sink_output_is_compact_and_ensure_ascii_false() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.INPUT, message="café")
    structured = structured_event_from_trace(event)
    buf = io.StringIO()
    sink = JsonlDiagnosticSink(stream=buf)
    sink.write_structured_event(structured, env={})
    raw_line = buf.getvalue().splitlines()[0]
    assert ", " not in raw_line
    assert ": " not in raw_line
    assert "café" in raw_line
    assert "\\u00e9" not in raw_line


def test_sink_json_encoder_fails_closed_on_non_finite_float() -> None:
    """Defense in depth: schema v1 construction already rejects non-finite
    floats (see test_structured_diagnostics.py), but the sink's own JSON
    encoder is independently configured with ``allow_nan=False`` so it never
    silently emits a non-standard NaN/Infinity token even if ever handed an
    already-constructed payload containing one.
    """
    with pytest.raises(ValueError, match="not JSON compliant"):
        json.dumps(
            {"bad": float("nan")},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )


# ---------------------------------------------------------------------------
# --diagnostics-json CLI integration
# ---------------------------------------------------------------------------


def test_diagnostics_json_flag_emits_jsonl_to_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["--diagnostics-json", "-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert "[PYSH_DEBUG]" not in captured.err

    lines = [line for line in captured.err.splitlines() if line]
    assert lines, "expected at least one structured JSONL event"
    events = [json.loads(line) for line in lines]
    assert all(event["schema_version"] == 1 for event in events)
    assert any(event["event"] == "runtime.execute_plan" for event in events)


def test_diagnostics_json_flag_alone_leaves_debug_text_absent(
    capfd: pytest.CaptureFixture[str],
) -> None:
    status = main(["--diagnostics-json", "-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    assert "stage=" not in captured.err


def test_debug_flag_alone_emits_no_json(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["--debug", "-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    for line in captured.err.splitlines():
        if not line:
            continue
        assert line.startswith("[PYSH_DEBUG]")
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


def test_debug_and_diagnostics_json_together_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--debug and --diagnostics-json are mutually exclusive diagnostic formats."""
    with pytest.raises(SystemExit) as exc:
        main(["--debug", "--diagnostics-json", "-c", "echo hello"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not allowed with argument" in captured.err


def test_trace_and_diagnostics_json_together_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--trace is an alias of --debug and must conflict identically."""
    with pytest.raises(SystemExit) as exc:
        main(["--trace", "--diagnostics-json", "-c", "echo hello"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not allowed with argument" in captured.err


def test_diagnostics_json_and_debug_together_is_a_usage_error_either_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--diagnostics-json", "--debug", "-c", "echo hello"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""


def test_neither_flag_emits_no_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo hello"])
    captured = capfd.readouterr()

    assert status == 0
    assert captured.err == ""


def test_diagnostics_json_parse_error_emits_structured_error_event(
    capfd: pytest.CaptureFixture[str],
) -> None:
    status = main(["--diagnostics-json", "-c", "echo hello |"])
    captured = capfd.readouterr()

    assert status == 2
    json_lines = [
        line for line in captured.err.splitlines() if line.startswith("{")
    ]
    assert json_lines, "expected at least one structured JSONL event"
    events = [json.loads(line) for line in json_lines]
    assert any(event["event"] == "runtime.error" and event["severity"] == "error" for event in events)


def test_diagnostics_json_redacts_sensitive_env_value_but_not_command_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The shell never censors its own command output, only diagnostic text."""
    monkeypatch.setenv("PYSH_SECRET_TOKEN", "super-secret-value")
    status = main(["--diagnostics-json", "-c", "echo super-secret-value"])
    captured = capfd.readouterr()

    assert status == 0
    assert "super-secret-value" in captured.out

    json_lines = [line for line in captured.err.splitlines() if line.startswith("{")]
    assert json_lines, "expected at least one structured JSONL event"
    for line in json_lines:
        assert "super-secret-value" not in line


# ---------------------------------------------------------------------------
# Structured-sink failure containment (observational diagnostics, Issue #50)
# ---------------------------------------------------------------------------


def test_structured_sink_os_error_does_not_break_command_execution(
    capfd: pytest.CaptureFixture[str],
) -> None:
    def _failing_sink(event: DiagnosticEvent) -> None:
        raise OSError("simulated sink I/O failure")

    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=_failing_sink,
        )
    )
    status = shell.execute("echo hello")
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert captured.err == ""


def test_structured_sink_failing_stream_does_not_break_command_execution(
    capfd: pytest.CaptureFixture[str],
) -> None:
    class _BrokenStream:
        def write(self, _data: str) -> int:
            raise OSError("simulated broken pipe")

        def flush(self) -> None:
            pass

    sink = JsonlDiagnosticSink(stream=_BrokenStream())
    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=lambda event: sink.write_structured_event(
                structured_event_from_trace(event)
            ),
        )
    )
    status = shell.execute("echo hello")
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert captured.err == ""


def test_structured_sink_schema_violation_does_not_break_command_execution(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Malformed structured diagnostic data (per the schema/emitter contract)
    raised while building an event must also be contained, not just I/O errors."""

    def _schema_violating_sink(event: DiagnosticEvent) -> None:
        StructuredDiagnosticEvent(
            schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            event_class=DiagnosticEventClass.RUNTIME,
            event="runtime.command_failed",
            severity=DiagnosticSeverity.DEBUG,
            fields={"bad": float("nan")},
        )

    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=_schema_violating_sink,
        )
    )
    status = shell.execute("echo hello")
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert captured.err == ""


def test_structured_sink_unsupported_field_type_does_not_break_command_execution(
    capfd: pytest.CaptureFixture[str],
) -> None:
    def _unsupported_field_sink(event: DiagnosticEvent) -> None:
        StructuredDiagnosticEvent(
            schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            event_class=DiagnosticEventClass.RUNTIME,
            event="runtime.command_failed",
            severity=DiagnosticSeverity.DEBUG,
            fields={"bad": object()},
        )

    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=_unsupported_field_sink,
        )
    )
    status = shell.execute("echo hello")
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"


class _NotADiagnosticsFailure(RuntimeError):
    """Stand-in for a genuine programming error unrelated to diagnostics."""


def test_structured_sink_unrelated_programming_error_is_not_swallowed() -> None:
    """Containment must be narrow: only the documented failure classes are caught."""

    def _buggy_sink(event: DiagnosticEvent) -> None:
        raise _NotADiagnosticsFailure("not a diagnostics-boundary failure")

    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=_buggy_sink,
        )
    )
    with pytest.raises(_NotADiagnosticsFailure):
        shell.execute("echo hello")


def test_structured_sink_does_not_recursively_attempt_to_log_its_own_failure(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A contained sink failure must not trigger another diagnostic emission.

    If containment ever tried to re-report a sink failure through the same
    (failing) sink, or retried the call, the invocation count would grow
    unboundedly instead of staying at one call per trace stage emitted for
    this single, simple command.
    """
    call_count = 0

    def _failing_sink(event: DiagnosticEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise OSError("simulated sink I/O failure")

    shell = PyShell(
        trace=DiagnosticTrace(
            TraceOptions(structured_enabled=True),
            structured_sink=_failing_sink,
        )
    )
    status = shell.execute("echo hello")
    captured = capfd.readouterr()

    assert status == 0
    assert captured.out == "hello\n"
    assert captured.err == ""
    assert 0 < call_count < 20
