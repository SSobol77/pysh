# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_platform_tier_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Stable repository-policy checks for the PySH v1.0 platform tiers."""
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


def _job(workflow: str, job_name: str) -> str:
    """Return one top-level workflow job without requiring a YAML dependency."""
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    assert match is not None, f"workflow job not found: {job_name}"
    return match.group(0)


def test_platform_contract_is_normative_and_indexed() -> None:
    """The canonical contract must exist and both compatibility indexes link it."""
    assert CONTRACT.is_file()
    text = CONTRACT.read_text(encoding="utf-8")
    assert "normative source" in text
    for relative in ("docs/README.md", "docs/compatibility/README.md"):
        index = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "platform-tiers.md" in index, f"{relative} does not index the contract"


def test_runtime_family_matrix_distinguishes_support_from_reference_evidence() -> None:
    """Supported families must remain broader than their exact evidence anchors."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "| Debian-family Linux | CPython `>=3.13` | Supported" in text
    assert "| RPM-family Linux | CPython `>=3.13` | Supported" in text
    assert "| FreeBSD | CPython `>=3.13` | Supported" in text
    assert "Debian 13 / amd64 / CPython 3.13" in text
    assert "FreeBSD 14.4 / amd64 / CPython 3.13" in text
    assert "`fedora:43`" in text
    assert "evidence anchor, not a runtime" in text
    assert "Supported, not independently reference-validated" in text
    assert "Debian with CPython 3.14" in text
    assert "not automatically unsupported" in text


def test_python_runtime_policy_and_reference_baselines_are_distinct() -> None:
    """Metadata permits >=3.13 while every current reference stays on 3.13."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.13"

    contract = CONTRACT.read_text(encoding="utf-8")
    assert "PySH requires CPython 3.13 or newer" in contract
    assert "Compatible newer CPython versions are inside" in contract

    workflow = CI.read_text(encoding="utf-8")
    linux_job = _job(workflow, "test")
    debian_job = _job(workflow, "platform-debian")
    freebsd_job = _job(workflow, "platform-freebsd")
    assert 'python-version: "3.13"' in linux_job
    assert "python3.13 -m venv .venv-debian" in debian_job
    assert "pkg install -y python313" in freebsd_job
    assert "uv venv --python python3.13" in freebsd_job


def test_debian_reference_gate_covers_platform_sensitive_contract() -> None:
    """Debian 13 must be an exact evidence lane, never a runtime allowlist."""
    workflow = CI.read_text(encoding="utf-8")
    job = _job(workflow, "platform-debian")
    assert "image: debian:13-slim" in job
    assert 'test "${ID}" = "debian"' in job
    assert 'test "${VERSION_ID}" = "13"' in job
    assert 'test "$(dpkg --print-architecture)" = "amd64"' in job
    assert "python3.13 -m venv .venv-debian" in job
    assert "timeout-minutes: 30" in job
    assert "continue-on-error" not in job

    required_commands = (
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
        "tests/test_platform_tier_contract.py",
    )
    missing = [command for command in required_commands if command not in job]
    assert not missing, f"Debian reference gate is missing: {missing!r}"


def test_freebsd_reference_gate_covers_platform_sensitive_contract() -> None:
    """FreeBSD reference CI must gate every reviewed portability surface."""
    workflow = CI.read_text(encoding="utf-8")
    job = _job(workflow, "platform-freebsd")
    assert 'release: "14.4"' in job
    assert 'test "$(uname -m)" = "amd64"' in job
    assert "continue-on-error" not in job

    required_commands = (
        "python scripts/run_language_conformance.py",
        "tests/test_language_conformance.py",
        "tests/test_parser.py",
        "tests/test_pty_integration.py",
        "tests/test_resize.py",
        "tests/test_secure_runner.py",
        "tests/test_signal_handling.py",
        "tests/test_job_control.py",
        "tests/test_redirection.py",
        "tests/test_isolated_plugin_runtime.py",
        "tests/test_safe_startup.py",
        "tests/test_platform_tier_contract.py",
        "--profile freebsd-14-4-python3-13",
    )
    missing = [command for command in required_commands if command not in job]
    assert not missing, f"FreeBSD reference gate is missing: {missing!r}"


