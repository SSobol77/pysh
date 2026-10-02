# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_structured_diagnostics.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Structured diagnostics schema v1, redaction, and emitter contract (Issue #50)."""
from __future__ import annotations

import math

import pytest

from pysh.diagnostics.emitter import DiagnosticEmitter
from pysh.diagnostics.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy
from pysh.diagnostics.schema import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    DiagnosticEventClass,
    DiagnosticResult,
    DiagnosticSeverity,
    StructuredDiagnosticEvent,
    to_json_compatible,
)
from pysh.diagnostics.trace import (
    DEFAULT_REDACTION_POLICY as TRACE_DEFAULT_REDACTION_POLICY,
)
from pysh.diagnostics.trace import (
    REDACTED_PLACEHOLDER as TRACE_REDACTED_PLACEHOLDER,
)
from pysh.diagnostics.trace import (
    DiagnosticEvent,
    DiagnosticStage,
    TraceOptions,
    format_trace_event,
)
from pysh.diagnostics.trace import RedactionPolicy as TraceRedactionPolicy

# ---------------------------------------------------------------------------
# A. Schema
# ---------------------------------------------------------------------------


def test_schema_version_is_exactly_one() -> None:
    assert DIAGNOSTIC_EVENT_SCHEMA_VERSION == 1


def test_all_required_event_classes_exist() -> None:
    required = {
        "startup",
        "parser",
        "runtime",
        "plugin",
        "security",
        "resource",
        "package",
        "ai",
        "remote",
    }
    assert {member.value for member in DiagnosticEventClass} == required


def test_valid_event_creation() -> None:
    event = StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=DiagnosticEventClass.RUNTIME,
        event="runtime.command_failed",
        severity=DiagnosticSeverity.ERROR,
        actor="pysh.core.shell",
        action="execute",
        target="ls -z",
        result=DiagnosticResult.FAILURE,
        reason_code="command_not_found",
        fields={"exit_code": 127},
    )
    assert event.schema_version == 1
    assert event.event == "runtime.command_failed"
    assert event.fields["exit_code"] == 127


def test_deterministic_payload_structure() -> None:
    event = StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=DiagnosticEventClass.STARTUP,
        event="startup.policy_selected",
        severity=DiagnosticSeverity.INFO,
        actor="pysh.config",
        action="select_policy",
        target="default",
        result=DiagnosticResult.SUCCESS,
        fields={"policy": "default", "flags": ("a", "b")},
    )
    emitter = DiagnosticEmitter()
    payload = emitter.to_payload(event)
    assert payload == {
        "schema_version": 1,
        "event_class": "startup",
        "event": "startup.policy_selected",
        "severity": "info",
        "actor": "pysh.config",
        "action": "select_policy",
        "target": "default",
        "result": "success",
        "reason_code": None,
        "fields": {"policy": "default", "flags": ["a", "b"]},
    }
    # Calling to_payload again must produce an identical result.
    assert emitter.to_payload(event) == payload


def _base_event_kwargs() -> dict[str, object]:
    return {
        "schema_version": DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        "event_class": DiagnosticEventClass.RUNTIME,
        "event": "runtime.command_failed",
        "severity": DiagnosticSeverity.ERROR,
        "actor": "pysh.core.shell",
        "action": "execute",
        "target": "ls",
        "result": DiagnosticResult.FAILURE,
    }


def test_invalid_schema_version_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["schema_version"] = 2
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_empty_event_identifier_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["event"] = ""
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_event_identifier_must_be_namespaced() -> None:
    kwargs = _base_event_kwargs()
    kwargs["event"] = "command_failed"
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_event_identifier_must_match_its_class() -> None:
    kwargs = _base_event_kwargs()
    kwargs["event"] = "plugin.command_failed"
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_empty_actor_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["actor"] = ""
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_empty_action_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["action"] = ""
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_empty_target_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["target"] = ""
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_empty_reason_code_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["reason_code"] = ""
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_invalid_result_type_rejected_when_provided() -> None:
    kwargs = _base_event_kwargs()
    kwargs["result"] = "failure"
    with pytest.raises(TypeError):
        StructuredDiagnosticEvent(**kwargs)


