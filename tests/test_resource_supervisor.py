# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resource_supervisor.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #53 Slice 3: default governance, wall-clock watchdog, concurrency, RESOURCE events."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from pysh.diagnostics.jsonl import JsonlDiagnosticSink
from pysh.diagnostics.schema import DiagnosticEventClass, DiagnosticResult, DiagnosticSeverity
from pysh.plugins.isolated import runtime as runtime_module
from pysh.plugins.isolated.capabilities import parse_capability
from pysh.plugins.isolated.diagnostics import (
    make_structured_plugin_event_sink,
    structured_event_from_isolated_plugin_event,
)
from pysh.plugins.isolated.errors import LifecycleError, ResourcePolicyError
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.manifest import validate_isolated_plugin_manifest
from pysh.plugins.isolated.protocol import IPC_PROTOCOL_VERSION
from pysh.plugins.isolated.resources import (
    DEFAULT_RESOURCE_CLASS,
    DEFAULT_RESOURCE_PROFILES,
    ResourceBudget,
    ResourceProfile,
    ResourceViolation,
    build_profile_catalog,
    resolve_resource_budget,
)
from pysh.plugins.isolated.runtime import IsolatedPluginRuntime, IsolatedPluginState
from pysh.plugins.isolated.supervisor import (
    DEFAULT_CONCURRENCY_GOVERNOR,
    ConcurrencyGovernor,
    WallClockWatchdog,
)

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN = (FIXTURES / "isolated_plugin.py").resolve()
PROBE = (FIXTURES / "resource_probe.py").resolve()
PY = str(Path(sys.executable).resolve())
SECRET = "super-secret-value"


def _manifest(mode="normal", *arguments, resource_class="standard", script=PLUGIN,
              name="fixture-plugin", capabilities=()):
    data: dict[str, object] = {
        "manifest_version": 1,
        "name": name,
        "plugin_version": "1.0",
        "protocol_version": 1,
        "entrypoint": [PY, str(script), name, "1.0", mode, *arguments],
        "requested_capabilities": list(capabilities),
    }
    if resource_class is not None:
        data["resource_class"] = resource_class
    return validate_isolated_plugin_manifest(data)


def _watchdog_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == WallClockWatchdog.THREAD_NAME]


def _wait_until(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _fd_count() -> int | None:
    return len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None


def _isolated_tempdirs() -> set[str]:
    return {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("pysh-isolated-")}


@pytest.fixture(autouse=True)
def _no_leaks():
    before_dirs = _isolated_tempdirs()
    yield
    assert DEFAULT_CONCURRENCY_GOVERNOR.total_active() == 0
    assert _wait_until(lambda: not _watchdog_threads(), 3.0), "watchdog thread leaked"
    assert _isolated_tempdirs() <= before_dirs, "temporary cwd leaked"


@pytest.fixture
def governor() -> ConcurrencyGovernor:
    return ConcurrencyGovernor()


class Recorder:
    """Records raw runtime events and process-group signals."""

    def __init__(self, monkeypatch) -> None:
        self.events: list[IsolatedPluginEvent] = []
        self.signals: list[tuple[int, int]] = []
        real = runtime_module._signal_group

        def spy(group, signum):
            self.signals.append((group, int(signum)))
            real(group, signum)

        monkeypatch.setattr(runtime_module, "_signal_group", spy)

    @property
    def resource_events(self):
        return [e for e in self.events if e.kind is IsolatedPluginEventKind.RESOURCE_VIOLATION]

    def kinds(self):
        return [e.kind for e in self.events]


@pytest.fixture
def rec(monkeypatch) -> Recorder:
    return Recorder(monkeypatch)


def _runtime(manifest, rec=None, **options):
    if rec is not None:
        options.setdefault("event_sink", rec.events.append)
    options.setdefault("shutdown_timeout", 0.3)
    options.setdefault("handshake_timeout", 3.0)
    options.setdefault("request_timeout", 5.0)
    return IsolatedPluginRuntime(manifest, **options)


def _assert_reaped(runtime, pid):
    assert runtime._process.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)
    assert runtime.working_directory is None


