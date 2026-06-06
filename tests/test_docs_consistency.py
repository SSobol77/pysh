# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository documentation consistency tests.

These checks are intentionally filesystem-only. They validate public Markdown
contracts without importing PySH runtime modules.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"

MARKDOWN_FILES: tuple[Path, ...] = (
    README,
    *tuple(sorted(DOCS.rglob("*.md"))),
)

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
AGENT_LINK_RE = re.compile(
    r"\]\((\.\./\.\./)?(AGENTS|CLAUDE|CODEX|CURSOR)\.md\)"
    r"|\]\((\.\./\.\./)?\.(claude|codex|cursor)/",
    re.IGNORECASE,
)


def _markdown_link_targets(text: str) -> list[str]:
    """Return Markdown link targets from *text*."""
    return [match.group(1) for match in LOCAL_LINK_RE.finditer(text)]


def test_docs_markdown_local_links_resolve() -> None:
    """All relative Markdown links in README.md and docs/**/*.md must resolve."""
    errors: list[str] = []
    for md_path in MARKDOWN_FILES:
        text = md_path.read_text(encoding="utf-8")
        for raw_target in _markdown_link_targets(text):
            target = raw_target.split("#", 1)[0]
            if (
                not target
                or target.startswith("#")
                or "://" in target
                or target.startswith("mailto:")
            ):
                continue
            resolved = (md_path.parent / target).resolve()
            if not resolved.exists():
                errors.append(
                    f"{md_path.relative_to(REPO_ROOT)}: broken local link -> {raw_target}"
                )

    assert not errors, "Broken local Markdown links:\n" + "\n".join(errors)


def test_root_readme_uses_github_urls_for_docs_links() -> None:
    """The PyPI-facing README must not contain relative docs/ links."""
    text = README.read_text(encoding="utf-8")
    violations = [
        target
        for target in _markdown_link_targets(text)
        if target.startswith("docs/") or target.startswith("./docs/")
    ]
    assert not violations, (
        "README.md must use absolute GitHub URLs for repository documentation links:\n"
        + "\n".join(f"  - {target}" for target in violations)
    )


def test_release_quality_gate_is_documented_and_executable() -> None:
    """The local release quality gate must be present, executable and documented."""
    script = REPO_ROOT / "scripts" / "check_release_quality.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111
    text = script.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-2.0-only" in text
    assert "Copyright (C) 2026 Siergej Sobolewski" in text

    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    assert "scripts/check_release_quality.sh" in release_doc
    assert "scripts/check_release_quality.sh" in packaging_doc


def test_release_quality_gate_enforces_mandatory_artifact_families() -> None:
    """The release quality gate must require PyPI, Debian, RPM and FreeBSD artifacts."""
    script = REPO_ROOT / "scripts" / "check_release_quality.sh"
    text = script.read_text(encoding="utf-8")

    assert "scripts/build_release_artifacts.sh" in text
    assert "scripts/check_release_artifacts.sh" in text
    assert "dist/*.whl" in text
    assert "dist/*.tar.gz" in text
    assert "dist/os/deb/pysh-shell_*-1_all.deb" in text
    assert "dist/os/rpm/pysh-shell-*-1.noarch.rpm" in text
    assert "dist/os/freebsd/pysh-shell-*.pkg" in text
    assert "dist/SHA256SUMS" in text
    assert "dist/release-assets/SHA256SUMS" in text
    assert "scripts/build_freebsd_pkg.sh" in text


