# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_performance_contract.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Versioned performance-policy and harness tests for Issue #47."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from pysh.editor.lineedit.autosuggest import AutoSuggester
from pysh.editor.lineedit.buffer import LineBuffer
from pysh.editor.lineedit.highlight import DEFAULT_SCHEME, LineHighlighter
from pysh.editor.lineedit.keys import Key, KeyEvent
from pysh.editor.lineedit.reader import RawLineReader

REPOSITORY_ROOT = Path(__file__).parent.parent
POLICY_PATH = REPOSITORY_ROOT / "performance.toml"
HARNESS_PATH = REPOSITORY_ROOT / "scripts" / "benchmark_performance.py"
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pysh_performance_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _load_harness()


def test_performance_policy_is_complete_and_versioned() -> None:
    """The policy defines every fixed scenario and both validation profiles."""
    policy = HARNESS.load_policy(POLICY_PATH)
    assert policy.schema_version == 1
    assert policy.aggregation_method == "median"
    assert set(policy.profiles) == {
        "freebsd-14-4-python3-13",
        "linux-python3-13",
    }
    assert set(policy.benchmarks_by_id) == HARNESS.EXPECTED_BENCHMARK_IDS
    assert {
        identifier: contract.budget
        for identifier, contract in policy.benchmarks_by_id.items()
    } == {
        "cold_start": 175.0,
        "completion_core": 50.0,
        "git_context": 10.0,
        "keystroke_render": 2.0,
        "prompt_render": 20.0,
    }
    for contract in policy.benchmarks:
        assert contract.release_blocking
        assert contract.unit == "milliseconds"
        assert contract.sample_count >= 5
        assert contract.sample_count % 2 == 1
        assert set(contract.platform_profiles) == set(policy.profiles)


def test_policy_rejects_unknown_benchmark_configuration(tmp_path: Path) -> None:
    """Policy data cannot smuggle commands or unreviewed configuration."""
    text = POLICY_PATH.read_text(encoding="utf-8")
    text = text.replace(
        'description = "Fresh Python process',
        'command = ["arbitrary"]\ndescription = "Fresh Python process',
        1,
    )
    policy = tmp_path / "performance.toml"
    policy.write_text(text, encoding="utf-8")
    with pytest.raises(HARNESS.PolicyError, match="unknown keys"):
        HARNESS.load_policy(policy)


def test_median_ignores_one_outlier() -> None:
    """A single infrastructure spike does not fail a stable median."""
    policy = HARNESS.load_policy(POLICY_PATH)
    contract = policy.benchmarks_by_id["prompt_render"]
    profile = policy.profiles["linux-python3-13"]
    result = HARNESS.evaluate_samples(contract, profile, [10.0, 10.0, 10.0, 10.0, 900.0])
    assert result["observed_aggregate"] == 10.0
    assert result["within_nominal_budget"] is True
    assert result["status"] == "PASS"


def test_material_regression_beyond_margin_fails() -> None:
    """A median beyond the explicit effective threshold is release-blocking."""
    policy = HARNESS.load_policy(POLICY_PATH)
    contract = policy.benchmarks_by_id["git_context"]
    profile = policy.profiles["linux-python3-13"]
    result = HARNESS.evaluate_samples(contract, profile, [12.001] * 5)
    assert result["contract_budget"] == 10.0
    assert result["effective_failure_threshold"] == 12.0
    assert result["within_nominal_budget"] is False
    assert result["status"] == "FAIL"


def test_below_budget_passes_without_using_margin() -> None:
    """A normal result is visibly within the nominal contract budget."""
    policy = HARNESS.load_policy(POLICY_PATH)
    contract = policy.benchmarks_by_id["completion_core"]
    profile = policy.profiles["linux-python3-13"]
    result = HARNESS.evaluate_samples(contract, profile, [40.0] * 5)
    assert result["within_nominal_budget"] is True
    assert result["status"] == "PASS"


