# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_gate.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RQG-H release gate orchestrator.

``scripts/release_gate.py`` sequences the existing RQG-A through RQG-G
checks (and ruff/pytest/git) into one PASS/FAIL/NOT_RUN/PLATFORM_BLOCKED
manifest. It never reimplements any check's validation logic.

Most tests here exercise the orchestrator's own logic (manifest assembly,
overall-status derivation, mode filtering, JSON schema, failure
collection) against small, fast, injected fake ``Check`` objects -- never
by re-running the real, expensive, already-exhaustively-tested checks a
second time. A handful of tests do invoke the real, fast checks (metadata,
ruff, headers, git diff, docs/workflow contract structural mode) to prove
the wiring is genuine, and one CLI-level test runs real ``--mode fast``
end to end. Nothing here builds artifacts, runs pytest recursively,
touches Docker, publishes, tags, or pushes.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # release_gate.py combines `from __future__ import annotations` with
    # @dataclasses.dataclass; resolving those string annotations requires
    # the module to already be registered in sys.modules before exec.
    sys.modules["release_gate"] = module
    spec.loader.exec_module(module)
    return module


GATE = _load_module()


def _fake_check(name: str, category: str, modes: frozenset[str], status: str, **kwargs):
    def _run(_log_dir: Path):
        return GATE.CheckResult(status=status, **kwargs)

    return GATE.Check(name=name, category=category, modes=modes, run=_run)


ALL_MODES = frozenset({"fast", "ci", "full"})


# ---------------------------------------------------------------- 1. all PASS


def test_all_checks_pass_yields_overall_pass(tmp_path: Path) -> None:
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("b", "cat", ALL_MODES, GATE.STATUS_PASS),
    ]
    manifest = GATE.run_gate("fast", checks, tmp_path)
    assert manifest["overall"] == GATE.OVERALL_PASS
    assert manifest["exit_code"] == 0
    assert all(e["status"] == GATE.STATUS_PASS for e in manifest["checks"])


# ------------------------------------------------- 2. one independent FAIL


def test_one_independent_failure_yields_overall_fail(tmp_path: Path) -> None:
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("b", "cat", ALL_MODES, GATE.STATUS_FAIL, diagnostic="boom"),
        _fake_check("c", "cat", ALL_MODES, GATE.STATUS_PASS),
    ]
    manifest = GATE.run_gate("fast", checks, tmp_path)
    assert manifest["overall"] == GATE.OVERALL_FAIL
    assert manifest["exit_code"] == 1


# ---------------------------------------------- 3. multiple failures listed


def test_multiple_failures_all_appear_in_manifest(tmp_path: Path) -> None:
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_FAIL, diagnostic="first failure"),
        _fake_check("b", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("c", "cat", ALL_MODES, GATE.STATUS_FAIL, diagnostic="second failure"),
    ]
    manifest = GATE.run_gate("fast", checks, tmp_path)
    assert manifest["overall"] == GATE.OVERALL_FAIL
    failing = [e for e in manifest["checks"] if e["status"] == GATE.STATUS_FAIL]
    assert {e["name"] for e in failing} == {"a", "c"}
    assert {e["diagnostic"] for e in failing} == {"first failure", "second failure"}
    # 'b' must still have executed (independent later checks are not
    # skipped merely because an earlier one failed).
    assert any(e["name"] == "b" and e["status"] == GATE.STATUS_PASS for e in manifest["checks"])


# ------------------------------------------- 4. one PLATFORM_BLOCKED + rest PASS


def test_platform_blocked_with_rest_passing_is_ready_except_platform(tmp_path: Path) -> None:
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("b", "platform", ALL_MODES, GATE.STATUS_PLATFORM_BLOCKED, diagnostic="no FreeBSD"),
    ]
    manifest = GATE.run_gate("full", checks, tmp_path)
    assert manifest["overall"] == GATE.OVERALL_READY_EXCEPT_PLATFORM
    assert manifest["exit_code"] == 0


def test_fail_takes_priority_over_platform_blocked(tmp_path: Path) -> None:
    """A real failure must never be masked by a platform-blocked status."""
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_FAIL),
        _fake_check("b", "platform", ALL_MODES, GATE.STATUS_PLATFORM_BLOCKED),
    ]
    manifest = GATE.run_gate("full", checks, tmp_path)
    assert manifest["overall"] == GATE.OVERALL_FAIL
    assert manifest["exit_code"] == 1


# ------------------------------------------- 5. NOT_RUN in intentional omission


