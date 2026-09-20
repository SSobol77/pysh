#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/release_gate.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Release Quality Gate 2.0 orchestrator (Issue #33 RQG-H).

The maintainer-facing answer to "is this PySH release candidate ready from
the currently available environment?" This module invokes the existing,
independently-maintained release checks (RQG-A through RQG-G) as
subprocesses and produces one deterministic PASS/FAIL/NOT_RUN/
PLATFORM_BLOCKED manifest. It never reimplements any check's validation
logic -- version/metadata/artifact/workflow/changelog/tag rules all live
exclusively in the scripts it calls.

This orchestrator never publishes, uploads, tags, pushes, or mutates the
version/changelog: every check it runs is a read-only validation, and it
performs no git or network write operation of its own.

Usage:
    uv run python scripts/release_gate.py --mode fast
    uv run python scripts/release_gate.py --mode ci
    uv run python scripts/release_gate.py --mode full
    uv run python scripts/release_gate.py --mode full --json /tmp/gate.json

Exit codes:
    0  overall PASS or READY_EXCEPT_PLATFORM_VALIDATION
    1  overall FAIL
    2  orchestrator misuse (bad arguments)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MODES = ("fast", "ci", "full")

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_PLATFORM_BLOCKED = "PLATFORM_BLOCKED"

OVERALL_PASS = "PASS"
OVERALL_FAIL = "FAIL"
OVERALL_READY_EXCEPT_PLATFORM = "READY_EXCEPT_PLATFORM_VALIDATION"

EXIT_CODE_BY_OVERALL = {
    OVERALL_PASS: 0,
    OVERALL_READY_EXCEPT_PLATFORM: 0,
    OVERALL_FAIL: 1,
}
MISUSE_EXIT_CODE = 2


@dataclasses.dataclass
class CheckResult:
    status: str
    exit_code: int | None = None
    duration_seconds: float = 0.0
    diagnostic: str = ""
    log_path: str | None = None


@dataclasses.dataclass
class Check:
    name: str
    category: str
    modes: frozenset[str]
    run: Callable[[Path], CheckResult]


# ------------------------------------------------------------- primitives


def _last_lines(text: str, count: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def run_subprocess_check(
    argv: list[str],
    *,
    log_dir: Path,
    log_name: str,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    timeout: float = 600.0,
) -> CheckResult:
    """Run *argv*, capturing status/exit_code/duration/diagnostic/log_path.

    A timeout or an inability to even start the subprocess is captured as
    FAIL with a diagnostic -- never an unhandled traceback.
    """
    start = time.monotonic()
    log_path = log_dir / f"{log_name}.log"
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        output = (exc.stdout or "") + (exc.stderr or "")
        log_path.write_text(output, encoding="utf-8")
        return CheckResult(
            status=STATUS_FAIL,
            exit_code=None,
            duration_seconds=duration,
            diagnostic=f"timed out after {timeout:.0f}s",
            log_path=str(log_path),
        )
    except OSError as exc:
        duration = time.monotonic() - start
        return CheckResult(
            status=STATUS_FAIL,
            exit_code=None,
            duration_seconds=duration,
            diagnostic=f"failed to start: {exc}",
            log_path=None,
        )
    duration = time.monotonic() - start
    output = result.stdout + result.stderr
    log_path.write_text(output, encoding="utf-8")
    status = STATUS_PASS if result.returncode == 0 else STATUS_FAIL
    diagnostic = "" if status == STATUS_PASS else _last_lines(output, 6)
    return CheckResult(
        status=status,
        exit_code=result.returncode,
        duration_seconds=duration,
        diagnostic=diagnostic,
        log_path=str(log_path),
    )


def docker_usable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], check=False, capture_output=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def canonical_version() -> str:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return pyproject["project"]["version"]


# ----------------------------------------------------------------- checks
#
# Every check below shells out to an existing, independently-tested
# script/tool (RQG-A through RQG-G, plus ruff/pytest/git). None of them
# reimplements version, metadata, artifact-naming, changelog, or workflow
# validation logic -- this module only sequences and reports.


def check_metadata_contract(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        ["bash", str(REPO_ROOT / "scripts" / "check_release_metadata.sh")],
        log_dir=log_dir,
        log_name="metadata-contract",
    )


def check_ruff(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        ["uv", "run", "ruff", "check", "src", "tests"],
        log_dir=log_dir,
        log_name="ruff",
    )


