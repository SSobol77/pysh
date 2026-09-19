# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_rpm_package_smoke_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RPM install-and-run smoke follow-up.

``scripts/smoke_rpm_package.sh`` installs a built ``.rpm`` through real
``dnf install ./<pkg>.rpm`` package management inside a disposable Fedora
container, then verifies the INSTALLED console entrypoint (``pysh
--version``, ``python3 -m pysh --version``, ``pysh -c``, and a real
PTY-driven interactive ``exit``/``quit``). It never treats
``rpm2cpio``/``cpio`` extraction as an installed package, and it never lets
``pip install pysh`` or a dnf repository substitute for the local artifact
under test.

Argument validation and the "Docker unavailable" diagnostic run on every
host, with no Docker dependency, because the script rejects those inputs
before ever touching Docker. The full install-and-run chain genuinely
needs Docker and takes real wall-clock time (a `dnf install python3` plus
the package install), so it is isolated into one comprehensive dynamic
test, skipped automatically when Docker is not usable on the current host
-- this suite never mocks that outcome, it only marks it skipped so the
rest of ``pytest -q`` remains fast and portable.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "smoke_rpm_package.sh"


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
    reason="Docker is required for the real RPM install-and-run smoke",
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


# ---------------------------------------------------- 1-4. argument validation


def test_missing_argument_is_rejected() -> None:
    result = _run()
    assert result.returncode != 0
    assert "expected exactly one argument" in result.stderr
    assert "usage:" in result.stderr


def test_missing_rpm_file_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "pysh-shell-0.9.0-1.noarch.rpm"
    result = _run(str(missing))
    assert result.returncode != 0
    assert f"artifact not found: {missing}" in result.stderr


def test_wrong_extension_is_rejected(tmp_path: Path) -> None:
    not_an_rpm = tmp_path / "pysh-shell-0.9.0-1.noarch.tar.gz"
    not_an_rpm.write_bytes(b"not an rpm\n")
    result = _run(str(not_an_rpm))
    assert result.returncode != 0
    assert "does not have a .rpm extension" in result.stderr


def test_zero_byte_rpm_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "pysh-shell-0.9.0-1.noarch.rpm"
    empty.touch()
    result = _run(str(empty))
    assert result.returncode != 0
    assert "empty (0 bytes)" in result.stderr


# --------------------------------------------- 5. docker-unavailable diagnostic


def test_docker_unavailable_gives_clear_diagnostic(tmp_path: Path) -> None:
    """A PATH without docker must fail closed with an explicit message.

    Deterministic regardless of whether Docker is actually installed on
    the host running this test: PATH is overridden to exclude whichever
    directory (if any) provides it, while keeping bash/coreutils/etc.
    available so the script itself can still run up to that check.
    """
    fixture_rpm = tmp_path / "pysh-shell-0.9.0-1.noarch.rpm"
    fixture_rpm.write_bytes(b"FIXTURE\n")

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
        ["bash", str(SCRIPT), str(fixture_rpm)],
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


# ------------------------------------------------ 6. canonical RPM accepted


def test_canonical_rpm_name_accepted_by_argument_validation(tmp_path: Path) -> None:
    """A correctly-named, non-empty .rpm must pass argument validation
    (i.e. fail later, at Docker/install, never at the naming/size checks).

    Docker is deliberately made unavailable (via a curated PATH, the same
    technique as test_docker_unavailable_gives_clear_diagnostic) so this
    stays fast and deterministic regardless of whether real Docker/Fedora
    pulls are already warm on the host running this test -- the real
    install-and-run path is exercised separately by
    test_real_rpm_install_and_run_smoke_passes.
    """
    canonical = tmp_path / "pysh-shell-0.9.0-1.noarch.rpm"
    canonical.write_bytes(b"FIXTURE RPM BYTES\n")

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
        ["bash", str(SCRIPT), str(canonical)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    # It must fail at the docker-unavailable check, never at the
    # filename/size checks that run before it.
    assert "does not have a .rpm extension" not in result.stderr
    assert "empty (0 bytes)" not in result.stderr
    assert "docker is required" in result.stderr


# -------------------------------------------------- 7. explicit Fedora image


def test_script_uses_explicit_fedora_image_not_latest() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'RPM_IMAGE="fedora:\d+"', text)
    assert "fedora:latest" not in text
    assert "centos:latest" not in text


# ------------------------------- 8-19. install/run/isolation contract (static)


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


def test_script_installs_via_real_dnf_not_extraction() -> None:
    body = _container_script_body(SCRIPT.read_text(encoding="utf-8"))
    assert "dnf -y install" in body
    assert "PYSH_RPM_PATH" in body
    # Must never substitute extraction for installation.
    assert "rpm2cpio" not in body
    assert re_search_absent(body, r"\bcpio\b")


def test_script_verifies_rpm_query_installed_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rpm -q --qf" in text
    assert "%{NAME}-%{VERSION}-%{RELEASE}" in text
    assert "pysh-shell" in text


def test_script_verifies_exact_installed_version() -> None:
    body = _container_script_body(SCRIPT.read_text(encoding="utf-8"))
    assert 'pysh-shell-${PYSH_EXPECTED_VERSION}-1' in body


