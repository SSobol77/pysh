# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resource_abuse.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #53 Slice 4: controlled, bounded abuse evidence for the resource governor.

Every scenario is deliberately tiny: allocation is capped far below any
host-risk size even if enforcement failed, fork attempts are capped at 16 with
immediately-exiting children, and descendants are limited to three idle
sleepers. Nothing here can exhaust the developer machine.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from pysh.plugins.isolated import launcher
from pysh.plugins.isolated.capabilities import parse_capability
from pysh.plugins.isolated.errors import LifecycleError, ResourcePolicyError
from pysh.plugins.isolated.events import IsolatedPluginEvent, IsolatedPluginEventKind
from pysh.plugins.isolated.manifest import validate_isolated_plugin_manifest
from pysh.plugins.isolated.resources import (
    HARD_RESOURCE_CEILINGS,
    ProcessLimitMode,
    ResourceBudget,
)
from pysh.plugins.isolated.runtime import IsolatedPluginRuntime, IsolatedPluginState
from pysh.plugins.isolated.supervisor import (
    DEFAULT_CONCURRENCY_GOVERNOR,
    ConcurrencyGovernor,
    WallClockWatchdog,
)

FIXTURES = Path(__file__).parent / "fixtures"
PROBE = (FIXTURES / "resource_probe.py").resolve()
PLUGIN = (FIXTURES / "isolated_plugin.py").resolve()
PY = str(Path(sys.executable).resolve())
MIB = 1024 * 1024

pytestmark = pytest.mark.skipif(launcher.resource is None, reason="POSIX resource module required")


def _manifest(script, mode, *arguments, name="abuse-plugin", resource_class="standard"):
    return validate_isolated_plugin_manifest({
        "manifest_version": 1, "name": name, "plugin_version": "1.0",
        "protocol_version": 1,
        "entrypoint": [PY, str(script), name, "1.0", mode, *arguments],
        "requested_capabilities": ["command:report"], "resource_class": resource_class,
    })


def _runtime(script, mode, *arguments, reports=None, events=None, **options):
    sink = (lambda event: events.append(event)) if events is not None else None
    handlers = {"report": lambda argv: (reports.extend(argv) if reports is not None else None) or 0}
    options.setdefault("shutdown_timeout", 0.3)
    options.setdefault("handshake_timeout", 3.0)
    options.setdefault("request_timeout", 5.0)
    return IsolatedPluginRuntime(
        _manifest(script, mode, *arguments),
        granted_capabilities=frozenset({parse_capability("command:report")}),
        command_handlers=handlers, event_sink=sink, **options,
    )