def check_headers(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        ["bash", str(REPO_ROOT / "scripts" / "check_headers.sh")],
        log_dir=log_dir,
        log_name="headers",
    )


def check_git_diff(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        ["git", "diff", "--check"], log_dir=log_dir, log_name="git-diff"
    )


def check_installation_docs(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        [
            "uv",
            "run",
            "python",
            str(REPO_ROOT / "scripts" / "check_installation_docs.py"),
            "--skip-portable",
        ],
        log_dir=log_dir,
        log_name="installation-docs",
    )


def check_release_workflow(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        [
            "uv",
            "run",
            "python",
            str(REPO_ROOT / "scripts" / "check_release_workflow.py"),
        ],
        log_dir=log_dir,
        log_name="release-workflow",
    )


def check_pytest(log_dir: Path) -> CheckResult:
    return run_subprocess_check(
        ["uv", "run", "pytest", "-q"], log_dir=log_dir, log_name="pytest", timeout=900.0
    )


def _check_pty(term: str, log_dir: Path) -> CheckResult:
    env = {**os.environ, "TERM": term}
    return run_subprocess_check(
        ["uv", "run", "pytest", "-q", "tests/test_pty_integration.py"],
        env=env,
        log_dir=log_dir,
        log_name=f"pty-term-{term}",
        timeout=400.0,
    )


def check_pty_dumb(log_dir: Path) -> CheckResult:
    return _check_pty("dumb", log_dir)


def check_pty_xterm(log_dir: Path) -> CheckResult:
    return _check_pty("xterm-256color", log_dir)


def check_artifact_contract(log_dir: Path) -> CheckResult:
    """Build real wheel/sdist/deb/rpm + one labeled FreeBSD fixture, contract-only.

    Mirrors ci.yml's own "Verify artifact contract" step exactly: only the
    FreeBSD .pkg (which cannot be produced on this host) is a clearly
    labeled, non-empty fixture. Reuses build_pysh_package.sh/build_deb.sh/
    build_rpm.sh/check_release_artifacts.sh unchanged.
    """
    start = time.monotonic()
    log_path = log_dir / "artifact-contract.log"
    output_parts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pysh-release-gate-artifacts-") as tmp:
        contract_dir = Path(tmp)
        (contract_dir / "os" / "deb").mkdir(parents=True)
        (contract_dir / "os" / "rpm").mkdir(parents=True)
        (contract_dir / "os" / "freebsd").mkdir(parents=True)

        steps = [
            ["uv", "run", "--with", "build", "python", "-m", "build"],
            ["bash", str(REPO_ROOT / "scripts" / "build_deb.sh")],
            ["bash", str(REPO_ROOT / "scripts" / "build_rpm.sh")],
        ]
        for step in steps:
            result = subprocess.run(
                step,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            output_parts.append(f"$ {' '.join(step)}\n{result.stdout}{result.stderr}")
            if result.returncode != 0:
                duration = time.monotonic() - start
                log_path.write_text("\n".join(output_parts), encoding="utf-8")
                return CheckResult(
                    status=STATUS_FAIL,
                    exit_code=result.returncode,
                    duration_seconds=duration,
                    diagnostic=_last_lines(result.stdout + result.stderr, 6),
                    log_path=str(log_path),
                )

        try:
            wheel = next((REPO_ROOT / "dist").glob("*.whl"))
            sdist = next((REPO_ROOT / "dist").glob("*.tar.gz"))
            deb = next((REPO_ROOT / "dist" / "os" / "deb").glob("*.deb"))
            rpm = next((REPO_ROOT / "dist" / "os" / "rpm").glob("*.rpm"))
        except StopIteration:
            duration = time.monotonic() - start
            log_path.write_text("\n".join(output_parts), encoding="utf-8")
            return CheckResult(
                status=STATUS_FAIL,
                duration_seconds=duration,
                diagnostic="expected build artifacts were not produced",
                log_path=str(log_path),
            )

        shutil.copy(wheel, contract_dir / wheel.name)
        shutil.copy(sdist, contract_dir / sdist.name)
        shutil.copy(deb, contract_dir / "os" / "deb" / deb.name)
        shutil.copy(rpm, contract_dir / "os" / "rpm" / rpm.name)

        version = canonical_version()
        fixture_pkg = contract_dir / "os" / "freebsd" / f"pysh-shell-{version}.pkg"
        fixture_pkg.write_text(
            "PYSH ARTIFACT-CONTRACT TEST FIXTURE - NOT A REAL FREEBSD PACKAGE.\n"
            "Real FreeBSD .pkg validation runs in "
            ".github/workflows/release-artifacts.yml via a FreeBSD 14+ VM build.\n",
            encoding="utf-8",
        )

        artifact_result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "check_release_artifacts.sh"),
                "--contract-only",
                str(contract_dir),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output_parts.append(
            "$ check_release_artifacts.sh --contract-only <dir>\n"
            f"{artifact_result.stdout}{artifact_result.stderr}"
        )

    duration = time.monotonic() - start
    log_path.write_text("\n".join(output_parts), encoding="utf-8")
    status = STATUS_PASS if artifact_result.returncode == 0 else STATUS_FAIL
    diagnostic = (
        ""
        if status == STATUS_PASS
        else _last_lines(artifact_result.stdout + artifact_result.stderr, 6)
    )
    return CheckResult(
        status=status,
        exit_code=artifact_result.returncode,
        duration_seconds=duration,
        diagnostic=diagnostic,
        log_path=str(log_path),
    )