def test_not_run_in_unselected_mode_does_not_affect_overall(tmp_path: Path) -> None:
    checks = [
        _fake_check("fast-check", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("heavy-check", "tests", frozenset({"ci", "full"}), GATE.STATUS_PASS),
    ]
    manifest = GATE.run_gate("fast", checks, tmp_path)
    heavy_entry = next(e for e in manifest["checks"] if e["name"] == "heavy-check")
    assert heavy_entry["status"] == GATE.STATUS_NOT_RUN
    assert manifest["overall"] == GATE.OVERALL_PASS


def test_not_run_check_never_executes_its_run_callable(tmp_path: Path) -> None:
    calls: list[str] = []

    def _run(_log_dir: Path):
        calls.append("ran")
        return GATE.CheckResult(status=GATE.STATUS_PASS)

    checks = [GATE.Check("heavy", "tests", frozenset({"ci", "full"}), _run)]
    GATE.run_gate("fast", checks, tmp_path)
    assert calls == []


# --------------------------------------- 6. mode contract: required checks present


@pytest.mark.parametrize(
    "expected_name",
    [
        "metadata contract",
        "Ruff",
        "headers",
        "git diff",
        "installation-doc contract",
        "release workflow contract",
    ],
)
def test_fast_mode_includes_expected_static_checks(expected_name: str) -> None:
    checks = GATE.build_checks()
    matching = next(c for c in checks if c.name == expected_name)
    assert "fast" in matching.modes


@pytest.mark.parametrize(
    "expected_name",
    [
        "unit/integration tests",
        "PTY TERM=dumb",
        "PTY TERM=xterm-256color",
        "artifact contract",
    ],
)
def test_ci_mode_includes_expected_heavy_checks(expected_name: str) -> None:
    checks = GATE.build_checks()
    matching = next(c for c in checks if c.name == expected_name)
    assert "ci" in matching.modes
    assert "fast" not in matching.modes


@pytest.mark.parametrize(
    "expected_name", ["Debian install smoke", "RPM install smoke", "FreeBSD install smoke"]
)
def test_full_mode_includes_platform_checks_only_in_full(expected_name: str) -> None:
    checks = GATE.build_checks()
    matching = next(c for c in checks if c.name == expected_name)
    assert matching.modes == frozenset({"full"})


def test_ci_mode_check_accidentally_missing_would_fail_this_contract() -> None:
    """Proves item 6 (a required CI check silently omitted is a contract error).

    If a future change accidentally removed "unit/integration tests" from
    ci mode's check set, this test -- not a human reading the manifest --
    would fail.
    """
    checks = GATE.build_checks()
    ci_names = {c.name for c in checks if "ci" in c.modes}
    required_for_ci = {
        "metadata contract",
        "Ruff",
        "headers",
        "git diff",
        "installation-doc contract",
        "release workflow contract",
        "unit/integration tests",
        "PTY TERM=dumb",
        "PTY TERM=xterm-256color",
        "artifact contract",
    }
    assert required_for_ci <= ci_names


# --------------------------------------------------------- 7/8. manifest schema


def test_json_manifest_is_schema_stable(tmp_path: Path) -> None:
    checks = [_fake_check("a", "cat", ALL_MODES, GATE.STATUS_PASS)]
    manifest = GATE.run_gate("fast", checks, tmp_path)
    text = json.dumps(manifest)
    parsed = json.loads(text)
    assert set(parsed.keys()) == {"mode", "overall", "exit_code", "host", "log_dir", "checks"}
    entry = parsed["checks"][0]
    assert set(entry.keys()) == {
        "name",
        "category",
        "status",
        "exit_code",
        "duration_seconds",
        "diagnostic",
        "log_path",
    }
    assert parsed["overall"] in (
        GATE.OVERALL_PASS,
        GATE.OVERALL_FAIL,
        GATE.OVERALL_READY_EXCEPT_PLATFORM,
    )


def test_human_manifest_is_deterministic_given_same_results(tmp_path: Path) -> None:
    checks = [
        _fake_check("a", "cat", ALL_MODES, GATE.STATUS_PASS),
        _fake_check("b", "cat", ALL_MODES, GATE.STATUS_FAIL, diagnostic="boom"),
    ]
    manifest1 = GATE.run_gate("fast", checks, tmp_path)
    manifest2 = GATE.run_gate("fast", checks, tmp_path)
    assert GATE.render_human_manifest(manifest1) == GATE.render_human_manifest(manifest2)


def test_human_manifest_shows_platform_blocked_label_distinctly(tmp_path: Path) -> None:
    checks = [_fake_check("a", "platform", ALL_MODES, GATE.STATUS_PLATFORM_BLOCKED)]
    manifest = GATE.run_gate("full", checks, tmp_path)
    text = GATE.render_human_manifest(manifest)
    assert "[PLATFORM BLOCKED] a" in text
    assert "Overall: READY_EXCEPT_PLATFORM_VALIDATION" in text


# ------------------------------------------------------------- 9. exit codes


def test_exit_code_contract() -> None:
    assert GATE.EXIT_CODE_BY_OVERALL[GATE.OVERALL_PASS] == 0
    assert GATE.EXIT_CODE_BY_OVERALL[GATE.OVERALL_READY_EXCEPT_PLATFORM] == 0
    assert GATE.EXIT_CODE_BY_OVERALL[GATE.OVERALL_FAIL] == 1
    assert GATE.MISUSE_EXIT_CODE == 2


def test_cli_invalid_mode_returns_misuse_exit_code() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "nonexistent"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    # argparse itself rejects an invalid choice with exit code 2, which is
    # also this orchestrator's own documented misuse code.
    assert result.returncode == 2


# --------------------------------------------- 10. timeout/failure captured safely


def test_subprocess_timeout_is_captured_as_fail_not_a_traceback(tmp_path: Path) -> None:
    result = GATE.run_subprocess_check(
        ["sleep", "5"], log_dir=tmp_path, log_name="slow", timeout=0.1
    )
    assert result.status == GATE.STATUS_FAIL
    assert "timed out" in result.diagnostic


def test_subprocess_start_failure_is_captured_as_fail_not_a_traceback(tmp_path: Path) -> None:
    result = GATE.run_subprocess_check(
        ["/no/such/executable-pysh-release-gate-test"], log_dir=tmp_path, log_name="missing"
    )
    assert result.status == GATE.STATUS_FAIL
    assert "failed to start" in result.diagnostic


def test_successful_subprocess_writes_a_readable_log(tmp_path: Path) -> None:
    result = GATE.run_subprocess_check(
        ["python3", "-c", "print('hello-from-release-gate-test')"],
        log_dir=tmp_path,
        log_name="ok",
    )
    assert result.status == GATE.STATUS_PASS
    assert result.log_path is not None
    assert "hello-from-release-gate-test" in Path(result.log_path).read_text(encoding="utf-8")


# ------------------------------------------------------- 11. Docker unavailable


def test_debian_smoke_is_platform_blocked_when_docker_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GATE, "docker_usable", lambda: False)
    result = GATE.check_debian_smoke(tmp_path)
    assert result.status == GATE.STATUS_PLATFORM_BLOCKED
    assert "Docker" in result.diagnostic