def test_release_artifact_script_stages_flat_github_release_assets() -> None:
    """Release artifacts must be staged flat without weakening nested package checks."""
    script = REPO_ROOT / "scripts" / "check_release_artifacts.sh"
    text = script.read_text(encoding="utf-8")

    assert 'RELEASE_ASSETS_DIR="${REPO_ROOT}/dist/release-assets"' in text
    assert 'rm -rf "${RELEASE_ASSETS_DIR}"' in text
    assert 'cp "${DEB_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_DEB}"' in text
    assert 'cp "${RPM_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_RPM}"' in text
    assert 'cp "${FREEBSD_PKG_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_FREEBSD_PKG}"' in text
    assert '"os/deb/${EXPECTED_DEB}"' in text
    assert '"os/rpm/${EXPECTED_RPM}"' in text
    assert '"os/freebsd/${EXPECTED_FREEBSD_PKG}"' in text
    assert '"${EXPECTED_DEB}"' in text
    assert '"${EXPECTED_RPM}"' in text
    assert '"${EXPECTED_FREEBSD_PKG}"' in text


def test_release_workflow_uploads_flat_staged_assets() -> None:
    """GitHub Release upload must use flat staged assets and include all families."""
    workflow = REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "bash scripts/build_pysh_package.sh" in text
    assert "bash scripts/build_deb.sh" in text
    assert "bash scripts/build_rpm.sh" in text
    assert "bash scripts/check_release_artifacts.sh" in text
    assert "dist/release-assets/*" in text
    assert "dist/os/deb/pysh-shell_*-1_all.deb" not in text
    assert "dist/os/rpm/pysh-shell-*-1.noarch.rpm" not in text
    assert "dist/SHA256SUMS" not in text

    freebsd_workflow = REPO_ROOT / ".github" / "workflows" / "freebsd-pkg.yml"
    freebsd_text = freebsd_workflow.read_text(encoding="utf-8")

    for name, workflow_text in (
        ("freebsd-pkg.yml", freebsd_text),
        ("release-artifacts.yml", text),
    ):
        assert "runs-on: [self-hosted, freebsd, x64]" not in workflow_text
        assert "vmactions/freebsd-vm" in workflow_text or "cross-platform-actions/action" in workflow_text
        assert "release: \"14.2\"" in workflow_text
        assert "pkg install -y python313" in workflow_text
        assert "python3.13 --version" in workflow_text
        assert "pkg --version" in workflow_text
        assert "pyproject.toml" in workflow_text
        assert 'PKG_PATH="dist/os/freebsd/pysh-shell-${VERSION}.pkg"' in workflow_text
        assert "pysh-shell-0.8.0.pkg" not in workflow_text
        assert "sh scripts/build_freebsd_pkg.sh" in workflow_text
        assert 'pkg info -F "${PKG_PATH}"' in workflow_text
        assert 'pkg query -F "${PKG_PATH}" "%Fp"' in workflow_text
        assert "/usr/local/bin/pysh" in workflow_text
        assert "/usr/local/lib/pysh-shell/pysh" in workflow_text
        assert "actions/upload-artifact" in workflow_text, name

    assert "workflow_dispatch:" in freebsd_text
    assert "push:" in freebsd_text
    assert "release/v0.8.0" in freebsd_text
    assert "runs-on: ubuntu-latest" in freebsd_text
    assert "dist/os/freebsd/pysh-shell-*.pkg" in freebsd_text
    assert "needs: freebsd-pkg" in text
    assert "actions/download-artifact" in text
    assert "path: dist/os/freebsd" in text


def test_release_docs_define_flat_assets_and_nested_local_layout() -> None:
    """Docs must distinguish flat GitHub assets from nested local build internals."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    for text in (packaging_doc, release_doc, installation_doc):
        assert "gh release download vX.Y.Z" in text
        assert "sha256sum -c SHA256SUMS" in text

    assert "dist/release-assets/" in packaging_doc
    assert "flat filenames only" in packaging_doc
    assert "dist/os/deb/" in packaging_doc
    assert "dist/os/rpm/" in packaging_doc
    assert "dist/os/freebsd/" in packaging_doc
    assert "dist/release-assets/" in release_doc
    assert "dist/os/deb/" in release_doc
    assert "dist/os/rpm/" in release_doc
    assert "dist/os/freebsd/" in release_doc
    assert "local `dist/os/`" in installation_doc


def test_release_quality_gate_enforces_os_package_contents() -> None:
    """The release quality gate must inspect mandatory OS package contents."""
    script = REPO_ROOT / "scripts" / "check_release_quality.sh"
    text = script.read_text(encoding="utf-8")

    assert "dpkg-deb --contents" in text
    assert "rpm -qpl" in text
    assert "/usr/bin/pysh" in text
    assert "/opt/pysh-shell/lib/pysh" in text
    assert "missing required path" in text


def test_release_docs_state_current_mandatory_artifact_policy() -> None:
    """Release docs must not treat OS package artifacts as optional."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")

    for text in (packaging_doc, release_doc):
        assert "PyPI wheel + sdist" in text
        assert "Debian `.deb`" in text
        assert "RPM `.rpm`" in text
        assert "FreeBSD `.pkg`" in text
        assert "SHA256SUMS" in text


