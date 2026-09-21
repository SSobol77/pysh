#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/benchmark_performance.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Run the versioned PySH performance contract without third-party tools."""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPOSITORY_ROOT / "src"
DEFAULT_POLICY_PATH = REPOSITORY_ROOT / "performance.toml"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

EXPECTED_BENCHMARK_IDS = frozenset({
    "cold_start",
    "completion_core",
    "git_context",
    "keystroke_render",
    "prompt_render",
})
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class PolicyError(ValueError):
    """Raised when the performance policy is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class PlatformProfile:
    """One CI/runtime profile and its bounded infrastructure-noise margin."""

    identifier: str
    platform_system: str
    python_minor: str
    ci_margin_percent: float
    description: str


@dataclass(frozen=True, slots=True)
class BenchmarkContract:
    """One benchmark definition loaded from ``performance.toml``."""

    identifier: str
    unit: str
    budget: float
    sample_count: int
    warmup_count: int
    aggregation: str
    scope: str
    release_blocking: bool
    timeout_seconds: float
    platform_profiles: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    """Validated, versioned performance policy."""

    schema_version: int
    aggregation_method: str
    profiles: dict[str, PlatformProfile]
    benchmarks: tuple[BenchmarkContract, ...]

    @property
    def benchmarks_by_id(self) -> dict[str, BenchmarkContract]:
        """Return benchmark contracts keyed by their stable identifiers."""
        return {benchmark.identifier: benchmark for benchmark in self.benchmarks}


def _required_string(table: Mapping[str, object], key: str, owner: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{owner}.{key} must be a non-empty string")
    return value


def _required_number(table: Mapping[str, object], key: str, owner: str) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{owner}.{key} must be a number")
    numeric = float(value)
    if numeric <= 0:
        raise PolicyError(f"{owner}.{key} must be greater than zero")
    return numeric


def _required_integer(
    table: Mapping[str, object],
    key: str,
    owner: str,
    *,
    minimum: int,
) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PolicyError(f"{owner}.{key} must be an integer >= {minimum}")
    return value


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> PerformancePolicy:
    """Load and strictly validate the canonical performance policy."""
    with path.open("rb") as stream:
        raw = tomllib.load(stream)

    expected_top_level = {"schema_version", "aggregation_method", "profiles", "benchmarks"}
    unknown_top_level = set(raw) - expected_top_level
    if unknown_top_level:
        raise PolicyError(f"unknown top-level policy keys: {sorted(unknown_top_level)!r}")
    if raw.get("schema_version") != 1:
        raise PolicyError("performance policy schema_version must be 1")
    aggregation_method = _required_string(raw, "aggregation_method", "policy")
    if aggregation_method != "median":
        raise PolicyError("only median aggregation is supported")

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise PolicyError("policy.profiles must be a non-empty table")
    profiles: dict[str, PlatformProfile] = {}
    expected_profile_keys = {
        "platform_system",
        "python_minor",
        "ci_margin_percent",
        "description",
    }
    for identifier, value in raw_profiles.items():
        owner = f"profiles.{identifier}"
        if not isinstance(identifier, str) or not identifier:
            raise PolicyError("profile identifiers must be non-empty strings")
        if not isinstance(value, dict):
            raise PolicyError(f"{owner} must be a table")
        unknown = set(value) - expected_profile_keys
        if unknown:
            raise PolicyError(f"{owner} has unknown keys: {sorted(unknown)!r}")
        margin = _required_number(value, "ci_margin_percent", owner)
        if margin > 50:
            raise PolicyError(f"{owner}.ci_margin_percent must not exceed 50")
        profiles[identifier] = PlatformProfile(
            identifier=identifier,
            platform_system=_required_string(value, "platform_system", owner),
            python_minor=_required_string(value, "python_minor", owner),
            ci_margin_percent=margin,
            description=_required_string(value, "description", owner),
        )

    raw_benchmarks = raw.get("benchmarks")
    if not isinstance(raw_benchmarks, list) or not raw_benchmarks:
        raise PolicyError("policy.benchmarks must be a non-empty array of tables")
    expected_benchmark_keys = {
        "id",
        "unit",
        "budget",
        "sample_count",
        "warmup_count",
        "aggregation",
        "scope",
        "release_blocking",
        "timeout_seconds",
        "platform_profiles",
        "description",
    }
    benchmarks: list[BenchmarkContract] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(raw_benchmarks):
        owner = f"benchmarks[{index}]"
        if not isinstance(value, dict):
            raise PolicyError(f"{owner} must be a table")
        unknown = set(value) - expected_benchmark_keys
        if unknown:
            raise PolicyError(f"{owner} has unknown keys: {sorted(unknown)!r}")
        identifier = _required_string(value, "id", owner)
        if identifier in seen_ids:
            raise PolicyError(f"duplicate benchmark id: {identifier}")
        seen_ids.add(identifier)
        unit = _required_string(value, "unit", owner)
        if unit != "milliseconds":
            raise PolicyError(f"{owner}.unit must be 'milliseconds'")
        aggregation = _required_string(value, "aggregation", owner)
        if aggregation != aggregation_method:
            raise PolicyError(f"{owner}.aggregation must match policy aggregation")
        scope = _required_string(value, "scope", owner)
        if scope not in {"process", "in_process"}:
            raise PolicyError(f"{owner}.scope must be 'process' or 'in_process'")
        release_blocking = value.get("release_blocking")
        if not isinstance(release_blocking, bool):
            raise PolicyError(f"{owner}.release_blocking must be a boolean")
        raw_platforms = value.get("platform_profiles")
        if not isinstance(raw_platforms, list) or not raw_platforms or not all(
            isinstance(item, str) and item for item in raw_platforms
        ):
            raise PolicyError(f"{owner}.platform_profiles must be a non-empty string array")
        platform_profiles = tuple(raw_platforms)
        unknown_profiles = set(platform_profiles) - set(profiles)
        if unknown_profiles:
            raise PolicyError(
                f"{owner} references unknown profiles: {sorted(unknown_profiles)!r}"
            )
        sample_count = _required_integer(value, "sample_count", owner, minimum=5)
        if sample_count % 2 == 0:
            raise PolicyError(f"{owner}.sample_count must be odd for median aggregation")
        benchmarks.append(
            BenchmarkContract(
                identifier=identifier,
                unit=unit,
                budget=_required_number(value, "budget", owner),
                sample_count=sample_count,
                warmup_count=_required_integer(value, "warmup_count", owner, minimum=0),
                aggregation=aggregation,
                scope=scope,
                release_blocking=release_blocking,
                timeout_seconds=_required_number(value, "timeout_seconds", owner),
                platform_profiles=platform_profiles,
                description=_required_string(value, "description", owner),
            )
        )

    if seen_ids != EXPECTED_BENCHMARK_IDS:
        missing = EXPECTED_BENCHMARK_IDS - seen_ids
        unexpected = seen_ids - EXPECTED_BENCHMARK_IDS
        raise PolicyError(
            f"benchmark ids disagree with harness; missing={sorted(missing)!r}, "
            f"unexpected={sorted(unexpected)!r}"
        )
    return PerformancePolicy(1, aggregation_method, profiles, tuple(benchmarks))


def select_profile(policy: PerformancePolicy, requested: str) -> PlatformProfile:
    """Resolve an explicit profile or select one from platform and Python minor."""
    if requested != "auto":
        try:
            return policy.profiles[requested]
        except KeyError as error:
            raise PolicyError(f"unknown platform profile: {requested}") from error
    python_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    matches = [
        profile
        for profile in policy.profiles.values()
        if profile.platform_system == platform.system()
        and profile.python_minor == python_minor
    ]
    if len(matches) != 1:
        identifiers = sorted(profile.identifier for profile in matches)
        raise PolicyError(
            "automatic profile selection requires exactly one match; "
            f"matched={identifiers!r}"
        )
    return matches[0]


def aggregate_samples(samples: Sequence[float], method: str = "median") -> float:
    """Return the policy aggregate for non-empty millisecond samples."""
    if not samples:
        raise ValueError("at least one sample is required")
    if any(isinstance(sample, bool) or sample < 0 for sample in samples):
        raise ValueError("samples must be non-negative numbers")
    if method != "median":
        raise ValueError(f"unsupported aggregation method: {method}")
    return float(statistics.median(samples))


def evaluate_samples(
    contract: BenchmarkContract,
    profile: PlatformProfile,
    samples: Sequence[float],
) -> dict[str, object]:
    """Evaluate samples against nominal and margin-adjusted CI thresholds."""
    observed = aggregate_samples(samples, contract.aggregation)
    effective_threshold = contract.budget * (1.0 + profile.ci_margin_percent / 100.0)
    within_budget = observed <= contract.budget
    passed = observed <= effective_threshold
    return {
        "id": contract.identifier,
        "description": contract.description,
        "unit": contract.unit,
        "scope": contract.scope,
        "release_blocking": contract.release_blocking,
        "sample_count": len(samples),
        "configured_sample_count": contract.sample_count,
        "warmup_count": contract.warmup_count,
        "samples": [round(float(sample), 6) for sample in samples],
        "aggregation_method": contract.aggregation,
        "observed_aggregate": round(observed, 6),
        "contract_budget": contract.budget,
        "ci_margin_percent": profile.ci_margin_percent,
        "effective_failure_threshold": round(effective_threshold, 6),
        "within_nominal_budget": within_budget,
        "status": "PASS" if passed else "FAIL",
    }


def _measure(operation: Callable[[], object], warmups: int, samples: int) -> list[float]:
    for _ in range(warmups):
        operation()
    measured: list[float] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(samples):
            started = time.perf_counter_ns()
            operation()
            measured.append((time.perf_counter_ns() - started) / 1_000_000.0)
    finally:
        if gc_was_enabled:
            gc.enable()
    return measured


def _cold_start_samples(contract: BenchmarkContract) -> list[float]:
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
        "PATH": os.defpath,
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(SOURCE_ROOT),
        "PYTHONUTF8": "1",
        "TERM": "dumb",
    }
    command = [sys.executable, "-m", "pysh", "--no-rc", "-c", ""]

    def run_fresh_process() -> None:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=contract.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"cold-start process exited with status {completed.returncode}"
            )

    return _measure(run_fresh_process, contract.warmup_count, contract.sample_count)


def _prompt_render_samples(contract: BenchmarkContract) -> list[float]:
    from pysh.config.startup import NO_RC_STARTUP_POLICY
    from pysh.core.shell import TOOL_VERSION_SPECS, PyShell

    with tempfile.TemporaryDirectory(prefix="pysh-perf-prompt-") as directory:
        original_cwd = Path.cwd()
        os.chdir(directory)
        try:
            shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
            options = dict(shell.prompt_options)
            options.update({
                "cwd_style": "basename",
                "show_aws_profile": False,
                "show_git_branch": False,
                "show_k8s_context": False,
                "show_ssh_indicator": False,
                "show_virtualenv": False,
            })
            for specification in TOOL_VERSION_SPECS:
                options[specification.option] = False
            shell.prompt_options = options
            shell._prompt_colors_enabled = lambda: False  # type: ignore[method-assign]

            def render_prompt() -> str:
                info = shell._prompt_info_line()
                prompt = shell._prompt()
                rendered = f"{info}\n{prompt}"
                if not rendered:
                    raise RuntimeError("prompt benchmark produced empty output")
                return rendered

            return _measure(render_prompt, contract.warmup_count, contract.sample_count)
        finally:
            os.chdir(original_cwd)


def _git_context_samples(contract: BenchmarkContract) -> list[float]:
    from pysh.core.shell import PyShell

    with tempfile.TemporaryDirectory(prefix="pysh-perf-git-") as directory:
        root = Path(directory)
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "objects").mkdir()
        (git_dir / "refs").mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/performance-contract\n", encoding="utf-8")

        def collect_git_context() -> object:
            result = PyShell._read_git_prompt_info(root)
            if result is None or result.label != "performance-contract":
                raise RuntimeError("Git context benchmark returned unexpected metadata")
            return result

        return _measure(
            collect_git_context,
            contract.warmup_count,
            contract.sample_count,
        )


def _completion_samples(contract: BenchmarkContract) -> list[float]:
    from pysh.editor.lineedit.completion import (
        CompletionEngine,
        CompletionOptions,
        _PathCache,
    )

    with tempfile.TemporaryDirectory(prefix="pysh-perf-completion-") as directory:
        root = Path(directory)
        executable_dir = root / "bin"
        executable_dir.mkdir()
        for index in range(256):
            executable = executable_dir / f"perf-command-{index:04d}"
            executable.write_bytes(b"")
            executable.chmod(0o755)
        cache = _PathCache(max_entries=512, ttl=60.0)
        engine = CompletionEngine(
            CompletionOptions(
                builtins=tuple(f"builtin-{index:03d}" for index in range(128)),
                aliases=tuple(f"alias-{index:03d}" for index in range(128)),
                path=str(executable_dir),
                cwd=root,
                env={},
                locals={},
                path_cache=cache,
            )
        )

        def complete_prefix() -> object:
            result = engine.complete("perf-command-0", len("perf-command-0"))
            if len(result.candidates) != 256:
                raise RuntimeError(
                    f"completion benchmark expected 256 candidates, got {len(result.candidates)}"
                )
            return result

        return _measure(complete_prefix, contract.warmup_count, contract.sample_count)


def _keystroke_samples(contract: BenchmarkContract) -> list[float]:
    from pysh.editor.lineedit.autosuggest import AutoSuggester
    from pysh.editor.lineedit.buffer import LineBuffer
    from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
    from pysh.editor.lineedit.keys import Key, KeyEvent
    from pysh.editor.lineedit.reader import RawLineReader

    class CaptureReader(RawLineReader):
        def __init__(self) -> None:
            super().__init__(output_fd=-1)
            self.rendered = ""

        def _write(self, text: str, fd: int | None) -> None:
            del fd
            self.rendered = text

        @staticmethod
        def _terminal_width(fd: int) -> int:
            del fd
            return 80

    reader = CaptureReader()
    suggester = AutoSuggester()
    highlighter = LineHighlighter(frozenset({"echo"}))
    options = SimpleNamespace(autosuggest=True, syntax_highlight=True)
    history = ("echo representative-command",)
    initial = "echo representative"

    def process_printable_key() -> str:
        reader._start_rows = 0
        buffer = LineBuffer(initial, len(initial))
        result = reader._handle_event(
            KeyEvent(Key.PRINTABLE, "x"),
            "> ",
            buffer,
            history,
            suggester,
            highlighter,
            DEFAULT_SCHEME,
            True,
            options,
            None,
            None,
            None,
        )
        if isinstance(result, str):
            raise RuntimeError("printable key unexpectedly submitted the buffer")
        _, suggestion = result
        reader._redraw(
            "> ",
            buffer,
            suggestion,
            highlighter,
            DEFAULT_SCHEME,
            True,
            None,
        )
        if not reader.rendered:
            raise RuntimeError("keystroke benchmark produced no redraw")
        return reader.rendered

    return _measure(process_printable_key, contract.warmup_count, contract.sample_count)


_BENCHMARK_RUNNERS: dict[str, Callable[[BenchmarkContract], list[float]]] = {
    "cold_start": _cold_start_samples,
    "completion_core": _completion_samples,
    "git_context": _git_context_samples,
    "keystroke_render": _keystroke_samples,
    "prompt_render": _prompt_render_samples,
}


def runtime_context() -> dict[str, object]:
    """Return non-sensitive execution context for structured evidence."""
    candidate_sha = os.environ.get("GITHUB_SHA", "")
    git_sha = candidate_sha.lower() if _SHA_RE.fullmatch(candidate_sha) else None
    return {
        "git_sha": git_sha,
        "runner_environment": (
            "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
        ),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
    }


def build_report(
    policy: PerformancePolicy,
    profile: PlatformProfile,
    measurements: Mapping[str, Sequence[float]],
    *,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the stable JSON-compatible report from raw benchmark samples."""
    results: list[dict[str, object]] = []
    for contract in policy.benchmarks:
        if profile.identifier not in contract.platform_profiles:
            continue
        try:
            samples = measurements[contract.identifier]
        except KeyError as error:
            raise ValueError(f"missing samples for {contract.identifier}") from error
        results.append(evaluate_samples(contract, profile, samples))
    overall_passed = all(
        result["status"] == "PASS"
        for result in results
        if result["release_blocking"]
    )
    return {
        "schema_version": policy.schema_version,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "profile": {
            "id": profile.identifier,
            "platform_system": profile.platform_system,
            "python_minor": profile.python_minor,
            "ci_margin_percent": profile.ci_margin_percent,
            "description": profile.description,
        },
        "context": dict(context if context is not None else runtime_context()),
        "aggregation_method": policy.aggregation_method,
        "benchmarks": results,
        "overall_status": "PASS" if overall_passed else "FAIL",
    }