def test_rpm_smoke_is_platform_blocked_when_docker_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GATE, "docker_usable", lambda: False)
    result = GATE.check_rpm_smoke(tmp_path)
    assert result.status == GATE.STATUS_PLATFORM_BLOCKED
    assert result.status != GATE.STATUS_PASS
    assert "Docker" in result.diagnostic


def test_rpm_smoke_never_reports_pass_from_build_success_alone() -> None:
    """A successful build_rpm.sh run must never be conflated with a real
    install-and-run PASS.

    Structural proof: check_rpm_smoke's only STATUS_PASS-producing path is
    its final `run_subprocess_check(...smoke_rpm_package.sh...)` return --
    there is no early `return CheckResult(status=STATUS_PASS` anywhere in
    the function, i.e. a successful build step alone can never short-
    circuit to PASS without the real smoke script actually running.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("def check_rpm_smoke(")
    end = source.index("\ndef check_freebsd_smoke(")
    body = source[start:end]
    assert "status=STATUS_PASS" not in body
    assert body.strip().endswith(
        'log_name="rpm-smoke",\n        timeout=600.0,\n    )'
    )


# ------------------------------------------------------- 12. FreeBSD unavailable


def test_freebsd_smoke_is_platform_blocked_on_non_freebsd_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a non-FreeBSD host, this must never fake a PASS.

    Real FreeBSD execution only happens on an actual FreeBSD host, which
    this repository's dev/CI/test environments are not; that real
    execution is exercised separately in
    tests/test_freebsd_package_smoke_contract.py and in
    .github/workflows/release-artifacts.yml's FreeBSD 14.4 VM job.
    """
    monkeypatch.setattr(GATE.platform, "system", lambda: "Linux")
    result = GATE.check_freebsd_smoke(tmp_path)
    assert result.status == GATE.STATUS_PLATFORM_BLOCKED
    assert result.status != GATE.STATUS_PASS
    assert "FreeBSD" in result.diagnostic
    assert "smoke_freebsd_package.sh" in result.diagnostic


