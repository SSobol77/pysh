# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_platform_tier_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository policy checks for the PySH platform support contract."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "compatibility" / "platform-tiers.md"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
RPM_SPEC = REPO_ROOT / "packaging" / "rpm" / "pysh-shell.spec"
DEB_CONTROL = REPO_ROOT / "packaging" / "debian" / "control"
OS_WRAPPER = REPO_ROOT / "packaging" / "wrappers" / "pysh.sh"
RPM_SMOKE = REPO_ROOT / "scripts" / "smoke_rpm_package.sh"
FREEBSD_CONFIG = REPO_ROOT / "scripts" / "_freebsd_python.sh"
FREEBSD_BUILDER = REPO_ROOT / "scripts" / "build_freebsd_pkg.sh"
FREEBSD_SMOKE = REPO_ROOT / "scripts" / "smoke_freebsd_package.sh"


def _job(workflow: str, job_name: str) -> str:
    """Return one top-level workflow job without requiring a YAML parser."""
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    assert match is not None, f"workflow job not found: {job_name}"
    return match.group(0)


def test_platform_contract_is_normative_and_indexed() -> None:
    """The canonical contract exists and remains discoverable from both indexes."""
    assert CONTRACT.is_file()
    text = CONTRACT.read_text(encoding="utf-8")
    assert "normative source" in text

    for relative in ("docs/README.md", "docs/compatibility/README.md"):
        index = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "platform-tiers.md" in index, f"{relative} does not index the contract"


def test_runtime_family_policy_is_broader_than_reference_evidence() -> None:
    """Exact reference images must never become runtime-family allowlists."""
    text = CONTRACT.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("|")]

    assert any(
        "Debian-family Linux" in row and "CPython `>=3.13`" in row
        for row in rows
    )
    assert any(
        "RPM-family Linux" in row and "CPython `>=3.13`" in row
        for row in rows
    )
    assert any(
        "FreeBSD family" in row and "CPython `>=3.13`" in row
        for row in rows
    )

    for system in (
        "Ubuntu",
        "Kali Linux",
        "Linux Mint",
        "Pop!_OS",
        "Red Hat Enterprise Linux",
        "Rocky Linux",
        "AlmaLinux",
        "CentOS Stream",
        "GhostBSD",
    ):
        assert system in text

    normalized = " ".join(text.split())

    assert "Debian 13 / amd64 / CPython 3.13" in normalized
    assert "`fedora:43`" in normalized
    assert "FreeBSD 14.4 / amd64 / CPython 3.13" in normalized
    assert "evidence anchor, not a runtime allowlist" in normalized
    assert "Supported, not independently reference-validated" in normalized
    assert "Debian with CPython 3.14" in normalized
    assert "not automatically unsupported" in normalized
    assert "CPython `==3.13`" not in normalized


def test_validation_tiers_are_explicit_and_do_not_become_allowlists() -> None:
    """Tier 1 and Tier 2 describe evidence strength, not runtime allowlists."""
    text = CONTRACT.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("|")]

    assert any(
        "**Tier 1**" in row
        and "Debian-family Linux" in row
        and "FreeBSD family" in row
        for row in rows
    )
    assert any(
        "**Tier 2**" in row and "RPM-family Linux" in row
        for row in rows
    )

    normalized = " ".join(text.split())
    assert "Tier 1 therefore requires native CI/conformance evidence" in normalized
    assert "Tier 2 is not “unsupported”" in normalized
    assert "not an installation allowlist" in normalized