def test_event_valid_with_all_optional_context_fields_omitted() -> None:
    """actor/action/target/result/reason_code are optional per Issue #50."""
    event = StructuredDiagnosticEvent(
        schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        event_class=DiagnosticEventClass.STARTUP,
        event="startup.policy_selected",
        severity=DiagnosticSeverity.INFO,
    )
    assert event.actor is None
    assert event.action is None
    assert event.target is None
    assert event.result is None
    assert event.reason_code is None
    assert dict(event.fields) == {}


def test_event_valid_without_actor() -> None:
    kwargs = _base_event_kwargs()
    kwargs["actor"] = None
    event = StructuredDiagnosticEvent(**kwargs)
    assert event.actor is None


def test_event_valid_without_action() -> None:
    kwargs = _base_event_kwargs()
    kwargs["action"] = None
    event = StructuredDiagnosticEvent(**kwargs)
    assert event.action is None


def test_event_valid_without_target() -> None:
    kwargs = _base_event_kwargs()
    kwargs["target"] = None
    event = StructuredDiagnosticEvent(**kwargs)
    assert event.target is None


def test_event_valid_without_result() -> None:
    kwargs = _base_event_kwargs()
    kwargs["result"] = None
    event = StructuredDiagnosticEvent(**kwargs)
    assert event.result is None


def test_event_valid_without_reason_code() -> None:
    kwargs = _base_event_kwargs()
    event = StructuredDiagnosticEvent(**kwargs)
    assert event.reason_code is None


def test_finite_float_field_is_accepted() -> None:
    kwargs = _base_event_kwargs()
    event = StructuredDiagnosticEvent(**kwargs, fields={"ratio": 0.5})
    assert event.fields["ratio"] == 0.5


def test_top_level_nan_field_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"bad": math.nan}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_top_level_positive_infinity_field_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"bad": math.inf}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_top_level_negative_infinity_field_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"bad": -math.inf}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_nested_mapping_non_finite_float_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"outer": {"inner": math.nan}}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_list_non_finite_float_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"values": [1.0, math.inf, 2.0]}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_tuple_non_finite_float_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"values": (1.0, -math.inf)}
    with pytest.raises(ValueError):
        StructuredDiagnosticEvent(**kwargs)


def test_non_string_mapping_key_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {1: "bad"}
    with pytest.raises(TypeError):
        StructuredDiagnosticEvent(**kwargs)


def test_non_string_nested_mapping_key_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"outer": {1: "bad"}}
    with pytest.raises(TypeError):
        StructuredDiagnosticEvent(**kwargs)


class _Unrepresentable:
    """An object with no safe structured representation."""


def test_unsupported_object_rejected_rather_than_reprd() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"bad": _Unrepresentable()}
    with pytest.raises(TypeError):
        StructuredDiagnosticEvent(**kwargs)


def test_unsupported_nested_object_rejected() -> None:
    kwargs = _base_event_kwargs()
    kwargs["fields"] = {"outer": [1, 2, _Unrepresentable()]}
    with pytest.raises(TypeError):
        StructuredDiagnosticEvent(**kwargs)


def test_to_json_compatible_converts_nested_structures() -> None:
    event = StructuredDiagnosticEvent(
        **_base_event_kwargs(),
        fields={"nested": {"inner": (1, 2, 3)}},
    )
    assert to_json_compatible(event.fields) == {"nested": {"inner": [1, 2, 3]}}


# ---------------------------------------------------------------------------
# B. Structured redaction
# ---------------------------------------------------------------------------


def test_sensitive_top_level_field_is_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    result = policy.redact_structured({"password": "hunter2"}, env={})
    assert result == {"password": "<redacted>"}


def test_sensitive_nested_field_is_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"user": {"name": "sam", "password": "hunter2"}}
    result = policy.redact_structured(original, env={})
    assert result == {"user": {"name": "sam", "password": "<redacted>"}}


def test_mixed_case_sensitive_key_is_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    result = policy.redact_structured({"Password": "hunter2"}, env={})
    assert result == {"Password": "<redacted>"}