def test_freebsd_smoke_attempts_real_build_and_install_on_freebsd_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a (simulated) FreeBSD host, the orchestrator must attempt the real
    build/smoke chain rather than short-circuiting to PLATFORM_BLOCKED.

    This cannot build a real .pkg on this (non-FreeBSD) test host, so
    build_freebsd_pkg.sh is expected to fail fast with its own
    "must be built on FreeBSD" guard -- the important behavior under test
    is that check_freebsd_smoke() actually invokes that script instead of
    skipping straight to PLATFORM_BLOCKED, and reports the failure as FAIL,
    not PLATFORM_BLOCKED and not a faked PASS.
    """
    monkeypatch.setattr(GATE.platform, "system", lambda: "FreeBSD")
    result = GATE.check_freebsd_smoke(tmp_path)
    assert result.status == GATE.STATUS_FAIL
    assert result.status != GATE.STATUS_PASS


# --------------------------------------------------- 13/14/15. mode semantics


def test_fast_mode_does_not_run_heavy_checks_end_to_end() -> None:
    """Real CLI invocation: fast mode must not attempt pytest/PTY/artifacts/platform."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "fast"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for heavy in (
        "unit/integration tests",
        "PTY TERM=dumb",
        "PTY TERM=xterm-256color",
        "artifact contract",
        "Debian install smoke",
        "RPM install smoke",
        "FreeBSD install smoke",
    ):
        assert f"[NOT RUN] {heavy}" in result.stdout
    assert "Overall: PASS" in result.stdout


# ----------------------------------------------- 16. no publish/tag/upload commands


def test_orchestrator_never_publishes_tags_or_uploads() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "git tag",
        "git push",
        "gh release upload",
        "gh release create",
        "twine upload",
        "pypa/gh-action-pypi-publish",
    )
    for phrase in forbidden:
        assert phrase not in text, f"release_gate.py must never contain: {phrase!r}"


def test_orchestrator_never_writes_pyproject_or_changelog() -> None:
    """The only writes in this file are: sub-check logs, the JSON manifest,
    and a disposable fixture file inside a temp directory
    (check_artifact_contract's labeled FreeBSD placeholder). None of those
    touch pyproject.toml, CHANGELOG.md, or any tracked repository file.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("pyproject.toml", "CHANGELOG.md"):
        assert f'{forbidden}", "w' not in text
        assert f"open({forbidden!r}" not in text
    # The three legitimate write sites, named explicitly so a new, unreviewed
    # write call anywhere else in the file fails this test.
    allowed_write_sites = ("log_path.write_text", "args.json.write_text", "fixture_pkg.write_text")
    remaining = text
    for site in allowed_write_sites:
        remaining = remaining.replace(site, "")
    assert ".write_text(" not in remaining
    assert ".write_bytes(" not in remaining


# ------------------------------------------------- 17. RQG-B/C/D/F/G intact


def test_rqg_bcdfg_scripts_still_present_and_reused() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for script_name in (
        "check_release_metadata.sh",
        "check_release_artifacts.sh",
        "check_installation_docs.py",
        "smoke_debian_package.sh",
        "check_release_workflow.py",
    ):
        assert script_name in text, f"release_gate.py must reuse {script_name}"
    for name in (
        "test_release_metadata_contract.py",
        "test_release_artifact_contract.py",
        "test_debian_package_smoke_contract.py",
        "test_installation_docs_contract.py",
        "test_release_workflow_contract.py",
    ):
        assert (REPO_ROOT / "tests" / name).is_file()


# ---------------------------------------------------- real, fast checks wiring


def test_metadata_contract_check_is_real_and_passes(tmp_path: Path) -> None:
    result = GATE.check_metadata_contract(tmp_path)
    assert result.status == GATE.STATUS_PASS, result.diagnostic


def test_release_workflow_check_is_real_and_passes(tmp_path: Path) -> None:
    result = GATE.check_release_workflow(tmp_path)
    assert result.status == GATE.STATUS_PASS, result.diagnostic


def test_installation_docs_check_is_real_and_passes(tmp_path: Path) -> None:
    result = GATE.check_installation_docs(tmp_path)
    assert result.status == GATE.STATUS_PASS, result.diagnostic


def test_git_diff_check_is_real(tmp_path: Path) -> None:
    result = GATE.check_git_diff(tmp_path)
    assert result.status in (GATE.STATUS_PASS, GATE.STATUS_FAIL)
