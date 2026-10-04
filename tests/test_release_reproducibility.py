# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_reproducibility.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #51 Slice 4: per-artifact reproducibility measurement and evidence.

Hermetic: temporary git repositories hold fake builders and fake host tools stand in for
dpkg-deb, rpmbuild and pkg. No network, no real packaging tool, no real artifact.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts import check_reproducibility_evidence as checker
from scripts import measure_release_reproducibility as harness
from tests.repro_support import COMMIT, VERSION, document, final_document, result

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT_DATE = "2026-01-02T03:04:05+00:00"
COMMIT_EPOCH = "1767323045"

WHEEL = f"pysh_shell-{VERSION}-py3-none-any.whl"
SDIST = f"pysh_shell-{VERSION}.tar.gz"
DEB = f"pysh-shell_{VERSION}-1_all.deb"
RPM = f"pysh-shell-{VERSION}-1.noarch.rpm"
PKG = f"pysh-shell-{VERSION}.pkg"

#: One fake builder body per script. ``FAKE_MODE`` (committed) holds ``family=mode`` lines.
BUILDER = r"""#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode_of() { grep "^$1=" FAKE_MODE | head -1 | cut -d= -f2 || true; }
sentinel() { cat FAKE_SENTINEL; }
write_file() {  # write_file <family> <path> <payload>; a wheel is a real zip that names its generator
    local family="$1" path="$2" payload="$3" generator=1.27.0
    if [ "$family" = wheel ]; then
        [ "$(mode_of wheel)" = wrongbackend ] && generator=9.9.9
        python3 - "$path" "$payload" "$generator" <<'PY'
import sys, zipfile
path, payload, generator = sys.argv[1:4]
with zipfile.ZipFile(path, "w") as bundle:
    bundle.writestr(zipfile.ZipInfo("pysh-9.8.7.dist-info/WHEEL", (2020, 1, 1, 0, 0, 0)), f"Wheel-Version: 1.0\nGenerator: hatchling {generator}\n")
    bundle.writestr(zipfile.ZipInfo("pysh/payload.txt", (2020, 1, 1, 0, 0, 0)), payload)
PY
    else
        printf '%s\n' "$payload" > "$path"
    fi
}
emit() {  # emit <family> <directory> <file>
    local family="$1" dir="$2" name="$3" mode payload
    mode="$(mode_of "$family")"; mode="${mode:-deterministic}"
    mkdir -p "$dir"
    if [ "$family" = wheel ] && [ -n "${PIP_LOG:-}" ] && [ "$mode" != nolog ]; then
        printf '2026-01-01T00:00:00,000 Successfully installed hatchling-1.27.0 packaging-24.2\n' >> "$PIP_LOG"
        [ "$mode" = twoversions ] && printf '2026-01-01T00:00:01,000 Successfully installed hatchling-1.28.0\n' >> "$PIP_LOG"
    fi
    payload="${family} epoch=${SOURCE_DATE_EPOCH} tz=${TZ} lc=${LC_ALL}"
    case "$mode" in
        random) payload="$payload $RANDOM$RANDOM$RANDOM$$" ;;
        path) payload="$payload $PWD" ;;
        time) payload="$payload $(date +%s%N)" ;;
        fail) echo "fake builder failure for ${family}" >&2; exit 3 ;;
        hang) sleep 300 & echo $! > "$(sentinel)"; wait ;;
        record) printf 'SDE=%s TZ=%s LC=%s HOME=%s TMPDIR=%s PWD=%s UMASK=%s\n' "$SOURCE_DATE_EPOCH" "$TZ" "$LC_ALL" "$HOME" "$TMPDIR" "$PWD" "$(umask)" >> "$(sentinel)" ;;
        touch) touch "$(sentinel)" ;;
    esac
    case "$mode" in
        empty) : > "$dir/$name" ;;
        badname) printf '%s\n' "$payload" > "$dir/wrong-name.bin" ;;
        symlink) printf '%s\n' "$payload" > "$dir/real.bin"; ln -s real.bin "$dir/$name" ;;
        extra) write_file "$family" "$dir/$name" "$payload"; printf 'x' > "$dir/stray.${name##*.}" ;;
        *) write_file "$family" "$dir/$name" "$payload" ;;
    esac
}
"""
BUILDERS = {
    "build_pysh_package.sh": f'emit wheel dist "{WHEEL}"\nemit sdist dist "{SDIST}"\n',
    "build_deb.sh": f'emit deb dist/os/deb "{DEB}"\n',
    "build_rpm.sh": f'emit rpm dist/os/rpm "{RPM}"\n',
    "build_freebsd_pkg.sh": f'emit freebsd_pkg dist/os/freebsd "{PKG}"\n',
}
PYPROJECT = (
    '[build-system]\nrequires = ["hatchling>=1.27.0"]\nbuild-backend = "hatchling.build"\n\n'
    f'[project]\nname = "pysh-shell"\nversion = "{VERSION}"\n'
)
FAKE_PYTHON = r"""#!/usr/bin/env bash
case "$*" in
    *"import build, twine"*) exit 0 ;;
    *"platform.python_version"*) echo 3.13.5 ;;
    *"m.version('build')"*) echo 1.6.1 ;;
    *"m.version('twine')"*) echo 7.0.0 ;;
    *) exit 1 ;;
esac
"""


@dataclass
class Repo:
    path: Path
    commit: str
    sentinel: Path


def git(repo: Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_COMMITTER_DATE": COMMIT_DATE, "GIT_AUTHOR_DATE": COMMIT_DATE,
           "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(repo.parent)}
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
         "-C", str(repo), *args],
        capture_output=True, text=True, check=check, env=env,
    )
    return done.stdout.strip()


