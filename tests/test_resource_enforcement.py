# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_resource_enforcement.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #53 Slice 2: POSIX rlimit enforcement through the launcher boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pysh.plugins.isolated import launcher
from pysh.plugins.isolated.capabilities import parse_capability
from pysh.plugins.isolated.errors import LifecycleError, ResourcePolicyError
from pysh.plugins.isolated.launcher import (
    EXIT_APPLY_FAILED,
    EXIT_POLICY_REJECTED,
    build_launcher_argv,
    parse_launcher_argv,
)
from pysh.plugins.isolated.manifest import validate_isolated_plugin_manifest
from pysh.plugins.isolated.protocol import (
    MAX_FRAME_BYTES,
    IPCMessage,
    encode_message,
    write_message,
)
from pysh.plugins.isolated.resources import (
    HARD_RESOURCE_CEILINGS,
    ProcessLimitMode,
    ResourceBudget,
    plan_enforcement,
    resolve_resource_budget,
)
from pysh.plugins.isolated.runtime import IsolatedPluginRuntime, IsolatedPluginState

PROBE = (Path(__file__).parent / "fixtures" / "resource_probe.py").resolve()
PY = str(Path(sys.executable).resolve())
MIB = 1024 * 1024

pytestmark = pytest.mark.skipif(
    launcher.resource is None, reason="POSIX resource module required"
)


def _manifest(mode: str, *arguments: str, resource_class: str = "small"):
    return validate_isolated_plugin_manifest({
        "manifest_version": 1,
        "name": "probe",
        "plugin_version": "1.0",
        "protocol_version": 1,
        "entrypoint": [PY, str(PROBE), "probe", "1.0", mode, *arguments],
        "requested_capabilities": ["command:report", "env.read:BIG"],
        "resource_class": resource_class,
    })


def _run_probe(mode, *arguments, limits=None, environment=None, **runtime_options):
    """Start the probe under ``limits``, serve one request, return (reports, runtime)."""
    reports: list[str] = []
    runtime = IsolatedPluginRuntime(
        _manifest(mode, *arguments),
        granted_capabilities=frozenset(
            parse_capability(item) for item in ("command:report", "env.read:BIG")
        ),
        broker_environment=environment,
        command_handlers={"report": lambda argv: reports.extend(argv) or 0},
        resource_limits=limits,
        handshake_timeout=5.0,
        request_timeout=5.0,
        **runtime_options,
    )
    return reports, runtime


def _report(mode, *arguments, limits, **runtime_options):
    reports, runtime = _run_probe(mode, *arguments, limits=limits, **runtime_options)
    try:
        runtime.start()
        runtime.serve_once()
        return json.loads(reports[0])
    finally:
        runtime.close()


# --- A. launcher parsing ---------------------------------------------------

GOOD = ["--cpu-seconds", "5", "--memory-bytes", str(64 * MIB), "--file-descriptors", "32"]


def test_valid_policy_parses_and_preserves_entrypoint_exactly() -> None:
    entry = ["/bin/true", "--", "a b", "$(rm -rf /)", ";", "--cpu-seconds", "1", ""]
    plan = parse_launcher_argv([*GOOD, "--", *entry])
    assert plan.entrypoint == tuple(entry)
    assert (plan.cpu_seconds, plan.memory_bytes, plan.file_descriptors) == (5, 64 * MIB, 32)
    assert plan.processes is None
    assert parse_launcher_argv([*GOOD, "--processes", "4", "--", "/x"]).processes == 4


@pytest.mark.parametrize("bad", ["0", "-1", "+5", "1e3", "5.0", " 5", "05", "", "abc", "٣"])
def test_malformed_integers_rejected(bad: str) -> None:
    argv = ["--cpu-seconds", bad, *GOOD[2:], "--", "/x"]
    with pytest.raises(ResourcePolicyError):
        parse_launcher_argv(argv)


def test_structural_launcher_argv_violations_rejected() -> None:
    with pytest.raises(ResourcePolicyError, match="unknown"):
        parse_launcher_argv([*GOOD, "--wall-clock", "1", "--", "/x"])
    with pytest.raises(ResourcePolicyError, match="duplicate"):
        parse_launcher_argv([*GOOD, "--cpu-seconds", "6", "--", "/x"])
    with pytest.raises(ResourcePolicyError, match="separator"):
        parse_launcher_argv([*GOOD, "/x"])
    with pytest.raises(ResourcePolicyError, match="entrypoint"):
        parse_launcher_argv([*GOOD, "--"])
    with pytest.raises(ResourcePolicyError, match="pairs"):
        parse_launcher_argv([*GOOD, "--processes", "--", "/x"])
    with pytest.raises(ResourcePolicyError, match="missing"):
        parse_launcher_argv(["--cpu-seconds", "5", "--", "/x"])