def test_secret_value_embedded_in_non_sensitive_message_is_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"token": "abc123", "message": "login with abc123 failed"}
    result = policy.redact_structured(original, env={})
    assert result == {
        "token": "<redacted>",
        "message": "login with <redacted> failed",
    }


def test_secret_value_embedded_in_target_and_action_text_is_redacted() -> None:
    kwargs = _base_event_kwargs()
    kwargs["action"] = "execute abc123"
    kwargs["target"] = "run with abc123"
    event = StructuredDiagnosticEvent(**kwargs, fields={"token": "abc123"})
    emitter = DiagnosticEmitter()
    sanitized = emitter.sanitize_event(event, env={})
    assert sanitized.action == "execute <redacted>"
    assert sanitized.target == "run with <redacted>"
    assert sanitized.fields["token"] == "<redacted>"


def test_lists_and_tuples_are_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"secret": "abc123", "history": ["used abc123 once", "clean entry"]}
    result = policy.redact_structured(original, env={})
    assert result == {
        "secret": "<redacted>",
        "history": ["used <redacted> once", "clean entry"],
    }

    original_tuple = {"secret": "abc123", "history": ("used abc123 once", "clean")}
    result_tuple = policy.redact_structured(original_tuple, env={})
    assert result_tuple == {
        "secret": "<redacted>",
        "history": ("used <redacted> once", "clean"),
    }


def test_one_character_secret_does_not_corrupt_unrelated_text() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"session": "1", "path": "/tmp/pytest-19/run"}
    result = policy.redact_structured(original, env={})
    assert result["path"] == "/tmp/pytest-19/run"


def test_one_character_standalone_exposure_is_redacted() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"session": "1", "message": "value is 1 here"}
    result = policy.redact_structured(original, env={})
    assert result["message"] == "value is <redacted> here"


def test_regex_metacharacter_secret_is_handled_literally() -> None:
    policy = DEFAULT_REDACTION_POLICY
    secret = "a.b*c+d"
    original = {"token": secret, "message": f"seen {secret} once"}
    result = policy.redact_structured(original, env={})
    assert result == {
        "token": "<redacted>",
        "message": "seen <redacted> once",
    }


def test_original_input_object_is_not_mutated() -> None:
    policy = DEFAULT_REDACTION_POLICY
    original = {"password": "hunter2", "nested": {"token": "abc123"}, "list": ["abc123"]}
    snapshot = {"password": "hunter2", "nested": {"token": "abc123"}, "list": ["abc123"]}
    policy.redact_structured(original, env={})
    assert original == snapshot


def test_unsupported_object_rejected_in_structured_redaction() -> None:
    policy = DEFAULT_REDACTION_POLICY
    with pytest.raises(TypeError):
        policy.redact_structured({"bad": _Unrepresentable()}, env={})


# ---------------------------------------------------------------------------
# C. Existing trace compatibility
# ---------------------------------------------------------------------------


def test_trace_module_reexports_canonical_redaction_policy() -> None:
    assert TraceRedactionPolicy is RedactionPolicy
    assert TRACE_DEFAULT_REDACTION_POLICY is DEFAULT_REDACTION_POLICY
    assert TRACE_REDACTED_PLACEHOLDER == "<redacted>"


def test_format_trace_event_output_shape_is_unchanged() -> None:
    event = DiagnosticEvent(stage=DiagnosticStage.RESOLVE, message="resolved ls")
    line = format_trace_event(event, TraceOptions(enabled=True))
    assert line.startswith("[PYSH_DEBUG] ")
    assert "stage=RESOLVE" in line
    assert "level=DEBUG" in line
    assert "message=" in line


# ---------------------------------------------------------------------------
# D. Architecture
# ---------------------------------------------------------------------------


def test_diagnostic_event_schema_is_a_versioned_external_protocol() -> None:
    import tomllib
    from pathlib import Path

    policy_path = Path(__file__).parent.parent / "architecture.toml"
    policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))
    assert "diagnostic_event_schema" in policy["public_api"]["versioned_external_protocols"]