def make_repo(tmp_path: Path, modes: str = "", extra: dict[str, str] | None = None) -> Repo:
    repo = tmp_path / "source"
    (repo / "scripts").mkdir(parents=True)
    sentinel = tmp_path / "sentinel"
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "FAKE_MODE").write_text(modes, encoding="utf-8")
    (repo / "FAKE_SENTINEL").write_text(str(sentinel), encoding="utf-8")
    for name, body in BUILDERS.items():
        (repo / "scripts" / name).write_text(BUILDER + body, encoding="utf-8")
    for name, content in (extra or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    return Repo(repo, git(repo, "rev-parse", "HEAD"), sentinel)


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory of fake host tools placed first on PATH."""
    directory = tmp_path / "tools"
    directory.mkdir()
    for name, line in (("dpkg-deb", "Debian 'dpkg-deb' package archive backend version 1.22.22 (amd64)."), ("rpmbuild", "RPM version 4.19.1"), ("pkg", "2.0.6"), ("fakeroot", "fakeroot version 1.37.1.1")):
        path = directory / name
        path.write_text(f"#!/usr/bin/env bash\necho '{line}'\n", encoding="utf-8")
        path.chmod(0o755)
    python = directory / "python-fake"
    python.write_text(FAKE_PYTHON, encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return directory


def host(tools_dir: Path, *, system: str = "Linux", without: tuple[str, ...] = ()) -> harness.Host:
    def which(name: str) -> str | None:
        if name in without:
            return None
        candidate = tools_dir / name
        return str(candidate) if candidate.exists() else None

    return harness.Host(system, "6.12.0", "x86_64", "3.13.5", which)


def run(repo: Repo, tools_dir: Path, families: list[str], **options: Any) -> dict[str, Any]:
    source = harness.resolve_source(repo.path, None)
    options.setdefault("host", host(tools_dir))
    options.setdefault("python", str(tools_dir / "python-fake"))
    options.setdefault("timeout", 60.0)
    return harness.measure(families, source, **options)


def by_family(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["family"]: r for r in doc["results"]}


# --- measurement: positive ---------------------------------------------------------------------------------------------


def test_deterministic_builders_give_reproducible_results_for_every_linux_family(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    doc = run(repo, tools, ["wheel", "sdist", "deb", "rpm"])
    results = by_family(doc)
    assert [r["family"] for r in doc["results"]] == ["wheel", "sdist", "deb", "rpm"]
    for family, name in (("wheel", WHEEL), ("sdist", SDIST), ("deb", DEB), ("rpm", RPM)):
        entry = results[family]
        assert entry["classification"] == "REPRODUCIBLE" and entry["equal"] is True
        assert entry["artifact"] == name and entry["build_a_sha256"] == entry["build_b_sha256"]
        assert entry["separate_source_roots"] is True and entry["separate_output_files"] is True
        assert entry["build_a_source_commit"] == entry["build_b_source_commit"] == repo.commit
        assert entry["source_date_epoch"] == COMMIT_EPOCH and entry["source_date_epoch_origin"] == "commit-timestamp"
        assert entry["platform"] == "Linux" and entry["python"] == "3.13.5"
    assert results["rpm"]["tools"] == {"rpmbuild": "4.19.1"}
    assert results["deb"]["tools"] == {"dpkg-deb": "1.22.22", "fakeroot": "1.37.1.1"}
    wheel_tools = results["wheel"]["tools"]
    assert wheel_tools == {"python": "3.13.5", "build": "1.6.1", "twine": "7.0.0", "hatchling": "1.27.0"}
    assert results["wheel"]["declared_requirements"] == ["hatchling>=1.27.0"] == results["sdist"]["declared_requirements"]
    assert results["deb"]["declared_requirements"] == []
    assert checker.check_document(doc, mode="local", source_commit=repo.commit) == []


def test_the_digests_are_computed_by_the_harness_from_the_artifact_bytes(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    entry = by_family(run(repo, tools, ["deb"]))["deb"]
    expected = hashlib.sha256(f"deb epoch={COMMIT_EPOCH} tz=UTC lc=C.UTF-8\n".encode()).hexdigest()
    assert entry["build_a_sha256"] == entry["build_b_sha256"] == expected


def test_a_native_freebsd_builder_measures_the_pkg(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    doc = run(repo, tools, ["freebsd_pkg"], host=host(tools, system="FreeBSD"))
    entry = by_family(doc)["freebsd_pkg"]
    assert entry["classification"] == "REPRODUCIBLE" and entry["platform"] == "FreeBSD"
    assert entry["artifact"] == PKG and entry["tools"] == {"pkg": "2.0.6", "python": "3.13.5"}
    assert checker.check_document(doc, mode="local", source_commit=repo.commit) == []


def test_the_evidence_document_is_deterministic(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    first = checker.canonical_json(run(repo, tools, ["deb", "wheel", "rpm", "sdist"]))
    second = checker.canonical_json(run(repo, tools, ["sdist", "rpm", "wheel", "deb"]))
    assert first == second
    assert first.endswith("\n") and json.loads(first)["schema_version"] == 1
    families = [r["family"] for r in json.loads(first)["results"]]
    assert families == ["wheel", "sdist", "deb", "rpm"]


def test_wheel_and_sdist_are_classified_independently(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, "sdist=random\n")
    results = by_family(run(repo, tools, ["wheel", "sdist"]))
    assert results["wheel"]["classification"] == "REPRODUCIBLE"
    assert results["sdist"]["classification"] == "NON_REPRODUCIBLE"


def test_differing_bytes_are_a_valid_non_reproducible_measurement(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, "deb=random\n")
    doc = run(repo, tools, ["deb"])
    entry = by_family(doc)["deb"]
    assert entry["classification"] == "NON_REPRODUCIBLE" and entry["equal"] is False
    assert entry["build_a_sha256"] != entry["build_b_sha256"]
    assert "first differing byte" in entry["diagnostic"] and "sizes" in entry["diagnostic"]
    assert checker.check_document(doc, mode="local") == []


def test_every_kind_of_variance_is_detected_between_independent_roots(tmp_path, tools) -> None:
    for mode in ("random", "path", "time"):
        repo = make_repo(tmp_path / mode, f"deb={mode}\n")
        if mode == "time":
            time.sleep(0.01)
        entry = by_family(run(repo, tools, ["deb"]))["deb"]
        assert entry["classification"] == "NON_REPRODUCIBLE", mode


def test_an_unavailable_tool_is_recorded_as_a_local_platform_block(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, extra={})
    doc = run(repo, tools, ["deb", "rpm", "freebsd_pkg"], host=host(tools, without=("rpmbuild",)))
    results = by_family(doc)
    assert results["deb"]["classification"] == "REPRODUCIBLE"
    for family, reason in (("rpm", "rpmbuild was not found"), ("freebsd_pkg", "native FreeBSD builder")):
        assert results[family]["classification"] == "PLATFORM_BLOCKED"
        assert reason in results[family]["diagnostic"]
        assert results[family]["build_a_sha256"] is None and results[family]["equal"] is None
    assert checker.check_document(doc, mode="local") == []
    assert checker.check_document(doc, mode="final")  # never acceptable as final evidence


def test_a_missing_dpkg_and_missing_build_modules_are_platform_blocks(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    doc = run(repo, tools, ["wheel", "deb"], host=host(tools, without=("dpkg-deb",)), python="/nonexistent/python")
    results = by_family(doc)
    assert results["deb"]["classification"] == "PLATFORM_BLOCKED" and "dpkg-deb" in results["deb"]["diagnostic"]
    assert results["wheel"]["classification"] == "PLATFORM_BLOCKED" and "not found" in results["wheel"]["diagnostic"]


def test_blocked_builders_are_never_executed(tmp_path, tools) -> None:
    """A placeholder .pkg or .rpm can never become evidence: the builder does not even run."""
    repo = make_repo(tmp_path, "freebsd_pkg=touch\nrpm=touch\n")
    doc = run(repo, tools, ["rpm", "freebsd_pkg"], host=host(tools, without=("rpmbuild",)))
    assert {r["classification"] for r in doc["results"]} == {"PLATFORM_BLOCKED"}
    assert not repo.sentinel.exists()
    assert checker.check_document(doc, mode="final")


def test_a_freebsd_host_without_pkg_is_blocked(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    doc = run(repo, tools, ["freebsd_pkg"], host=host(tools, system="FreeBSD", without=("pkg",)))
    assert by_family(doc)["freebsd_pkg"]["classification"] == "PLATFORM_BLOCKED"


# --- source isolation and the build contract -----------------------------------------------------------------------------------


def test_builds_use_the_commit_epoch_a_private_home_and_separate_roots(tmp_path, tools, monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/maintainer-real")
    repo = make_repo(tmp_path, "deb=record\n")
    run(repo, tools, ["deb"])
    lines = repo.sentinel.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (dict(item.split("=", 1) for item in line.split(" ")) for line in lines)
    assert first["SDE"] == second["SDE"] == COMMIT_EPOCH  # the commit timestamp, never wall-clock time
    assert first["TZ"] == "UTC" and first["LC"] == "C.UTF-8"
    assert first["UMASK"] == second["UMASK"] == "0022"  # the declared umask, not the caller's
    assert first["PWD"] != second["PWD"]  # two independent source/build roots
    assert "/a/" in first["PWD"] and "/b/" in second["PWD"]
    for env in (first, second):
        assert env["HOME"] != "/home/maintainer-real" and "maintainer-real" not in env["TMPDIR"]
    assert first["HOME"] != second["HOME"] and first["TMPDIR"] != second["TMPDIR"]


def test_the_epoch_is_the_commit_timestamp_not_the_current_time(tmp_path) -> None:
    repo = make_repo(tmp_path)
    source = harness.resolve_source(repo.path, None)
    assert source.epoch == COMMIT_EPOCH and source.commit == repo.commit
    assert abs(int(source.epoch) - time.time()) > 86400
    assert harness.resolve_source(repo.path, repo.commit[:12]).commit == repo.commit


def test_the_measured_tree_is_the_commit_not_the_working_directory(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    (repo.path / "FAKE_MODE").write_text("deb=random\n", encoding="utf-8")  # uncommitted edit
    (repo.path / "dist").mkdir()  # untracked output of an earlier build
    entry = by_family(run(repo, tools, ["deb"]))["deb"]
    assert entry["classification"] == "REPRODUCIBLE"
    status = git(repo.path, "status", "--short")  # the developer tree is left exactly as it was
    assert "M FAKE_MODE" in status and (repo.path / "dist").is_dir()
    assert (repo.path / "FAKE_MODE").read_text(encoding="utf-8") == "deb=random\n"


def test_an_archive_source_is_equivalent_to_git_archive(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    archive = tmp_path / "source.tar"
    git(repo.path, "archive", "--format=tar", "-o", str(archive), repo.commit)
    from_git = by_family(run(repo, tools, ["deb"]))["deb"]
    source = harness.Source(repo.commit, COMMIT_EPOCH, archive=archive)
    from_archive = by_family(harness.measure(["deb"], source, host=host(tools), timeout=60.0))["deb"]
    assert from_archive["build_a_sha256"] == from_git["build_a_sha256"]
    assert from_archive["build_a_source_tree_sha256"] == from_git["build_a_source_tree_sha256"]


def test_the_work_directory_must_be_new_or_empty(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "left-over").write_text("x", encoding="utf-8")
    with pytest.raises(harness.MeasurementError, match="must be empty"):
        run(repo, tools, ["deb"], work_dir=work)


def test_a_source_that_already_contains_build_output_is_rejected(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, extra={"dist/os/deb/old.deb": "stale"})
    with pytest.raises(harness.MeasurementError, match="already contains dist/"):
        run(repo, tools, ["deb"])


def test_a_differing_source_tree_between_a_and_b_is_rejected(tmp_path, tools, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    digests = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(harness, "tree_digest", lambda root: next(digests))
    with pytest.raises(harness.MeasurementError, match="identical source tree"):
        run(repo, tools, ["deb"])


def test_builds_a_and_b_cannot_share_one_output_file(tmp_path, tools, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    shared: dict[str, Path] = {}
    original = harness.locate_outputs

    def locate(root: Path, group: harness.Group, version: str) -> dict[str, Path]:
        found = original(root, group, version)
        shared.setdefault("a", found["deb"])
        return {"deb": shared["a"]}  # build B "produces" build A's file

    monkeypatch.setattr(harness, "locate_outputs", locate)
    with pytest.raises(harness.MeasurementError, match="share one output file"):
        run(repo, tools, ["deb"])


def test_an_output_reused_from_a_by_hard_link_is_rejected(tmp_path, tools, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    original = harness.locate_outputs
    seen: list[Path] = []

    def locate(root: Path, group: harness.Group, version: str) -> dict[str, Path]:
        found = original(root, group, version)
        if seen:  # build B: replace its output with a hard link to build A's output
            target = found["deb"]
            target.unlink()
            os.link(seen[0], target)
            return {"deb": target}
        seen.append(found["deb"])
        return found

    monkeypatch.setattr(harness, "locate_outputs", locate)
    with pytest.raises(harness.MeasurementError, match="share one output file"):
        run(repo, tools, ["deb"])


# --- builder failures ------------------------------------------------------------------------------------------------------------------


def test_a_failing_build_is_an_error_not_a_classification(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, "deb=fail\n")
    with pytest.raises(harness.MeasurementError, match=r"build A of deb failed \(exit 3\).*fake builder failure"):
        run(repo, tools, ["deb"])


def test_a_hanging_build_is_stopped_with_its_descendants(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, "deb=hang\n")
    with pytest.raises(harness.MeasurementError, match="time limit"):
        run(repo, tools, ["deb"], timeout=1.0)
    pid = int(repo.sentinel.read_text(encoding="utf-8").split()[0])
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:  # pragma: no cover - failure branch
        pytest.fail("the build's background process survived the timeout")


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("empty", "is empty"),
        ("badname", "must produce exactly one of"),
        ("extra", "must produce exactly one of"),
        ("symlink", "not a regular file|must produce exactly one"),
    ],
)
def test_builder_output_is_validated_not_trusted(tmp_path, tools, mode: str, message: str) -> None:
    repo = make_repo(tmp_path, f"deb={mode}\n")
    with pytest.raises(harness.MeasurementError, match=message):
        run(repo, tools, ["deb"])


def test_a_missing_artifact_after_a_successful_build_is_an_error(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    original = harness.run_bounded

    def quiet(argv, cwd, env, timeout, umask=None):
        if argv[0] == "bash":
            return harness.RunResult(0, "")
        return original(argv, cwd, env, timeout, umask)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(harness, "run_bounded", quiet)
        with pytest.raises(harness.MeasurementError, match="must produce exactly one of"):
            run(repo, tools, ["deb"])


def test_family_selection_is_validated(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    with pytest.raises(harness.MeasurementError, match="at least one family"):
        run(repo, tools, [])
    with pytest.raises(harness.MeasurementError, match="at most once"):
        run(repo, tools, ["deb", "deb"])


def test_an_unresolvable_commit_is_an_error(tmp_path) -> None:
    repo = make_repo(tmp_path)
    with pytest.raises(harness.MeasurementError, match="cannot resolve the source commit"):
        harness.resolve_source(repo.path, "0" * 40)


# --- command line -----------------------------------------------------------------------------------------------------------------------


def test_the_cli_writes_validated_evidence(tmp_path, tools, capsys) -> None:
    repo = make_repo(tmp_path)
    out = tmp_path / "out" / "evidence.json"
    code = harness.main(["--family", "deb", "--repo-root", str(repo.path), "--output", str(out), "--timeout", "60"])
    assert code == 0 and capsys.readouterr().out.strip() == "deb: REPRODUCIBLE"
    document_ = json.loads(out.read_text(encoding="utf-8"))
    assert checker.check_document(document_, mode="local", source_commit=repo.commit) == []
    assert out.read_text(encoding="utf-8") == checker.canonical_json(document_)


def test_the_cli_records_what_the_host_cannot_build(tmp_path, tools, capsys) -> None:
    repo = make_repo(tmp_path)
    out = tmp_path / "evidence.json"
    argv = ["--all", "--repo-root", str(repo.path), "--output", str(out), "--python", "/nonexistent/python"]
    assert harness.main(argv) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[2] == "deb: REPRODUCIBLE" and lines[4] == "freebsd_pkg: PLATFORM_BLOCKED"
    assert lines[0] == "wheel: PLATFORM_BLOCKED"  # no usable Python with 'build' and 'twine'
    assert lines[3] == "rpm: REPRODUCIBLE"  # the fake rpmbuild is on PATH


def test_a_failed_measurement_writes_no_evidence(tmp_path, tools, capsys) -> None:
    repo = make_repo(tmp_path, "deb=fail\n")
    out = tmp_path / "evidence.json"
    assert harness.main(["--family", "deb", "--repo-root", str(repo.path), "--output", str(out)]) == 1
    assert not out.exists() and not list(tmp_path.glob("evidence.json*"))
    assert "measure_release_reproducibility: FAIL" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--all", "--family", "deb"],
        ["--family", "deb", "--timeout", "0"],
        ["--family", "deb", "--source-date-epoch", "1"],
        ["--family", "deb", "--source-archive", "x.tar"],
        ["--family", "deb", "--source-archive", "x.tar", "--source-commit", "abc", "--source-date-epoch", "1"],
        ["--family", "deb", "--source-archive", "x.tar", "--source-commit", "a" * 40, "--source-date-epoch", "now"],
    ],
)
def test_cli_misuse_is_exit_two(tmp_path, argv: list[str], capsys) -> None:
    code = harness.main([*argv, "--output", str(tmp_path / "e.json")]) if "--output" not in argv else harness.main(argv)
    assert code == 2
    assert not (tmp_path / "e.json").exists()


def test_the_freebsd_vm_invocation_shape_works_without_git(tmp_path, tools, capsys, monkeypatch) -> None:
    """The workflow passes a host-made archive, the commit and its timestamp (no git in the VM)."""
    repo = make_repo(tmp_path)
    archive = tmp_path / "source.tar"
    git(repo.path, "archive", "--format=tar", "-o", str(archive), repo.commit)
    monkeypatch.setattr(harness.Host, "detect", classmethod(lambda cls: host(tools, system="FreeBSD")))
    out = tmp_path / "freebsd_pkg.json"
    code = harness.main([
        "--family", "freebsd_pkg", "--source-archive", str(archive), "--source-commit", repo.commit,
        "--source-date-epoch", COMMIT_EPOCH, "--python", "python3.13", "--output", str(out),
    ])
    assert code == 0
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert by_family(loaded)["freebsd_pkg"]["classification"] == "REPRODUCIBLE"
    assert checker.check_document(loaded, mode="local", source_commit=repo.commit) == []


# --- merge: combining platforms into the published final evidence -------------------------------------------------------------------------


def linux_doc(**kw: Any) -> dict[str, Any]:
    return document([result(f, **kw) for f in ("wheel", "sdist", "deb", "rpm")])


def freebsd_doc(**kw: Any) -> dict[str, Any]:
    return document([result("freebsd_pkg", **kw)])


def test_merging_both_platforms_gives_valid_final_evidence() -> None:
    merged = harness.merge_documents([freebsd_doc(), linux_doc()], COMMIT)
    assert [r["family"] for r in merged["results"]] == list(checker.FAMILY_ORDER)
    assert checker.check_document(merged, mode="final", source_commit=COMMIT) == []
    assert checker.canonical_json(merged) == checker.canonical_json(harness.merge_documents([linux_doc(), freebsd_doc()], COMMIT))


def test_a_non_reproducible_family_is_valid_final_evidence() -> None:
    linux = document([result("wheel"), result("sdist"), result("deb", "NON_REPRODUCIBLE"), result("rpm", "NON_REPRODUCIBLE")])
    merged = harness.merge_documents([linux, freebsd_doc()], COMMIT)
    assert checker.check_document(merged, mode="final") == []


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ([linux_doc()], "at least two platforms"),
        ([linux_doc(), linux_doc()], "duplicate family"),
        ([linux_doc(), document([result("freebsd_pkg", "PLATFORM_BLOCKED")])], "not accepted in final evidence"),
        ([document([result("wheel"), result("sdist"), result("deb")]), freebsd_doc()], "rpm is missing"),
        ([linux_doc(), document([result("freebsd_pkg", commit="f" * 40)], commit="f" * 40)], "does not match the expected commit"),
    ],
)
def test_merge_refuses_anything_but_valid_final_evidence(inputs, message: str) -> None:
    with pytest.raises(harness.MeasurementError, match=message):
        harness.merge_documents(inputs, COMMIT)


def test_merge_refuses_inputs_that_disagree_on_the_release() -> None:
    other = freebsd_doc()
    other["version"] = "9.9.9"
    for entry in other["results"]:
        entry["artifact"] = "pysh-shell-9.9.9.pkg"
    with pytest.raises(harness.MeasurementError, match="disagrees on version"):
        harness.merge_documents([linux_doc(), other], None)


def test_the_merge_command_writes_the_published_evidence(tmp_path, capsys) -> None:
    linux, freebsd, out = tmp_path / "linux.json", tmp_path / "freebsd.json", tmp_path / "REPRODUCIBILITY.json"
    linux.write_text(checker.canonical_json(linux_doc()), encoding="utf-8")
    freebsd.write_text(checker.canonical_json(freebsd_doc()), encoding="utf-8")
    argv = ["merge", "--input", str(linux), "--input", str(freebsd), "--source-commit", COMMIT, "--output", str(out)]
    assert harness.main(argv) == 0
    assert checker.main([str(out), "--mode", "final", "--source-commit", COMMIT]) == 0
    assert harness.main(["merge", "--input", str(linux), "--output", str(out), "--source-commit", COMMIT]) == 1
    assert harness.main(["merge", "--input", str(linux), "--output", str(out), "--source-commit", "bad"]) == 2
    assert capsys.readouterr().err.count("measure_release_reproducibility") >= 2


# --- evidence validator: positive -----------------------------------------------------------------------------------------------------------


def test_final_evidence_with_every_family_measured_is_valid() -> None:
    assert checker.check_document(final_document(), mode="final", source_commit=COMMIT) == []


def test_local_evidence_may_cover_a_subset_with_blocked_families() -> None:
    doc = document([result("deb"), result("rpm", "PLATFORM_BLOCKED"), result("freebsd_pkg", "NOT_YET_MEASURED")])
    assert checker.check_document(doc, mode="local") == []


def test_the_vocabulary_is_exactly_four_states() -> None:
    assert checker.CLASSIFICATIONS == ("REPRODUCIBLE", "NON_REPRODUCIBLE", "NOT_YET_MEASURED", "PLATFORM_BLOCKED")
    assert checker.FAMILY_ORDER == ("wheel", "sdist", "deb", "rpm", "freebsd_pkg")
    assert checker.EVIDENCE_FILENAME == "REPRODUCIBILITY.json"


# --- evidence validator: negative (each case must be reported) -----------------------------------------------------------------------------------


def mutate(index: int, **changes: Any) -> Callable[[dict[str, Any]], None]:
    def apply(doc: dict[str, Any]) -> None:
        doc["results"][index].update(changes)

    return apply


def top(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def apply(doc: dict[str, Any]) -> None:
        doc.update(changes)

    return apply


def drop(family: str) -> Callable[[dict[str, Any]], None]:
    def apply(doc: dict[str, Any]) -> None:
        doc["results"] = [r for r in doc["results"] if r["family"] != family]

    return apply


def duplicate(doc: dict[str, Any]) -> None:
    doc["results"].insert(1, dict(doc["results"][0]))


DEB_INDEX, RPM_INDEX, PKG_INDEX = 2, 3, 4

CASES = [
    ("duplicate family", duplicate, "duplicate family: wheel"),
    ("unknown family", mutate(0, family="zipapp"), "unknown family"),
    ("uppercase sha", mutate(0, build_a_sha256="A" * 64), "build_a_sha256 must be a lowercase hexadecimal SHA-256"),
    ("short sha", mutate(0, build_b_sha256="abc"), "build_b_sha256 must be a lowercase hexadecimal SHA-256"),
    ("reproducible but hashes differ", mutate(0, build_b_sha256="b" * 64), "REPRODUCIBLE requires two identical"),
    ("reproducible but equal false", mutate(0, equal=False), "REPRODUCIBLE requires two identical"),
    ("non-reproducible but hashes equal", mutate(0, classification="NON_REPRODUCIBLE", diagnostic="x"), "NON_REPRODUCIBLE requires two different"),
    ("non-reproducible without a reason", mutate(0, classification="NON_REPRODUCIBLE", build_b_sha256="b" * 64, equal=False), "documented reason"),
    ("blocked without reason", mutate(RPM_INDEX, classification="PLATFORM_BLOCKED", diagnostic=""), "requires a diagnostic"),
    ("blocked but claims hashes", mutate(RPM_INDEX, classification="PLATFORM_BLOCKED", diagnostic="no rpmbuild"), "must not claim a build outcome"),
    ("unknown classification", mutate(0, classification="MOSTLY_REPRODUCIBLE"), "classification must be one of"),
    ("freebsd measured on Linux", mutate(PKG_INDEX, platform="Linux"), "native FreeBSD builder"),
    ("rpm without rpmbuild metadata", mutate(RPM_INDEX, tools={}), "tool metadata for rpmbuild is required"),
    ("deb without dpkg-deb metadata", mutate(DEB_INDEX, tools={"fakeroot": "1"}), "tool metadata for dpkg-deb is required"),
    ("freebsd without pkg metadata", mutate(PKG_INDEX, tools={"uname": "FreeBSD"}), "tool metadata for pkg is required"),
    ("wheel without build metadata", mutate(0, tools={"python": "3.13.5"}), "tool metadata for build is required"),
    ("a/b source commit mismatch", mutate(0, build_b_source_commit="f" * 40), "build_b_source_commit must equal"),
    ("build commit differs from evidence commit", mutate(0, build_a_source_commit="e" * 40, build_b_source_commit="e" * 40), "build_a_source_commit must equal"),
    ("a/b source tree mismatch", mutate(0, build_b_source_tree_sha256="c" * 64), "identical source tree"),
    ("same build root", mutate(0, separate_source_roots=False), "separate source/build roots"),
    ("output reused from A to B", mutate(0, separate_output_files=False), "separate output files"),
    ("wall-clock epoch origin", mutate(0, source_date_epoch_origin="wall-clock"), "never wall-clock time"),
    ("missing epoch", mutate(0, source_date_epoch=None), "source_date_epoch must be the commit timestamp"),
    ("non-numeric epoch", mutate(0, source_date_epoch="now"), "source_date_epoch must be the commit timestamp"),
    ("wrong artifact name", mutate(DEB_INDEX, artifact="pysh.deb"), "canonical basename"),
    ("wrong builder", mutate(DEB_INDEX, builder="scripts/make_deb.sh"), "repository builder"),
    ("missing platform metadata", mutate(0, platform=""), "platform metadata is required"),
    ("missing python metadata", mutate(0, python=""), "python metadata is required"),
    ("extra result field", mutate(0, extra="x"), "fields must be exactly"),
    ("schema version", top(schema_version=2), "schema_version must be 1"),
    ("short top-level commit", top(source_commit="abc"), "full lowercase 40-hex"),
    ("bad version", top(version="latest"), "version must be the release version"),
    ("changed build environment", top(build_environment={"TZ": "Europe/Warsaw", "LC_ALL": "C.UTF-8", "umask": "0022"}), "build_environment must be exactly"),
    ("build environment without umask", top(build_environment={"TZ": "UTC", "LC_ALL": "C.UTF-8"}), "build_environment must be exactly"),
    # --- release-byte binding ---
    ("release digest differs from both builds", mutate(0, release_sha256="c" * 64, release_matches_build_a=False, release_matches_build_b=False), "matches neither measured build"),
    ("release flags contradict the hashes", mutate(0, release_matches_build_b=False), "release_matches flags contradict"),
    ("release flags claim a match that is not there", mutate(0, release_sha256="c" * 64), "release_matches flags contradict"),
    ("non-reproducible release matches neither build", mutate(DEB_INDEX, classification="NON_REPRODUCIBLE", build_b_sha256="b" * 64, equal=False, diagnostic="members differ", release_sha256="d" * 64, release_matches_build_a=False, release_matches_build_b=False), "matches neither measured build"),
    ("reproducible release matches only an unrelated digest", mutate(DEB_INDEX, release_sha256="e" * 64), "matches neither measured build"),
    ("release digest malformed", mutate(0, release_sha256="NOT-A-DIGEST"), "release_sha256 must be a lowercase hexadecimal SHA-256"),
    ("release flags not booleans", mutate(0, release_matches_build_a="yes"), "must be booleans"),
    ("release digest without flags", mutate(0, release_matches_build_a=None, release_matches_build_b=None), "must be booleans"),
    ("blocked result claims a release binding", mutate(RPM_INDEX, classification="PLATFORM_BLOCKED", diagnostic="no rpmbuild", build_a_sha256=None, build_b_sha256=None, equal=None, build_a_source_commit=None, build_b_source_commit=None, build_a_source_tree_sha256=None, build_b_source_tree_sha256=None, separate_source_roots=None, separate_output_files=None), "must not claim a build outcome"),
    # --- resolved toolchain ---
    ("hatchling only has a >= requirement", mutate(0, tools={"python": "3.13.5", "build": "1.6.1", "hatchling": ">=1.27.0"}), "exact resolved version"),
    ("hatchling resolved version missing", mutate(0, tools={"python": "3.13.5", "build": "1.6.1"}), "tool metadata for hatchling is required"),
    ("sdist hatchling resolved version missing", mutate(1, tools={"python": "3.13.5", "build": "1.6.1"}), "tool metadata for hatchling is required"),
    ("build tool version missing", mutate(0, tools={"python": "3.13.5", "hatchling": "1.32.4"}), "tool metadata for build is required"),
    ("build tool version is a requirement", mutate(0, tools={"python": "3.13.5", "build": "build>=1", "hatchling": "1.32.4"}), "exact resolved version"),
    ("python version missing for wheel", mutate(0, tools={"build": "1.6.1", "hatchling": "1.32.4"}), "tool metadata for python is required"),
    ("declared requirement missing", mutate(0, declared_requirements=[]), "must record the declared hatchling requirement"),
    ("declared requirement is not a list", mutate(0, declared_requirements=">=1.27.0"), "list of requirement strings"),
    ("declared requirement on a deb", mutate(DEB_INDEX, declared_requirements=["hatchling>=1"]), "applies only to wheel and sdist"),
    ("rpm measured without an rpmbuild version", mutate(RPM_INDEX, tools={"rpmbuild": ""}), "tools must map tool names"),
    ("rpm tool is a banner, not a version", mutate(RPM_INDEX, tools={"rpmbuild": "RPM version 4.19.1.1"}), "exact resolved version"),
    ("dpkg-deb tool is a banner, not a version", mutate(DEB_INDEX, tools={"dpkg-deb": "Debian 'dpkg-deb' package archive backend version 1.22.22 (amd64)."}), "exact resolved version"),
    ("freebsd measured without a pkg version", mutate(PKG_INDEX, tools={"python": "3.13.5"}), "tool metadata for pkg is required"),
    ("freebsd measured without a python version", mutate(PKG_INDEX, tools={"pkg": "2.0.6"}), "tool metadata for python is required"),
    ("freebsd pkg version is a range", mutate(PKG_INDEX, tools={"pkg": ">=2.0", "python": "3.13.5"}), "exact resolved version"),
    ("empty results", top(results=[]), "non-empty list"),
    ("unordered results", lambda d: d["results"].reverse(), "canonical family order"),
    ("extra top-level field", top(generated_at="2026-01-01"), "top-level fields must be exactly"),
]


@pytest.mark.parametrize(("label", "change", "message"), CASES, ids=[c[0] for c in CASES])
def test_invalid_evidence_is_rejected(label: str, change: Callable[[dict[str, Any]], None], message: str) -> None:
    doc = final_document()
    change(doc)
    problems = checker.check_document(doc, mode="local")
    assert any(message in p for p in problems), (label, problems)


def test_a_source_commit_mismatch_against_the_expected_release_commit_is_rejected() -> None:
    problems = checker.check_document(final_document(), mode="final", source_commit="f" * 40)
    assert any("does not match the expected commit" in p for p in problems)


def test_not_yet_measured_is_rejected_in_final_mode() -> None:
    doc = final_document()
    doc["results"][DEB_INDEX] = result("deb", "NOT_YET_MEASURED")
    assert checker.check_document(doc, mode="local") == []
    assert any("NOT_YET_MEASURED is not accepted in final evidence" in p for p in checker.check_document(doc, mode="final"))


def test_platform_blocked_is_rejected_in_final_mode() -> None:
    doc = final_document()
    doc["results"][PKG_INDEX] = result("freebsd_pkg", "PLATFORM_BLOCKED")
    assert checker.check_document(doc, mode="local") == []
    assert any("PLATFORM_BLOCKED is not accepted in final evidence" in p for p in checker.check_document(doc, mode="final"))


@pytest.mark.parametrize("family", checker.FAMILY_ORDER)
def test_final_evidence_missing_any_family_is_rejected(family: str) -> None:
    doc = final_document()
    drop(family)(doc)
    assert any(f"{family} is missing" in p for p in checker.check_document(doc, mode="final"))
    assert checker.check_document(doc, mode="local") == []  # a subset is fine locally


@pytest.mark.parametrize("family", ["wheel", "sdist", "deb", "rpm"])
def test_final_evidence_requires_the_linux_families_to_be_measured_on_linux(family: str) -> None:
    doc = final_document()
    index = checker.FAMILY_ORDER.index(family)
    doc["results"][index]["platform"] = "FreeBSD"
    assert any("final evidence requires the" in p and "Linux" in p for p in checker.check_document(doc, mode="final"))


def test_final_evidence_with_incomplete_platform_coverage_is_rejected() -> None:
    doc = document([result(f) for f in ("wheel", "sdist", "deb", "rpm")])  # no native FreeBSD result
    problems = checker.check_document(doc, mode="final")
    assert any("freebsd_pkg is missing" in p for p in problems)


def test_a_malformed_document_never_crashes_the_validator() -> None:
    for broken in (None, [], "text", 5, {}, {"schema_version": 1}):
        assert checker.check_document(broken, mode="final")
    assert checker.check_document(final_document(), mode="weekly") == ["unknown mode 'weekly'"]
    doc = final_document()
    doc["results"][0] = "not an object"
    assert any("must be an object" in p for p in checker.check_document(doc, mode="local"))


def test_the_validator_cli(tmp_path, capsys) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(checker.canonical_json(final_document()), encoding="utf-8")
    broken = final_document()
    broken["results"][0]["equal"] = False
    bad.write_text(checker.canonical_json(broken), encoding="utf-8")
    assert checker.main([str(good), "--mode", "final", "--source-commit", COMMIT]) == 0
    assert "classification deb: REPRODUCIBLE" in capsys.readouterr().out
    assert checker.main([str(bad), "--mode", "final"]) == 1
    assert "REPRODUCIBLE requires two identical" in capsys.readouterr().err
    assert checker.main([str(tmp_path / "absent.json")]) == 1
    assert checker.main([str(good), "--source-commit", "main"]) == 2
    with pytest.raises(SystemExit) as misuse:
        checker.main([str(good), "--mode", "weekly"])
    assert misuse.value.code == 2


def test_the_validator_never_modifies_the_evidence(tmp_path) -> None:
    path = tmp_path / "e.json"
    path.write_text(checker.canonical_json(final_document()), encoding="utf-8")
    before = path.read_bytes()
    checker.main([str(path), "--mode", "final"])
    assert path.read_bytes() == before


# --- how non-identical artifacts are described ---------------------------------------------------------------------------------------------------------


def _ar(members: dict[str, bytes]) -> bytes:
    data = b"!<arch>\n"
    for name, body in members.items():
        data += f"{name:<16}{'0':<12}{'0':<6}{'0':<6}{'100644':<8}{len(body):<10}`\n".encode() + body
        data += b"\n" if len(body) % 2 else b""
    return data


def test_describe_difference_names_the_differing_archive_members(tmp_path) -> None:
    a, b = tmp_path / "a.deb", tmp_path / "b.deb"
    a.write_bytes(_ar({"debian-binary": b"2.0\n", "control.tar.xz": b"one", "data.tar.xz": b"same"}))
    b.write_bytes(_ar({"debian-binary": b"2.0\n", "control.tar.xz": b"two", "data.tar.xz": b"same"}))
    text = harness.describe_difference(a, b)
    assert "1 differing archive member(s): control.tar.xz" in text

    za, zb = tmp_path / "a.whl", tmp_path / "b.whl"
    for path, stamp in ((za, (2020, 1, 1, 0, 0, 0)), (zb, (2021, 2, 2, 0, 0, 0))):
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr(zipfile.ZipInfo("pysh/__init__.py", stamp), "x = 1\n")
    assert "pysh/__init__.py" in harness.describe_difference(za, zb)

    ta, tb = tmp_path / "a.tar", tmp_path / "b.tar"
    for path, mtime in ((ta, 1), (tb, 2)):
        with tarfile.open(path, "w") as bundle:
            info = tarfile.TarInfo("pkg/x")
            info.size, info.mtime = 1, mtime
            bundle.addfile(info, io.BytesIO(b"x"))
    assert "pkg/x" in harness.describe_difference(ta, tb)


def test_describe_difference_reports_container_only_differences(tmp_path) -> None:
    import gzip

    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as bundle:
        info = tarfile.TarInfo("x")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    a.write_bytes(gzip.compress(payload.getvalue(), mtime=1))
    b.write_bytes(gzip.compress(payload.getvalue(), mtime=2))
    assert "archive members are identical, only container or compression metadata differs" in harness.describe_difference(a, b)


# --- the harness and validator are test equipment for release assurance, not product code ---------------------------------------------------------------


def test_the_scripts_are_offline_shell_free_and_do_not_normalize_output() -> None:
    import re

    for name in ("measure_release_reproducibility.py", "check_reproducibility_evidence.py"):
        source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "shell=True" not in code and "os.system" not in code
        assert not re.search(r"urllib|socket|requests|http\.client|strip-nondeterminism|\butime\b", code)
        assert not re.search(r"time\.time\(|datetime\.now|utcnow", code)
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "measure_release_reproducibility" not in text and "check_reproducibility_evidence" not in text


# --- Slice 4 hardening: release-byte binding ------------------------------------------------------------------------------------


def deb_bytes(path_suffix: str = "") -> bytes:
    """What the fake deb builder writes (``path_suffix`` is its working directory in ``path`` mode)."""
    tail = f" {path_suffix}" if path_suffix else ""
    return f"deb epoch={COMMIT_EPOCH} tz=UTC lc=C.UTF-8{tail}\n".encode()


def stage(tmp_path: Path, name: str, content: bytes) -> Path:
    release = tmp_path / "release-assets"
    release.mkdir(parents=True, exist_ok=True)
    (release / name).write_bytes(content)
    return release


def test_the_staged_release_artifact_is_bound_to_both_reproducible_builds(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    release = stage(tmp_path, DEB, deb_bytes())
    before = {p.name: p.read_bytes() for p in release.iterdir()}
    doc = run(repo, tools, ["deb"], release_dir=release)
    entry = by_family(doc)["deb"]
    digest = hashlib.sha256(deb_bytes()).hexdigest()
    assert entry["release_sha256"] == entry["build_a_sha256"] == entry["build_b_sha256"] == digest
    assert entry["release_matches_build_a"] is True and entry["release_matches_build_b"] is True
    assert {p.name: p.read_bytes() for p in release.iterdir()} == before  # only read, never written
    assert checker.check_document(doc, mode="local", source_commit=repo.commit) == []


def test_without_a_release_directory_the_binding_is_null_and_not_final_evidence(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    doc = run(repo, tools, ["deb"])
    entry = by_family(doc)["deb"]
    assert entry["release_sha256"] is None and entry["release_matches_build_a"] is None
    assert checker.check_document(doc, mode="local") == []
    complete = final_document()
    complete["results"][2].update(release_sha256=None, release_matches_build_a=None, release_matches_build_b=None)
    assert any("requires the release-byte binding" in p for p in checker.check_document(complete, mode="final"))


def test_a_release_artifact_that_equals_neither_build_fails_the_measurement(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    release = stage(tmp_path, DEB, b"a different build of the same source\n")
    with pytest.raises(harness.MeasurementError, match=r"deb: the staged release artifact .* matches neither measured build"):
        run(repo, tools, ["deb"], release_dir=release)


def test_a_non_reproducible_family_must_still_ship_one_of_its_measured_outputs(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, "deb=path\n")
    work = tmp_path / "work"
    release = stage(tmp_path, DEB, deb_bytes(str(work / "a" / "deb" / "src")))
    doc = run(repo, tools, ["deb"], work_dir=work, release_dir=release)
    entry = by_family(doc)["deb"]
    assert entry["classification"] == "NON_REPRODUCIBLE"
    assert entry["release_matches_build_a"] is True and entry["release_matches_build_b"] is False
    assert entry["release_sha256"] == entry["build_a_sha256"] != entry["build_b_sha256"]
    assert checker.check_document(doc, mode="local") == []
    other = stage(tmp_path / "other", DEB, deb_bytes("/somewhere/else"))
    with pytest.raises(harness.MeasurementError, match="matches neither measured build"):
        run(repo, tools, ["deb"], work_dir=tmp_path / "work2", release_dir=other)


@pytest.mark.parametrize("problem", ["missing", "empty", "symlink"])
def test_a_missing_or_irregular_staged_artifact_fails(tmp_path, tools, problem: str) -> None:
    repo = make_repo(tmp_path)
    release = tmp_path / "release-assets"
    release.mkdir()
    if problem == "empty":
        (release / DEB).write_bytes(b"")
    elif problem == "symlink":
        (release / "real").write_bytes(deb_bytes())
        (release / DEB).symlink_to(release / "real")
    with pytest.raises(harness.MeasurementError, match="missing, empty or not a regular file"):
        run(repo, tools, ["deb"], release_dir=release)


def test_blocked_families_need_no_staged_artifact(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    release = tmp_path / "release-assets"
    release.mkdir()
    doc = run(repo, tools, ["rpm"], host=host(tools, without=("rpmbuild",)), release_dir=release)
    assert by_family(doc)["rpm"]["release_sha256"] is None


def test_the_cli_binds_the_release_and_refuses_a_mismatch(tmp_path, tools, capsys) -> None:
    repo = make_repo(tmp_path)
    release = stage(tmp_path, DEB, deb_bytes())
    out = tmp_path / "evidence.json"
    argv = ["--family", "deb", "--repo-root", str(repo.path), "--output", str(out), "--release-dir", str(release)]
    assert harness.main(argv) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["results"][0]["release_matches_build_a"] is True
    (release / DEB).write_bytes(b"tampered\n")
    out.unlink()
    assert harness.main(argv) == 1 and not out.exists()
    assert "matches neither measured build" in capsys.readouterr().err


def staged_for(final: dict[str, Any], tmp_path: Path) -> Path:
    """A release directory whose files hash to each result's build A digest (repro_support digests are of labels)."""
    release = tmp_path / "release-assets"
    release.mkdir(exist_ok=True)
    for entry in final["results"]:
        (release / entry["artifact"]).write_bytes((entry["family"] + "a").encode())
    return release


def test_merge_binds_every_measured_family_to_the_staged_public_artifacts(tmp_path) -> None:
    unbound_linux = linux_doc()
    unbound_freebsd = freebsd_doc()
    for doc in (unbound_linux, unbound_freebsd):
        for entry in doc["results"]:
            entry.update(release_sha256=None, release_matches_build_a=None, release_matches_build_b=None)
    release = staged_for(final_document(), tmp_path)
    merged = harness.merge_documents([unbound_linux, unbound_freebsd], COMMIT, release)
    for entry in merged["results"]:
        assert entry["release_sha256"] == entry["build_a_sha256"] and entry["release_matches_build_a"] is True
    assert checker.check_document(merged, mode="final", source_commit=COMMIT) == []


def test_merge_without_a_release_directory_refuses_unbound_evidence() -> None:
    unbound = linux_doc()
    for entry in unbound["results"]:
        entry.update(release_sha256=None, release_matches_build_a=None, release_matches_build_b=None)
    with pytest.raises(harness.MeasurementError, match="requires the release-byte binding"):
        harness.merge_documents([unbound, freebsd_doc()], COMMIT)


def test_merge_refuses_when_the_staged_artifact_differs_from_the_measured_builds(tmp_path) -> None:
    release = staged_for(final_document(), tmp_path)
    (release / DEB).write_bytes(b"swapped after measurement\n")
    with pytest.raises(harness.MeasurementError, match="matches neither measured build|recorded release digest"):
        harness.merge_documents([linux_doc(), freebsd_doc()], COMMIT, release)


def test_merge_refuses_a_recorded_digest_that_disagrees_with_the_staged_bytes(tmp_path) -> None:
    release = staged_for(final_document(), tmp_path)
    linux = linux_doc()
    linux["results"][0]["release_sha256"] = "9" * 64
    linux["results"][0]["release_matches_build_a"] = False
    linux["results"][0]["release_matches_build_b"] = False
    with pytest.raises(harness.MeasurementError):  # the input is already invalid: it matches neither build
        harness.merge_documents([linux, freebsd_doc()], COMMIT, release)


def test_the_merge_command_binds_with_release_dir(tmp_path) -> None:
    linux, freebsd, out = tmp_path / "linux.json", tmp_path / "freebsd.json", tmp_path / "REPRODUCIBILITY.json"
    for path, doc in ((linux, linux_doc()), (freebsd, freebsd_doc())):
        for entry in doc["results"]:
            entry.update(release_sha256=None, release_matches_build_a=None, release_matches_build_b=None)
        path.write_text(checker.canonical_json(doc), encoding="utf-8")
    release = staged_for(final_document(), tmp_path)
    argv = ["merge", "--input", str(linux), "--input", str(freebsd), "--source-commit", COMMIT, "--output", str(out)]
    assert harness.main(argv) == 1  # unbound evidence cannot become final evidence
    assert harness.main([*argv, "--release-dir", str(release)]) == 0
    assert checker.main([str(out), "--mode", "final", "--source-commit", COMMIT]) == 0


# --- Slice 4 hardening: the resolved build toolchain --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("banner", "version"),
    [
        ("Debian 'dpkg-deb' package archive backend version 1.22.22 (amd64).", "1.22.22"),
        ("RPM version 4.19.1.1", "4.19.1.1"),
        ("fakeroot version 1.37.1.1", "1.37.1.1"),
        ("2.0.6", "2.0.6"),
        ("  3.13.5  ", "3.13.5"),
        ("1.21.3_1", "1.21.3_1"),
    ],
)
def test_exact_versions_are_extracted_from_banners(banner: str, version: str) -> None:
    assert harness.exact_version("tool", banner) == version


