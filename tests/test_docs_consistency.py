# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository documentation consistency tests.

These checks are intentionally filesystem-only. They validate public Markdown
contracts without importing PySH runtime modules.
"""
from __future__ import annotations

import re
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
    """The release quality gate must require PyPI, Debian and RPM artifacts."""
    script = REPO_ROOT / "scripts" / "check_release_quality.sh"
    text = script.read_text(encoding="utf-8")

    assert "scripts/build_release_artifacts.sh" in text
    assert "scripts/check_release_artifacts.sh" in text
    assert "dist/*.whl" in text
    assert "dist/*.tar.gz" in text
    assert "dist/os/deb/pysh-shell_*-1_all.deb" in text
    assert "dist/os/rpm/pysh-shell-*-1.noarch.rpm" in text
    assert "dist/SHA256SUMS" in text


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
        assert "Issue #18" in text


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

CURRENT_VERSION = "0.7.0"
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


def test_changelog_v070_covers_mandatory_features() -> None:
    """CHANGELOG v0.7.0 section must document all mandatory v0.7.0 features."""
    text = CHANGELOG.read_text(encoding="utf-8")

    start = text.find(f"## {CURRENT_VERSION}")
    assert start != -1, f"CHANGELOG.md missing ## {CURRENT_VERSION} section"

    # Find end of the 0.7.0 section (next ## header or EOF).
    rest = text[start:]
    next_section = rest.find("\n## ", 1)
    section = rest[:next_section] if next_section != -1 else rest

    required_phrases = (
        "migrate",
        "migration",
        "zsh",
        "/bin/sh",
        "SHA256SUMS",
        "Issue #18",
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


def test_docs_freebsd_pkg_is_deferred() -> None:
    """Packaging and release docs must defer FreeBSD .pkg to Issue #18."""
    packaging_doc = (DOCS / "development" / "packaging.md").read_text(encoding="utf-8")
    release_doc = (DOCS / "development" / "release.md").read_text(encoding="utf-8")
    for name, text in (("packaging.md", packaging_doc), ("release.md", release_doc)):
        assert "FreeBSD" in text, f"{name} must mention FreeBSD .pkg deferral"
        assert "Issue #18" in text, f"{name} must reference Issue #18 for FreeBSD .pkg"