def _print_summary(report: Mapping[str, Any]) -> None:
    profile = report["profile"]
    print(
        "PySH performance contract "
        f"schema={report['schema_version']} profile={profile['id']} "
        f"margin={profile['ci_margin_percent']:.1f}%"
    )
    for result in report["benchmarks"]:
        samples = result["samples"]
        print(
            f"{result['id']}: {result['status']} "
            f"median={result['observed_aggregate']:.3f} ms "
            f"budget={result['contract_budget']:.3f} ms "
            f"threshold={result['effective_failure_threshold']:.3f} ms "
            f"samples={result['sample_count']} "
            f"range={min(samples):.3f}..{max(samples):.3f} ms "
            f"nominal={'PASS' if result['within_nominal_budget'] else 'MISS'}"
        )
    print(f"overall: {report['overall_status']}")


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="performance policy path (default: repository performance.toml)",
    )
    parser.add_argument(
        "--profile",
        default="auto",
        help="platform profile identifier, or 'auto' (default)",
    )
    parser.add_argument(
        "--benchmark",
        action="append",
        dest="benchmarks",
        help="run only this benchmark ID; may be repeated",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="write structured JSON evidence to this path",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run selected fixed scenarios and return non-zero on a blocking regression."""
    args = _parse_args(argv)
    try:
        policy = load_policy(args.policy)
        profile = select_profile(policy, args.profile)
        requested = set(args.benchmarks or EXPECTED_BENCHMARK_IDS)
        unknown = requested - EXPECTED_BENCHMARK_IDS
        if unknown:
            raise PolicyError(f"unknown benchmark ids: {sorted(unknown)!r}")
        measurements: dict[str, Sequence[float]] = {}
        for contract in policy.benchmarks:
            if contract.identifier not in requested:
                continue
            if profile.identifier not in contract.platform_profiles:
                continue
            measurements[contract.identifier] = _BENCHMARK_RUNNERS[contract.identifier](
                contract
            )
        selected_policy = PerformancePolicy(
            policy.schema_version,
            policy.aggregation_method,
            policy.profiles,
            tuple(
                contract
                for contract in policy.benchmarks
                if contract.identifier in requested
            ),
        )
        report = build_report(selected_policy, profile, measurements)
    except (OSError, PolicyError, RuntimeError, ValueError) as error:
        print(f"pysh-performance: {error}", file=sys.stderr)
        return 2

    _write_report(args.output, report)
    _print_summary(report)
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