@pytest.mark.parametrize("banner", ["", "dpkg-deb", ">=1.27.0", "version", "latest", "tool 1.2"])
def test_a_banner_without_an_exact_version_is_rejected(banner: str) -> None:
    with pytest.raises(harness.MeasurementError, match="cannot determine the exact version"):
        harness.exact_version("tool", banner)


def test_the_resolved_backend_is_read_from_the_build_environments_pip_log(tmp_path) -> None:
    log = tmp_path / "pip.log"
    log.write_text(
        "2026 Collecting hatchling>=1.27.0\n2026 Successfully installed hatchling-1.32.4 packaging-26.3 pluggy-1.6.0\n"
        "2026 Successfully installed hatchling-1.32.4 packaging-26.3\n", encoding="utf-8")
    assert harness.resolved_backend(log) == "1.32.4"


@pytest.mark.parametrize(
    "text",
    [
        "Collecting hatchling>=1.27.0\n",  # only a requirement, nothing was installed
        "Successfully installed packaging-26.3\n",
        "Successfully installed hatchling-1.32.4\nSuccessfully installed hatchling-1.33.0\n",
        "",
    ],
)
def test_an_unprovable_or_inconsistent_backend_is_an_error(tmp_path, text: str) -> None:
    log = tmp_path / "pip.log"
    log.write_text(text, encoding="utf-8")
    with pytest.raises(harness.MeasurementError, match="cannot prove the resolved hatchling version"):
        harness.resolved_backend(log)
    with pytest.raises(harness.MeasurementError, match="unreadable"):
        harness.resolved_backend(tmp_path / "absent.log")


