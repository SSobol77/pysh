# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_installation_docs_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Regression tests for the Issue #33 RQG-F installation-doc contract gate.

``scripts/check_installation_docs.py`` parses only explicitly marked
(``<!-- pysh-install:NAME --> ... <!-- /pysh-install:NAME -->``) snippets in
README.md and docs/user/installation.md -- never an arbitrary Markdown code
block -- validates them structurally against pyproject.toml's canonical
package identity, cross-checks README against the installation guide, and
(unless ``--skip-portable``) builds a real local wheel/sdist and installs
each into a disposable temporary virtualenv to prove the documented PyPI
install path actually works, with no PyPI/network access.

Fixture-based tests in this file never modify the real README.md or
docs/user/installation.md; they pass ``--readme``/``--installation-doc``
overrides pointing at temporary files. The one real dynamic end-to-end test
(wheel/sdist install-and-run) builds real artifacts under this repository's
own dist/ (the same disposable build area RQG-B/C/D already use) and cleans
up its own temporary virtualenvs.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_installation_docs.py"
README = REPO_ROOT / "README.md"
INSTALLATION_DOC = REPO_ROOT / "docs" / "user" / "installation.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

_PROJECT = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
CANONICAL_NAME = _PROJECT["name"]
CANONICAL_VERSION = _PROJECT["version"]


