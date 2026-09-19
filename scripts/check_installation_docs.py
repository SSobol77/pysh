#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_installation_docs.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Installation-command contract gate for Issue #33 (RQG-F).

Validates that README.md's and docs/user/installation.md's *designated*
installation snippets -- marked with ``<!-- pysh-install:NAME -->`` /
``<!-- /pysh-install:NAME -->`` comment pairs -- are structurally correct,
agree with each other, and agree with the canonical package identity in
``pyproject.toml``. This is deliberately NOT a general Markdown shell
executor: only marked snippets are parsed, and only a narrow, portable
subset of them (PyPI wheel/sdist install) is ever actually executed, into
disposable temporary virtualenvs. Platform-native install commands
(``apt``/``dnf``/``pkg``) are validated structurally only; their real
execution is scripts/smoke_debian_package.sh's job (RQG-D) and future
native RPM/FreeBSD companions, never duplicated here.

No network access is required or performed: the "PyPI install" contract
validates package-name *structure* against pyproject.toml, and the
portable execution smoke installs a wheel/sdist built locally by the
existing scripts/build_pysh_package.sh, never a real PyPI download.
"""
from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_MARKER_OPEN_RE = re.compile(r"<!--\s*pysh-install:([a-z0-9-]+)\s*-->")
_MARKER_CLOSE_RE = re.compile(r"<!--\s*/pysh-install:([a-z0-9-]+)\s*-->")
_MARKER_PAIR_RE = re.compile(
    r"<!--\s*pysh-install:([a-z0-9-]+)\s*-->(.*?)<!--\s*/pysh-install:\1\s*-->",
    re.DOTALL,
)
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)

_PIP_INSTALL_RE = re.compile(
    r"pip\s+install(?:\s+--upgrade)?\s+(?:-e\s+)?([^\s\"']+)"
)
_VERSION_STATEMENT_RE = re.compile(r"PySH\s+(\d+\.\d+\.\d+)")
_SCRIPT_PATH_RE = re.compile(r"\bscripts/[A-Za-z0-9_.\-]+\.sh\b")
_LOCAL_PKG_ARG_RE = re.compile(r"\./([A-Za-z0-9_.\-]+\.(?:deb|rpm|pkg))")

_LEGACY_SYNTAX_PATTERNS = ("setup.py install", "easy_install")


class DocContractError(Exception):
    """Raised for a single, reported installation-doc contract violation."""


def _fenced_body(snippet: str) -> str:
    """Return the inner text of the first fenced code block, or raw text."""
    match = _FENCE_RE.search(snippet)
    if match is not None:
        return match.group(1)
    return snippet.strip()


def extract_snippets(path: Path) -> dict[str, str]:
    """Return {marker_name: raw_snippet_text} for one doc, validating markers.

    Raises DocContractError for unmatched, mismatched, or duplicated
    ``pysh-install`` markers -- the "markers must be tested for uniqueness
    and proper pairing" requirement.
    """
    text = path.read_text(encoding="utf-8")
    opens = _MARKER_OPEN_RE.findall(text)
    closes = _MARKER_CLOSE_RE.findall(text)
    if len(opens) != len(set(opens)):
        dupes = sorted({name for name in opens if opens.count(name) > 1})
        raise DocContractError(f"{path}: duplicate pysh-install marker name(s): {dupes}")
    if sorted(opens) != sorted(closes):
        raise DocContractError(
            f"{path}: unmatched pysh-install markers (open={sorted(opens)}, "
            f"close={sorted(closes)})"
        )
    snippets: dict[str, str] = {}
    for match in _MARKER_PAIR_RE.finditer(text):
        snippets[match.group(1)] = match.group(2)
    if set(snippets) != set(opens):
        raise DocContractError(f"{path}: markers present but snippet extraction failed")
    return snippets


def load_pyproject() -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def canonical_identity(pyproject: dict[str, object]) -> tuple[str, str, str]:
    """Return (package_name, version, requires_python) from pyproject.toml."""
    project = pyproject["project"]  # type: ignore[index]
    return project["name"], project["version"], project["requires-python"]  # type: ignore[index]


def _requires_python_floor(requires_python: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", requires_python)
    if match is None:
        raise DocContractError(f"cannot parse requires-python: {requires_python!r}")
    return int(match.group(1)), int(match.group(2))


# --------------------------------------------------------------- doc contract


def _extract_pip_targets(command_text: str) -> set[str]:
    """Return the real target package names from ``pip install`` invocations.

    Excludes ``pip`` itself (the common ``pip install --upgrade pip``
    self-bootstrap idiom, never a reference to the package under test) and
    local paths / requirements-file style arguments.
    """
    targets: set[str] = set()
    for spec in _PIP_INSTALL_RE.findall(command_text):
        name = re.split(r"[=<>!~;]", spec, maxsplit=1)[0]
        if name in (".", "-e") or name.startswith(("-", "./", "/")):
            continue
        if name.lower() == "pip":
            continue
        targets.add(name)
    return targets


def check_pip_package_name(label: str, command_text: str, expected_name: str) -> list[str]:
    targets = _extract_pip_targets(command_text)
    if not targets:
        return [f"{label}: no 'pip install <package>' command found"]
    errors = []
    for name in targets:
        if name != expected_name:
            errors.append(f"{label}: pip install references {name!r}, expected {expected_name!r}")
    return errors


def check_version_statement(label: str, text: str, expected_version: str) -> list[str]:
    match = _VERSION_STATEMENT_RE.search(text)
    if match is None:
        return [f"{label}: no explicit 'PySH X.Y.Z' version statement found"]
    if match.group(1) != expected_version:
        return [
            f"{label}: states version {match.group(1)!r}, but pyproject.toml is "
            f"{expected_version!r} (stale documented version)"
        ]
    return []


def check_os_package_name_pattern(label: str, text: str, pattern: re.Pattern[str]) -> list[str]:
    candidate = _fenced_body(text).strip()
    if not pattern.match(candidate):
        return [f"{label}: {candidate!r} does not match the canonical naming pattern"]
    return []


def check_referenced_scripts_exist(label: str, text: str) -> list[str]:
    errors: list[str] = []
    for rel in _SCRIPT_PATH_RE.findall(text):
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"{label}: references nonexistent script: {rel}")
    return errors


def check_shell_syntax(label: str, text: str) -> list[str]:
    """Reject unparsable shell lines in a designated command snippet."""
    errors: list[str] = []
    for line in _fenced_body(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            shlex.split(stripped, comments=True)
        except ValueError as exc:
            errors.append(f"{label}: malformed shell command {stripped!r}: {exc}")
    return errors


def check_no_legacy_syntax(label: str, text: str) -> list[str]:
    errors: list[str] = []
    for pattern in _LEGACY_SYNTAX_PATTERNS:
        if pattern in text:
            errors.append(f"{label}: uses unsupported legacy install syntax: {pattern!r}")
    return errors


def check_local_package_arg_matches(
    label: str, text: str, pattern: re.Pattern[str]
) -> list[str]:
    """The install command's local ./<file> argument must match the naming pattern.

    Also guards against "points at another package" (requirement 12):
    a filename that does not match pysh-shell's own naming contract is
    rejected, whatever it is named.
    """
    body = _fenced_body(text)
    matches = _LOCAL_PKG_ARG_RE.findall(body)
    if not matches:
        return [f"{label}: no local './<package-file>' install argument found"]
    errors = []
    for basename in matches:
        if not pattern.match(basename):
            errors.append(
                f"{label}: install command references {basename!r}, which does not "
                "match the canonical package naming contract"
            )
    return errors


def run_doc_contract(
    readme_path: Path,
    installation_path: Path,
    pyproject: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    name, version, requires_python = canonical_identity(pyproject)
    py_major, py_minor = _requires_python_floor(requires_python)

    try:
        readme_snippets = extract_snippets(readme_path)
    except DocContractError as exc:
        return [str(exc)]
    try:
        install_snippets = extract_snippets(installation_path)
    except DocContractError as exc:
        return [str(exc)]

    deb_name_re = re.compile(rf"^{re.escape(name)}_X\.Y\.Z-1_all\.deb$")
    rpm_name_re = re.compile(rf"^{re.escape(name)}-X\.Y\.Z-1\.noarch\.rpm$")
    freebsd_name_re = re.compile(rf"^{re.escape(name)}-X\.Y\.Z\.pkg$")

    # --- README.md ---------------------------------------------------
    if "pypi" in readme_snippets:
        errors += check_pip_package_name("README.md:pypi", readme_snippets["pypi"], name)
        errors += check_shell_syntax("README.md:pypi", readme_snippets["pypi"])
        errors += check_no_legacy_syntax("README.md:pypi", readme_snippets["pypi"])
    else:
        errors.append("README.md: missing required 'pypi' installation marker")

    if "dev" in readme_snippets:
        errors += check_referenced_scripts_exist("README.md:dev", readme_snippets["dev"])
        errors += check_shell_syntax("README.md:dev", readme_snippets["dev"])

    # --- docs/user/installation.md ------------------------------------
    required_install_markers = (
        "version",
        "pypi",
        "pypi-verify",
        "deb-name",
        "deb",
        "rpm-name",
        "rpm",
        "freebsd-name",
        "freebsd",
        "freebsd-build",
        "dev",
    )
    for marker in required_install_markers:
        if marker not in install_snippets:
            errors.append(f"docs/user/installation.md: missing required {marker!r} marker")

    if "version" in install_snippets:
        errors += check_version_statement(
            "docs/user/installation.md:version", install_snippets["version"], version
        )

    if "pypi" in install_snippets:
        errors += check_pip_package_name(
            "docs/user/installation.md:pypi", install_snippets["pypi"], name
        )
        errors += check_shell_syntax("docs/user/installation.md:pypi", install_snippets["pypi"])
        errors += check_no_legacy_syntax(
            "docs/user/installation.md:pypi", install_snippets["pypi"]
        )

    if "pypi-verify" in install_snippets:
        errors += check_shell_syntax(
            "docs/user/installation.md:pypi-verify", install_snippets["pypi-verify"]
        )

    if "deb-name" in install_snippets:
        errors += check_os_package_name_pattern(
            "docs/user/installation.md:deb-name", install_snippets["deb-name"], deb_name_re
        )
    if "deb" in install_snippets:
        errors += check_shell_syntax("docs/user/installation.md:deb", install_snippets["deb"])
        errors += check_local_package_arg_matches(
            "docs/user/installation.md:deb", install_snippets["deb"], deb_name_re
        )

    if "rpm-name" in install_snippets:
        errors += check_os_package_name_pattern(
            "docs/user/installation.md:rpm-name", install_snippets["rpm-name"], rpm_name_re
        )
    if "rpm" in install_snippets:
        errors += check_shell_syntax("docs/user/installation.md:rpm", install_snippets["rpm"])
        errors += check_local_package_arg_matches(
            "docs/user/installation.md:rpm", install_snippets["rpm"], rpm_name_re
        )

    if "freebsd-name" in install_snippets:
        errors += check_os_package_name_pattern(
            "docs/user/installation.md:freebsd-name",
            install_snippets["freebsd-name"],
            freebsd_name_re,
        )
    if "freebsd" in install_snippets:
        errors += check_shell_syntax(
            "docs/user/installation.md:freebsd", install_snippets["freebsd"]
        )
        errors += check_local_package_arg_matches(
            "docs/user/installation.md:freebsd", install_snippets["freebsd"], freebsd_name_re
        )

    if "freebsd-build" in install_snippets:
        errors += check_referenced_scripts_exist(
            "docs/user/installation.md:freebsd-build", install_snippets["freebsd-build"]
        )
        errors += check_shell_syntax(
            "docs/user/installation.md:freebsd-build", install_snippets["freebsd-build"]
        )

    if "dev" in install_snippets:
        errors += check_referenced_scripts_exist(
            "docs/user/installation.md:dev", install_snippets["dev"]
        )
        errors += check_shell_syntax("docs/user/installation.md:dev", install_snippets["dev"])

    # --- Python version requirement ------------------------------------
    requirements_text = installation_path.read_text(encoding="utf-8")
    stated_python = re.search(r"Python\s+\*\*(\d+)\.(\d+)", requirements_text)
    if stated_python is None:
        errors.append("docs/user/installation.md: no 'Python **X.Y' requirement statement found")
    else:
        stated = (int(stated_python.group(1)), int(stated_python.group(2)))
        if stated != (py_major, py_minor):
            errors.append(
                f"docs/user/installation.md: states Python {stated[0]}.{stated[1]}+, but "
                f"pyproject.toml requires-python is {requires_python!r}"
            )

    # --- README <-> installation.md shared-marker consistency -----------
    for shared in ("pypi", "dev"):
        if shared not in readme_snippets or shared not in install_snippets:
            continue
        if shared == "pypi":
            readme_pkgs = _extract_pip_targets(readme_snippets[shared])
            install_pkgs = _extract_pip_targets(install_snippets[shared])
            if readme_pkgs != install_pkgs:
                errors.append(
                    "README.md and docs/user/installation.md disagree on the PyPI "
                    f"package name for the canonical install command: "
                    f"{sorted(readme_pkgs)} vs {sorted(install_pkgs)}"
                )
        elif shared == "dev":
            editable_re = re.compile(r'pip install -e ".\[dev\]"')
            readme_has = bool(editable_re.search(readme_snippets[shared]))
            install_has = bool(editable_re.search(install_snippets[shared]))
            if readme_has != install_has:
                errors.append(
                    "README.md and docs/user/installation.md disagree on the "
                    "canonical editable development-install command"
                )

    return errors


# ------------------------------------------------------- portable execution


def _expected_wheel_sdist_names(version: str) -> tuple[str, set[str]]:
    wheel = f"pysh_shell-{version}-py3-none-any.whl"
    sdists = {f"pysh_shell-{version}.tar.gz", f"pysh-shell-{version}.tar.gz"}
    return wheel, sdists


def check_artifact_names(dist_dir: Path, version: str) -> list[str]:
    """Validate that built wheel/sdist filenames match the canonical pattern.

    Reuses the exact same naming convention as scripts/check_release_artifacts.sh
    (RQG-C) rather than inventing a second one; this function exists so that
    naming can be validated against a caller-supplied directory (including a
    test fixture), independent of running a real build.
    """
    errors: list[str] = []
    expected_wheel, expected_sdists = _expected_wheel_sdist_names(version)

    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        errors.append(f"expected exactly one wheel in {dist_dir}, found {len(wheels)}")
    elif wheels[0].name != expected_wheel:
        errors.append(f"wheel filename must be {expected_wheel!r}, got {wheels[0].name!r}")

    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(sdists) != 1:
        errors.append(f"expected exactly one sdist in {dist_dir}, found {len(sdists)}")
    elif sdists[0].name not in expected_sdists:
        errors.append(
            f"sdist filename must be one of {sorted(expected_sdists)}, got {sdists[0].name!r}"
        )
    return errors


def is_repository_source_path(resolved: Path) -> bool:
    """Return True if *resolved* lies inside this repository checkout.

    Used to detect PYTHONPATH/import contamination: an installed artifact's
    ``pysh`` module must resolve under the target venv's site-packages,
    never under ``REPO_ROOT`` (a repo-source shadow import).
    """
    return resolved == REPO_ROOT or REPO_ROOT in resolved.parents


def _run_cli_smoke(python_bin: Path, expected_version: str) -> list[str]:
    errors: list[str] = []
    bin_dir = python_bin.parent
    pysh_bin = bin_dir / "pysh"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tempfile.gettempdir(),
        )

    version_result = run(str(pysh_bin), "--version")
    if version_result.returncode != 0 or expected_version not in version_result.stdout:
        errors.append(f"'pysh --version' did not report {expected_version!r}: {version_result}")

    module_result = run(str(python_bin), "-m", "pysh", "--version")
    if module_result.returncode != 0 or expected_version not in module_result.stdout:
        errors.append(
            f"'python -m pysh --version' did not report {expected_version!r}: {module_result}"
        )

    echo_result = run(str(pysh_bin), "-c", "echo docs-smoke")
    if echo_result.returncode != 0 or echo_result.stdout.strip() != "docs-smoke":
        errors.append(f"'pysh -c \"echo docs-smoke\"' did not print docs-smoke: {echo_result}")

    file_result = run(str(python_bin), "-c", "import pysh; print(pysh.__file__)")
    if file_result.returncode != 0:
        errors.append(f"'python -c import pysh' failed: {file_result}")
    else:
        resolved = Path(file_result.stdout.strip()).resolve()
        if is_repository_source_path(resolved):
            errors.append(
                f"installed pysh resolved to a repository path (contamination): {resolved}"
            )

    return errors


def install_and_smoke(artifact: Path, expected_version: str, venv_root: Path) -> list[str]:
    venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
    python_bin = venv_root / "bin" / "python"

    # Installing a wheel needs no build backend at all. Installing an sdist
    # does (PySH's own build-system requirement, hatchling) -- by default
    # pip fetches that backend into a fresh isolated build env, which
    # requires network access. Pre-installing hatchling from uv's already
    # populated local cache (this project already depends on it for its
    # own build-system) and passing --no-build-isolation avoids that
    # entirely, keeping this smoke genuinely network-free; --no-build-isolation
    # is a no-op for a plain wheel install, so the same call works for both
    # artifact kinds without branching.
    hatchling_install = subprocess.run(
        ["uv", "pip", "install", "--python", str(python_bin), "hatchling"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if hatchling_install.returncode != 0:
        return [f"failed to pre-install hatchling for {artifact.name}: {hatchling_install.stderr}"]

    install = subprocess.run(
        [
            str(python_bin),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            str(artifact),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if install.returncode != 0:
        return [f"pip install of {artifact.name} failed: {install.stderr}"]
    return _run_cli_smoke(python_bin, expected_version)


def run_portable_smoke(pyproject: dict[str, object]) -> list[str]:
    _name, version, _rp = canonical_identity(pyproject)
    errors: list[str] = []

    # Build directly with "uv run --with build python -m build", the same
    # two-line pattern ci.yml's own "Build sdist and wheel" step already
    # uses, rather than scripts/build_pysh_package.sh: that script also
    # bakes in a "twine check" step, which is scripts/check_release_quality.sh's
    # job (and ci.yml's own "Validate package metadata" step), never
    # duplicated here. This install-and-run smoke only needs a real
    # wheel/sdist to exist; it does not re-validate PyPI metadata.
    shutil.rmtree(REPO_ROOT / "dist", ignore_errors=True)
    shutil.rmtree(REPO_ROOT / "build", ignore_errors=True)
    build = subprocess.run(
        ["uv", "run", "--with", "build", "python", "-m", "build"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if build.returncode != 0:
        return [f"python -m build failed: {build.stderr}"]

    dist_dir = REPO_ROOT / "dist"
    errors += check_artifact_names(dist_dir, version)
    if errors:
        return errors

    wheel = next(dist_dir.glob("*.whl"))
    sdist = next(dist_dir.glob("*.tar.gz"))

    with tempfile.TemporaryDirectory(prefix="pysh-docs-smoke-wheel-") as wheel_venv:
        errors += [f"[wheel] {e}" for e in install_and_smoke(wheel, version, Path(wheel_venv))]
    with tempfile.TemporaryDirectory(prefix="pysh-docs-smoke-sdist-") as sdist_venv:
        errors += [f"[sdist] {e}" for e in install_and_smoke(sdist, version, Path(sdist_venv))]

    return errors


# ------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=REPO_ROOT / "README.md")
    parser.add_argument(
        "--installation-doc", type=Path, default=REPO_ROOT / "docs" / "user" / "installation.md"
    )
    parser.add_argument(
        "--skip-portable",
        action="store_true",
        help="skip the wheel/sdist install-and-run smoke (doc contract only)",
    )
    args = parser.parse_args(argv)

    pyproject = load_pyproject()
    errors = run_doc_contract(args.readme, args.installation_doc, pyproject)

    if not args.skip_portable:
        errors += run_portable_smoke(pyproject)

    if errors:
        for error in errors:
            print(f"check_installation_docs.py: {error}", file=sys.stderr)
        return 1

    print("check_installation_docs.py: all installation documentation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