def test_public_docs_do_not_link_to_agent_instruction_files() -> None:
    """Public docs must not link to ignored or untracked agent/rules files."""
    violations: list[str] = []
    for md_path in MARKDOWN_FILES:
        text = md_path.read_text(encoding="utf-8")
        if AGENT_LINK_RE.search(text):
            violations.append(str(md_path.relative_to(REPO_ROOT)))

    assert not violations, (
        "Public Markdown links to private agent instruction files are not allowed:\n"
        + "\n".join(f"  - {path}" for path in violations)
    )


def test_no_stale_issue_6_signal_or_boundary_claims() -> None:
    """Issue #6 docs must not retain stale proc.wait or boundary-cleanup claims."""
    stale_patterns: tuple[re.Pattern[str], ...] = (
        re.compile(r"does not currently " + r"convert", re.IGNORECASE),
        re.compile(r"raw value from proc\.wait", re.IGNORECASE),
        re.compile(r"raw proc\.wait", re.IGNORECASE),
        re.compile(r"leaking negative", re.IGNORECASE),
        re.compile(
            r"Issue #6[^.\n]*resol" + r"ves[^.\n]*pysh\." + r"security",
            re.IGNORECASE,
        ),
        re.compile(r"pysh\.security[^.\n]*Issue #6", re.IGNORECASE),
    )

    violations: list[str] = []
    for md_path in MARKDOWN_FILES:
        text = md_path.read_text(encoding="utf-8")
        for pattern in stale_patterns:
            match = pattern.search(text)
            if match:
                violations.append(
                    f"{md_path.relative_to(REPO_ROOT)}: stale text -> {match.group(0)!r}"
                )

    assert not violations, "Stale Issue #6 documentation claims:\n" + "\n".join(violations)


def _find_list_header(lines: list[str], item_idx: int) -> str:
    """Return the nearest non-bullet, non-blank ancestor of a bullet item.

    Walks backward from ``item_idx - 1`` through blank lines and sibling
    bullet items to find the closest list header (a prose line, typically
    ending with ``:``) that governs the current bullet.
    """
    for i in range(item_idx - 1, -1, -1):
        stripped = lines[i].rstrip()
        if not stripped:
            continue  # blank line — keep walking
        if stripped.lstrip().startswith(("- ", "* ", "+ ")):
            continue  # sibling bullet — keep walking
        return stripped  # first non-blank, non-bullet ancestor
    return ""