def check_debian_smoke(log_dir: Path) -> CheckResult:
    """Real Debian install-and-run smoke, reusing scripts/smoke_debian_package.sh.

    Docker unavailability is an environment capability gap, not a product
    defect: it is reported as PLATFORM_BLOCKED, never FAIL or PASS.
    """
    if not docker_usable():
        return CheckResult(
            status=STATUS_PLATFORM_BLOCKED,
            diagnostic="Docker is not installed or the daemon is not reachable",
        )

    start = time.monotonic()
    build = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "build_deb.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if build.returncode != 0:
        duration = time.monotonic() - start
        log_path = log_dir / "debian-smoke.log"
        log_path.write_text(build.stdout + build.stderr, encoding="utf-8")
        return CheckResult(
            status=STATUS_FAIL,
            exit_code=build.returncode,
            duration_seconds=duration,
            diagnostic=_last_lines(build.stdout + build.stderr, 6),
            log_path=str(log_path),
        )

    debs = sorted((REPO_ROOT / "dist" / "os" / "deb").glob("*.deb"))
    if not debs:
        duration = time.monotonic() - start
        return CheckResult(
            status=STATUS_FAIL,
            duration_seconds=duration,
            diagnostic="build_deb.sh did not produce a .deb",
        )

    return run_subprocess_check(
        ["bash", str(REPO_ROOT / "scripts" / "smoke_debian_package.sh"), str(debs[-1])],
        log_dir=log_dir,
        log_name="debian-smoke",
        timeout=180.0,
    )


def check_rpm_smoke(log_dir: Path) -> CheckResult:
    """Real RPM install-and-run smoke, reusing scripts/smoke_rpm_package.sh.

    Docker unavailability is an environment capability gap, not a product
    defect: it is reported as PLATFORM_BLOCKED, never FAIL or a faked PASS.
    A successful `build_rpm.sh` run is never treated as sufficient by
    itself -- this check always attempts the real install, exactly like
    check_debian_smoke.
    """
    if not docker_usable():
        return CheckResult(
            status=STATUS_PLATFORM_BLOCKED,
            diagnostic="Docker is not installed or the daemon is not reachable",
        )

    start = time.monotonic()
    build = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "build_rpm.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if build.returncode != 0:
        duration = time.monotonic() - start
        log_path = log_dir / "rpm-smoke.log"
        log_path.write_text(build.stdout + build.stderr, encoding="utf-8")
        return CheckResult(
            status=STATUS_FAIL,
            exit_code=build.returncode,
            duration_seconds=duration,
            diagnostic=_last_lines(build.stdout + build.stderr, 6),
            log_path=str(log_path),
        )

    rpms = sorted((REPO_ROOT / "dist" / "os" / "rpm").glob("*.rpm"))
    if not rpms:
        duration = time.monotonic() - start
        return CheckResult(
            status=STATUS_FAIL,
            duration_seconds=duration,
            diagnostic="build_rpm.sh did not produce a .rpm",
        )

    # 1800s, not 600s: measured directly (see tests/test_rpm_package_smoke_
    # contract.py), real end-to-end durations for this same script ranged
    # from ~5 to ~19.5 minutes across repeated runs, purely from Fedora
    # mirror/dnf and Docker image-pull variability. 600s was observed to
    # both time out outright and pass with under 10% margin on separate
    # occasions -- genuinely too tight, not merely flaky.
    return run_subprocess_check(
        ["bash", str(REPO_ROOT / "scripts" / "smoke_rpm_package.sh"), str(rpms[-1])],
        log_dir=log_dir,
        log_name="rpm-smoke",
        timeout=1800.0,
    )


