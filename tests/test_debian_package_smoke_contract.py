# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_debian_package_smoke_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RQG-D Debian install-and-run smoke.

``scripts/smoke_debian_package.sh`` installs a built ``.deb`` through real
``apt-get install ./<pkg>.deb`` package management inside a disposable
``debian:13-slim`` container, then verifies the INSTALLED console
entrypoint (``pysh --version``, ``python3 -m pysh --version``, ``pysh -c``,
and a real PTY-driven interactive ``exit``/``quit``). It never treats
``dpkg-deb --extract``/``ar``/``tar`` output as an installed package, and it
never lets ``pip install pysh`` or an apt repository substitute for the
local artifact under test.

Argument validation and the "Docker unavailable" diagnostic run on every
host, with no Docker dependency, because the script rejects those inputs
before ever touching Docker. The full install-and-run chain genuinely
needs Docker and takes real wall-clock time (an ``apt-get update`` plus
install), so it is isolated into one comprehensive dynamic test, skipped
automatically when Docker is not usable on the current host -- this suite
never mocks that outcome, it only marks it skipped so the rest of
``pytest -q`` remains fast and portable.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "smoke_debian_package.sh"


def _docker_usable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


DOCKER_USABLE = _docker_usable()

requires_docker = pytest.mark.skipif(
    not DOCKER_USABLE,
    reason="Docker is required for the real Debian install-and-run smoke",
)


