# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_metadata_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Dynamic regression tests for the Issue #33 RQG-B metadata/changelog/tag gate.

``scripts/check_release_metadata.sh`` validates, without building anything:

- ``src/pysh/__init__.py`` ``__version__`` against ``pyproject.toml``'s
  authoritative version;
- ``pyproject.toml`` name/license/Requires-Python/console-script entrypoint;
- a CHANGELOG.md heading contract (ordering, duplicates, Unreleased
  handling), optionally in strict release mode;
- an optional explicit release tag, only when ``--tag`` is passed.

These tests build small fixture CHANGELOG files under ``tmp_path`` and
invoke the real script as a subprocess. They never modify the repository's
real ``pyproject.toml``, ``src/pysh/__init__.py``, or ``CHANGELOG.md``, and
never create a git tag. See
``docs/architecture/release-quality-gate-2-audit.md`` for the design this
implements.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_release_metadata.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"

CANONICAL_VERSION = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_changelog(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------- real-repo baseline


def test_check_release_metadata_passes_on_real_repository() -> None:
    """The gate must pass, unmodified, against this repository's real state."""
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "all release metadata checks passed" in result.stdout


def test_check_release_metadata_passes_in_release_mode_on_real_repository() -> None:
    """The real repository must pass release-mode validation for the
    finalized current release."""
    result = _run("--release-mode")
    assert result.returncode == 0, result.stderr


# --------------------------------------------------- 1/2/3. version equality


def test_pyproject_version_matches_runtime_init_version() -> None:
    init_text = (REPO_ROOT / "src" / "pysh" / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{CANONICAL_VERSION}"' in init_text


def test_cli_version_flag_matches_canonical_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``pysh --version`` (in-process) must print the pyproject.toml version.

    Traces directly back to pyproject.toml rather than to
    ``pysh.__version__``, so this fails even if ``__init__.py`` and
    ``pyproject.toml`` drift together in a way that keeps ``pysh.cli``
    internally consistent but wrong relative to the real release version.
    """
    from pysh.cli import main  # noqa: PLC0415

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert CANONICAL_VERSION in capsys.readouterr().out


def test_module_invocation_version_matches_canonical_version() -> None:
    """``python -m pysh --version`` (real subprocess) prints the canonical version."""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "pysh", "--version"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert CANONICAL_VERSION in result.stdout


# ------------------------------------------- 4. no duplicate literal remains


def test_docs_consistency_derives_current_version_from_pyproject() -> None:
    """test_docs_consistency.py must not maintain a second hardcoded literal.

    Checks the actual assignment statement, not prose: the history comment
    in that file legitimately mentions the old literal in backticks while
    explaining why it was removed.
    """
    text = (REPO_ROOT / "tests" / "test_docs_consistency.py").read_text(encoding="utf-8")
    assignment_lines = [
        line for line in text.splitlines() if line.startswith("CURRENT_VERSION")
    ]
    assert len(assignment_lines) == 1, assignment_lines
    assert assignment_lines[0] == (
        'CURRENT_VERSION = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))'
        '["project"]["version"]'
    )


# ---------------------------------------- 5-10. artifact naming (RQG-C reuse)


def test_artifact_naming_checks_are_owned_by_rqg_c_contract_gate() -> None:
    """Wheel/sdist/deb/rpm/pkg naming-vs-version checks live in RQG-C.

    This slice must not duplicate them; it only re-confirms the dedicated
    module exists and is collected, so a missing/renamed file would be
    caught here too.
    """
    rqg_c_tests = REPO_ROOT / "tests" / "test_release_artifact_contract.py"
    assert rqg_c_tests.is_file()
    text = rqg_c_tests.read_text(encoding="utf-8")
    for marker in (
        "test_complete_canonical_artifact_set_passes",
        "test_wrong_version_in_wheel_filename_fails",
        "test_wrong_version_in_deb_filename_fails",
    ):
        assert marker in text


# --------------------------------------------------------- 11. changelog


def test_changelog_allows_newer_unreleased_section_above_released_target(
    tmp_path: Path,
) -> None:
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n"
        "## 0.9.0 - Unreleased\n\n- wip\n\n"
        "## 0.8.2 - 2026-06-08\n\n- released\n",
    )
    result = _run("--changelog", str(changelog), "--target-version", "0.8.2")
    assert result.returncode == 0, result.stderr


def test_changelog_release_mode_rejects_unreleased_target(tmp_path: Path) -> None:
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n## 0.9.0 - Unreleased\n\n- wip\n\n## 0.8.2 - 2026-06-08\n\n- released\n",
    )
    result = _run(
        "--release-mode", "--changelog", str(changelog), "--target-version", "0.9.0"
    )
    assert result.returncode != 0
    assert "release mode requires" in result.stderr
    assert "no longer be marked Unreleased" in result.stderr


def test_changelog_default_mode_allows_unreleased_target(tmp_path: Path) -> None:
    """Ordinary (non-release-mode) validation must not require finalization."""
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n## 0.9.0 - Unreleased\n\n- wip\n\n## 0.8.2 - 2026-06-08\n\n- released\n",
    )
    result = _run("--changelog", str(changelog), "--target-version", "0.9.0")
    assert result.returncode == 0, result.stderr


def test_changelog_duplicate_heading_fails(tmp_path: Path) -> None:
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n"
        "## 0.8.2 - 2026-06-08\n\n- first\n\n"
        "## 0.8.2 - 2026-06-09\n\n- duplicate\n",
    )
    result = _run("--changelog", str(changelog))
    assert result.returncode != 0
    assert "duplicate version heading(s): 0.8.2" in result.stderr


def test_changelog_malformed_ordering_fails(tmp_path: Path) -> None:
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n"
        "## 0.8.0 - 2026-06-06\n\n- older listed first\n\n"
        "## 0.8.2 - 2026-06-08\n\n- newer listed second\n",
    )
    result = _run("--changelog", str(changelog))
    assert result.returncode != 0
    assert "strictly descending order" in result.stderr


def test_changelog_missing_target_heading_fails(tmp_path: Path) -> None:
    changelog = _write_changelog(
        tmp_path / "CHANGELOG.md",
        "# Changelog\n\n## 0.7.0 - 2026-06-05\n\n- unrelated\n",
    )
    result = _run("--changelog", str(changelog), "--target-version", "0.8.2")
    assert result.returncode != 0
    assert "missing a heading for version 0.8.2" in result.stderr


def test_changelog_file_missing_fails(tmp_path: Path) -> None:
    result = _run("--changelog", str(tmp_path / "does-not-exist.md"))
    assert result.returncode != 0
    assert "changelog not found" in result.stderr


# ---------------------------------------------------------------- 12. tag


def test_tag_matching_canonical_version_passes() -> None:
    result = _run("--tag", f"v{CANONICAL_VERSION}")
    assert result.returncode == 0, result.stderr


def test_tag_wrong_version_fails() -> None:
    result = _run("--tag", "v9.9.9")
    assert result.returncode != 0
    assert "does not match target version" in result.stderr


def test_tag_missing_v_prefix_fails() -> None:
    result = _run("--tag", CANONICAL_VERSION)
    assert result.returncode != 0
    assert "malformed tag" in result.stderr


def test_tag_malformed_suffix_fails() -> None:
    result = _run("--tag", "v0.8.2-rc1")
    assert result.returncode != 0
    assert "malformed tag" in result.stderr


def test_ordinary_invocation_requires_no_tag() -> None:
    """Ordinary CI must never fail merely because no tag was supplied."""
    result = _run()
    assert result.returncode == 0, result.stderr


def test_ci_workflow_never_passes_tag_or_release_mode() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check_release_metadata.sh" in text
    assert "--tag" not in text
    assert "--release-mode" not in text


def test_release_workflow_invokes_strict_tag_and_release_mode_check() -> None:
    """release-artifacts.yml must gate on tag/version consistency at release time."""
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "check_release_metadata.sh --release-mode" in text
    assert '--tag "${{ github.event.release.tag_name }}"' in text
    # The tag check must be conditioned on a real release event, since
    # workflow_dispatch (manual dry runs) has no tag context.
    assert "if: github.event_name == 'release'" in text


# -------------------------------------------------------------- 13/14/15


def test_license_metadata_is_gpl_2_0_only() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["license"] == "GPL-2.0-only"


def test_requires_python_is_3_13_or_newer() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.13"


def test_console_script_entrypoint_is_pysh_cli_main() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["pysh"] == "pysh.cli:main"


def test_wrong_license_in_fixture_pyproject_would_be_caught() -> None:
    """Sanity check on the checker's own license assertion, not just pyproject.toml.

    Runs the real script against a temp copy of the repo's pyproject.toml
    with the license field mutated, proving the check is load-bearing and
    not a tautology.
    """
    import shutil

    fixture_root = Path(subprocess.run(
        ["mktemp", "-d"], check=True, capture_output=True, text=True
    ).stdout.strip())
    try:
        shutil.copytree(REPO_ROOT / "src", fixture_root / "src")
        text = PYPROJECT.read_text(encoding="utf-8")
        mutated = text.replace('license = "GPL-2.0-only"', 'license = "MIT"')
        assert mutated != text
        (fixture_root / "pyproject.toml").write_text(mutated, encoding="utf-8")
        shutil.copy(REPO_ROOT / "CHANGELOG.md", fixture_root / "CHANGELOG.md")
        (fixture_root / "scripts").mkdir()
        shutil.copy(
            REPO_ROOT / "scripts" / "_pysh_version.sh",
            fixture_root / "scripts" / "_pysh_version.sh",
        )
        shutil.copy(SCRIPT, fixture_root / "scripts" / "check_release_metadata.sh")

        result = subprocess.run(
            ["bash", str(fixture_root / "scripts" / "check_release_metadata.sh")],
            cwd=fixture_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        assert "project.license must be 'GPL-2.0-only'" in result.stderr
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)


# --------------------------------------------------------- 16. RQG-C intact


def test_release_artifact_contract_tests_still_present() -> None:
    assert (REPO_ROOT / "tests" / "test_release_artifact_contract.py").is_file()