def test_no_forbidden_security_claims() -> None:
    """No affirmative forbidden security claims may appear in public docs.

    Allowed when negated in context:
    - same line (e.g., "is not sandboxed", "does not auto-wrap sudo"), OR
    - governing list header, found by walking backward through blank lines
      and sibling bullets (e.g., "It does not provide:\\n- Privilege separation.").
    """
    negation_re = re.compile(
        r"\b(not|no|never|does\s+not|do\s+not|cannot|is\s+not|are\s+not|"
        r"without|forbidden|prohibited|avoids?|rejects?|provide|unsupported)\b",
        re.IGNORECASE,
    )

    forbidden: tuple[str, ...] = (
        "safe to run untrusted code",
        "privilege separation",
        "capability confinement",
        "sandboxed execution",
        "PySH is sandboxed",
        "PySH sandboxes",
        "executes .zshrc by default",
        "executes .bashrc by default",
        "auto-wraps sudo",
        "knows password correctness",
    )
    violations: list[str] = []
    for md_path in MARKDOWN_FILES:
        lines = md_path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if phrase_lower := next(
                (p for p in forbidden if p.lower() in line.lower()), None
            ):
                # Build context: current line + governing list header (if any).
                header = _find_list_header(lines, lineno - 1)
                context = header + "\n" + line
                if negation_re.search(context):
                    continue
                violations.append(
                    f"{md_path.relative_to(REPO_ROOT)}:{lineno}: {phrase_lower!r} "
                    f"(no negation in line or list header)"
                )

    assert not violations, (
        "Affirmative forbidden security claims found in public docs:\n"
        + "\n".join(f"  - {item}" for item in violations)
    )


def test_no_affirmative_broad_compatibility_claims_in_public_docs() -> None:
    """Broad shell-compatibility claims must be negated or avoided."""
    forbidden = (
        "PySH is zsh-" + "compatible",
        "PySH is bash-" + "compatible",
        "PySH is POSIX-" + "compatible",
        "PySH is a /bin/sh " + "replacement",
        "PySH is a drop-in " + "replacement",
        "fully " + "compatible",
    )
    violations: list[str] = []
    for md_path in MARKDOWN_FILES:
        text = md_path.read_text(encoding="utf-8")
        for phrase in forbidden:
            if phrase in text:
                violations.append(f"{md_path.relative_to(REPO_ROOT)}: {phrase}")

    assert not violations, (
        "Avoid broad compatibility phrases even in explanatory prose; use scoped wording:\n"
        + "\n".join(f"  - {item}" for item in violations)
    )


# ---------------------------------------------------------------------------
# Version gate tests — prevent stale release metadata from surviving a bump
# ---------------------------------------------------------------------------

CURRENT_VERSION = "0.8.0"
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "src" / "pysh" / "__init__.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def test_pyproject_toml_version_is_current() -> None:
    """pyproject.toml must declare the current release version."""
    import tomllib

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    actual = data["project"]["version"]
    assert actual == CURRENT_VERSION, (
        f"pyproject.toml version must be {CURRENT_VERSION!r}, got {actual!r}"
    )


def test_init_py_version_is_current() -> None:
    """src/pysh/__init__.py __version__ must match the current release."""
    text = INIT_PY.read_text(encoding="utf-8")
    import re

    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    assert match, "__version__ not found in src/pysh/__init__.py"
    actual = match.group(1)
    assert actual == CURRENT_VERSION, (
        f"__version__ must be {CURRENT_VERSION!r}, got {actual!r}"
    )


def test_readme_does_not_present_stale_version_as_current() -> None:
    """README.md must not claim 0.6.1 or 0.6.0 as the current release."""
    text = README.read_text(encoding="utf-8")
    stale = re.compile(r"\b0\.6\.[01]\b")
    matches = [(m.start(), m.group()) for m in stale.finditer(text)]
    assert not matches, (
        "README.md references stale version as current release: "
        + ", ".join(v for _, v in matches)
    )


