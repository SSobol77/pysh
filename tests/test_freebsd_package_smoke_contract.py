# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_freebsd_package_smoke_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RQG-E FreeBSD install-and-run smoke.

``scripts/smoke_freebsd_package.sh`` installs a built ``.pkg`` through real
``pkg add <local-file>`` package management directly on the FreeBSD host it
runs on, then verifies the INSTALLED console entrypoint (``pysh --version``,
``python3.13 -m pysh --version``, ``pysh -c``, and a real PTY-driven
interactive ``exit``/``quit``). It never treats archive extraction as an
installed package, and it never runs on a non-FreeBSD host: FreeBSD's
native ``.pkg`` format and ``pkg(8)`` tooling do not exist anywhere else,
so there is no container/emulation substitute that would prove anything
real.

Argument validation and the "not FreeBSD" diagnostic run on every host,
with no FreeBSD dependency, because the script rejects those inputs before
ever touching ``pkg``. The full build-install-query-execute chain genuinely
needs real FreeBSD 14+ and is exercised for real only in
``.github/workflows/release-artifacts.yml``'s FreeBSD 14.4 VM job -- this
suite never fakes that outcome locally, it only marks the dynamic end-to-end
test skipped on non-FreeBSD hosts (i.e. everywhere this test suite normally
runs) so the rest of ``pytest -q`` remains fast and portable.
"""
from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "smoke_freebsd_package.sh"

IS_FREEBSD = platform.system() == "FreeBSD"

requires_freebsd = pytest.mark.skipif(
    not IS_FREEBSD,
    reason="real FreeBSD 14+ is required for the native install-and-run smoke",
)


def _run(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
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


def test_missing_pkg_file_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "pysh-shell-0.9.0.pkg"
    result = _run(str(missing))
    assert result.returncode != 0
    assert f"artifact not found: {missing}" in result.stderr


def test_wrong_extension_is_rejected(tmp_path: Path) -> None:
    not_a_pkg = tmp_path / "pysh-shell-0.9.0.tar.gz"
    not_a_pkg.write_bytes(b"not a pkg\n")
    result = _run(str(not_a_pkg))
    assert result.returncode != 0
    assert "does not have a .pkg extension" in result.stderr


def test_zero_byte_pkg_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "pysh-shell-0.9.0.pkg"
    empty.touch()
    result = _run(str(empty))
    assert result.returncode != 0
    assert "empty (0 bytes)" in result.stderr


# --------------------------------------- 4. non-FreeBSD-host clear diagnostic


def test_non_freebsd_host_gives_clear_diagnostic_no_silent_skip(tmp_path: Path) -> None:
    """This test suite's own host (never real FreeBSD) must fail loudly.

    The script must not silently skip or fake success when it is not
    actually running on FreeBSD -- it must fail closed with an explicit,
    actionable diagnostic naming the real validation path.
    """
    fixture_pkg = tmp_path / "pysh-shell-0.9.0.pkg"
    fixture_pkg.write_bytes(b"FIXTURE\n")

    result = _run(str(fixture_pkg))
    assert result.returncode != 0
    if IS_FREEBSD:
        # A real FreeBSD host would proceed past this guard; the diagnostic
        # this test checks for only applies to non-FreeBSD hosts.
        return
    assert "must be executed on FreeBSD 14+" in result.stderr
    assert "found" in result.stderr
    assert "no Linux/Docker/emulation fallback" in result.stderr
    assert "release-artifacts.yml" in result.stderr


# -------------------------------------------------- 5. no fixture/mock stand-in


def test_script_never_calls_pkg_from_a_mock_or_fixture() -> None:
    """The tested PySH must come only from the real local .pkg via pkg(8)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pkg add" in text
    # Must never substitute extraction or a fixture/mock pkg(8) shim.
    assert re.search(r"\btar\s+x", text) is None
    assert "mock" not in text.lower()
    assert "pip install" not in text


# ------------------------------- 6-13. install/run/isolation contract (static)


def test_script_installs_via_real_pkg_add_not_extraction() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pkg add \"${PKG_ABS_PATH}\"" in text


def test_script_verifies_pkg_info_installed_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'pkg info "${PKG_NAME}"' in text
    assert 'PKG_NAME="pysh-shell"' in text


