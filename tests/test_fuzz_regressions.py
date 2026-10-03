# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fuzz_regressions.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 2: permanent fuzz regressions replay without any fuzz engine."""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from tests.fuzz_support import driver

REPO = Path(__file__).resolve().parents[1]


def test_regression_directory_exists_documents_its_format_and_loads() -> None:
    assert driver.REGRESSION_DIR.is_dir()
    assert (driver.REGRESSION_DIR / "README.md").is_file()
    records = driver.load_regressions()
    for record in records:
        assert record.path is not None and record.path.name == record.filename
    assert len({record.sha256 for record in records}) == len(records)


def test_every_permanent_regression_replays_clean() -> None:
    records = driver.load_regressions()
    replayed = 0
    with driver.replay_context() as ctx:
        for record in records:
            driver.replay_record(record, ctx)  # a regressed reproducer raises PropertyFailure
            replayed += 1
    assert replayed == len(records)


def test_replay_and_normal_pysh_import_never_need_or_import_the_fuzz_engine() -> None:
    code = (
        "import sys\n"
        "import pysh, pysh.core.shell\n"
        "assert 'atheris' not in sys.modules\n"
        "from tests.fuzz_support import driver\n"
        "with driver.replay_context() as ctx:\n"
        "    for record in driver.load_regressions():\n"
        "        driver.replay_record(record, ctx)\n"
        "assert 'atheris' not in sys.modules\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed interpreter and inline code
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60, check=False,
        env={"PYTHONPATH": f"{REPO / 'src'}:{REPO}", "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr


def test_atheris_is_a_dev_only_dependency_group_not_a_runtime_dependency() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []
    assert any(req.startswith("atheris") for req in project["dependency-groups"]["fuzz"])
    for extra, requirements in project["project"]["optional-dependencies"].items():
        assert not any("atheris" in requirement for requirement in requirements), extra
    assert not any("atheris" in req for req in project["dependency-groups"]["dev"])
