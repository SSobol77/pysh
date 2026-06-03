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