def test_changelog_has_current_version_section() -> None:
    """CHANGELOG.md must contain a section for the current release."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"## {CURRENT_VERSION}" in text, (
        f"CHANGELOG.md must contain a '## {CURRENT_VERSION}' section"
    )


def test_changelog_current_release_covers_mandatory_features() -> None:
    """CHANGELOG current-release section must document mandatory v0.8.0 scope."""
    text = CHANGELOG.read_text(encoding="utf-8")

    start = text.find(f"## {CURRENT_VERSION}")
    assert start != -1, f"CHANGELOG.md missing ## {CURRENT_VERSION} section"

    # Find end of the current release section (next ## header or EOF).
    rest = text[start:]
    next_section = rest.find("\n## ", 1)
    section = rest[:next_section] if next_section != -1 else rest

    required_phrases = (
        "Issue #18",
        "Issue #21",
        "Issue #22",
        "Issue #23",
        "Issue #24",
        "prompt",
        "banner",
        "multiline paste",
        "stale input",
        "exit",
        "quit",
        "FreeBSD 14+",
        "`.pkg`",
        "wheel",
        "sdist",
        "`.deb`",
        "`.rpm`",
        "SHA256SUMS",
        "Debian/Linux",
        "fake `.pkg`",
        "~/.pyshrc.py",
        "not overwritten",
    )
    missing = [p for p in required_phrases if p.lower() not in section.lower()]
    assert not missing, (
        f"CHANGELOG v{CURRENT_VERSION} section missing coverage of: "
        + ", ".join(missing)
    )


def test_docs_system_shell_policy_present() -> None:
    """System shell integration policy doc must exist and assert PySH is not /bin/sh."""
    policy_doc = DOCS / "compatibility" / "system-shell-integration-policy.md"
    assert policy_doc.exists(), "Missing system-shell-integration-policy.md"
    text = policy_doc.read_text(encoding="utf-8")
    assert "/bin/sh" in text, "system-shell-integration-policy.md must mention /bin/sh"


def test_freebsd_pkg_builder_script_exists_and_is_executable() -> None:
    """FreeBSD package builder must exist, be executable and document FreeBSD-only use."""
    script = REPO_ROOT / "scripts" / "build_freebsd_pkg.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111
    text = script.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-2.0-only" in text
    assert "uname -s" in text
    assert "FreeBSD 14+" in text
    assert "pkg create" in text
    assert "pkg info -F" in text
    assert "pkg query -F" in text
    assert "/usr/local/bin/pysh" in text
    assert "exec /usr/local/bin/python3.13 -m pysh" in text
    assert "/usr/local/lib/pysh-shell/pysh" in text
    assert "pysh-shell-${VERSION}.pkg" in text


def test_freebsd_pkg_builder_refuses_non_freebsd_without_fake_pkg() -> None:
    """On non-FreeBSD hosts, the builder must fail before creating fake .pkg bytes."""
    if os.uname().sysname == "FreeBSD":
        return
    import tomllib

    version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    expected = REPO_ROOT / "dist" / "os" / "freebsd" / f"pysh-shell-{version}.pkg"
    if expected.exists():
        expected.unlink()

    result = subprocess.run(
        ["bash", "scripts/build_freebsd_pkg.sh"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert (
        "FreeBSD .pkg must be built on FreeBSD 14+ with native pkg tooling; "
        f"refusing to fake .pkg on {os.uname().sysname}."
    ) in result.stderr
    assert not expected.exists()


def test_docs_freebsd_pkg_is_mandatory_for_v080() -> None:
    """Docs must describe FreeBSD .pkg as mandatory/current for v0.8.0."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    assert "FreeBSD validation and package build for v0.8.0" in packaging_doc
    assert "Install from a GitHub Release `.pkg` (FreeBSD 14+)" in installation_doc
    assert "FreeBSD 14+ package and smoke validation" in release_doc

    for name, text in (
        ("packaging.md", packaging_doc),
        ("release.md", release_doc),
        ("installation.md", installation_doc),
    ):
        assert "FreeBSD" in text, f"{name} must mention FreeBSD validation"
        assert ".pkg" in text, f"{name} must mention FreeBSD .pkg status"
        assert "mandatory" in text.lower() or "canonical FreeBSD artifact" in text
        assert "planned/future" not in text
        assert "deferred" not in text