def test_launcher_revalidates_ceilings_and_floors() -> None:
    over = str(HARD_RESOURCE_CEILINGS.cpu_seconds + 1)
    with pytest.raises(ResourcePolicyError, match="ceiling"):
        parse_launcher_argv(["--cpu-seconds", over, *GOOD[2:], "--", "/x"])
    with pytest.raises(ResourcePolicyError, match="minimum"):
        parse_launcher_argv(
            ["--cpu-seconds", "5", "--memory-bytes", str(MIB), "--file-descriptors", "32",
             "--", "/x"]
        )
    with pytest.raises(ResourcePolicyError, match="minimum"):
        parse_launcher_argv(
            ["--cpu-seconds", "5", "--memory-bytes", str(64 * MIB), "--file-descriptors", "3",
             "--", "/x"]
        )


def test_build_and_parse_round_trip_without_shell() -> None:
    argv = build_launcher_argv(
        {"cpu_seconds": 3, "memory_bytes": 64 * MIB, "file_descriptors": 16},
        ("/opt/p", "--flag", "v"),
    )
    assert argv[:2] == [sys.executable, "-I"]
    assert argv[argv.index("--") + 1 :] == ["/opt/p", "--flag", "v"]
    plan = parse_launcher_argv(argv[3:])
    assert plan.entrypoint == ("/opt/p", "--flag", "v")
    with pytest.raises(ResourcePolicyError):
        build_launcher_argv({"cpu_seconds": 3}, ("/opt/p",))
    with pytest.raises(ResourcePolicyError):
        build_launcher_argv({**dict(zip(launcher._REQUIRED, (3, 64 * MIB, 16), strict=True)),
                             "bogus": 1}, ("/opt/p",))


# --- enforcement planning --------------------------------------------------


def test_plan_reports_enforced_and_deferred_fields() -> None:
    effective = resolve_resource_budget("small")
    plan = plan_enforcement(effective)
    assert set(plan.os_limits) == {"cpu_seconds", "memory_bytes", "file_descriptors"}
    assert plan.message_bytes == effective.message_bytes
    assert plan.deferred_fields == ("concurrency", "processes", "wall_clock_seconds")
    per_uid = plan_enforcement(effective, process_mode=ProcessLimitMode.OS_PER_UID)
    assert per_uid.os_limits["processes"] == effective.processes
    assert "processes" not in per_uid.deferred_fields


@pytest.mark.parametrize(
    ("override", "match"),
    [
        (ResourceBudget(wall_clock_seconds=1), "not enforced yet"),
        (ResourceBudget(concurrency=1), "not enforced yet"),
        (ResourceBudget(processes=1), "cannot be enforced per plugin"),
        (ResourceBudget(file_descriptors=3), "enforceable minimum"),
        (ResourceBudget(memory_bytes=MIB), "enforceable minimum"),
        (ResourceBudget(message_bytes=10), "enforceable minimum"),
    ],
)
def test_plan_fails_closed_for_unenforceable_requests(override, match) -> None:
    effective = resolve_resource_budget("small", override)
    with pytest.raises(ResourcePolicyError, match=match):
        plan_enforcement(effective, override)


# --- B/C/D. limits observed by the real plugin process ----------------------


def test_child_sees_exact_cpu_memory_and_descriptor_limits() -> None:
    limits = _report(
        "rlimits",
        limits=ResourceBudget(cpu_seconds=3, memory_bytes=96 * MIB, file_descriptors=24),
    )
    assert limits["cpu"] == [3, 3]
    assert limits[("as" if "as" in limits else "vmem")] == [96 * MIB, 96 * MIB]
    assert limits["nofile"] == [24, 24]


def test_profile_defaults_are_enforced_without_overrides() -> None:
    limits = _report("rlimits", limits=ResourceBudget())
    small = resolve_resource_budget("small")
    assert limits["cpu"] == [small.cpu_seconds] * 2
    assert limits["nofile"] == [small.file_descriptors] * 2


def test_child_cannot_raise_its_limits() -> None:
    results = _report("raise_limits", limits=ResourceBudget())
    assert set(results.values()) == {"denied"}


def test_address_space_limit_blocks_allocation_beyond_budget() -> None:
    limits = ResourceBudget(memory_bytes=64 * MIB)
    assert _report("alloc", "200", limits=limits) == "memory_error"
    assert _report("alloc", "1", limits=limits) == "ok:1048576"


def test_descriptor_limit_is_hit_and_parent_stays_healthy() -> None:
    before = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
    result = _report("open_fds", limits=ResourceBudget(file_descriptors=16))
    assert result["errno"] == result["emfile"]
    assert 0 < result["opened"] <= 16
    if before is not None:
        assert len(os.listdir("/dev/fd")) <= before + 1