def _run(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------- 1-3. argument validation


def test_missing_argument_is_rejected() -> None:
    result = _run()
    assert result.returncode != 0
    assert "expected exactly one argument" in result.stderr
    assert "usage:" in result.stderr


def test_missing_deb_file_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "pysh-shell_0.8.2-1_all.deb"
    result = _run(str(missing))
    assert result.returncode != 0
    assert f"artifact not found: {missing}" in result.stderr


def test_wrong_extension_is_rejected(tmp_path: Path) -> None:
    not_a_deb = tmp_path / "pysh-shell_0.8.2-1_all.tar.gz"
    not_a_deb.write_bytes(b"not a deb\n")
    result = _run(str(not_a_deb))
    assert result.returncode != 0
    assert "does not have a .deb extension" in result.stderr


def test_zero_byte_deb_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "pysh-shell_0.8.2-1_all.deb"
    empty.touch()
    result = _run(str(empty))
    assert result.returncode != 0
    assert "empty (0 bytes)" in result.stderr


# --------------------------------------------- 4. docker-unavailable diagnostic


def test_docker_unavailable_gives_clear_diagnostic(tmp_path: Path) -> None:
    """A PATH without docker must fail closed with an explicit message.

    Deterministic regardless of whether Docker is actually installed on
    the host running this test: PATH is overridden to exclude whichever
    directory (if any) provides it, while keeping bash/coreutils/etc.
    available so the script itself can still run up to that check.
    """
    fixture_deb = tmp_path / "pysh-shell_0.8.2-1_all.deb"
    fixture_deb.write_bytes(b"FIXTURE\n")

    # Build a curated PATH directory: a symlink for every executable
    # currently reachable via PATH, except "docker". This keeps bash,
    # coreutils (dirname/basename/cat/...), etc. available so the script
    # runs its own argument-validation logic normally and only fails at
    # the docker-specific check -- unlike wiping PATH's directories
    # wholesale, which would remove bash itself if it happened to share a
    # directory with docker (e.g. /usr/bin on this host).
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    real_path = os.environ.get("PATH", "")
    for directory in real_path.split(os.pathsep):
        dir_path = Path(directory)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            if entry.name == "docker":
                continue
            link = fake_bin / entry.name
            if not link.exists():
                try:
                    link.symlink_to(entry)
                except OSError:
                    continue
    env = dict(os.environ)
    env["PATH"] = str(fake_bin)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(fixture_deb)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    assert result.returncode != 0
    assert "docker is required" in result.stderr
    assert "not found in PATH" in result.stderr
    assert "does not fall back to installing the package on the host" in result.stderr


# -------------------------------------------------- 5. explicit Debian 13 image


def test_script_uses_explicit_debian_13_image_not_latest() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'DEBIAN_IMAGE="debian:13-slim"' in text
    assert "debian:latest" not in text
    # An image reference, not incidental prose mentioning the word.
    assert "ubuntu:" not in text.lower()
    assert "FROM ubuntu" not in text


# ------------------------------- 6-13. install/run/isolation contract (static)


def _container_script_body(text: str) -> str:
    """Return only the in-container heredoc body, excluding host-side prose.

    The file's top-of-file comment legitimately *names* forbidden patterns
    (extraction commands, pip install, etc.) while explaining why the
    script avoids them; scoping checks to the actual executed heredoc body
    avoids false positives against that explanatory prose.
    """
    start = text.index("bash -s <<'CONTAINER_EOF'") + len("bash -s <<'CONTAINER_EOF'")
    end = text.rindex("CONTAINER_EOF")
    return text[start:end]


def re_search_absent(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is None


def test_script_installs_via_real_apt_get_not_extraction() -> None:
    body = _container_script_body(SCRIPT.read_text(encoding="utf-8"))
    assert "apt-get install" in body
    assert "PYSH_DEB_PATH" in body
    # Must never substitute extraction for installation.
    assert "dpkg-deb --extract" not in body
    assert re_search_absent(body, r"\bar\s+x\b")
    assert re_search_absent(body, r"\btar\s+xf\b")


def test_script_verifies_dpkg_installed_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "dpkg-query -W pysh-shell" in text


def test_script_verifies_installed_version_output() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pysh --version" in text
    assert "python3 -m pysh --version" in text


def test_script_verifies_cli_echo_exit_quit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'pysh -c "echo deb-smoke"' in text
    assert 'pysh -c "exit"' in text
    assert 'pysh -c "quit"' in text


def test_script_checks_module_path_excludes_repo_and_venv() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import pysh; print(pysh.__file__)" in text
    assert "/opt/pysh-shell/lib/pysh/__init__.py" in text
    # The check must not accept a repo checkout or virtualenv path.
    assert str(REPO_ROOT) not in text
    assert ".venv" not in text


def test_script_never_calls_pip_install_pysh() -> None:
    """The tested PySH must come only from the local .deb, never PyPI/apt repos."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pip install" not in text
    assert re_search_absent(text, r"apt-get install\s+(-y\s+)?pysh-shell(?!\S)")


def test_container_run_does_not_mount_host_paths_beyond_artifact() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "-v \"${DEB_ABS_PATH}" in text
    assert "/var/run/docker.sock" not in text
    assert "$HOME" not in text
    assert "--privileged" not in text

    docker_run_start = text.index("docker run")
    docker_run_end = text.index("<<'CONTAINER_EOF'")
    docker_run_invocation = text[docker_run_start:docker_run_end]
    assert "--publish" not in docker_run_invocation
    assert re_search_absent(docker_run_invocation, r"(?<!\S)-p(?!\S)")


# ------------------------------------------------------------- 14/15. CI wiring


def test_ci_workflow_invokes_debian_smoke_unconditionally() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "smoke_debian_package.sh" in text
    assert "continue-on-error" not in text


def test_ci_debian_smoke_runs_after_deb_build() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    build_idx = text.index("Build Debian .deb")
    smoke_idx = text.index("smoke_debian_package.sh")
    assert build_idx < smoke_idx


# ------------------------------------------------------- 16. release gate reuse


def test_release_quality_gate_reuses_the_same_smoke_script() -> None:
    text = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")
    assert "scripts/smoke_debian_package.sh" in text
    # The existing static content-listing check must remain.
    assert "dpkg-deb --contents" in text


def test_release_quality_gate_requires_docker() -> None:
    text = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")
    assert "require_command docker" in text


# --------------------------------------------------- real dynamic end-to-end


@requires_docker
def test_real_debian_install_and_run_smoke_passes(tmp_path: Path) -> None:
    """Build a fresh .deb and run the complete real smoke against it.

    This is the one genuinely slow, Docker-dependent test in this module:
    it performs an actual apt-get update + install inside a disposable
    debian:13-slim container. Everything else in this file is fast and
    Docker-independent by design.
    """
    build_result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "build_deb.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build_result.returncode == 0, build_result.stderr

    debs = sorted((REPO_ROOT / "dist" / "os" / "deb").glob("pysh-shell_*-1_all.deb"))
    assert debs, "build_deb.sh did not produce a .deb"
    deb_path = debs[-1]

    result = _run(str(deb_path), timeout=600.0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL DEBIAN INSTALL-AND-RUN SMOKE CHECKS PASSED" in result.stdout
    assert "/opt/pysh-shell/lib/pysh/__init__.py" in result.stdout
    assert "deb-smoke" in result.stdout
    assert "PTY interactive smoke PASSED" in result.stdout