def test_freebsd_validation_docs_include_required_smoke_commands() -> None:
    """FreeBSD validation docs must include the required package and smoke commands."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    required_commands = (
        "python3.13 -m venv /tmp/pysh-freebsd-smoke",
        ". /tmp/pysh-freebsd-smoke/bin/activate",
        "python -m pip install --upgrade pip",
        "python -m pip install pysh-shell==X.Y.Z",
        "pysh --version",
        "python -m pysh --version",
        'pysh -c "echo freebsd-smoke"',
        'pysh -c "exit"',
        'pysh -c "quit"',
        "bash scripts/build_freebsd_pkg.sh",
        "sudo pkg install ./pysh-shell-X.Y.Z.pkg",
    )
    for text in (packaging_doc, installation_doc):
        for command in required_commands:
            assert command in text


def test_freebsd_validation_docs_capture_portability_and_interactive_checks() -> None:
    """FreeBSD docs must capture platform risks and interactive safety checks."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")
    combined = packaging_doc + "\n" + installation_doc

    required_phrases = (
        "Python 3.13 or newer",
        "virtual environment",
        "startup banner renders",
        "framed prompt",
        "Unicode",
        "exit` exits on the first attempt",
        "quit` exits on the first attempt",
        "multiline paste safety remains enabled",
        "Python-first",
        "must not replace `/bin/sh`",
        "terminal and PTY behavior",
        "platform.release()",
        "/proc/cpuinfo",
        "package manager semantics",
        "filesystem layout",
        "executable wrapper paths",
    )
    for phrase in required_phrases:
        assert phrase in combined