def check_freebsd_smoke(log_dir: Path) -> CheckResult:
    """Real FreeBSD install-and-run smoke, reusing scripts/smoke_freebsd_package.sh.

    FreeBSD's native .pkg format and pkg(8) tooling only exist on FreeBSD
    itself -- there is no daemon-reachability capability probe the way
    Docker has one for check_debian_smoke: the host either IS FreeBSD or
    it isn't. On any other host this is an environment capability gap, not
    a product defect, and is reported as PLATFORM_BLOCKED, never a faked
    PASS. The real build-install-query-execute lifecycle also runs,
    unconditionally, inside .github/workflows/release-artifacts.yml's
    FreeBSD 14.4 VM job via this same script.
    """
    if platform.system() != "FreeBSD":
        return CheckResult(
            status=STATUS_PLATFORM_BLOCKED,
            diagnostic=(
                f"this host is {platform.system()}, not FreeBSD; native FreeBSD "
                ".pkg install/run smoke requires real FreeBSD 14+ and has no "
                "container/emulation fallback. The real smoke runs "
                "unconditionally in .github/workflows/release-artifacts.yml's "
                "FreeBSD 14.4 VM job via scripts/smoke_freebsd_package.sh."
            ),
        )

    start = time.monotonic()
    build = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "build_freebsd_pkg.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if build.returncode != 0:
        duration = time.monotonic() - start
        log_path = log_dir / "freebsd-smoke.log"
        log_path.write_text(build.stdout + build.stderr, encoding="utf-8")
        return CheckResult(
            status=STATUS_FAIL,
            exit_code=build.returncode,
            duration_seconds=duration,
            diagnostic=_last_lines(build.stdout + build.stderr, 6),
            log_path=str(log_path),
        )

    pkgs = sorted((REPO_ROOT / "dist" / "os" / "freebsd").glob("*.pkg"))
    if not pkgs:
        duration = time.monotonic() - start
        return CheckResult(
            status=STATUS_FAIL,
            duration_seconds=duration,
            diagnostic="build_freebsd_pkg.sh did not produce a .pkg",
        )

    return run_subprocess_check(
        ["sh", str(REPO_ROOT / "scripts" / "smoke_freebsd_package.sh"), str(pkgs[-1])],
        log_dir=log_dir,
        log_name="freebsd-smoke",
        timeout=180.0,
    )


# ------------------------------------------------------------- registry


def build_checks() -> list[Check]:
    fast_ci_full = frozenset({"fast", "ci", "full"})
    ci_full = frozenset({"ci", "full"})
    full_only = frozenset({"full"})
    return [
        Check("metadata contract", "metadata", fast_ci_full, check_metadata_contract),
        Check("Ruff", "static", fast_ci_full, check_ruff),
        Check("headers", "static", fast_ci_full, check_headers),
        Check("git diff", "static", fast_ci_full, check_git_diff),
        Check(
            "installation-doc contract", "docs", fast_ci_full, check_installation_docs
        ),
        Check(
            "release workflow contract",
            "workflow",
            fast_ci_full,
            check_release_workflow,
        ),
        Check("unit/integration tests", "tests", ci_full, check_pytest),
        Check("PTY TERM=dumb", "tests", ci_full, check_pty_dumb),
        Check("PTY TERM=xterm-256color", "tests", ci_full, check_pty_xterm),
        Check("artifact contract", "artifacts", ci_full, check_artifact_contract),
        Check("Debian install smoke", "platform", full_only, check_debian_smoke),
        Check("RPM install smoke", "platform", full_only, check_rpm_smoke),
        Check("FreeBSD install smoke", "platform", full_only, check_freebsd_smoke),
    ]


# ----------------------------------------------------------------- gate


def derive_overall(statuses: list[str]) -> str:
    if STATUS_FAIL in statuses:
        return OVERALL_FAIL
    if STATUS_PLATFORM_BLOCKED in statuses:
        return OVERALL_READY_EXCEPT_PLATFORM
    return OVERALL_PASS