def test_harness_writes_structured_json_for_synthetic_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI writes complete JSON evidence without running wall-clock gates."""
    for identifier in HARNESS.EXPECTED_BENCHMARK_IDS:
        monkeypatch.setitem(
            HARNESS._BENCHMARK_RUNNERS,
            identifier,
            lambda contract: [contract.budget] * contract.sample_count,
        )
    output = tmp_path / "performance.json"
    status = HARNESS.main([
        "--policy",
        str(POLICY_PATH),
        "--profile",
        "linux-python3-13",
        "--output",
        str(output),
    ])
    assert status == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["overall_status"] == "PASS"
    assert report["profile"]["id"] == "linux-python3-13"
    assert {result["id"] for result in report["benchmarks"]} == (
        HARNESS.EXPECTED_BENCHMARK_IDS
    )
    for result in report["benchmarks"]:
        assert len(result["samples"]) == result["configured_sample_count"]
        assert result["aggregation_method"] == "median"
        assert result["status"] == "PASS"
        assert "effective_failure_threshold" in result


def test_harness_writes_json_then_returns_nonzero_on_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed budget remains diagnosable without converting failure to success."""
    contract_id = "cold_start"
    monkeypatch.setitem(
        HARNESS._BENCHMARK_RUNNERS,
        contract_id,
        lambda contract: [contract.budget * 2.0] * contract.sample_count,
    )
    output = tmp_path / "failed.json"
    status = HARNESS.main([
        "--policy",
        str(POLICY_PATH),
        "--profile",
        "linux-python3-13",
        "--benchmark",
        contract_id,
        "--output",
        str(output),
    ])
    assert status == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall_status"] == "FAIL"
    assert report["benchmarks"][0]["status"] == "FAIL"


@pytest.mark.parametrize("module_name", ["pysh", "pysh.api"])
def test_public_imports_keep_heavy_optional_modules_lazy(module_name: str) -> None:
    """Bare public imports do not load highlighting or runtime-heavy modules."""
    code = f"""
import json
import sys
import {module_name}

forbidden = sorted(
    name for name in sys.modules
    if name in {{"curses", "readline", "pygments"}}
    or name.startswith((
        "pygments.",
        "pysh.config",
        "pysh.core",
        "pysh.diagnostics",
        "pysh.editor",
        "pysh.plugins.isolated",
        "pysh.python_layer",
    ))
)
print(json.dumps(forbidden))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == []


def test_printable_key_does_not_call_completion_provider() -> None:
    """Ordinary typing remains separate from TAB-triggered provider work."""
    calls = 0

    def forbidden_completion(_line: str, _cursor: int) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("completion provider ran for a printable key")

    reader = RawLineReader()
    buffer = LineBuffer("echo rep")
    result = reader._handle_event(
        KeyEvent(Key.PRINTABLE, "r"),
        "> ",
        buffer,
        ("echo representative",),
        AutoSuggester(forbidden_completion),  # type: ignore[arg-type]
        LineHighlighter(frozenset({"echo"})),
        DEFAULT_SCHEME,
        True,
        SimpleNamespace(autosuggest=True, syntax_highlight=True),
        None,
        None,
        None,
    )
    assert not isinstance(result, str)
    assert calls == 0


def test_ci_has_gating_linux_and_freebsd_performance_jobs() -> None:
    """Pull-request CI executes both platform gates and preserves JSON evidence."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "performance-linux:" in text
    assert "performance-freebsd:" in text
    assert text.count("scripts/benchmark_performance.py") == 2
    assert "--profile linux-python3-13" in text
    assert "--profile freebsd-14-4-python3-13" in text
    assert 'release: "14.4"' in text
    assert "pkg install -y python313" in text
    assert "python3.13 scripts/benchmark_performance.py" in text
    assert "artifacts/performance/linux-python3-13.json" in text
    assert "artifacts/performance/freebsd-14.4-python3-13.json" in text
    assert text.count("if: ${{ always() }}") >= 2
    assert "continue-on-error" not in text
    assert "timeout-minutes:" in text
