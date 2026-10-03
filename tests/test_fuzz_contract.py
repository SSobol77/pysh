# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fuzz_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 4: repository contract for the fuzz/property evidence wiring.

Platform-lane wiring (Debian/FreeBSD jobs, FreeBSD portability) is pinned in
``test_platform_tier_contract.py``; this module owns the evidence script, the
scheduled workflow, dependency separation, and the documentation.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_fuzz_evidence.sh"
NIGHTLY = REPO_ROOT / ".github" / "workflows" / "fuzz-nightly.yml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOC = REPO_ROOT / "docs" / "development" / "fuzzing.md"
REGRESSIONS = REPO_ROOT / "tests" / "fuzz" / "regressions"
PYPROJECT = REPO_ROOT / "pyproject.toml"

REQUIRED_PORTABLE_TESTS = (
    "tests/test_parser_properties.py",
    "tests/test_fuzz_corpus.py",
    "tests/test_fuzz_driver.py",
    "tests/test_fuzz_regressions.py",
    "tests/test_fd_robustness.py",
    "tests/test_fuzz_contract.py",
)
REQUIRED_NIGHTLY_TARGETS = (
    "grammar.split_chain",
    "grammar.split_pipeline",
    "redirection.parse_redirections",
    "path_expansion.tokenize_and_glob_expand",
)


def _code_lines(text: str) -> str:
    """Drop comment lines so prose cannot satisfy or violate a code assertion."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_evidence_script_is_executable_posix_sh_and_owns_the_portable_list() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert os.access(SCRIPT, os.X_OK)
    assert "set -eu" in text
    missing = [name for name in REQUIRED_PORTABLE_TESTS if name not in text]
    assert not missing, f"portable fuzz evidence is missing: {missing!r}"
    assert "PYSH_PYTEST" in text
    for path in REQUIRED_PORTABLE_TESTS:
        assert (REPO_ROOT / path).is_file(), path


def test_portable_evidence_does_not_depend_on_atheris_or_linux_only_fd_paths() -> None:
    code = _code_lines(SCRIPT.read_text(encoding="utf-8"))
    assert "test_fuzz_atheris_smoke" not in code
    assert "atheris" not in code.lower()
    assert "--group fuzz" not in code
    assert "/proc" not in code
    assert "/dev/fd" not in code
    # No network, publishing, or privilege escalation in the evidence entry point.
    for forbidden in ("curl", "wget", "pip install", "sudo", "git push"):
        assert forbidden not in code


def test_normal_ci_runs_only_the_bounded_evidence_never_the_campaign() -> None:
    workflow = CI.read_text(encoding="utf-8")
    assert "scripts/check_fuzz_evidence.sh" in workflow
    assert "scripts/fuzz_atheris.py" not in workflow
    assert "--group fuzz" not in workflow
    assert "max-total-time" not in workflow


def test_nightly_workflow_is_scheduled_manual_read_only_and_publication_free() -> None:
    text = NIGHTLY.read_text(encoding="utf-8")
    code = _code_lines(text)
    triggers = re.search(r"(?ms)^on:\n(?P<body>.*?)(?=^\S)", code).group("body")

    assert re.search(r"(?m)^  schedule:", triggers)
    assert re.search(r"(?m)^  workflow_dispatch:", triggers)
    for forbidden in ("pull_request", "push:", "release:", "workflow_run", "tags:"):
        assert forbidden not in triggers

    assert re.search(r"(?ms)^permissions:\n  contents: read\n(?!  )", code)
    assert "contents: write" not in code
    assert "write-all" not in code
    assert "continue-on-error" not in code
    for forbidden in (
        "git push", "git commit", "gh release", "gh pr", "gh issue", "twine",
        "pypi", "publish", "secrets.", "GITHUB_TOKEN", "printenv", "env |",
    ):
        assert forbidden not in code, forbidden
    assert re.search(r"(?m)^\s+if: failure\(\)$", code)
    assert "retention-days:" in code
    assert "ubuntu-latest" in code
    assert "runs-on: freebsd" not in code.lower()

    missing = [t for t in REQUIRED_NIGHTLY_TARGETS if t not in code]
    assert not missing, f"nightly matrix is missing: {missing!r}"
    assert "--max-total-time" in code
    assert "--artifact-dir" in code
    assert "timeout-minutes:" in code


def test_nightly_targets_exist_in_the_registry() -> None:
    from tests.fuzz_support import driver

    known = {target.name for target in driver.fuzzable_targets()}
    listed = re.findall(r"(?m)^          - ([a-z_]+\.[a-z_]+)$", NIGHTLY.read_text(encoding="utf-8"))
    assert set(REQUIRED_NIGHTLY_TARGETS) <= set(listed)
    assert set(listed) <= known, sorted(set(listed) - known)
    assert len(listed) == len(set(listed))


def test_atheris_is_a_linux_x86_64_dev_dependency_not_a_runtime_dependency() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    runtime = " ".join(data["project"].get("dependencies", []))
    optional = " ".join(
        dep for group in data["project"].get("optional-dependencies", {}).values() for dep in group
    )
    assert "atheris" not in runtime.lower()
    assert "atheris" not in optional.lower()
    assert "hypothesis" not in runtime.lower()

    fuzz = data["dependency-groups"]["fuzz"]
    assert len(fuzz) == 1 and fuzz[0].startswith("atheris")
    assert "sys_platform == 'linux'" in fuzz[0]
    assert "platform_machine == 'x86_64'" in fuzz[0]
    dev = " ".join(data["dependency-groups"]["dev"])
    assert "atheris" not in dev.lower()


def test_fuzz_sources_do_not_leak_into_runtime_package() -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if re.search(r"(?m)^\s*(import|from)\s+(atheris|tests\.fuzz_support)\b", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_regression_directory_and_documentation_exist_and_state_the_platform_split() -> None:
    assert (REGRESSIONS / "README.md").is_file()
    assert DOC.is_file()
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    for phrase in (
        "Issue #48",
        "Linux x86_64 only",
        "scripts/check_fuzz_evidence.sh",
        "fuzz-nightly.yml",
        "--replay",
        "makes **no coverage-guided claim**",
        "pending the first native PR CI run",
        "Automation never converts a crash artifact into committed source",
    ):
        assert phrase in text, phrase
    index = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "development/fuzzing.md" in index