def test_freebsd_pkg_future_direction_is_not_current_artifact_policy() -> None:
    """Docs must define FreeBSD .pkg as a current mandatory artifact policy."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")
    combined = packaging_doc + "\n" + installation_doc

    current_artifacts = (
        "PyPI wheel + sdist",
        "Debian `.deb`",
        "RPM `.rpm`",
        "FreeBSD `.pkg`",
        "SHA256SUMS",
    )
    for artifact in current_artifacts:
        assert artifact in combined

    assert "FreeBSD `.pkg` packaging is current mandatory v0.8.0 release work" in combined
    assert "pysh-shell-X.Y.Z.pkg" in combined
    assert "dist/os/freebsd/pysh-shell-X.Y.Z.pkg" in combined
    assert "dist/release-assets/pysh-shell-X.Y.Z.pkg" in combined
    assert "/usr/local/bin/pysh" in packaging_doc
    assert "/usr/local/lib/pysh-shell/pysh/" in combined
    assert "/usr/local/share/doc/pysh-shell/" in combined
    assert "no system shell diversion" in packaging_doc
    assert "no overwrite of an existing `~/.pyshrc.py`" in combined
    assert "must not replace `/bin/sh`" in combined


def test_release_gates_require_freebsd_pkg_without_fake_builds() -> None:
    """Release scripts/workflow must require .pkg while refusing non-FreeBSD fake builds."""
    quality_gate = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(
        encoding="utf-8"
    )
    artifact_gate = (REPO_ROOT / "scripts" / "check_release_artifacts.sh").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(
        encoding="utf-8"
    )

    for text in (quality_gate, artifact_gate):
        assert "dist/*.whl" in text or "EXPECTED_WHEEL_NAME" in text
        assert "dist/*.tar.gz" in text or "EXPECTED_SDIST" in text
        assert "pysh-shell_*-1_all.deb" in text or "EXPECTED_DEB" in text
        assert "pysh-shell-*-1.noarch.rpm" in text or "EXPECTED_RPM" in text
        assert "pysh-shell-*.pkg" in text or "EXPECTED_FREEBSD_PKG" in text
        assert "SHA256SUMS" in text
    assert "FreeBSD .pkg is mandatory" in (
        REPO_ROOT / "scripts" / "build_release_artifacts.sh"
    ).read_text(encoding="utf-8")
    assert "dist/release-assets/*" in workflow


def test_release_quality_gate_preserves_prebuilt_freebsd_pkg_before_cleaning() -> None:
    """Top-level quality gate must preserve prebuilt .pkg before removing dist/."""
    quality_gate = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(
        encoding="utf-8"
    )

    assert 'EXPECTED_FREEBSD_PKG="pysh-shell-${VERSION}.pkg"' in quality_gate
    assert 'FREEBSD_PKG_PATH="${REPO_ROOT}/dist/os/freebsd/${EXPECTED_FREEBSD_PKG}"' in (
        quality_gate
    )
    assert "preserve_freebsd_pkg()" in quality_gate
    assert "restore_freebsd_pkg()" in quality_gate
    assert 'cp "${FREEBSD_PKG_PATH}" "${PRESERVED_FREEBSD_PKG}"' in quality_gate
    assert 'cp "${PRESERVED_FREEBSD_PKG}" "${FREEBSD_PKG_PATH}"' in quality_gate

    preserve_idx = quality_gate.index("\npreserve_freebsd_pkg\n")
    clean_idx = quality_gate.index("rm -rf dist build ./*.egg-info")
    restore_idx = quality_gate.index("\nrestore_freebsd_pkg\n")
    build_idx = quality_gate.index('bash "${REPO_ROOT}/scripts/build_release_artifacts.sh"')
    assert preserve_idx < clean_idx < restore_idx < build_idx


# ---------------------------------------------------------------------------
# Issue #23 — Release asset workflow regression guard
# ---------------------------------------------------------------------------


def test_installation_doc_has_upgrade_paths() -> None:
    """Installation doc must document upgrade instructions for all distribution channels.

    Regression guard for Issue #23: every supported install path (PyPI, .deb,
    .rpm) must also have a documented upgrade path so users can move between
    releases without losing configuration or consulting external sources.
    """
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    assert "## Upgrading" in installation_doc, (
        "installation.md must contain an ## Upgrading section"
    )
    assert "pip install --upgrade pysh-shell" in installation_doc, (
        "installation.md must document 'pip install --upgrade pysh-shell' for PyPI upgrades"
    )
    assert "apt install" in installation_doc, (
        "installation.md must document apt install for .deb upgrades"
    )
    assert "dnf upgrade" in installation_doc, (
        "installation.md must document 'dnf upgrade' for .rpm upgrades"
    )


def test_installation_doc_states_pyshrc_py_preserved_on_upgrade() -> None:
    """Installation doc must explicitly state that ~/.pyshrc.py is not overwritten on upgrade.

    Regression guard for Issue #23: users must be informed that upgrading PySH
    through any distribution channel (PyPI, .deb, .rpm) preserves their
    existing Python-native configuration file.  If a future release ships a new
    default template it must be delivered as a template only, never forced over
    an existing file.
    """
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    assert "pyshrc.py" in installation_doc, (
        "installation.md must mention ~/.pyshrc.py in the upgrade section"
    )
    preserved = (
        "not overwritten" in installation_doc
        or "never overwrites" in installation_doc
        or "never overwritten" in installation_doc
    )
    assert preserved, (
        "installation.md must state that ~/.pyshrc.py is not overwritten during upgrades"
    )
    assert "template" in installation_doc, (
        "installation.md must state that future default configs are installed as templates only"
    )


def test_release_quality_gate_validates_flat_sha256sums_entries() -> None:
    """Quality gate must reject dist/release-assets/SHA256SUMS entries with path separators.

    Regression guard for Issue #23: the v0.7.0 incident showed that a
    SHA256SUMS file with nested paths (``os/deb/...``) does not survive a plain
    ``gh release download vX.Y.Z`` intact.  The quality gate's Python
    inspection block must actively reject any ``/`` or ``./`` prefix in the
    flat release-facing checksum file.
    """
    script = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")

    assert '"/" in filename' in script, (
        "check_release_quality.sh must check that release-assets/SHA256SUMS "
        "entries contain no '/' path separator"
    )
    assert "must use flat filenames" in script, (
        "check_release_quality.sh must emit a 'must use flat filenames' error "
        "when a path separator is found in release-assets/SHA256SUMS"
    )