def test_script_checks_command_v_pysh() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "command -v pysh" in text
    assert "/usr/bin/pysh" in text


def test_script_checks_module_path_excludes_repo_and_venv() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import pysh; print(pysh.__file__)" in text
    assert "/opt/pysh-shell/lib/pysh/__init__.py" in text
    # The check must not accept a repo checkout or virtualenv path.
    assert str(REPO_ROOT) not in text
    assert ".venv" not in text


def test_script_verifies_installed_version_output() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pysh --version" in text
    assert "python3 -m pysh --version" in text


def test_script_verifies_cli_echo_exit_quit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'pysh -c "echo rpm-smoke"' in text
    assert 'pysh -c "exit"' in text
    assert 'pysh -c "quit"' in text


def test_script_includes_non_tty_batch_checks() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "batch-mode exit status" in text
    assert "batch-mode quit status" in text
    assert "NOT a PTY test" in text


def test_script_includes_real_pty_driven_interactive_smoke() -> None:
    """The genuine PTY smoke is delegated to the shared, strictly-bounded
    scripts/pty_smoke.py helper (Issue #33), never a copied driver here."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "def run_pty_command" not in text
    assert "import pty" not in text
    assert "pty_smoke.py:/pysh-pty-smoke.py:ro" in text
    assert "python3 /pysh-pty-smoke.py 10 exit /usr/bin/pysh" in text
    assert "python3 /pysh-pty-smoke.py 10 quit /usr/bin/pysh" in text
    assert "PTY interactive smoke PASSED" in text


def test_script_never_calls_pip_install_pysh() -> None:
    """The tested PySH must come only from the local .rpm, never PyPI/dnf repos."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pip install" not in text
    assert re_search_absent(text, r"dnf\s+(-y\s+)?install\s+(-y\s+)?pysh-shell(?!\S)")


def test_script_does_not_weaken_python_requirement() -> None:
    """The base-image python3 must be checked against >= 3.13, never skipped."""
    body = _container_script_body(SCRIPT.read_text(encoding="utf-8"))
    assert "python3 --version" in body
    assert "3.13" in body


def test_container_run_does_not_mount_host_paths_beyond_artifact() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '-v "${RPM_ABS_PATH}' in text
    assert "/var/run/docker.sock" not in text
    assert "$HOME" not in text
    assert "--privileged" not in text

    docker_run_start = text.index("docker run")
    docker_run_end = text.index("<<'CONTAINER_EOF'")
    docker_run_invocation = text[docker_run_start:docker_run_end]
    assert "--publish" not in docker_run_invocation
    assert re_search_absent(docker_run_invocation, r"(?<!\S)-p(?!\S)")


# ------------------------------------------------------------- 20/21. CI wiring


def test_ci_workflow_invokes_rpm_smoke_unconditionally() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "smoke_rpm_package.sh" in text
    assert "continue-on-error" not in text


def test_ci_rpm_smoke_runs_after_rpm_build() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    build_idx = text.index("Build RPM .rpm")
    smoke_idx = text.index("smoke_rpm_package.sh")
    assert build_idx < smoke_idx


def test_release_artifacts_workflow_runs_rpm_smoke_before_artifact_gate() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "smoke_rpm_package.sh" in text
    assert "continue-on-error" not in text
    build_idx = text.index("Build RPM .rpm")
    smoke_idx = text.index("smoke_rpm_package.sh")
    gate_idx = text.index("Verify canonical artifact names")
    assert build_idx < smoke_idx < gate_idx


# ------------------------------------------------------- 22. release gate reuse


def test_release_quality_gate_reuses_the_same_smoke_script() -> None:
    text = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")
    assert "scripts/smoke_rpm_package.sh" in text
    # The existing static rpm -qip/-qlp content-listing check must remain.
    assert "rpm -qpl" in text or "rpm --dbpath" in text


def test_release_gate_registers_rpm_smoke_check() -> None:
    text = (REPO_ROOT / "scripts" / "release_gate.py").read_text(encoding="utf-8")
    assert "scripts/smoke_rpm_package.sh" in text
    assert '"RPM install smoke"' in text


# --------------------------------------------------- real dynamic end-to-end


@requires_docker
def test_real_rpm_install_and_run_smoke_passes(tmp_path: Path) -> None:
    """Build a fresh .rpm and run the complete real smoke against it.

    This is the one genuinely slow, Docker-dependent test in this module:
    it performs an actual dnf install inside a disposable Fedora
    container. Everything else in this file is fast and Docker-independent
    by design.
    """
    build_result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "build_rpm.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build_result.returncode == 0, build_result.stderr

    rpms = sorted((REPO_ROOT / "dist" / "os" / "rpm").glob("pysh-shell-*-1.noarch.rpm"))
    assert rpms, "build_rpm.sh did not produce a .rpm"
    rpm_path = rpms[-1]

    result = _run(str(rpm_path), timeout=600.0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL RPM INSTALL-AND-RUN SMOKE CHECKS PASSED" in result.stdout
    assert "/opt/pysh-shell/lib/pysh/__init__.py" in result.stdout
    assert "rpm-smoke" in result.stdout
    assert "PTY interactive smoke PASSED" in result.stdout