def test_descriptor_limit_never_relaxes_a_lower_inherited_hard_limit() -> None:
    code = (
        "import resource, os, sys\n"
        "resource.setrlimit(resource.RLIMIT_NOFILE, (20, 20))\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n"
    )
    probe = "import resource;print(resource.getrlimit(resource.RLIMIT_NOFILE))"
    argv = build_launcher_argv(
        {"cpu_seconds": 5, "memory_bytes": 64 * MIB, "file_descriptors": 64},
        (PY, "-c", probe),
    )
    done = subprocess.run(  # noqa: S603
        [PY, "-c", code, *argv], capture_output=True, text=True, timeout=20, check=False
    )
    assert done.stdout.strip() == "(20, 20)", done.stderr


# --- E. process limit ------------------------------------------------------


def test_processes_default_is_deferred_and_rlimit_nproc_untouched() -> None:
    limits = _report("rlimits", limits=ResourceBudget())
    assert limits["nproc"] == list(launcher.resource.getrlimit(launcher.resource.RLIMIT_NPROC))
    reports, runtime = _run_probe("rlimits", limits=ResourceBudget())
    try:
        runtime.start()
        assert "processes" in runtime.enforcement.deferred_fields
    finally:
        runtime.close()


def test_explicit_process_budget_fails_closed_unless_per_uid_mode_opted_in() -> None:
    _reports, runtime = _run_probe("rlimits", limits=ResourceBudget(processes=2))
    with pytest.raises(LifecycleError, match="cannot be enforced per plugin"):
        runtime.start()
    assert runtime.state is IsolatedPluginState.NEW


@pytest.mark.skipif(not hasattr(launcher.resource, "RLIMIT_NPROC"), reason="no RLIMIT_NPROC")
def test_per_uid_mode_applies_rlimit_nproc_with_documented_semantics() -> None:
    limits = _report(
        "rlimits",
        limits=ResourceBudget(processes=2),
        process_limit_mode=ProcessLimitMode.OS_PER_UID,
    )
    assert limits["nproc"] == [2, 2]


@pytest.mark.skipif(
    not hasattr(launcher.resource, "RLIMIT_NPROC") or os.geteuid() == 0,
    reason="needs RLIMIT_NPROC and a non-root user",
)
def test_per_uid_mode_blocks_fork_when_user_already_exceeds_the_count() -> None:
    result = _report(
        "fork",
        limits=ResourceBudget(processes=1),
        process_limit_mode=ProcessLimitMode.OS_PER_UID,
    )
    assert result == {"forked": False, "errno": result["eagain"], "eagain": result["eagain"]}


# --- CPU containment (bounded) ---------------------------------------------


def test_cpu_budget_terminates_a_spinning_plugin_without_hurting_the_parent() -> None:
    _reports, runtime = _run_probe("spin", limits=ResourceBudget(cpu_seconds=1))
    started = time.monotonic()
    try:
        runtime.start()
        with pytest.raises(LifecycleError):
            runtime.serve_once(timeout=10.0)
    finally:
        runtime.close()
    assert time.monotonic() - started < 9.0
    assert runtime.state in {IsolatedPluginState.FAILED, IsolatedPluginState.STOPPED}


# --- F. IPC message budget -------------------------------------------------


def test_inbound_oversized_message_is_rejected_under_lower_budget() -> None:
    limits = ResourceBudget(message_bytes=2048)
    _reports, runtime = _run_probe("big_request", "3000", limits=limits)
    try:
        runtime.start()
        assert runtime.enforcement.message_bytes == 2048
        with pytest.raises(LifecycleError):
            runtime.serve_once()
        assert runtime.state is IsolatedPluginState.FAILED
    finally:
        runtime.close()


def test_same_message_passes_without_a_lower_budget() -> None:
    reports, runtime = _run_probe("big_request", "3000", limits=None)
    try:
        runtime.start()
        runtime.serve_once()
        assert reports == ["x" * 3000]
    finally:
        runtime.close()


def test_outbound_oversized_response_is_rejected_under_lower_budget() -> None:
    _reports, runtime = _run_probe(
        "request_environment", "BIG",
        limits=ResourceBudget(message_bytes=2048),
        environment={"BIG": "y" * 3000},
    )
    try:
        runtime.start()
        with pytest.raises(LifecycleError):
            runtime.serve_once()
        assert runtime.state is IsolatedPluginState.FAILED
    finally:
        runtime.close()


def test_response_within_budget_is_delivered() -> None:
    _reports, runtime = _run_probe(
        "request_environment", "BIG",
        limits=ResourceBudget(message_bytes=2048),
        environment={"BIG": "y" * 100},
    )
    try:
        runtime.start()
        assert runtime.serve_once().ok
    finally:
        runtime.close()


