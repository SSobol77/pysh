# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_docs_consistency.py
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
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"
ARCHITECTURE_POLICY = REPO_ROOT / "architecture.toml"
LAYERING_DOC = DOCS / "architecture" / "layering.md"

MARKDOWN_FILES: tuple[Path, ...] = (
    *tuple(
        sorted(
            REPO_ROOT / line
            for line in subprocess.run(
                ["git", "ls-files", "README.md", "docs/*.md"],
                cwd=REPO_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.splitlines()
            if line
        )
    ),
)

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
AGENT_LINK_RE = re.compile(
    r"\]\((\.\./\.\./)?(AGENTS|CLAUDE|CODEX|CURSOR)\.md\)"
    r"|\]\((\.\./\.\./)?\.(claude|codex|cursor)/",
    re.IGNORECASE,
)


def _tracked_files(*patterns: str) -> tuple[Path, ...]:
    """Return tracked repository files matching git pathspec patterns."""
    result = subprocess.run(
        ["git", "ls-files", *patterns],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return tuple(REPO_ROOT / line for line in result.stdout.splitlines() if line)


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


def test_tracked_source_docs_and_scripts_declare_repository_relative_file_path() -> None:
    """Tracked Markdown, Python and shell files must self-identify by path."""
    errors: list[str] = []
    for path in _tracked_files("*.md", "*.py", "*.sh"):
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        expected = f"File: {rel_path}"
        text = path.read_text(encoding="utf-8")
        if expected not in text and f"# {expected}" not in text:
            errors.append(f"{rel_path}: missing {expected}")

    assert not errors, "Missing canonical File metadata:\n" + "\n".join(errors)


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

    assert 'RELEASE_ASSETS_DIR="${DIST_DIR}/release-assets"' in text
    assert 'DIST_DIR="${1:-${REPO_ROOT}/dist}"' in text, (
        "the default (no-args) invocation must still resolve to the real dist/, "
        "even though DIST_DIR is now parameterized for --contract-only"
    )
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

    assert "runs-on: [self-hosted, freebsd, x64]" not in text
    assert "vmactions/freebsd-vm" in text or "cross-platform-actions/action" in text
    assert 'release: "14.4"' in text
    assert "pkg install -y python313" in text
    assert "python3.13 --version" in text
    assert "pkg --version" in text
    assert 'PKG_PATH="dist/os/freebsd/pysh-shell-${VERSION}.pkg"' in text
    assert "pysh-shell-0.8.0.pkg" not in text
    assert "sh scripts/build_freebsd_pkg.sh" in text
    assert 'pkg info -F "${PKG_PATH}"' in text
    assert 'pkg query -F "${PKG_PATH}" "%Fp"' in text
    assert "/usr/local/bin/pysh" in text
    assert "/usr/local/lib/pysh-shell/pysh" in text
    assert "actions/upload-artifact" in text
    assert "actions/download-artifact" in text
    assert "path: dist/os/freebsd" in text

    # Issue #33 RQG-G: freebsd-pkg.yml was a byte-for-byte duplicate of the
    # freebsd-pkg job below, with a push trigger (branches: release/v*)
    # that never matched this project's real develop/vX.Y.Z branch model.
    # It added no unique release guarantee and was retired; the real
    # FreeBSD VM build lives solely here now.
    assert not (REPO_ROOT / ".github" / "workflows" / "freebsd-pkg.yml").exists()

    # Explicit three-job pipeline: build -> validate -> upload. Upload must
    # depend on the validate job succeeding and must never run unless the
    # trigger was a real release (workflow_dispatch dry runs build and
    # validate but never publish).
    assert "needs: freebsd-pkg" in text
    assert "needs: build-and-validate" in text
    assert "if: github.event_name == 'release'" in text
    assert "continue-on-error" not in text


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


def test_v1_threat_model_preserves_security_assurance_contract() -> None:
    """Issue #43 must remain explicit about implemented and deferred controls."""
    threat_model = DOCS / "security" / "threat-model.md"
    assert threat_model.is_file()
    text = threat_model.read_text(encoding="utf-8")

    required_contracts = (
        "CPython in-process execution is\n**not a security boundary**",
        "## Data classification",
        "## Safe startup: `--no-rc`",
        "`pysh.diagnostics.trace.RedactionPolicy` is the canonical policy",
        "## Threat register",
        "TM-PARSER-001",
        "TM-RUNTIME-001",
        "TM-RC-001",
        "TM-PLUGIN-001",
        "TM-HISTORY-001",
        "TM-DIAG-001",
        "TM-PTY-001",
        "TM-AI-001",
        "TM-REMOTE-001",
        "TM-PKG-001",
        "## Capability principles for Issue #44",
    )
    for contract in required_contracts:
        assert contract in text, f"v1 threat model is missing contract: {contract}"


def test_v1_threat_model_does_not_claim_current_plugin_sandboxing() -> None:
    text = (DOCS / "security" / "threat-model.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Current plugins remain executable trusted-local code" in normalized
    assert "do not retrofit isolation onto today's trusted in-process" in normalized
    assert "no ambient PySH parent-mediated capability" in normalized
    assert "satisfies the Issue #44 portable parent-authority boundary" in normalized
    assert "Direct same-UID syscalls remain governed by the host platform" in normalized


def test_isolated_plugin_contract_preserves_enforced_scope_and_limitations() -> None:
    """Issue #44 docs must distinguish broker controls from OS confinement."""
    contract = DOCS / "security" / "plugin-isolation.md"
    assert contract.is_file()
    text = contract.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    required = (
        "manifest version `1`",
        "isolated IPC protocol version `1`",
        "Requested capabilities are not grants",
        "no ambient PySH parent-mediated capability",
        "Capability grants govern only parent-mediated operations",
        "PYTHONNOUSERSITE=1",
        "PYTHONUTF8=1",
        "close_fds=True",
        "Issue #50",
        "Issue #52",
        "Issue #53",
        "FreeBSD validation is pending rather than PASS",
    )
    for statement in required:
        assert statement in normalized, f"isolated-plugin contract is missing: {statement}"

    assert "subprocess isolation is not a filesystem sandbox" in normalized
    assert "subprocess isolation is not a network sandbox" in normalized
    assert "subprocess isolation is not a process sandbox" in normalized
    assert "direct child syscalls" in normalized
    assert "FreeBSD Capsicum integration" in normalized
    assert "process-count" in normalized


def test_api_stability_contract_defines_external_boundary_and_version_domains() -> None:
    """Issue #45 must retain its normative API, SemVer, and deprecation rules."""
    contract = DOCS / "development" / "api-stability.md"
    assert contract.is_file()
    normalized = " ".join(contract.read_text(encoding="utf-8").split())

    required = (
        "This is the normative external-compatibility contract established by Issue #45",
        "`pysh.api` | `STABLE_PUBLIC`",
        "`pysh.contracts` | `COMPATIBILITY_PUBLIC`",
        "`pysh.shell.PyShell` | `COMPATIBILITY_PUBLIC`",
        "`pysh.plugins.isolated.*` Python objects | `INTERNAL`",
        "`ShellSession` is the supported non-interactive embedding boundary",
        "remains available through at least `1.(N+1)`",
        "earliest normal removal is `1.(N+2)`",
        "`DeprecationWarning`, never `FutureWarning`",
        "It will not be removed before PySH 1.2.0",
        "Changing one domain does not automatically change another",
        "Issue #46 owns structural enforcement",
    )
    for statement in required:
        assert statement in normalized, f"API stability contract is missing: {statement}"

    assert "pysh.core.shell.PyShell` is deliberately absent" in normalized
    assert "Issue #50 must name and version" in normalized


def test_api_stability_contract_is_linked_from_required_docs() -> None:
    """Architecture, plugin, release, roadmap, and index docs must link the policy."""
    expected_links = {
        DOCS / "README.md": "development/api-stability.md",
        DOCS / "architecture" / "architecture.md": "../development/api-stability.md",
        DOCS / "plugins" / "plugin-api.md": "../development/api-stability.md",
        DOCS / "security" / "plugin-isolation.md": "../development/api-stability.md",
        DOCS / "development" / "release.md": "api-stability.md",
        DOCS / "roadmap" / "ROADMAP-v1-2.md": "../development/api-stability.md",
    }
    for path, link in expected_links.items():
        assert link in path.read_text(encoding="utf-8"), f"{path} does not link {link}"


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

PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "src" / "pysh" / "__init__.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# The canonical release version has exactly one authoritative source:
# pyproject.toml. Earlier revisions of this test module additionally
# maintained a hardcoded ``CURRENT_VERSION = "0.8.2"`` literal that every
# version bump had to remember to update in lockstep -- a second copy that
# could itself drift. CURRENT_VERSION is now derived, not duplicated: every
# test below that references it is really asserting "agrees with
# pyproject.toml" (see docs/architecture/release-quality-gate-2-audit.md,
# RQG-B). Runtime __version__ vs. pyproject.toml agreement is still
# independently enforced by test_init_py_version_is_current below, and by
# scripts/check_release_metadata.sh for CI/release use.
CURRENT_VERSION = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
CURRENT_FACING_DOCS: tuple[Path, ...] = (
    README,
    REPO_ROOT / "roadmap.md",
    DOCS / "README.md",
    DOCS / "architecture" / "roadmap.md",
    DOCS / "compatibility" / "README.md",
    DOCS / "user" / "installation.md",
    DOCS / "development" / "release.md",
    DOCS / "development" / "packaging.md",
    DOCS / "compatibility" / "validation-matrix.md",
)
STALE_CURRENT_PHRASES: tuple[str, ...] = (
    "Current compatibility status (PySH 0.6.x)",
    "The v0.6.x release baseline includes:",
    "current release is 0.6.x",
    "current baseline is 0.6.x",
)


def _read_pyproject() -> dict[str, object]:
    """Return parsed pyproject.toml metadata."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_toml_version_is_well_formed() -> None:
    """pyproject.toml's version must be a well-formed X.Y.Z release string.

    This does not compare against a second hardcoded literal (there isn't
    one any more -- CURRENT_VERSION *is* this value); it guards against a
    malformed or accidentally-emptied version field, which the equality
    checks below would not otherwise catch on their own.
    """
    data = _read_pyproject()
    actual = data["project"]["version"]
    assert re.match(r"^\d+\.\d+\.\d+$", actual), (
        f"pyproject.toml version must be X.Y.Z, got {actual!r}"
    )


def test_init_py_version_is_current() -> None:
    """src/pysh/__init__.py __version__ must match pyproject.toml's version.

    This is the real cross-check: runtime-packaged metadata
    (``pysh.__version__``, which feeds both ``pysh --version`` and
    ``python -m pysh --version`` via ``src/pysh/cli.py``) must never drift
    from the single authoritative build version in pyproject.toml.
    """
    text = INIT_PY.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    assert match, "__version__ not found in src/pysh/__init__.py"
    actual = match.group(1)
    assert actual == CURRENT_VERSION, (
        f"__version__ must match pyproject.toml ({CURRENT_VERSION!r}), got {actual!r}"
    )


def test_readme_does_not_present_stale_version_as_current() -> None:
    """README.md must not claim the 0.6.x line as the current release."""
    text = README.read_text(encoding="utf-8")
    stale = re.compile(r"\b(?:PySH\s+)?0\.6\.(?:x|[01])\b", re.IGNORECASE)
    matches = [(m.start(), m.group()) for m in stale.finditer(text)]
    assert not matches, (
        "README.md references stale version as current release: "
        + ", ".join(v for _, v in matches)
    )


def test_roadmap_does_not_present_stale_version_as_current() -> None:
    """roadmap.md must not claim the 0.6.x line as the current release baseline."""
    roadmap = DOCS / "architecture" / "roadmap.md"
    text = roadmap.read_text(encoding="utf-8")
    stale = re.compile(r"\bv0\.6\.x release baseline\b", re.IGNORECASE)
    assert not stale.search(text), "roadmap.md still claims v0.6.x as release baseline"


def test_current_facing_docs_contain_current_version() -> None:
    """Current-facing public docs must name the current release version."""
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in CURRENT_FACING_DOCS
        if path.exists()
        if CURRENT_VERSION not in path.read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"Current-facing docs must contain {CURRENT_VERSION}:\n"
        + "\n".join(f"  - {path}" for path in missing)
    )


def test_current_facing_docs_do_not_claim_06x_as_current() -> None:
    """Current-facing docs must not present the 0.6.x line as current."""
    violations: list[str] = []
    checked = 0
    for doc in CURRENT_FACING_DOCS:
        if not doc.exists():
            continue
        checked += 1
        text = doc.read_text(encoding="utf-8")
        for phrase in STALE_CURRENT_PHRASES:
            if phrase in text:
                violations.append(f"{doc.relative_to(REPO_ROOT)}: {phrase!r}")

    assert checked > 0, "current-facing docs list did not match any files"
    assert not violations, (
        "Current-facing docs present 0.6.x as current:\n  "
        + "\n  ".join(violations)
    )


def test_contract_docs_only_use_06x_as_historical_or_normative_baseline() -> None:
    """Contract docs may mention 0.6.x only as historical/normative provenance."""
    contract_docs = (
        DOCS / "architecture" / "architecture.md",
        DOCS / "architecture" / "source-tree.md",
        DOCS / "architecture" / "path-expansion-contract.md",
        DOCS / "architecture" / "completion-engine-contract.md",
        DOCS / "architecture" / "job-control-contract.md",
        DOCS / "architecture" / "signal-handling.md",
        DOCS / "architecture" / "security-trust-model.md",
        DOCS / "compatibility" / "unsupported-constructs.md",
        DOCS / "compatibility" / "shell-compatibility-contract.md",
        DOCS / "compatibility" / "feature-matrix.md",
    )
    violations: list[str] = []
    for path in contract_docs:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            if "0.6.x" not in line:
                continue
            paragraph = " ".join(lines[max(0, line_no - 3): min(len(lines), line_no + 2)])
            is_historical_normative = (
                "established in the PySH 0.6.x line" in paragraph
                and (
                    "still normative for current releases unless superseded "
                    "by a newer contract section" in paragraph
                )
            )
            is_version_floor = re.search(r"PySH\s+>=\s+0\.6\.x", paragraph) is not None
            if not (is_historical_normative or is_version_floor):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line}")

    assert not violations, (
        "0.6.x references in contract docs must be historical/normative, not current:\n"
        + "\n".join(f"  - {item}" for item in violations)
    )


def test_default_runtime_is_stdlib_only() -> None:
    """Default installation must remain stdlib-only."""
    data = _read_pyproject()
    mandatory = [d.lower() for d in data["project"].get("dependencies", [])]
    assert mandatory == [], (
        "Default install must be stdlib-only; mandatory dependencies must be "
        f"empty, got: {mandatory}"
    )


def test_pygments_is_optional_only() -> None:
    """Pygments is allowed only in highlight/dev metadata, not runtime deps."""
    data = _read_pyproject()
    project = data["project"]
    mandatory = [d.lower() for d in project.get("dependencies", [])]

    assert not any(d.startswith("pygments") for d in mandatory), (
        "Pygments must not be a mandatory runtime dependency"
    )

    extras = project.get("optional-dependencies", {})
    assert "highlight" in extras, "optional extra 'highlight' is required"
    assert any(d.lower().startswith("pygments") for d in extras["highlight"]), (
        "optional extra 'highlight' must include pygments"
    )

    for name, deps in extras.items():
        if any(d.lower().startswith("pygments") for d in deps):
            assert name in {"highlight", "dev"}, (
                f"Pygments is only allowed under 'highlight' or 'dev', found in {name!r}"
            )

    dependency_groups = data.get("dependency-groups", {})
    for name, deps in dependency_groups.items():
        if any(d.lower().startswith("pygments") for d in deps):
            assert name == "dev", (
                f"Pygments is only allowed under development groups, found in {name!r}"
            )


def test_pyyaml_is_fully_removed_from_dependency_metadata() -> None:
    """PyYAML must not remain in runtime, extras, or UV dependency groups."""
    data = _read_pyproject()
    project = data["project"]
    groups = [project.get("dependencies", [])]
    groups.extend(project.get("optional-dependencies", {}).values())
    groups.extend(data.get("dependency-groups", {}).values())
    flat = [d.lower() for group in groups for d in group]

    assert not any(d.startswith("pyyaml") for d in flat), (
        "PyYAML must be fully removed from dependency metadata, found: "
        f"{[d for d in flat if 'yaml' in d]}"
    )


def test_python_renderer_imports_and_falls_back_without_pygments() -> None:
    """Blocking Pygments must still allow PySH import and plain-text rendering."""
    code = (
        "import sys; "
        "sys.modules['pygments'] = None; "
        "import pysh; "
        "from pysh.python_layer.highlighting import PythonSyntaxRenderer, pygments_available; "
        "assert pygments_available() is False; "
        "assert PythonSyntaxRenderer(force_color=True).render_code('print(1)') == 'print(1)'; "
        "print('no-pygments-import-ok')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, (
        f"no-Pygments fallback subprocess failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert result.stdout.strip() == "no-pygments-import-ok"


def test_changelog_has_current_version_section() -> None:
    """CHANGELOG.md must contain a section for the current release."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"## {CURRENT_VERSION}" in text, (
        f"CHANGELOG.md must contain a '## {CURRENT_VERSION}' section"
    )


def test_changelog_080_section_covers_mandatory_features() -> None:
    """The historical 0.8.0 section must permanently document its mandatory scope.

    Pinned to the literal '0.8.0' — decoupled from CURRENT_VERSION so a later
    release bump cannot demand 0.8.0-specific content inside a newer section.
    """
    text = CHANGELOG.read_text(encoding="utf-8")

    start = text.find("## 0.8.0")
    assert start != -1, "CHANGELOG.md missing ## 0.8.0 section"

    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    section = rest[:nxt] if nxt != -1 else rest

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
    assert not missing, "CHANGELOG 0.8.0 section missing: " + ", ".join(missing)


def test_changelog_081_section_covers_hotfix_scope() -> None:
    """The historical 0.8.1 section must document the runtime/paste hotfix scope."""
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.find("## 0.8.1")
    assert start != -1, "CHANGELOG.md missing ## 0.8.1 section"
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    section = rest[:nxt] if nxt != -1 else rest

    required_phrases = ("stdlib-only", "Pygments", "optional", "PyYAML", "drift")
    missing = [p for p in required_phrases if p.lower() not in section.lower()]
    assert not missing, "CHANGELOG 0.8.1 section missing: " + ", ".join(missing)


def test_changelog_v082_release_covers_metadata_hotfix_scope() -> None:
    """The historical 0.8.2 section must document its metadata hotfix scope.

    This is a fixed historical contract, deliberately anchored to the
    literal ``## 0.8.2`` heading rather than ``CURRENT_VERSION``: 0.8.2 was
    a metadata-only hotfix release, and that scope does not move forward
    when the current release advances (Issue #33 RQG-E version
    finalization). Anchoring this to ``CURRENT_VERSION`` would silently
    start asserting 0.8.2-specific phrases against a later release's
    section once the version bumps, which is not what this test is for.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.find("## 0.8.2")
    assert start != -1, "CHANGELOG.md missing ## 0.8.2 section"
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    section = rest[:nxt] if nxt != -1 else rest

    required_phrases = (
        "metadata hotfix",
        "author email",
        "Karol Sobolewski",
        "No runtime behavior changes",
        "No dependency changes",
    )
    missing = [p for p in required_phrases if p.lower() not in section.lower()]
    assert not missing, "CHANGELOG 0.8.2 section missing: " + ", ".join(missing)


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


def test_docs_freebsd_pkg_is_mandatory_for_current_release() -> None:
    """Docs must describe FreeBSD .pkg as mandatory/current for this release."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")
    installation_doc = (DOCS / "user" / "installation.md").read_text(encoding="utf-8")

    assert f"FreeBSD validation and package build for v{CURRENT_VERSION}" in packaging_doc
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

    assert (
        f"FreeBSD `.pkg` packaging is current mandatory v{CURRENT_VERSION} release work"
        in combined
    )
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

    # Initial preserve must happen before step [1/12] (ruff check) so that the
    # pytest suite cannot delete the .pkg before it is saved to a temp file.
    ruff_idx = quality_gate.index("ruff check src tests")
    assert preserve_idx < ruff_idx, (
        "preserve_freebsd_pkg must be called before step [1/12] ruff check src tests"
    )

    # restore_freebsd_pkg must be called immediately after rm -rf dist
    restore_after_clean_idx = quality_gate.index("\nrestore_freebsd_pkg\n", clean_idx)
    assert clean_idx < restore_after_clean_idx < build_idx, (
        "restore_freebsd_pkg must be called immediately after rm -rf dist"
    )

    # restore_freebsd_pkg must also be called a second time immediately before
    # build_release_artifacts.sh (redundant guard in case TMPDIR setup intervenes)
    final_restore_idx = quality_gate.rindex("\nrestore_freebsd_pkg\n", 0, build_idx)
    assert final_restore_idx > restore_after_clean_idx, (
        "a second restore_freebsd_pkg call must appear immediately before build_release_artifacts.sh"
    )

    # Non-FreeBSD must hard-fail with a clear message if the .pkg is absent or empty
    assert '! -s "${FREEBSD_PKG_PATH}"' in quality_gate, (
        "check_release_quality.sh must guard [ ! -s FREEBSD_PKG_PATH ] before build_release_artifacts.sh"
    )
    assert "prebuilt FreeBSD .pkg is required before build_release_artifacts.sh" in quality_gate, (
        "check_release_quality.sh must emit a hard-fail message when the prebuilt .pkg is missing"
    )


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


# ---------------------------------------------------------------------------
# FreeBSD .pkg preservation chain — regression guard for the v0.8.0 gate
# ---------------------------------------------------------------------------


def test_build_release_artifacts_preserves_and_restores_freebsd_pkg_redundantly() -> None:
    """build_release_artifacts.sh must preserve the prebuilt .pkg and restore it at multiple
    points so that no individual build sub-script can cause it to go missing.

    Regression guard: build_pysh_package.sh runs 'rm -rf dist', which removes
    dist/os/freebsd/*.pkg.  A single restore call after that script is not
    sufficient if build_deb.sh or build_rpm.sh also clean dist/.  Redundant
    restore calls after every build sub-script and immediately before
    check_release_artifacts.sh make the pipeline robust regardless of which
    sub-script cleans dist/.
    """
    script = (REPO_ROOT / "scripts" / "build_release_artifacts.sh").read_text(encoding="utf-8")

    # --- preserve block at script start ---
    assert 'PRESERVED_FREEBSD_PKG="$(mktemp' in script
    assert 'cp "${FREEBSD_PKG_PATH}" "${PRESERVED_FREEBSD_PKG}"' in script
    assert "Preserved prebuilt FreeBSD .pkg" in script

    # --- restore_freebsd_pkg function logs when it restores ---
    assert "restore_freebsd_pkg()" in script
    assert 'cp "${PRESERVED_FREEBSD_PKG}" "${FREEBSD_PKG_PATH}"' in script
    assert "Restored prebuilt FreeBSD .pkg" in script

    # --- restore order: after build_pysh_package.sh, after build_deb.sh,
    #     after build_rpm.sh, and immediately before check_release_artifacts.sh ---
    pysh_pkg_idx = script.index("build_pysh_package.sh")
    restore_after_pysh = script.index("restore_freebsd_pkg", pysh_pkg_idx)

    deb_idx = script.index("build_deb.sh")
    restore_after_deb = script.index("restore_freebsd_pkg", deb_idx)
    assert restore_after_pysh < deb_idx < restore_after_deb, (
        "restore_freebsd_pkg must appear after build_deb.sh"
    )

    rpm_idx = script.index("build_rpm.sh")
    restore_after_rpm = script.index("restore_freebsd_pkg", rpm_idx)
    assert restore_after_deb < rpm_idx < restore_after_rpm, (
        "restore_freebsd_pkg must appear after build_rpm.sh"
    )

    check_artifacts_idx = script.index("check_release_artifacts.sh")
    restore_before_check = script.rindex("restore_freebsd_pkg", 0, check_artifacts_idx)
    assert restore_after_rpm < restore_before_check < check_artifacts_idx, (
        "restore_freebsd_pkg must appear immediately before check_release_artifacts.sh"
    )

    # --- missing .pkg on non-FreeBSD must be a hard release-blocking failure ---
    mandatory_idx = script.index("FreeBSD .pkg is mandatory")
    assert "exit 1" in script[mandatory_idx:mandatory_idx + 300], (
        "Missing FreeBSD .pkg must cause exit 1, not silent continuation"
    )


def test_check_release_quality_logs_freebsd_pkg_preserve_and_restore() -> None:
    """Quality gate must emit log lines when it preserves and restores the prebuilt .pkg."""
    script = (REPO_ROOT / "scripts" / "check_release_quality.sh").read_text(encoding="utf-8")

    assert "Preserved prebuilt FreeBSD .pkg" in script, (
        "check_release_quality.sh must log when it preserves the prebuilt FreeBSD .pkg"
    )
    assert "Restored prebuilt FreeBSD .pkg" in script, (
        "check_release_quality.sh must log when it restores the prebuilt FreeBSD .pkg"
    )


# ---------------------------------------------------------------------------
# Issue #34 — public user manual completeness
# ---------------------------------------------------------------------------


def test_issue_34_user_manual_required_documents_are_present_and_indexed() -> None:
    """Issue #34 public-manual deliverables must remain present and discoverable."""
    required = (
        DOCS / "user" / "troubleshooting.md",
        DOCS / "user" / "project-philosophy.md",
        DOCS / "user" / "manual-validation.md",
        DOCS / "development" / "release-notes-template.md",
    )
    for path in required:
        assert path.is_file(), f"missing Issue #34 documentation: {path}"

    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for name in (
        "troubleshooting.md",
        "project-philosophy.md",
        "manual-validation.md",
        "release-notes-template.md",
    ):
        assert name in index, f"docs/README.md must index {name}"


def test_issue_34_fish_migration_and_manual_evidence_contract() -> None:
    """Issue #34 must retain Fish migration guidance and the final evidence checklist."""
    migration = (DOCS / "migration" / "migration.md").read_text(encoding="utf-8")
    assert "## Migrating from Fish" in migration
    assert "does not currently provide a `source_fish` importer" in migration
    assert "fish ./legacy-script.fish" in migration

    philosophy = (DOCS / "user" / "project-philosophy.md").read_text(encoding="utf-8")
    assert "# Project Philosophy" in philosophy
    assert "Python-first" in philosophy
    assert "Explicit compatibility boundaries" in philosophy

    checklist = (DOCS / "user" / "manual-validation.md").read_text(encoding="utf-8")
    for required in (
        "## Fresh virtual environment",
        "## Package install",
        "## First interactive run",
        "## Configuration generation and preservation",
        "## Basic command session",
        "## PySH 0.9.0 evidence record",
    ):
        assert required in checklist

    release_template = (
        DOCS / "development" / "release-notes-template.md"
    ).read_text(encoding="utf-8")
    assert "# Release Notes Template" in release_template
    assert "## Validation evidence" in release_template
    assert "## Known limitations" in release_template


# ---------------------------------------------------------------------------
# Issue #46 — architecture policy/documentation consistency
# ---------------------------------------------------------------------------


def test_issue_46_layering_policy_is_normative_and_indexed() -> None:
    """The machine policy and normative layer document must be discoverable."""
    assert ARCHITECTURE_POLICY.is_file()
    assert LAYERING_DOC.is_file()

    index = (DOCS / "README.md").read_text(encoding="utf-8")
    architecture = (DOCS / "architecture" / "architecture.md").read_text(
        encoding="utf-8"
    )
    source_tree = (DOCS / "architecture" / "source-tree.md").read_text(
        encoding="utf-8"
    )
    assert "[layering.md](architecture/layering.md)" in index
    assert "[layering.md](layering.md)" in architecture
    assert "[layering.md](layering.md)" in source_tree
    assert "architecture.toml" in architecture
    assert "architecture.toml" in source_tree


def test_issue_46_layering_document_covers_policy_domains_and_exceptions() -> None:
    """Every machine-owned domain and debt edge must appear in normative prose."""
    with ARCHITECTURE_POLICY.open("rb") as stream:
        policy = tomllib.load(stream)
    layering = LAYERING_DOC.read_text(encoding="utf-8")

    for domain in policy["domains"]:
        assert f"`{domain['module']}`" in layering
    for exception in policy["exceptions"]:
        assert f"`{exception['importer']}`" in layering
        assert f"`{exception['imported']}`" in layering
        assert exception["cleanup_issue"] in layering

    assert "boundary freeze, not implementation freeze" in layering
    assert "Private helper" in layering
    assert "ordinary `pytest -q` step" in layering


def test_issue_46_related_contracts_reference_layering_owner() -> None:
    """API and both plugin contracts must point to the same ownership model."""
    api_stability = (DOCS / "development" / "api-stability.md").read_text(
        encoding="utf-8"
    )
    plugin_api = (DOCS / "plugins" / "plugin-api.md").read_text(encoding="utf-8")
    isolation = (DOCS / "security" / "plugin-isolation.md").read_text(
        encoding="utf-8"
    )
    roadmap = (DOCS / "roadmap" / "ROADMAP-v1-2.md").read_text(encoding="utf-8")

    for text in (api_stability, plugin_api, isolation, roadmap):
        assert "layering.md" in text
    assert "architecture.toml" in api_stability
    assert "core-to-extension integration boundary" in isolation
    assert "pysh.plugins.isolated" in isolation