def test_the_wheel_names_the_backend_that_built_it(tmp_path) -> None:
    wheel = tmp_path / "x.whl"
    with zipfile.ZipFile(wheel, "w") as bundle:
        bundle.writestr("pkg-1.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: hatchling 1.32.4\n")
    assert harness.wheel_generator(wheel) == "hatchling 1.32.4"
    bare = tmp_path / "bare.whl"
    with zipfile.ZipFile(bare, "w") as bundle:
        bundle.writestr("pkg-1.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    with pytest.raises(harness.MeasurementError, match="records no Generator"):
        harness.wheel_generator(bare)
    (tmp_path / "text.whl").write_text("not a zip", encoding="utf-8")
    with pytest.raises(harness.MeasurementError, match="not a readable wheel"):
        harness.wheel_generator(tmp_path / "text.whl")


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("nolog", "cannot prove the resolved hatchling version"),
        ("twoversions", "cannot prove the resolved hatchling version"),
        ("wrongbackend", "generated by 'hatchling 9.9.9' but the build environment resolved hatchling 1.27.0"),
    ],
)
def test_wheel_and_sdist_need_a_provable_resolved_backend(tmp_path, tools, mode: str, message: str) -> None:
    repo = make_repo(tmp_path, f"wheel={mode}\n")
    with pytest.raises(harness.MeasurementError, match=message):
        run(repo, tools, ["wheel", "sdist"])