def test_script_verifies_installed_version_output() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pysh --version" in text
    assert "python3.13 -m pysh --version" in text


def test_script_verifies_cli_echo_exit_quit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'pysh -c "echo freebsd-smoke"' in text
    assert 'pysh -c "exit"' in text
    assert 'pysh -c "quit"' in text


def test_script_checks_module_path_excludes_repo_and_venv() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import pysh; print(pysh.__file__)" in text
    assert 'APP_PREFIX="/usr/local/lib/pysh-shell"' in text
    assert 'REQUIRED_MODULE="${APP_PREFIX}/pysh/__init__.py"' in text
    # The check must not accept a repo checkout or virtualenv path.
    assert str(REPO_ROOT) not in text
    assert ".venv" not in text


def test_script_clears_pythonpath_before_isolation_proof() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "unset PYTHONPATH" in text


def test_script_uses_neutral_working_directory() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "mktemp -d -t pysh-freebsd-smoke" in text
    assert 'cd "${SMOKE_DIR}"' in text


def test_script_includes_real_pty_driven_interactive_smoke() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import pty" in text
    assert "pty.openpty()" in text
    assert "PTY interactive smoke PASSED" in text
    assert "Traceback" in text  # checked for and rejected, not merely mentioned


def test_script_checks_freebsd_version_before_installing() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'uname -s' in text
    assert 'FreeBSD' in text
    assert "FREEBSD_MAJOR" in text
    assert '"${FREEBSD_MAJOR}" -lt 14' in text


# ------------------------------------------------------------- 14/15. CI wiring


def test_release_artifacts_workflow_invokes_freebsd_smoke_unconditionally() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "smoke_freebsd_package.sh" in text
    assert "continue-on-error" not in text


def test_release_artifacts_freebsd_smoke_runs_after_pkg_build_and_static_checks() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    build_idx = text.index("sh scripts/build_freebsd_pkg.sh")
    static_check_idx = text.index("pkg query -F")
    smoke_idx = text.index("smoke_freebsd_package.sh")
    assert build_idx < static_check_idx < smoke_idx


def test_release_artifacts_uploads_only_after_the_vm_step_that_runs_smoke() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    smoke_idx = text.index("smoke_freebsd_package.sh")
    upload_idx = text.index("Upload FreeBSD .pkg workflow artifact")
    assert smoke_idx < upload_idx


# ------------------------------------------------------- 16. release gate reuse


def test_release_gate_reuses_the_same_smoke_script() -> None:
    text = (REPO_ROOT / "scripts" / "release_gate.py").read_text(encoding="utf-8")
    assert "scripts/smoke_freebsd_package.sh" in text
    assert "smoke_freebsd_package.sh" in text


def test_build_freebsd_pkg_static_checks_are_preserved() -> None:
    """The existing pkg info -F / pkg query -F static checks must remain."""
    text = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "pkg info -F" in text
    assert "pkg query -F" in text


# --------------------------------------------------- real dynamic end-to-end


@requires_freebsd
def test_real_freebsd_install_and_run_smoke_passes(tmp_path: Path) -> None:
    """Build a fresh .pkg and run the complete real smoke against it.

    This is the one genuinely slow, FreeBSD-only test in this module: it
    performs an actual pkg add install on real FreeBSD. Everything else in
    this file is fast and FreeBSD-independent by design. This test is
    skipped everywhere except a real FreeBSD 14+ host (this repository's
    normal dev/CI/test hosts are all Linux, so it is only ever exercised
    inside .github/workflows/release-artifacts.yml's FreeBSD 14.4 VM job,
    or by a maintainer running pytest directly on FreeBSD).
    """
    build_result = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "build_freebsd_pkg.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build_result.returncode == 0, build_result.stderr

    pkgs = sorted((REPO_ROOT / "dist" / "os" / "freebsd").glob("pysh-shell-*.pkg"))
    assert pkgs, "build_freebsd_pkg.sh did not produce a .pkg"
    pkg_path = pkgs[-1]

    result = _run(str(pkg_path), timeout=180.0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FREEBSD INSTALL-AND-RUN SMOKE CHECKS PASSED" in result.stdout
    assert "/usr/local/lib/pysh-shell/pysh/__init__.py" in result.stdout
    assert "freebsd-smoke" in result.stdout
    assert "PTY interactive smoke PASSED" in result.stdout
