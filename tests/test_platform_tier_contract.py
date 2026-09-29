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


def _job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    assert match is not None, f"workflow job not found: {job_name}"
    return match.group(0)


def test_platform_contract_is_normative_and_indexed() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "normative source" in text
    for relative in ("docs/README.md", "docs/compatibility/README.md"):
        assert "platform-tiers.md" in (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_supported_families_are_broader_than_reference_images() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for family in ("Debian-family Linux", "RPM-family Linux", "FreeBSD family"):
        assert family in text
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
    assert "not minimum releases" in text
    assert "not independently reference-validated" in text


def test_python_policy_has_floor_without_upper_bound() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    text = CONTRACT.read_text(encoding="utf-8")
    assert project["requires-python"] == ">=3.13"
    assert "CPython 3.13.0 or newer" in text
    assert "no upper Python-version bound" in text
    assert "sys.version_info >= (3, 13)" in text


def test_reference_ci_versions_are_explicit_but_not_product_gates() -> None:
    workflow = CI.read_text(encoding="utf-8")
    debian = _job(workflow, "platform-debian")
    freebsd = _job(workflow, "platform-freebsd")
    assert "image: debian:13-slim" in debian
    assert 'release: "14.4"' in freebsd
    assert "pkg install -y bash python313 uv git" in freebsd
    assert freebsd.index("command -v bash") < freebsd.index("tests/test_pty_integration.py")
    assert "continue-on-error" not in debian + freebsd


def test_native_freebsd_package_keeps_abi_check_and_one_reference_asset() -> None:
    workflow = RELEASE.read_text(encoding="utf-8")
    builder = (REPO_ROOT / "scripts" / "build_freebsd_pkg.sh").read_text(
        encoding="utf-8"
    )
    smoke = (REPO_ROOT / "scripts" / "smoke_freebsd_package.sh").read_text(
        encoding="utf-8"
    )
    assert 'release: "${{ matrix.release }}"' in workflow
    assert "reference-pkg: true" in workflow
    assert "freebsd-reference-pkg" in workflow
    assert 'pkg query -F "${PKG_PATH}" "%q"' in workflow
    assert 'HOST_ABI="$(pkg config ABI)"' in builder
    assert 'if [ "${PACKAGE_ABI}" != "${HOST_ABI}" ]' in builder
    assert "refusing installation" in smoke
    assert "freebsd14" not in workflow
    assert "freebsd15" not in workflow


def test_deb_and_rpm_metadata_keep_python_floor() -> None:
    deb = (REPO_ROOT / "packaging" / "debian" / "control").read_text(encoding="utf-8")
    rpm = (REPO_ROOT / "packaging" / "rpm" / "pysh-shell.spec").read_text(
        encoding="utf-8"
    )
    wrapper = (REPO_ROOT / "packaging" / "wrappers" / "pysh.sh").read_text(
        encoding="utf-8"
    )
    assert "Depends: python3 (>= 3.13)" in deb
    assert "Requires:       python3 >= 3.13" in rpm
    assert "sys.version_info >= (3, 13)" in wrapper
    assert "exec /usr/bin/python3" not in wrapper
