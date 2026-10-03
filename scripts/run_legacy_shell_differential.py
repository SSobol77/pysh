#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/run_legacy_shell_differential.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Run the Tier-1 legacy-shell differential evidence laboratory (Issue #54).

Bash, Zsh and Fish are CI/test equipment only: this script never runs in the
shell runtime and PySH does not depend on them. For the current platform it
verifies each configured reference profile (version drift, startup isolation),
observes the selected #48 cases under PySH first and then under each reference,
classifies them (MATCH / INTENDED_DIVERGENCE / REGRESSION) and writes a
deterministic evidence document.

Exit codes: 0 no problem, 1 classification problem (a REGRESSION, an unreviewed
state for a pinned profile, or with --strict any unreviewed difference), 3
infrastructure problem (missing required shell, version drift, failed isolation,
no profile for the platform), 2 usage error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

EXIT_OK, EXIT_CLASSIFICATION, EXIT_USAGE, EXIT_INFRASTRUCTURE = 0, 1, 2, 3
INFRASTRUCTURE_MARKERS = (
    "version drift", "startup isolation failed", "is not installed", "no legacy reference profiles",
    "cannot read the version", "cannot execute", "executable not found",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--require-all", action="store_true",
                        help="a configured reference shell that is not installed is a failure")
    parser.add_argument("--strict", action="store_true",
                        help="any unreviewed difference between PySH and a reference is a failure")
    parser.add_argument("--evidence-dir", metavar="DIR", help="write the evidence JSON here")
    args = parser.parse_args(argv)

    from tests.differential import reference

    commit = os.environ.get("GITHUB_SHA")
    target = Path(args.evidence_dir) if args.evidence_dir else None

    def write(document: dict[str, object]) -> None:
        if target is None:
            return
        target.mkdir(parents=True, exist_ok=True)
        (target / f"legacy-shell-differential-{document['platform']}.json").write_text(
            reference.canonical_json(document), encoding="utf-8"
        )

    # The evidence file is rewritten as the run progresses, so the profile/version
    # discovery is on disk before any semantic step (or crash) can lose it.
    document, problems = reference.run_lab(
        require_all=args.require_all, strict=args.strict, commit=commit, progress=write
    )
    write(document)
    platform_id = str(document["platform"])
    print(f"legacy-shell differential evidence: platform={platform_id} pysh={document['pysh_version']}")
    for profile in document["profiles"]:
        records = profile["records"]
        counts: dict[str, int] = {}
        for record in records:
            counts[record["classification"]] = counts.get(record["classification"], 0) + 1
        state = profile["skipped_reason"] or f"{profile['observed_version']}"
        print(f"  {profile['profile_id']} [{profile['version_status']}] {state}")
        if profile["version_status"] == "pending" and profile["observed_version"]:
            print(f"    pin proposal: version={profile['observed_version']!r} "
                  f"package_version={profile['observed_package_version']!r}")
        print(f"    cases={len(records)} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if not problems:
        print("legacy-shell differential: OK")
        return EXIT_OK
    infrastructure = any(marker in p for p in problems for marker in INFRASTRUCTURE_MARKERS)
    return EXIT_INFRASTRUCTURE if infrastructure else EXIT_CLASSIFICATION


if __name__ == "__main__":
    sys.exit(main())