def test_protocol_maximum_remains_authoritative(tmp_path: Path) -> None:
    message = IPCMessage("request.command", "r", {"name": "x", "argv": []})
    with pytest.raises(ValueError, match="max_bytes"):
        encode_message(message, max_bytes=MAX_FRAME_BYTES + 1)
    with pytest.raises(ValueError, match="max_bytes"):
        write_message(1, message, max_bytes=True)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="exceeds 16 bytes"):
        encode_message(message, max_bytes=16)


# --- G. spawn safety -------------------------------------------------------


def _marker_manifest(marker: Path):
    return validate_isolated_plugin_manifest({
        "manifest_version": 1, "name": "marker", "plugin_version": "1.0",
        "protocol_version": 1,
        "entrypoint": [PY, "-c", f"open({str(marker)!r}, 'w').close()"],
        "requested_capabilities": [], "resource_class": "small",
    })


def test_plugin_never_runs_when_policy_validation_fails(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "ran"
    popen_calls: list[object] = []
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: popen_calls.append(a) or real_popen(*a, **k)
    )
    runtime = IsolatedPluginRuntime(
        _marker_manifest(marker), resource_limits=ResourceBudget(memory_bytes=MIB)
    )
    with pytest.raises(LifecycleError, match="enforceable minimum"):
        runtime.start()
    assert popen_calls == []
    assert not marker.exists()
    assert runtime.state is IsolatedPluginState.NEW
    assert runtime.working_directory is None
    assert runtime.process_id is None


def test_unsupported_primitive_fails_closed_before_spawn(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "ran"
    monkeypatch.setattr(launcher, "_rlimit_names", lambda: {"cpu_seconds": 0})
    runtime = IsolatedPluginRuntime(_marker_manifest(marker), resource_limits=ResourceBudget())
    with pytest.raises(LifecycleError, match="no supported rlimit primitive"):
        runtime.start()
    assert not marker.exists()
    assert runtime.state is IsolatedPluginState.NEW


def test_launcher_refuses_bad_policy_without_executing_plugin(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    plugin = [PY, "-c", f"open({str(marker)!r}, 'w').close()"]
    for options in (
        ["--cpu-seconds", "0", *GOOD[2:]],
        [*GOOD, "--cpu-seconds", "9"],
        ["--cpu-seconds", "5"],
    ):
        done = subprocess.run(  # noqa: S603
            [PY, "-I", str(launcher.LAUNCHER_PATH), *options, "--", *plugin],
            capture_output=True, timeout=20, check=False,
        )
        assert done.returncode == EXIT_POLICY_REJECTED
        assert done.stdout == b""
    assert not marker.exists()


def test_launcher_exec_failure_is_deterministic(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603
        [PY, "-I", str(launcher.LAUNCHER_PATH), *GOOD, "--", str(tmp_path / "missing")],
        capture_output=True, timeout=20, check=False,
    )
    assert done.returncode == EXIT_APPLY_FAILED
    assert done.stdout == b""


def test_limits_are_in_force_when_the_plugin_first_runs() -> None:
    # The plugin is the exec'd image: its very first code observes the limits,
    # and there is no supervising launcher process left behind.
    code = (
        "import os, resource\n"
        "print(os.getppid() > 0, resource.getrlimit(resource.RLIMIT_NOFILE)[0],"
        " resource.getrlimit(resource.RLIMIT_CPU)[0], os.getpid())\n"
    )
    argv = build_launcher_argv(
        {"cpu_seconds": 7, "memory_bytes": 64 * MIB, "file_descriptors": 12}, (PY, "-c", code)
    )
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)  # noqa: S603
    out, _ = proc.communicate(timeout=20)
    _parent_ok, nofile, cpu, pid = out.split()
    assert (nofile, cpu) == ("12", "7")
    assert int(pid) == proc.pid  # launcher became the plugin: same PID, exec not fork


def test_launched_runtime_cleans_up_cwd_and_process_group() -> None:
    reports, runtime = _run_probe("rlimits", limits=ResourceBudget())
    runtime.start()
    cwd = runtime.working_directory
    pid = runtime.process_id
    assert cwd is not None and cwd.is_dir()
    runtime.shutdown()  # graceful or forced; either way it must be contained
    assert not cwd.exists()
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


# --- H. existing behaviour -------------------------------------------------


def test_ungoverned_runtime_still_spawns_directly_with_full_protocol_limit() -> None:
    reports, runtime = _run_probe("rlimits", limits=None)
    try:
        runtime.start()
        assert runtime.enforcement is None
        runtime.serve_once()
        limits = json.loads(reports[0])
        assert limits["nofile"][0] != 32  # not governed
    finally:
        runtime.close()