def run_gate(
    mode: str,
    checks: list[Check],
    log_dir: Path,
    *,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, object]:
    """Run every check applicable to *mode*; independent later checks still
    run after an earlier failure (no check depends on another's success --
    this orchestrator performs no destructive/release step, so there is
    nothing "unsafe" to guard by stopping early).

    *on_progress*, if given, is called as ``on_progress(check_name,
    "start" | status)`` so a caller can print live progress for long runs
    without that noise being part of the returned manifest.
    """
    entries: list[dict[str, object]] = []
    for check in checks:
        if mode not in check.modes:
            entries.append(
                {
                    "name": check.name,
                    "category": check.category,
                    "status": STATUS_NOT_RUN,
                    "exit_code": None,
                    "duration_seconds": 0.0,
                    "diagnostic": "",
                    "log_path": None,
                }
            )
            continue
        if on_progress is not None:
            on_progress(check.name, "start")
        result = check.run(log_dir)
        if on_progress is not None:
            on_progress(check.name, result.status)
        entries.append(
            {
                "name": check.name,
                "category": check.category,
                "status": result.status,
                "exit_code": result.exit_code,
                "duration_seconds": round(result.duration_seconds, 3),
                "diagnostic": result.diagnostic,
                "log_path": result.log_path,
            }
        )

    executed_statuses = [
        e["status"] for e in entries if e["status"] != STATUS_NOT_RUN  # type: ignore[comparison-overlap]
    ]
    overall = derive_overall([str(s) for s in executed_statuses])
    return {
        "mode": mode,
        "overall": overall,
        "exit_code": EXIT_CODE_BY_OVERALL[overall],
        "host": platform.platform(),
        "log_dir": str(log_dir),
        "checks": entries,
    }


# ----------------------------------------------------------------- report


def render_human_manifest(manifest: dict[str, object]) -> str:
    lines = ["Release Quality Gate 2.0", "========================", ""]
    for entry in manifest["checks"]:  # type: ignore[union-attr]
        status = entry["status"]
        label = {
            STATUS_PASS: "PASS",
            STATUS_FAIL: "FAIL",
            STATUS_NOT_RUN: "NOT RUN",
            STATUS_PLATFORM_BLOCKED: "PLATFORM BLOCKED",
        }[status]
        lines.append(f"[{label}] {entry['name']}")
        if status in (STATUS_FAIL, STATUS_PLATFORM_BLOCKED) and entry.get("diagnostic"):
            for diag_line in str(entry["diagnostic"]).splitlines():
                lines.append(f"    {diag_line}")
            if entry.get("log_path"):
                lines.append(f"    log: {entry['log_path']}")
    lines.append("")
    lines.append(f"Overall: {manifest['overall']}")
    return "\n".join(lines)


# ------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="fast")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        metavar="PATH",
        help="also write a JSON manifest",
    )
    parser.add_argument(
        "--keep-logs",
        type=Path,
        default=None,
        metavar="DIR",
        help="persist sub-check logs here instead of a disposable temp directory",
    )
    args = parser.parse_args(argv)

    if args.mode not in MODES:
        print(f"release_gate.py: invalid mode: {args.mode!r}", file=sys.stderr)
        return MISUSE_EXIT_CODE

    checks = build_checks()

    # Logs default to a disposable-looking temp directory (never inside the
    # repository), but are deliberately NOT auto-deleted when this process
    # exits: a FAIL/PLATFORM_BLOCKED entry's log_path must still be openable
    # after the manifest is printed. --keep-logs points this at a specific,
    # more permanent location instead of a randomly named one.
    if args.keep_logs is not None:
        log_dir = args.keep_logs
        log_dir.mkdir(parents=True, exist_ok=True)
    else:
        log_dir = Path(tempfile.mkdtemp(prefix="pysh-release-gate-logs-"))

    def _report_progress(name: str, event: str) -> None:
        if event == "start":
            print(f"==> running: {name}...", file=sys.stderr, flush=True)
        else:
            print(f"==> {event}: {name}", file=sys.stderr, flush=True)

    manifest = run_gate(args.mode, checks, log_dir, on_progress=_report_progress)
    print(render_human_manifest(manifest))
    if args.json is not None:
        args.json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return int(manifest["exit_code"])  # type: ignore[arg-type]


if __name__ == "__main__":
    raise SystemExit(main())