def test_a_backend_that_is_not_hatchling_is_rejected(tmp_path, tools) -> None:
    other = PYPROJECT.replace("hatchling.build", "setuptools.build_meta")
    repo = make_repo(tmp_path, extra={"pyproject.toml": other})
    with pytest.raises(harness.MeasurementError, match="unsupported build backend"):
        run(repo, tools, ["wheel"])


def test_the_declared_requirement_is_kept_apart_from_the_resolved_version(tmp_path, tools) -> None:
    repo = make_repo(tmp_path)
    entry = by_family(run(repo, tools, ["wheel"]))["wheel"]
    assert entry["declared_requirements"] == ["hatchling>=1.27.0"]
    assert entry["tools"]["hatchling"] == "1.27.0"
    assert entry["tools"]["hatchling"] != entry["declared_requirements"][0]


# --- Slice 4 hardening: the source tree equals a checkout, whatever the caller's umask -----------------------------------------------------


def test_the_extracted_tree_has_the_modes_of_a_git_checkout_under_umask_022(tmp_path, tools) -> None:
    repo = make_repo(tmp_path, extra={"tools/run.sh": "#!/bin/sh\n"})
    (repo.path / "tools" / "run.sh").chmod(0o755)
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "exec bit")
    source = harness.resolve_source(repo.path, None)
    previous = os.umask(0o002)  # a permissive caller umask must not leak into the measured tree
    try:
        harness.materialize(source, tmp_path / "tree")
    finally:
        os.umask(previous)
    tree = tmp_path / "tree"
    assert (tree / "pyproject.toml").stat().st_mode & 0o777 == 0o644
    assert (tree / "tools" / "run.sh").stat().st_mode & 0o777 == 0o755
    assert (tree / "tools").stat().st_mode & 0o777 == 0o755 and (tree / "scripts").stat().st_mode & 0o777 == 0o755