def test_native_package_evidence_remains_separate() -> None:
    """The platform gate must not replace native FreeBSD package validation."""
    workflow = RELEASE.read_text(encoding="utf-8")
    freebsd_package_job = _job(workflow, "freebsd-pkg")
    assert 'freebsd: ["14", "15"]' in freebsd_package_job
    assert 'release: "${{ matrix.freebsd }}"' in freebsd_package_job
    assert "sh scripts/build_freebsd_pkg.sh" in freebsd_package_job
    assert 'pkg info -F "${PKG_PATH}"' in freebsd_package_job
    assert 'pkg query -F "${PKG_PATH}" "%q"' in freebsd_package_job
    assert "freebsd${major}-amd64.pkg" in freebsd_package_job
    assert 'sh scripts/smoke_freebsd_package.sh "${PKG_PATH}"' in freebsd_package_job
    assert "export PYSH_FREEBSD_PYTHON_VERSION=3.13" in freebsd_package_job
    assert "continue-on-error" not in freebsd_package_job


def test_rpm_family_policy_and_pinned_package_reference_are_distinct() -> None:
    """Fedora 43 evidence must not become an RPM-family runtime allowlist."""
    contract = CONTRACT.read_text(encoding="utf-8")
    smoke = RPM_SMOKE.read_text(encoding="utf-8")
    spec = RPM_SPEC.read_text(encoding="utf-8")
    deb_control = DEB_CONTROL.read_text(encoding="utf-8")
    wrapper = OS_WRAPPER.read_text(encoding="utf-8")
    assert 'RPM_IMAGE="fedora:43"' in smoke
    assert "Requires:       python3 >= 3.13" in spec
    assert "Depends: python3 (>= 3.13)" in deb_control
    assert 'exec /usr/bin/python3 -m pysh "$@"' in wrapper
    assert "python3.13" not in wrapper
    assert "RPM-family Linux | CPython `>=3.13`" in contract
    assert "package-path evidence" in contract
    assert "not a claim that every Fedora" in contract


def test_freebsd_package_target_is_configurable_but_release_stays_on_3_13() -> None:
    """Package machinery is selectable while current evidence remains pinned."""
    helper = FREEBSD_CONFIG.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    assert "PYSH_FREEBSD_PYTHON_VERSION-3.13" in helper
    assert "PYSH_FREEBSD_PYTHON_COMMAND" in helper
    assert "PYSH_FREEBSD_PYTHON_PACKAGE" in helper
    assert "PYSH_FREEBSD_PYTHON_ORIGIN" in helper
    assert "single package is not interpreter-version agnostic" in contract
    assert "export PYSH_FREEBSD_PYTHON_VERSION=3.13" in release
    assert "Python selection does not determine OS ABI compatibility" in contract


def test_proc_fd_is_linux_only_and_freebsd_has_a_native_probe_policy() -> None:
    """Linux procfs must never become the cross-platform descriptor contract."""
    text = CONTRACT.read_text(encoding="utf-8")
    proc_paragraph = next(
        paragraph for paragraph in text.split("\n\n") if "/proc/self/fd" in paragraph
    )
    assert "Linux-specific" in proc_paragraph
    assert "not a portable PySH abstraction" in proc_paragraph
    assert "fstat" in text
    freebsd_policy = text.split("## FreeBSD-specific mechanisms", maxsplit=1)[1]
    assert all(word in freebsd_policy for word in ("mounting", "emulating", "Linux `/proc`"))


def test_contract_does_not_overstate_capsicum_or_plugin_isolation() -> None:
    """The hardening anchor must not be presented as implemented confinement."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "does **not** implement or claim Capsicum confinement" in text
    assert "is not a filesystem or network sandbox" in text
