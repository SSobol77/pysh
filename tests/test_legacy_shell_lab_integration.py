# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_legacy_shell_lab_integration.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 3: real reference-shell integration (CI/test equipment only).

These tests execute real Bash/Zsh/Fish and therefore never run in the normal
suite. ``PYSH_LEGACY_LAB`` selects the mode:

* unset: every test here is skipped;
* ``1``: run for each configured reference shell that is installed (workstation
  evidence only, never authoritative);
* ``required``: Tier-1 CI. A configured reference shell that is missing FAILS.
"""
from __future__ import annotations

import pytest

from tests.differential import reference
from tests.differential.corpus import load_migration

MODE = reference.lab_mode()
PLATFORM = reference.detect_platform_id()
PROFILES = sorted(
    (p for p in load_migration().profiles.values() if p.platform == PLATFORM),
    key=lambda p: p.profile_id,
)

pytestmark = pytest.mark.skipif(
    MODE == "off", reason=f"real reference shells run only with {reference.LAB_ENV}=1 or =required"
)


def test_a_tier1_platform_has_all_three_reference_profiles() -> None:
    if MODE == "required":
        assert {p.legacy_shell for p in PROFILES} == {"bash", "zsh", "fish"}, PLATFORM
    elif not PROFILES:
        pytest.skip(f"no reference profiles for platform {PLATFORM}")


@pytest.fixture(params=PROFILES or [None], ids=lambda p: p.profile_id if p else "no-profile")
def installed(request):
    profile = request.param
    if profile is None:
        pytest.skip(f"no reference profiles for platform {PLATFORM}")
    try:
        executable = reference.resolve_executable(profile)
    except reference.ReferenceUnavailable as error:
        if MODE == "required":
            pytest.fail(str(error))
        pytest.skip(str(error))
    return profile, executable


def test_version_matches_the_pin_or_is_reported_when_pending(installed) -> None:
    profile, executable = installed
    probe = reference.probe_reference(profile, executable)
    assert probe.version_line
    if profile.version_status == "pinned":
        reference.check_version(profile, probe)  # raises VersionDriftError on drift
    else:
        print(f"PENDING {profile.profile_id}: {probe.version_line!r} / {probe.package_version!r}")


def test_startup_isolation_is_proven_on_the_installed_version(installed) -> None:
    profile, executable = installed
    checks = reference.isolation_checks(profile, executable)
    failed = [c for c in checks if not c.ok]
    assert not failed, [f"{c.name}: {c.detail}" for c in failed]
    assert {c.name for c in checks} >= {
        "positive-control-reads-hostile-startup-files",
        "isolated-run-ignores-hostile-startup-files",
        "home-is-the-controlled-directory",
        "host-environment-is-not-inherited",
        "cwd-is-the-controlled-directory",
        "timeout-terminates-the-tree",
        "output-is-bounded",
    }


def test_selected_cases_satisfy_the_pysh_oracle_first_and_are_never_excused_by_a_reference(
    installed,
) -> None:
    profile, executable = installed
    from scripts.run_language_conformance import load_corpus

    language = {case["id"]: case for case in load_corpus()["cases"]}
    for case in reference.load_reference_cases():
        if profile.legacy_shell not in case.shells:
            continue
        case48 = language[case.case_id]
        pysh_obs = reference.observe_pysh(case48["input"])
        from tests.differential import oracle

        assert not oracle.mismatches(
            case48["pysh_expected"], pysh_obs, case.dimensions, reference.IDENTITY_PLACEHOLDERS
        ), f"PySH violates #48 for {case.case_id}"


def test_controlled_pty_cases_agree_with_the_pysh_owned_expectations(installed) -> None:
    """Real interactive sessions through the controlled PTY harness (selected, deterministic cases)."""
    from tests.differential import pty_lab

    profile, executable = installed
    cases, _data = pty_lab.load_pty_corpus()
    applicable = [c for c in cases if profile.legacy_shell in c.shells]
    records, problems = pty_lab.evaluate_profile(profile, executable)
    assert problems == [], problems
    assert [r.case_id for r in records] == [c.case_id for c in applicable]
    assert {r.classification for r in records} == {"MATCH"}  # no PTY divergence is registered