# --- the RPM builder honors the commit epoch (first real dry run: Issue #51 Slice 5) -----------------------------------------


def rpm_tree(tmp_path: Path) -> Path:
    """The smallest source tree scripts/build_rpm.sh accepts, with a fake rpmbuild that records its arguments."""
    root = tmp_path / "rpm-tree"
    for relative in ("scripts/build_rpm.sh", "scripts/_pysh_version.sh"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "src" / "pysh").mkdir(parents=True)
    (root / "src" / "pysh" / "__init__.py").write_text("", encoding="utf-8")
    for relative in ("packaging/rpm/pysh-shell.spec", "packaging/wrappers/pysh.sh"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("x\n", encoding="utf-8")
    (root / "LICENSE").write_text("x\n", encoding="utf-8")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    rpmbuild = fake / "rpmbuild"
    rpmbuild.write_text(
        "#!/usr/bin/env bash\nset -eu\nprintf '%s\\n' \"$@\" > \"$RECORD\"\n"
        "top=\"$(printf '%s\\n' \"$@\" | sed -n 's/^_topdir //p')\"\n"
        f"mkdir -p \"$top/RPMS/noarch\"; echo rpm > \"$top/RPMS/noarch/{RPM}\"\n",
        encoding="utf-8",
    )
    rpmbuild.chmod(0o755)
    return root


def run_rpm_builder(root: Path, tmp_path: Path, epoch: str | None) -> list[str]:
    record = tmp_path / "rpmbuild-args"
    env = {"PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}", "RECORD": str(record), "HOME": str(tmp_path)}
    if epoch is not None:
        env["SOURCE_DATE_EPOCH"] = epoch
    done = subprocess.run(["bash", str(root / "scripts" / "build_rpm.sh")], capture_output=True, text=True, check=False, env=env)
    assert done.returncode == 0, done.stderr
    return record.read_text(encoding="utf-8").splitlines()


def test_the_rpm_builder_enables_the_epoch_macros_when_an_epoch_is_set(tmp_path) -> None:
    root = rpm_tree(tmp_path)
    args = run_rpm_builder(root, tmp_path, COMMIT_EPOCH)
    assert "use_source_date_epoch_as_buildtime 1" in args  # rpmbuild ignores SOURCE_DATE_EPOCH without these
    assert "clamp_mtime_to_source_date_epoch 1" in args
    assert args.count("--define") >= 6 and args[-2] == "-bb"


def test_the_rpm_builder_is_unchanged_without_an_epoch(tmp_path) -> None:
    root = rpm_tree(tmp_path)
    args = run_rpm_builder(root, tmp_path, None)
    assert not any("source_date_epoch" in arg for arg in args)
    assert any(arg.startswith("pysh_version ") for arg in args) and "-bb" in args


def test_the_rpm_builder_never_rewrites_the_built_package() -> None:
    import re

    code = "\n".join(
        line for line in (REPO_ROOT / "scripts" / "build_rpm.sh").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert not re.search(r"strip-nondeterminism|\btouch\b|\butime\b|rpmrebuild|rpmsign|add-determinism", code)