def _wait_until(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():  # a zombie awaiting its (container) init is not running
        try:
            return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
    return True


def _resource_events(events):
    return [e for e in events if e.kind is IsolatedPluginEventKind.RESOURCE_VIOLATION]


def _assert_session_healthy() -> None:
    """The parent can still run a normal governed plugin after an abuse scenario."""
    runtime = IsolatedPluginRuntime(
        validate_isolated_plugin_manifest({
            "manifest_version": 1, "name": "healthy-plugin", "plugin_version": "1.0",
            "protocol_version": 1,
            "entrypoint": [PY, str(PLUGIN), "healthy-plugin", "1.0", "normal"],
            "requested_capabilities": [], "resource_class": "standard",
        })
    )
    runtime.start()
    assert runtime.state is IsolatedPluginState.RUNNING
    assert runtime.shutdown() is True


@pytest.fixture(autouse=True)
def _no_leaks():
    yield
    assert DEFAULT_CONCURRENCY_GOVERNOR.total_active() == 0
    assert _wait_until(
        lambda: not [t for t in __import__("threading").enumerate()
                     if t.name == WallClockWatchdog.THREAD_NAME], 3.0)


# --- timeout ----------------------------------------------------------------


def test_hung_plugin_is_stopped_and_the_session_survives() -> None:
    events: list[IsolatedPluginEvent] = []
    runtime = _runtime(PLUGIN, "hang_after_ready", events=events,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    with pytest.raises(LifecycleError, match="wall_clock"):
        runtime.serve_once(timeout=10.0)
    assert runtime.state is IsolatedPluginState.FAILED
    assert len(_resource_events(events)) == 1
    _assert_session_healthy()


def test_cpu_bound_busy_loop_is_stopped_by_the_wall_clock_without_cooperation() -> None:
    events: list[IsolatedPluginEvent] = []
    # CPU budget (15 s default) is far above the 1 s lifetime: only the watchdog can stop it.
    runtime = _runtime(PROBE, "spin", events=events,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    started = time.monotonic()
    with pytest.raises(LifecycleError, match="wall_clock"):
        runtime.serve_once(timeout=10.0)
    assert time.monotonic() - started < 4.0
    assert [e.resource for e in _resource_events(events)] == ["wall_clock"]
    _assert_session_healthy()


# --- request flood ----------------------------------------------------------


def test_request_flood_is_bounded_by_the_total_lifetime() -> None:
    events: list[IsolatedPluginEvent] = []
    reports: list[str] = []
    runtime = _runtime(PROBE, "flood", reports=reports, events=events,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    served = 0
    started = time.monotonic()
    with pytest.raises(LifecycleError, match="wall_clock"):
        while True:
            runtime.serve_once(timeout=5.0)
            served += 1
    assert served > 0  # real traffic was flowing when the deadline hit
    assert time.monotonic() - started < 5.0
    assert runtime.state is IsolatedPluginState.FAILED
    assert len(_resource_events(events)) == 1
    _assert_session_healthy()


# --- memory (OOM) -----------------------------------------------------------


def test_unbounded_allocation_is_refused_inside_the_plugin_not_the_host() -> None:
    reports: list[str] = []
    runtime = _runtime(PROBE, "alloc_loop", "4", "40", reports=reports,
                       resource_limits=ResourceBudget(memory_bytes=64 * MIB))
    runtime.start()
    runtime.serve_once()
    result = json.loads(reports[0])
    assert result["refused"] is True
    assert result["chunks"] * result["chunk_mib"] * MIB < 64 * MIB  # never beyond the budget
    assert runtime.shutdown() is True  # the plugin survived its own MemoryError cleanly
    _assert_session_healthy()


# --- process creation -------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(launcher.resource, "RLIMIT_NPROC") or os.geteuid() == 0,
    reason="needs RLIMIT_NPROC and a non-root user",
)
def test_fork_loop_is_blocked_by_the_opt_in_per_uid_process_limit() -> None:
    reports: list[str] = []
    runtime = _runtime(PROBE, "fork_loop", "16", reports=reports,
                       process_limit_mode=ProcessLimitMode.OS_PER_UID,
                       resource_limits=ResourceBudget(processes=1))
    runtime.start()
    runtime.serve_once()
    result = json.loads(reports[0])
    assert result["forked"] == 0
    assert result["failures"] == [result["eagain"]] * 16
    runtime.close()
    _assert_session_healthy()


def test_descendants_are_killed_with_the_plugin_process_group() -> None:
    reports: list[str] = []
    events: list[IsolatedPluginEvent] = []
    runtime = _runtime(PROBE, "spawn_sleepers", "3", reports=reports, events=events,
                       resource_limits=ResourceBudget(wall_clock_seconds=1))
    runtime.start()
    runtime.serve_once()
    pids = json.loads(reports[0])
    assert len(pids) == 3 and all(_alive(pid) for pid in pids)
    try:
        assert _wait_until(lambda: runtime.state is IsolatedPluginState.FAILED)
        assert _wait_until(lambda: not any(_alive(pid) for pid in pids)), "descendants survived"
    finally:
        for pid in pids:  # belt and braces so a failure cannot leave sleepers behind
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
    assert len(_resource_events(events)) == 1
    _assert_session_healthy()


# --- descriptors and messages ----------------------------------------------


def test_descriptor_exhaustion_is_contained_to_the_plugin() -> None:
    reports: list[str] = []
    before = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
    runtime = _runtime(PROBE, "open_fds", reports=reports,
                       resource_limits=ResourceBudget(file_descriptors=16))
    runtime.start()
    runtime.serve_once()
    result = json.loads(reports[0])
    assert result["errno"] == result["emfile"] and result["opened"] <= 16
    runtime.close()
    if before is not None:
        assert len(os.listdir("/dev/fd")) <= before + 1
    _assert_session_healthy()


def test_oversized_message_is_contained_as_a_single_resource_violation() -> None:
    events: list[IsolatedPluginEvent] = []
    runtime = _runtime(PLUGIN, "oversized_running", events=events)
    runtime.start()
    with pytest.raises(LifecycleError, match="message_size"):
        runtime.serve_once()
    assert [e.resource for e in _resource_events(events)] == ["message_size"]
    _assert_session_healthy()


# --- concurrency ------------------------------------------------------------


def test_spawn_storm_of_one_plugin_is_capped_by_the_concurrency_permit() -> None:
    governor = ConcurrencyGovernor()
    options = {"concurrency_governor": governor, "resource_limits": ResourceBudget(concurrency=2)}
    runtimes = [_runtime(PLUGIN, "normal", **options) for _ in range(6)]
    started = refused = 0
    try:
        for runtime in runtimes:
            try:
                runtime.start()
                started += 1
            except LifecycleError as exc:
                assert "concurrency" in str(exc)
                refused += 1
        assert (started, refused) == (2, 4)
        assert governor.active("abuse-plugin") == 2
    finally:
        for runtime in runtimes:
            runtime.close()
    assert governor.total_active() == 0


# --- ceilings cannot be exceeded by configuration ---------------------------


@pytest.mark.parametrize("field", [f for f in vars(HARD_RESOURCE_CEILINGS.__class__)["__slots__"]])
def test_no_configuration_can_exceed_a_hard_ceiling(field: str, monkeypatch) -> None:
    monkeypatch.setenv("PYSH_RESOURCE_OVERRIDE", "unlimited")
    too_big = getattr(HARD_RESOURCE_CEILINGS, field) + 1
    with pytest.raises(ResourcePolicyError, match="hard ceiling"):
        ResourceBudget(**{field: too_big})


def test_a_runtime_override_cannot_raise_its_profile_even_below_the_ceiling() -> None:
    runtime = _runtime(PLUGIN, "normal", resource_limits=ResourceBudget(wall_clock_seconds=599))
    with pytest.raises(LifecycleError, match="resource policy rejected"):
        runtime.start()
    assert runtime.state is IsolatedPluginState.NEW


def test_the_plugin_cannot_raise_its_own_limits() -> None:
    reports: list[str] = []
    runtime = _runtime(PROBE, "raise_limits", reports=reports)
    runtime.start()
    runtime.serve_once()
    assert set(json.loads(reports[0]).values()) == {"denied"}
    runtime.close()