# --- A. profiles and no ungoverned path -------------------------------------


def test_missing_resource_class_resolves_to_the_standard_profile() -> None:
    assert DEFAULT_RESOURCE_CLASS == "standard"
    runtime = _runtime(_manifest(resource_class=None))
    try:
        runtime.start()
        assert runtime.enforcement.effective == DEFAULT_RESOURCE_PROFILES["standard"].budget
    finally:
        runtime.close()


@pytest.mark.parametrize("name", ["small", "standard", "large"])
def test_each_production_profile_resolves_and_is_enforced(name: str) -> None:
    runtime = _runtime(_manifest(resource_class=name))
    try:
        runtime.start()
        assert runtime.enforcement.effective == DEFAULT_RESOURCE_PROFILES[name].budget
    finally:
        runtime.close()


def test_unknown_resource_class_fails_before_spawn_and_is_not_mapped_to_standard(
    monkeypatch, governor
) -> None:
    spawned: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
    runtime = _runtime(_manifest(resource_class="bogus"), concurrency_governor=governor)
    with pytest.raises(LifecycleError, match="unknown resource class"):
        runtime.start()
    assert spawned == []
    assert governor.total_active() == 0
    assert runtime.state is IsolatedPluginState.NEW


def test_default_class_missing_from_injected_catalog_fails_closed() -> None:
    catalog = build_profile_catalog((DEFAULT_RESOURCE_PROFILES["small"],))
    with pytest.raises(ResourcePolicyError, match="unknown resource class"):
        resolve_resource_budget(None, catalog=catalog)


def test_injected_test_profile_is_usable_without_being_production() -> None:
    profile = ResourceProfile("test", DEFAULT_RESOURCE_PROFILES["small"].budget)
    runtime = _runtime(
        _manifest(resource_class="test"), resource_catalog=build_profile_catalog((profile,))
    )
    try:
        runtime.start()
        assert runtime.state is IsolatedPluginState.RUNNING
    finally:
        runtime.close()
    assert "test" not in DEFAULT_RESOURCE_PROFILES


def test_there_is_no_direct_spawn_path_even_without_any_budget_argument() -> None:
    runtime = _runtime(_manifest())
    try:
        runtime.start()
        argv = runtime._process.args
        assert argv[1] == "-I" and argv[2].endswith("launcher.py")
        assert runtime.enforcement is not None
    finally:
        runtime.close()


# --- B. wall-clock watchdog -------------------------------------------------