def _load_module():
    spec = importlib.util.spec_from_file_location("check_installation_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHECK = _load_module()


def _run(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# --------------------------------------------------- minimal valid fixture

_VALID_README = f"""\
## Installation

### From PyPI

<!-- pysh-install:pypi -->
```bash
pip install {CANONICAL_NAME}
```
<!-- /pysh-install:pypi -->

### Development install

<!-- pysh-install:dev -->
```bash
uv sync
scripts/check_release_quality.sh
python -m pip install -e ".[dev]"
```
<!-- /pysh-install:dev -->
"""

_VALID_INSTALLATION_DOC = f"""\
<!-- pysh-install:version -->Current release: **PySH {CANONICAL_VERSION}**.<!-- /pysh-install:version -->

## Requirements

Python **3.13 or newer**.

<!-- pysh-install:pypi -->
```bash
python3.13 -m pip install --upgrade pip
python3.13 -m pip install {CANONICAL_NAME}
```
<!-- /pysh-install:pypi -->

<!-- pysh-install:pypi-verify -->
```bash
pysh --version
python -m pysh --version
```
<!-- /pysh-install:pypi-verify -->

<!-- pysh-install:deb-name -->
```
{CANONICAL_NAME}_X.Y.Z-1_all.deb
```
<!-- /pysh-install:deb-name -->

<!-- pysh-install:deb -->
```bash
sudo apt install ./{CANONICAL_NAME}_X.Y.Z-1_all.deb
pysh --version
```
<!-- /pysh-install:deb -->

<!-- pysh-install:rpm-name -->
```
{CANONICAL_NAME}-X.Y.Z-1.noarch.rpm
```
<!-- /pysh-install:rpm-name -->

<!-- pysh-install:rpm -->
```bash
sudo dnf install ./{CANONICAL_NAME}-X.Y.Z-1.noarch.rpm
pysh --version
```
<!-- /pysh-install:rpm -->

<!-- pysh-install:freebsd-name -->
```
{CANONICAL_NAME}-X.Y.Z.pkg
```
<!-- /pysh-install:freebsd-name -->

<!-- pysh-install:freebsd -->
```sh
sudo pkg install ./{CANONICAL_NAME}-X.Y.Z.pkg
pysh --version
```
<!-- /pysh-install:freebsd -->

<!-- pysh-install:freebsd-build -->
```sh
bash scripts/build_freebsd_pkg.sh
```
<!-- /pysh-install:freebsd-build -->

<!-- pysh-install:dev -->
```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```
<!-- /pysh-install:dev -->
"""


def _write_pair(tmp_path: Path, readme: str, installation_doc: str) -> tuple[Path, Path]:
    readme_path = tmp_path / "README.md"
    install_path = tmp_path / "installation.md"
    readme_path.write_text(readme, encoding="utf-8")
    install_path.write_text(installation_doc, encoding="utf-8")
    return readme_path, install_path


# --------------------------------------------------------- 1/2. real docs PASS


def test_real_readme_and_installation_doc_pass() -> None:
    result = _run("--skip-portable")
    assert result.returncode == 0, result.stderr
    assert "all installation documentation checks passed" in result.stdout


# ------------------------------------------------- 3. wrong PyPI package name


def test_wrong_pypi_package_name_fails(tmp_path: Path) -> None:
    bad_readme = _VALID_README.replace(f"pip install {CANONICAL_NAME}", "pip install some-other-package")
    readme_path, install_path = _write_pair(tmp_path, bad_readme, _VALID_INSTALLATION_DOC)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "some-other-package" in result.stderr
    assert f"expected {CANONICAL_NAME!r}" in result.stderr


# --------------------------------------------------- 4. stale explicit version


def test_stale_explicit_version_fails(tmp_path: Path) -> None:
    stale = _VALID_INSTALLATION_DOC.replace(CANONICAL_VERSION, "0.0.1", 1)
    readme_path, install_path = _write_pair(tmp_path, _VALID_README, stale)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "stale documented version" in result.stderr


# ------------------------------------------------- 5. wrong wheel filename


def test_wrong_wheel_filename_fixture_fails(tmp_path: Path) -> None:
    (tmp_path / f"{CANONICAL_NAME.replace('-', '_')}-9.9.9-py3-none-any.whl").write_bytes(b"x")
    (tmp_path / f"{CANONICAL_NAME}-{CANONICAL_VERSION}.tar.gz").write_bytes(b"x")
    errors = CHECK.check_artifact_names(tmp_path, CANONICAL_VERSION)
    assert any("wheel filename must be" in e for e in errors)


def test_correct_artifact_names_fixture_passes(tmp_path: Path) -> None:
    wheel_name = f"{CANONICAL_NAME.replace('-', '_')}-{CANONICAL_VERSION}-py3-none-any.whl"
    sdist_name = f"{CANONICAL_NAME}-{CANONICAL_VERSION}.tar.gz"
    (tmp_path / wheel_name).write_bytes(b"x")
    (tmp_path / sdist_name).write_bytes(b"x")
    assert CHECK.check_artifact_names(tmp_path, CANONICAL_VERSION) == []


# --------------------------------------------- 6/7/8. wrong OS package basename


@pytest.mark.parametrize(
    ("marker_name", "wrong_value"),
    [
        ("deb-name", "wrong-name_X.Y.Z-1_all.deb"),
        ("rpm-name", "wrong-name-X.Y.Z-1.noarch.rpm"),
        ("freebsd-name", "wrong-name-X.Y.Z.pkg"),
    ],
)
def test_wrong_os_package_basename_fails(tmp_path: Path, marker_name: str, wrong_value: str) -> None:
    marker = f"<!-- pysh-install:{marker_name} -->"
    close_marker = f"<!-- /pysh-install:{marker_name} -->"
    start = _VALID_INSTALLATION_DOC.index(marker)
    end = _VALID_INSTALLATION_DOC.index(close_marker) + len(close_marker)
    original_block = _VALID_INSTALLATION_DOC[start:end]
    mutated_block = f"{marker}\n```\n{wrong_value}\n```\n{close_marker}"
    mutated_doc = _VALID_INSTALLATION_DOC.replace(original_block, mutated_block)

    readme_path, install_path = _write_pair(tmp_path, _VALID_README, mutated_doc)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "does not match the canonical naming pattern" in result.stderr


# --------------------------------------------- 9. nonexistent referenced script


def test_nonexistent_referenced_script_fails(tmp_path: Path) -> None:
    mutated_doc = _VALID_INSTALLATION_DOC.replace(
        "bash scripts/build_freebsd_pkg.sh", "bash scripts/does-not-exist.sh"
    )
    readme_path, install_path = _write_pair(tmp_path, _VALID_README, mutated_doc)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "references nonexistent script: scripts/does-not-exist.sh" in result.stderr


# ------------------------------------------- 10. malformed designated command


def test_malformed_shell_command_fails(tmp_path: Path) -> None:
    bad_readme = _VALID_README.replace(
        f"pip install {CANONICAL_NAME}", f'pip install "{CANONICAL_NAME}'
    )
    readme_path, install_path = _write_pair(tmp_path, bad_readme, _VALID_INSTALLATION_DOC)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "malformed shell command" in result.stderr


# --------------------------------------- 11. README/guide canonical mismatch


def test_readme_installation_doc_pypi_mismatch_fails(tmp_path: Path) -> None:
    mutated_doc = _VALID_INSTALLATION_DOC.replace(
        f"pip install {CANONICAL_NAME}", f"pip install {CANONICAL_NAME}-cli"
    )
    readme_path, install_path = _write_pair(tmp_path, _VALID_README, mutated_doc)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "disagree on the PyPI package name" in result.stderr


def test_readme_installation_doc_dev_mismatch_fails(tmp_path: Path) -> None:
    mutated_doc = _VALID_INSTALLATION_DOC.replace(
        'python -m pip install -e ".[dev]"', 'python -m pip install -e ".[develop]"'
    )
    readme_path, install_path = _write_pair(tmp_path, _VALID_README, mutated_doc)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "disagree on the canonical editable development-install command" in result.stderr


# ------------------------------------------------- 12. Python requirement


def test_python_requirement_mismatch_fails(tmp_path: Path) -> None:
    mutated_doc = _VALID_INSTALLATION_DOC.replace(
        "Python **3.13 or newer**", "Python **3.12 or newer**"
    )
    readme_path, install_path = _write_pair(tmp_path, _VALID_README, mutated_doc)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "states Python 3.12" in result.stderr


# ---------------------------------------------- 13. unsupported legacy syntax


def test_legacy_setup_py_install_syntax_fails(tmp_path: Path) -> None:
    bad_readme = _VALID_README.replace(
        f"pip install {CANONICAL_NAME}", "python setup.py install"
    )
    readme_path, install_path = _write_pair(tmp_path, bad_readme, _VALID_INSTALLATION_DOC)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "unsupported legacy install syntax" in result.stderr


# --------------------------------------------------- marker hygiene (bonus)


def test_duplicate_marker_name_is_rejected(tmp_path: Path) -> None:
    doubled = _VALID_README + _VALID_README  # duplicates every marker name
    readme_path, install_path = _write_pair(tmp_path, doubled, _VALID_INSTALLATION_DOC)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "duplicate pysh-install marker name" in result.stderr


def test_unmatched_marker_is_rejected(tmp_path: Path) -> None:
    broken = _VALID_README.replace("<!-- /pysh-install:pypi -->", "")
    readme_path, install_path = _write_pair(tmp_path, broken, _VALID_INSTALLATION_DOC)
    result = _run(
        "--skip-portable", "--readme", str(readme_path), "--installation-doc", str(install_path)
    )
    assert result.returncode != 0
    assert "unmatched pysh-install markers" in result.stderr


# ------------------------------------------------ 14/15/16. real portable smoke


def test_real_wheel_and_sdist_install_and_run_smoke() -> None:
    """Build real artifacts and install-and-run both in isolated venvs.

    This is the one genuinely slow test in this module (a real `python -m
    build` plus two isolated pip installs); everything else here is fast
    and needs neither a build nor network access.
    """
    result = _run(timeout=180.0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all installation documentation checks passed" in result.stdout


def test_install_and_smoke_reports_no_errors_for_a_real_wheel(tmp_path: Path) -> None:
    """Direct, evidence-based check of install_and_smoke() against a real wheel."""
    build = subprocess.run(
        ["uv", "run", "--with", "build", "python", "-m", "build", "--wheel"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    wheel = next((REPO_ROOT / "dist").glob("*.whl"))
    errors = CHECK.install_and_smoke(wheel, CANONICAL_VERSION, tmp_path / "venv")
    assert errors == []


# ------------------------------------------- 17. no repo-source contamination


def test_contamination_predicate_flags_repo_paths() -> None:
    assert CHECK.is_repository_source_path(REPO_ROOT / "src" / "pysh" / "__init__.py") is True
    assert CHECK.is_repository_source_path(REPO_ROOT) is True


def test_contamination_predicate_allows_venv_paths(tmp_path: Path) -> None:
    fake_site_packages = tmp_path / "venv" / "lib" / "python3.13" / "site-packages" / "pysh"
    assert CHECK.is_repository_source_path(fake_site_packages / "__init__.py") is False


def test_pythonpath_contamination_is_actually_detectable() -> None:
    """Prove the scenario the predicate guards against is real, not theoretical.

    Forcing PYTHONPATH at the repository src/ makes a bare interpreter
    resolve pysh from the checkout -- exactly what is_repository_source_path
    must flag when it happens inside an installed artifact's venv.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import pysh; print(pysh.__file__)"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    resolved = Path(result.stdout.strip()).resolve()
    assert CHECK.is_repository_source_path(resolved) is True


# ----------------------------------------------------- 18. RQG-B/C/D coexist


def test_rqg_bcd_test_modules_still_present() -> None:
    for name in (
        "test_release_metadata_contract.py",
        "test_release_artifact_contract.py",
        "test_debian_package_smoke_contract.py",
    ):
        assert (REPO_ROOT / "tests" / name).is_file()


def test_does_not_duplicate_debian_smoke_execution() -> None:
    """RQG-F must validate Debian command structure only, never execute apt/dpkg."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "apt-get install" not in text
    assert "apt install ./" not in text
    assert "subprocess" in text  # sanity: file still uses subprocess elsewhere
    assert "docker" not in text.lower()


# --------------------------------------------------------- CI wiring rationale


def test_pytest_runs_unconditionally_in_ci_covering_this_gate() -> None:
    """No separate CI step is added: `pytest -q` already runs unconditionally.

    ci.yml's "Run pytest" step has no conditional and no continue-on-error,
    and this test module is collected by an ordinary `pytest -q`, so the
    installation-doc contract already runs on every PR and push without a
    redundant second shell step.
    """
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    run_pytest_idx = text.index("- name: Run pytest")
    following = text[run_pytest_idx : run_pytest_idx + 200]
    assert "continue-on-error" not in following