def test_python_runtime_policy_has_floor_without_upper_bound() -> None:
    """Project metadata and the platform contract permit compatible >=3.13."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    contract = CONTRACT.read_text(encoding="utf-8")

    assert project["requires-python"] == ">=3.13"
    assert "PySH requires CPython 3.13 or newer" in contract
    assert "Compatible newer CPython versions are" in contract
    assert "There is no upper Python-version bound" in contract


EVIDENCE_ENTRYPOINT = "scripts/check_resource_governor_evidence.sh"


def _assert_resource_governor_evidence_entrypoint(job: str, venv: str) -> None:
    """Pin the evidence ENTRYPOINT (the script owns the suite list), not its contents."""
    assert EVIDENCE_ENTRYPOINT in job
    assert 'PYSH_PYTEST="python -m pytest"' in job
    assert "Run resource governor evidence" in job or "Resource governor evidence" in job
    assert job.count(EVIDENCE_ENTRYPOINT) == 1
    assert "continue-on-error" not in job
    assert job.index(venv) < job.index(EVIDENCE_ENTRYPOINT)
    # The script, not the workflow, owns the resource test list.
    assert "tests/test_resource_" not in job


def test_debian_reference_gate_covers_platform_sensitive_contract() -> None:
    """Debian 13 is an exact evidence lane, not a runtime allowlist."""
    workflow = CI.read_text(encoding="utf-8")
    job = _job(workflow, "platform-debian")

    assert "image: debian:13-slim" in job
    assert 'test "${ID}" = "debian"' in job
    assert 'test "${VERSION_ID}" = "13"' in job
    assert 'test "$(dpkg --print-architecture)" = "amd64"' in job
    assert "python3.13 -m venv .venv-debian" in job
    assert "timeout-minutes: 30" in job
    assert "continue-on-error" not in job

    required = (
        "python scripts/run_language_conformance.py",
        "tests/test_language_conformance.py",
        "tests/test_parser.py",
        "tests/test_pty_integration.py",
        "tests/test_pty_smoke_helper.py",
        "tests/test_resize.py",
        "tests/test_secure_runner.py",
        "tests/test_signal_handling.py",
        "tests/test_job_control.py",
        "tests/test_redirection.py",
        "tests/test_isolated_plugin_runtime.py",
        "tests/test_safe_startup.py",
        "tests/test_rc.py",
        "tests/test_pyshrc_py.py",
        "tests/test_platform_tier_contract.py",
    )

    missing = [item for item in required if item not in job]
    assert not missing, f"Debian reference gate is missing: {missing!r}"
    _assert_resource_governor_evidence_entrypoint(job, ".venv-debian")


def test_freebsd_reference_gate_covers_platform_sensitive_contract() -> None:
    """FreeBSD 14.4 gates the reviewed native portability surfaces."""
    workflow = CI.read_text(encoding="utf-8")
    job = _job(workflow, "platform-freebsd")

    assert 'release: "14.4"' in job
    assert 'test "$(freebsd-version -u | cut -d- -f1)" = "14.4"' in job
    assert 'test "$(uname -m)" = "amd64"' in job
    assert "pkg install -y bash python313 uv git" in job
    assert "uv venv --python python3.13" in job
    assert "timeout-minutes: 45" in job
    assert "continue-on-error" not in job
    assert job.index("command -v bash") < job.index("tests/test_pty_integration.py")

    required = (
        "python scripts/run_language_conformance.py",
        "tests/test_language_conformance.py",
        "tests/test_parser.py",
        "tests/test_pty_integration.py",
        "tests/test_pty_smoke_helper.py",
        "tests/test_resize.py",
        "tests/test_secure_runner.py",
        "tests/test_signal_handling.py",
        "tests/test_job_control.py",
        "tests/test_redirection.py",
        "tests/test_isolated_plugin_runtime.py",
        "tests/test_safe_startup.py",
        "tests/test_rc.py",
        "tests/test_pyshrc_py.py",
        "tests/test_platform_tier_contract.py",
    )

    missing = [item for item in required if item not in job]
    assert not missing, f"FreeBSD reference gate is missing: {missing!r}"
    _assert_resource_governor_evidence_entrypoint(job, ".venv-freebsd")
    # Governor success evidence runs as a dedicated unprivileged account because
    # the launcher fails closed for any account able to raise its own rlimits.
    assert "pw useradd pyshci" in job
    assert "PYSH_EVIDENCE_REQUIRE_UNPRIVILEGED=1" in job
    assert (
        job.index("pw useradd pyshci")
        < job.index(EVIDENCE_ENTRYPOINT)
        < job.index("su -l pyshci")
    )


def test_native_freebsd_package_keeps_one_reference_release_asset() -> None:
    """FreeBSD ABI validation must not become two public release packages."""
    workflow = RELEASE.read_text(encoding="utf-8")
    package_job = _job(workflow, "freebsd-pkg")
    build_job = _job(workflow, "build-and-validate")
    builder = FREEBSD_BUILDER.read_text(encoding="utf-8")
    smoke = FREEBSD_SMOKE.read_text(encoding="utf-8")

    assert '- release: "14.4"' in package_job
    assert "artifact: freebsd-reference-pkg" in package_job
    assert "reference-pkg: true" in package_job

    assert "freebsd-validation-15" in workflow

    assert 'release: "${{ matrix.release }}"' in package_job
    assert 'pkg query -F "${PKG_PATH}" "%q"' in package_job
    assert "freebsd-reference-pkg" in build_job
    assert "freebsd-validation-15" not in build_job

    assert 'HOST_ABI="$(pkg config ABI)"' in builder
    assert 'if [ "${PACKAGE_ABI}" != "${HOST_ABI}" ]' in builder
    assert "refusing installation" in smoke

    assert "freebsd14" not in workflow
    assert "freebsd15" not in workflow


def test_deb_and_rpm_metadata_keep_runtime_python_floor() -> None:
    """OS packages use the >=3.13 runtime contract without a hard upper bound."""
    deb = DEB_CONTROL.read_text(encoding="utf-8")
    rpm = RPM_SPEC.read_text(encoding="utf-8")
    wrapper = OS_WRAPPER.read_text(encoding="utf-8")

    assert "Depends: python3 (>= 3.13)" in deb
    assert "Requires:       python3 >= 3.13" in rpm
    assert "sys.version_info >= (3, 13)" in wrapper
    assert "command -v python3" in wrapper
    assert 'python3.*' in wrapper
    assert 'exec "${PYSH_PYTHON}" -m pysh "$@"' in wrapper


def test_rpm_reference_is_package_evidence_not_runtime_allowlist() -> None:
    """Fedora 43 remains a pinned RPM evidence environment only."""
    contract = CONTRACT.read_text(encoding="utf-8")
    smoke = RPM_SMOKE.read_text(encoding="utf-8")

    assert 'RPM_IMAGE="fedora:43"' in smoke
    assert "`fedora:43`" in contract
    assert "package reference" in contract
    assert "runtime allowlist" in contract


def test_freebsd_python_target_is_configurable_but_reference_stays_on_3_13() -> None:
    """Package Python selection is explicit and separate from the runtime floor."""
    helper = FREEBSD_CONFIG.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")

    assert "PYSH_FREEBSD_PYTHON_VERSION-3.13" in helper
    assert "PYSH_FREEBSD_PYTHON_COMMAND" in helper
    assert "PYSH_FREEBSD_PYTHON_PACKAGE" in helper
    assert "PYSH_FREEBSD_PYTHON_ORIGIN" in helper
    assert "export PYSH_FREEBSD_PYTHON_VERSION=3.13" in release

    assert "single package is not interpreter-version agnostic" in contract
    assert "Python selection does not determine OS ABI compatibility" in contract


def test_proc_fd_is_linux_only_and_freebsd_has_native_probe_policy() -> None:
    """Linux procfs must not become a FreeBSD portability requirement."""
    text = CONTRACT.read_text(encoding="utf-8")

    proc_paragraph = next(
        paragraph for paragraph in text.split("\n\n") if "/proc/self/fd" in paragraph
    )

    assert "Linux-specific" in proc_paragraph
    assert "not a portable PySH" in proc_paragraph

    freebsd_policy = text.split("## FreeBSD-specific mechanisms", maxsplit=1)[1]
    assert "mounting" in freebsd_policy
    assert "emulating" in freebsd_policy
    assert "Linux" in freebsd_policy
    assert "fstat" in freebsd_policy


def test_platform_capability_fallback_policy_is_fail_closed() -> None:
    """Unknown platforms and failed capability probes cannot silently pass."""
    text = CONTRACT.read_text(encoding="utf-8")

    assert "deterministic supported fallback" in text
    assert "unsupported on this platform" in text
    assert "Silent behavior changes" in text
    assert "fails its gate" in text


def test_contract_does_not_overstate_capsicum_or_plugin_isolation() -> None:
    """Future hardening anchors must not be presented as current confinement."""
    text = CONTRACT.read_text(encoding="utf-8")

    normalized = " ".join(text.split())

    assert "does **not** implement or claim Capsicum confinement" in normalized
    assert "not a filesystem or network sandbox" in normalized