def test_hung_child_is_terminated_by_total_deadline_sigterm_path(rec) -> None:
    runtime = _runtime(_manifest("hang_after_ready"), rec,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    started = time.monotonic()
    runtime.start()
    pid = runtime.process_id
    process = runtime._process
    with pytest.raises(LifecycleError, match="resource limit exceeded: wall_clock"):
        runtime.serve_once(timeout=10.0)
    elapsed = time.monotonic() - started
    assert 0.9 <= elapsed < 4.0
    assert runtime.state is IsolatedPluginState.FAILED
    assert process.returncode == -15  # died on SIGTERM; no SIGKILL was needed
    assert rec.signals[0] == (pid, 15)
    assert {group for group, _ in rec.signals} == {pid}
    _assert_reaped(runtime, pid)
    assert len(rec.resource_events) == 1
    assert IsolatedPluginEventKind.FAILURE not in rec.kinds()
    assert IsolatedPluginEventKind.STOPPED not in rec.kinds()


def test_sigterm_ignoring_child_is_killed_after_bounded_grace(rec) -> None:
    runtime = _runtime(_manifest("ignore_sigterm"), rec, shutdown_timeout=0.3,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    pid = runtime.process_id
    process = runtime._process
    started = time.monotonic()
    with pytest.raises(LifecycleError, match="wall_clock"):
        runtime.serve_once(timeout=10.0)
    assert time.monotonic() - started < 4.0
    assert process.returncode == -9
    assert [sig for _, sig in rec.signals][:2] == [15, 9]
    assert {group for group, _ in rec.signals} == {pid}
    _assert_reaped(runtime, pid)


def test_idle_runtime_is_contained_by_the_watchdog_itself(rec) -> None:
    runtime = _runtime(_manifest("hang_after_ready"), rec,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    pid = runtime.process_id
    assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
    _assert_reaped(runtime, pid)
    assert len(rec.resource_events) == 1
    assert runtime.shutdown() is False  # idempotent, no second outcome
    assert len(rec.resource_events) == 1
    assert IsolatedPluginEventKind.STOPPED not in rec.kinds()


def test_deadline_is_total_lifetime_and_not_reset_by_ipc_activity(rec) -> None:
    reports: list[str] = []
    runtime = _runtime(
        _manifest("report_args", "ping", capabilities=("command:report",)), rec,
        granted_capabilities=frozenset({parse_capability("command:report")}),
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
        resource_limits=ResourceBudget(wall_clock_seconds=2),
    )
    t0 = time.monotonic()
    runtime.start()
    time.sleep(0.8)
    assert runtime.serve_once().ok  # successful IPC mid-life must not extend the deadline
    assert reports == ["ping"]
    assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
    assert 1.9 <= time.monotonic() - t0 < 3.9
    assert len(rec.resource_events) == 1


def test_deadline_includes_launch_and_handshake_time(rec) -> None:
    runtime = _runtime(_manifest("hang_handshake"), rec, handshake_timeout=5.0,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    t0 = time.monotonic()
    with pytest.raises(LifecycleError, match="wall_clock"):
        runtime.start()
    assert time.monotonic() - t0 < 4.0  # watchdog beat the 5 s handshake timeout
    assert runtime.state is IsolatedPluginState.FAILED
    assert len(rec.resource_events) == 1


def test_watchdog_primitive_cancel_prevents_expiry_and_is_idempotent() -> None:
    fired: list[int] = []
    dog = WallClockWatchdog(time.monotonic() + 0.2, lambda: fired.append(1))
    dog.start()
    dog.cancel()
    dog.cancel()
    time.sleep(0.4)
    assert fired == [] and not dog.alive
    expiring = WallClockWatchdog(time.monotonic() + 0.05, lambda: fired.append(2))
    expiring.start()
    assert _wait_until(lambda: fired == [2])
    expiring.cancel()


# --- C. concurrency ---------------------------------------------------------


def test_at_limit_succeeds_and_over_limit_is_rejected_before_spawn(
    rec, governor, monkeypatch
) -> None:
    limits = ResourceBudget(concurrency=2)
    first = _runtime(_manifest(), concurrency_governor=governor, resource_limits=limits)
    second = _runtime(_manifest(), concurrency_governor=governor, resource_limits=limits)
    third = _runtime(_manifest(), rec, concurrency_governor=governor, resource_limits=limits)
    first.start()
    second.start()
    assert governor.active("fixture-plugin") == 2
    popen_calls: list[object] = []
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: popen_calls.append(a) or real_popen(*a, **k)
    )
    with pytest.raises(LifecycleError, match="resource limit exceeded: concurrency"):
        third.start()
    assert popen_calls == []
    assert third.state is IsolatedPluginState.NEW and third.process_id is None
    assert governor.active("fixture-plugin") == 2
    assert len(rec.resource_events) == 1
    assert rec.resource_events[0].resource == "concurrency"
    assert rec.resource_events[0].enforcement == "permit"
    first.close()
    third.start()  # a freed permit is immediately reusable
    for runtime in (second, third):
        runtime.close()
    assert governor.total_active() == 0


def test_override_can_lower_concurrency_and_keys_are_per_plugin(governor) -> None:
    lowered = ResourceBudget(concurrency=1)
    a = _runtime(_manifest(name="alpha"), concurrency_governor=governor, resource_limits=lowered)
    a2 = _runtime(_manifest(name="alpha"), concurrency_governor=governor, resource_limits=lowered)
    b = _runtime(_manifest(name="beta"), concurrency_governor=governor, resource_limits=lowered)
    a.start()
    b.start()  # a different plugin has its own slot
    with pytest.raises(LifecycleError, match="concurrency"):
        a2.start()
    a.close()
    b.close()


def test_concurrency_override_cannot_raise_the_profile() -> None:
    runtime = _runtime(_manifest(resource_class="small"),
                       resource_limits=ResourceBudget(concurrency=4))
    with pytest.raises(LifecycleError, match="resource policy rejected"):
        runtime.start()


def _failing_launcher_manifest(tmp_path: Path):
    broken = tmp_path / "broken-plugin"
    broken.write_text("#!/nonexistent/interpreter\n")
    broken.chmod(0o755)
    return validate_isolated_plugin_manifest({
        "manifest_version": 1, "name": "broken-plugin", "plugin_version": "1.0",
        "protocol_version": 1, "entrypoint": [str(broken)],
        "requested_capabilities": [], "resource_class": "standard",
    })


@pytest.mark.parametrize(
    "scenario",
    ["normal_shutdown", "explicit_close", "handshake_failure", "protocol_failure",
     "crash", "launcher_failure", "watchdog", "spawn_oserror", "policy_failure"],
)
def test_permit_is_released_on_every_exit_path(scenario, governor, tmp_path, monkeypatch) -> None:
    options = {"concurrency_governor": governor}
    manifest = _manifest()
    if scenario == "handshake_failure":
        manifest = _manifest("identity_mismatch")
    elif scenario == "protocol_failure":
        manifest = _manifest("malformed_running")
    elif scenario == "crash":
        manifest = _manifest("crash")
    elif scenario == "launcher_failure":
        manifest = _failing_launcher_manifest(tmp_path)
    elif scenario == "watchdog":
        manifest = _manifest("hang_after_ready")
        options["resource_limits"] = ResourceBudget(wall_clock_seconds=1)
    elif scenario == "policy_failure":
        options["resource_limits"] = ResourceBudget(memory_bytes=1024)
    elif scenario == "spawn_oserror":
        def boom(*_a, **_k):
            raise OSError("no spawn")
        monkeypatch.setattr(subprocess, "Popen", boom)
    runtime = _runtime(manifest, **options)
    try:
        if scenario in {"handshake_failure", "launcher_failure", "spawn_oserror",
                        "policy_failure"}:
            with pytest.raises(LifecycleError):
                runtime.start()
        elif scenario == "protocol_failure" or scenario == "crash":
            runtime.start()
            with pytest.raises(LifecycleError):
                runtime.serve_once()
        elif scenario == "watchdog":
            runtime.start()
            assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
        else:
            runtime.start()
            if scenario == "normal_shutdown":
                assert runtime.shutdown() is True
    finally:
        runtime.close()
    assert governor.total_active() == 0
    assert runtime.working_directory is None


def test_launcher_failure_is_reported_deterministically(tmp_path, governor) -> None:
    runtime = _runtime(_failing_launcher_manifest(tmp_path), concurrency_governor=governor)
    with pytest.raises(LifecycleError, match="could not apply limits or exec"):
        runtime.start()
    assert runtime.state is IsolatedPluginState.FAILED


def test_concurrency_governor_primitive() -> None:
    gov = ConcurrencyGovernor()
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ResourcePolicyError):
            gov.acquire("k", bad)  # type: ignore[arg-type]
    permit = gov.acquire("k", 1)
    with pytest.raises(ResourcePolicyError, match="reached"):
        gov.acquire("k", 1)  # immediate; never queues or blocks
    permit.release()
    permit.release()  # idempotent
    assert gov.active("k") == 0
    wins: list[object] = []
    barrier = threading.Barrier(8)

    def contend() -> None:
        barrier.wait()
        try:
            wins.append(gov.acquire("c", 3))
        except ResourcePolicyError:
            pass

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(wins) == 3 and gov.active("c") == 3
    for permit in wins:
        permit.release()
    assert gov.total_active() == 0


# --- D. diagnostics ---------------------------------------------------------


def test_wall_clock_violation_maps_to_one_structured_resource_event() -> None:
    structured: list = []
    runtime = _runtime(
        _manifest("hang_after_ready", name="demo-plugin"),
        event_sink=make_structured_plugin_event_sink(structured.append),
        broker_environment={"TOKEN": SECRET},
        resource_limits=ResourceBudget(wall_clock_seconds=1),
    )
    runtime.start()
    assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
    resource = [e for e in structured if e.event_class is DiagnosticEventClass.RESOURCE]
    assert len(resource) == 1
    event = resource[0]
    assert event.schema_version == 1
    assert event.event == "resource.limit_exceeded"
    assert event.severity is DiagnosticSeverity.ERROR
    assert event.result is DiagnosticResult.FAILURE
    assert event.actor == "demo-plugin"
    assert event.reason_code == "wall_clock_exceeded"
    assert dict(event.fields) == {
        "plugin_name": "demo-plugin",
        "resource": "wall_clock",
        "configured_limit": 1,
        "enforcement": "watchdog",
    }
    assert SECRET not in repr(event)


def test_oversized_inbound_message_is_exactly_one_resource_event(rec) -> None:
    runtime = _runtime(_manifest("oversized_running"), rec)
    runtime.start()
    with pytest.raises(LifecycleError, match="resource limit exceeded: message_size"):
        runtime.serve_once()
    assert runtime.state is IsolatedPluginState.FAILED
    assert len(rec.resource_events) == 1
    event = rec.resource_events[0]
    assert event.resource == "message_size"
    assert event.configured_limit == resolve_resource_budget("standard").message_bytes
    assert event.enforcement == "ipc_bound"
    assert IsolatedPluginEventKind.FAILURE not in rec.kinds()  # no duplicate generic report
    assert runtime.working_directory is None


def test_oversized_handshake_message_is_a_resource_violation(rec) -> None:
    runtime = _runtime(_manifest("oversized_handshake"), rec)
    with pytest.raises(LifecycleError, match="message_size"):
        runtime.start()
    assert runtime.state is IsolatedPluginState.FAILED
    assert len(rec.resource_events) == 1
    assert IsolatedPluginEventKind.FAILURE not in rec.kinds()


def test_oversized_outbound_response_is_a_resource_violation_without_payload(rec) -> None:
    runtime = _runtime(
        _manifest("request_environment", "BIG", script=PROBE,
                  capabilities=("env.read:BIG",)),
        rec,
        granted_capabilities=frozenset({parse_capability("env.read:BIG")}),
        broker_environment={"BIG": "y" * 3000},
        resource_limits=ResourceBudget(message_bytes=2048),
    )
    runtime.start()
    with pytest.raises(LifecycleError, match="message_size"):
        runtime.serve_once()
    assert len(rec.resource_events) == 1
    assert rec.resource_events[0].configured_limit == 2048
    assert "yyy" not in repr(rec.events)


def test_resource_events_serialize_through_issue_50_jsonl_without_payload() -> None:
    stream = io.StringIO()
    sink = JsonlDiagnosticSink(stream)
    runtime = _runtime(
        _manifest("oversized_running"),
        event_sink=make_structured_plugin_event_sink(sink.write_structured_event),
        broker_environment={"TOKEN": SECRET},
    )
    runtime.start()
    with pytest.raises(LifecycleError):
        runtime.serve_once()
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    resource = [line for line in lines if line["event"] == "resource.limit_exceeded"]
    assert len(resource) == 1
    assert resource[0]["schema_version"] == 1
    assert resource[0]["event_class"] == "resource"
    assert SECRET not in stream.getvalue()


def test_runtime_error_from_sink_does_not_prevent_containment(rec) -> None:
    def hostile(event: IsolatedPluginEvent) -> None:
        rec.events.append(event)
        if event.kind is IsolatedPluginEventKind.RESOURCE_VIOLATION:
            raise RuntimeError("diagnostics exploded")

    runtime = _runtime(_manifest("hang_after_ready"), event_sink=hostile,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    pid = runtime.process_id
    with pytest.raises(LifecycleError, match="wall_clock"):
        runtime.serve_once(timeout=10.0)
    assert runtime.state is IsolatedPluginState.FAILED
    _assert_reaped(runtime, pid)
    assert len(rec.resource_events) == 1


def test_base_exception_from_sink_propagates_but_still_contains(rec) -> None:
    def hostile(event: IsolatedPluginEvent) -> None:
        rec.events.append(event)
        if event.kind is IsolatedPluginEventKind.RESOURCE_VIOLATION:
            raise KeyboardInterrupt

    runtime = _runtime(_manifest("oversized_running"), event_sink=hostile)
    runtime.start()
    pid = runtime.process_id
    with pytest.raises(KeyboardInterrupt):
        runtime.serve_once()
    assert runtime.state is IsolatedPluginState.FAILED
    _assert_reaped(runtime, pid)


def test_ambiguous_os_death_is_not_attributed_to_a_resource(rec) -> None:
    runtime = _runtime(_manifest("spin", script=PROBE, resource_class="small"), rec,
                       resource_limits=ResourceBudget(cpu_seconds=1))
    runtime.start()
    with pytest.raises(LifecycleError):
        runtime.serve_once(timeout=10.0)
    assert rec.resource_events == []
    assert IsolatedPluginEventKind.FAILURE in rec.kinds()


def test_resource_event_adapter_contains_only_bounded_fields() -> None:
    event = structured_event_from_isolated_plugin_event(IsolatedPluginEvent(
        kind=IsolatedPluginEventKind.RESOURCE_VIOLATION, plugin_name="demo",
        reason_code="wall_clock_exceeded", resource="wall_clock",
        configured_limit=5, enforcement="watchdog",
    ))
    assert set(event.fields) == {"plugin_name", "resource", "configured_limit", "enforcement"}
    assert {v.value for v in ResourceViolation} >= {"wall_clock", "message_size", "concurrency"}


# --- E. races ---------------------------------------------------------------


def test_normal_shutdown_just_before_deadline_never_reports_a_violation(rec) -> None:
    runtime = _runtime(_manifest(), rec, resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    assert runtime.shutdown() is True
    assert runtime._watchdog is not None and not runtime._watchdog.alive
    time.sleep(1.2)  # past the would-be deadline
    assert runtime.state is IsolatedPluginState.STOPPED
    assert rec.resource_events == []


def test_deadline_callback_after_shutdown_claim_is_ignored(rec) -> None:
    runtime = _runtime(_manifest(), rec)
    runtime.start()
    runtime._closing = True  # shutdown has claimed the runtime
    runtime._on_deadline()
    assert runtime._violation is None and rec.resource_events == []
    runtime._closing = False
    assert runtime.shutdown() is True


def test_expiry_before_shutdown_completes_the_violation_and_shutdown_is_quiet(rec) -> None:
    runtime = _runtime(_manifest("hang_shutdown"), rec)
    runtime.start()
    pid = runtime.process_id
    runtime._on_deadline()  # the watchdog's work, run deterministically
    assert runtime.state is IsolatedPluginState.FAILED
    assert runtime.shutdown() is False
    assert len(rec.resource_events) == 1
    assert IsolatedPluginEventKind.STOPPED not in rec.kinds()
    _assert_reaped(runtime, pid)


def test_expiry_for_an_already_exited_child_claims_nothing(rec) -> None:
    runtime = _runtime(_manifest("exit_clean"), rec)
    runtime.start()
    assert _wait_until(lambda: runtime._process.poll() is not None)
    runtime._on_deadline()
    assert runtime._violation is None and rec.resource_events == []
    runtime.close()


@pytest.mark.parametrize("offset", [0.55, 0.95, 1.0, 1.05, 1.2])
def test_close_racing_the_watchdog_yields_one_deterministic_outcome(rec, offset) -> None:
    runtime = _runtime(_manifest("hang_after_ready"), rec,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    t0 = time.monotonic()
    runtime.start()
    pid = runtime.process_id
    time.sleep(max(0.0, offset - (time.monotonic() - t0)))
    errors: list[BaseException] = []

    def closer() -> None:
        try:
            runtime.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=closer)
    thread.start()
    thread.join(10)
    assert not thread.is_alive() and errors == []
    assert _wait_until(lambda: runtime.state in {IsolatedPluginState.STOPPED,
                                                 IsolatedPluginState.FAILED})
    assert runtime._process.returncode is not None
    stopped = IsolatedPluginEventKind.STOPPED in rec.kinds()
    assert len(rec.resource_events) <= 1
    assert not (stopped and rec.resource_events)  # never contradictory outcomes
    assert runtime.state is (IsolatedPluginState.FAILED if rec.resource_events
                             else IsolatedPluginState.STOPPED)
    _assert_reaped(runtime, pid)


def test_failed_spawn_leaves_no_watchdog_permit_or_tempdir(governor, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise OSError("no spawn")

    monkeypatch.setattr(subprocess, "Popen", boom)
    runtime = _runtime(_manifest(), concurrency_governor=governor)
    with pytest.raises(LifecycleError):
        runtime.start()
    assert runtime._watchdog is None and governor.total_active() == 0
    assert runtime.state is IsolatedPluginState.FAILED


def test_handshake_failure_cancels_the_watchdog_and_releases_everything(governor) -> None:
    runtime = _runtime(_manifest("identity_mismatch"), concurrency_governor=governor)
    with pytest.raises(LifecycleError):
        runtime.start()
    assert runtime._watchdog is not None and not runtime._watchdog.alive
    assert governor.total_active() == 0 and runtime.working_directory is None


def test_signals_never_reach_unrelated_processes_and_fds_do_not_leak(rec) -> None:
    bystander = subprocess.Popen(  # noqa: S603
        [PY, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    before = _fd_count()
    try:
        runtime = _runtime(_manifest("ignore_sigterm"), rec,
                           resource_limits=ResourceBudget(wall_clock_seconds=1))
        runtime.start()
        pid = runtime.process_id
        assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
        assert {group for group, _ in rec.signals} == {pid}
        assert bystander.poll() is None
        assert before is None or _fd_count() <= before + 1
    finally:
        bystander.kill()
        bystander.wait()


# --- F. regressions ---------------------------------------------------------


def test_protocol_version_and_diagnostic_schema_version_are_unchanged() -> None:
    assert IPC_PROTOCOL_VERSION == 1
    event = structured_event_from_isolated_plugin_event(IsolatedPluginEvent(
        kind=IsolatedPluginEventKind.RESOURCE_VIOLATION, plugin_name="demo",
        reason_code="wall_clock_exceeded", resource="wall_clock",
        configured_limit=1, enforcement="watchdog",
    ))
    assert event.schema_version == 1


def test_normal_plugin_and_capability_broker_behave_as_before(rec) -> None:
    runtime = _runtime(
        _manifest("request_environment", "VISIBLE", capabilities=("env.read:VISIBLE",)), rec,
        granted_capabilities=frozenset({parse_capability("env.read:VISIBLE")}),
        broker_environment={"VISIBLE": "allowed", "HIDDEN": SECRET},
    )
    runtime.start()
    assert runtime.serve_once().ok
    assert runtime.shutdown() is True
    assert rec.resource_events == []
    assert rec.kinds()[-1] is IsolatedPluginEventKind.STOPPED
