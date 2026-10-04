#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/measure_release_reproducibility.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Measure per-artifact release reproducibility with independent A/B builds (Issue #51, Slice 4).

For each requested family (wheel, sdist, deb, rpm, freebsd_pkg) the real repository
builder is run twice, from two independent source/build roots that are each extracted
from the exact source commit (``git archive`` or a host-provided archive of that
commit). The two public artifacts are compared by SHA-256 computed here; the result is
recorded as machine-readable evidence (``scripts/check_reproducibility_evidence.py``
owns the schema and validates every document before it is written).

Classifications: REPRODUCIBLE (byte-identical), NON_REPRODUCIBLE (different bytes) and
PLATFORM_BLOCKED (the host genuinely cannot build the family: missing tooling or not a
native FreeBSD builder). A build that fails is an error, never a classification, and
nothing is written for it. No artifact is ever normalized, renamed or copied from one
build to the other, and nothing is published, tagged or uploaded.

``SOURCE_DATE_EPOCH`` is always the commit timestamp of the exact source commit, never
wall-clock time.

Two further bindings make the evidence about the artifact that is actually shipped:

* Release-byte binding: with ``--release-dir`` the already-staged public artifact is hashed
  and must equal build A or build B (``release_sha256``, ``release_matches_build_a``,
  ``release_matches_build_b``). Nothing is copied into the release tree; a release artifact
  that matches neither measured build is an error.
* Resolved toolchain: the evidence records the exact tool versions that performed the build.
  For wheel and sdist the isolated PEP 517 environment's real ``hatchling`` version is taken
  from the pip log of that environment (``PIP_LOG``) and corroborated by the ``Generator``
  line of the built wheel; the declared requirement is recorded separately.

``merge`` combines the evidence of several platforms into one final document, only when
the result is valid final evidence.

Exit codes: 0 evidence written, 1 measurement failed, 2 command-line misuse.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import io
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_reproducibility_evidence as evidence  # noqa: E402
from scripts import generate_release_sboms as sboms  # noqa: E402

DEFAULT_BUILD_TIMEOUT_SECONDS = 1800.0
TOOL_TIMEOUT_SECONDS = 60.0
GIT_TIMEOUT_SECONDS = 120.0
MAX_TAIL_CHARS = 1500
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_DIFFERENCES = 8
#: Environment that is forwarded when set (network access for build isolation, certificates).
PASSTHROUGH_ENV = (
    "PATH", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
    "PIP_CERT", "PYSH_FREEBSD_PYTHON_VERSION",
)


class MeasurementError(Exception):
    """The measurement could not be completed; no evidence is written."""


@dataclasses.dataclass(frozen=True)
class Host:
    """The build host as seen by the harness; injectable so tests need no real tooling."""

    system: str
    release: str
    machine: str
    python: str
    which: Callable[[str], str | None]

    @classmethod
    def detect(cls) -> Host:
        return cls(platform.system(), platform.release(), platform.machine(), platform.python_version(), shutil.which)


@dataclasses.dataclass(frozen=True)
class Source:
    """Where the exact commit comes from: the repository (``git archive``) or an archive of it."""

    commit: str
    epoch: str
    repo: Path | None = None
    archive: Path | None = None


@dataclasses.dataclass(frozen=True)
class Group:
    """Families that one builder invocation produces."""

    key: str
    families: tuple[str, ...]
    argv: tuple[str, ...]


GROUPS = (
    Group("pypi", ("wheel", "sdist"), ("bash", evidence.BUILDERS["wheel"])),
    Group("deb", ("deb",), ("bash", evidence.BUILDERS["deb"])),
    Group("rpm", ("rpm",), ("bash", evidence.BUILDERS["rpm"])),
    Group("freebsd_pkg", ("freebsd_pkg",), ("sh", evidence.BUILDERS["freebsd_pkg"])),
)
OUTPUT_DIRS = {
    "wheel": "dist", "sdist": "dist", "deb": "dist/os/deb", "rpm": "dist/os/rpm", "freebsd_pkg": "dist/os/freebsd",
}
OUTPUT_SUFFIXES = {
    "wheel": (".whl",), "sdist": (".tar.gz",), "deb": (".deb",), "rpm": (".rpm",), "freebsd_pkg": (".pkg",),
}


# --- bounded subprocesses -------------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RunResult:
    returncode: int
    output: str


def run_bounded(
    argv: Sequence[str], cwd: Path, env: dict[str, str], timeout: float, umask: int | None = None
) -> RunResult:
    """Run an explicit argv (never a shell) in its own process group with a hard timeout.

    ``umask`` (when given) is part of the declared build contract: package contents such as
    directory modes depend on it, so a measured build never inherits the caller's umask.
    """
    try:
        process = subprocess.Popen(  # noqa: S603 - explicit argv, no shell
            list(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, shell=False, umask=-1 if umask is None else umask,
        )
    except OSError as error:
        raise MeasurementError(f"cannot execute {argv[0]}: {error.strerror or error}") from error
    try:
        raw, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise MeasurementError(f"{' '.join(argv[:2])} exceeded the {timeout:.0f}s time limit") from error
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)  # no stray descendant outlives the build
    return RunResult(process.returncode, raw.decode("utf-8", errors="replace"))


def _tail(text: str) -> str:
    return " ".join(text.split())[-MAX_TAIL_CHARS:]


def tool_line(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> str:
    """First non-empty output line of a ``--version`` style command."""
    result = run_bounded(argv, cwd, env, TOOL_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise MeasurementError(f"{' '.join(argv)} failed (exit {result.returncode}): {_tail(result.output)}")
    for line in result.output.splitlines():
        if line.strip():
            return line.strip()
    raise MeasurementError(f"{' '.join(argv)} printed nothing")


# --- source materialization ---------------------------------------------------------------------------------------------


def resolve_source(repo: Path, commit: str | None) -> Source:
    """The exact commit (default: HEAD) and its commit timestamp, from git."""
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"}
    resolved = run_bounded(["git", "rev-parse", "--verify", f"{commit or 'HEAD'}^{{commit}}"], repo, env, GIT_TIMEOUT_SECONDS)
    sha = resolved.output.strip()
    if resolved.returncode != 0 or not evidence.COMMIT_RE.fullmatch(sha):
        raise MeasurementError(f"cannot resolve the source commit: {_tail(resolved.output)}")
    stamp = run_bounded(["git", "show", "-s", "--format=%ct", sha], repo, env, GIT_TIMEOUT_SECONDS)
    epoch = stamp.output.strip()
    if stamp.returncode != 0 or not evidence.EPOCH_RE.fullmatch(epoch):
        raise MeasurementError(f"cannot read the commit timestamp of {sha[:12]}")
    return Source(sha, epoch, repo=repo)


def checkout_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """Extract exactly what ``git checkout`` creates under the declared umask (022).

    ``git archive`` records group-writable modes (0664/0775); a checkout has 0644/0755 (and
    0755 for files with the executable bit). Package contents depend on these source modes,
    so the measured tree must equal a real checkout. This prepares the SOURCE tree only;
    build output is never touched.
    """
    member = tarfile.data_filter(member, path)
    if member is None or member.issym() or member.islnk():
        return member
    if member.isdir():
        return member.replace(mode=0o755)
    return member.replace(mode=0o755 if member.mode & 0o111 else 0o644)


def _extract(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as bundle:
            bundle.extractall(destination, filter=checkout_filter)
    except (tarfile.TarError, OSError) as error:
        raise MeasurementError(f"cannot extract the source archive: {error}") from error


def materialize(source: Source, destination: Path) -> None:
    """Extract an independent copy of the exact commit into the (new) ``destination``."""
    if source.archive is not None:
        data = source.archive.read_bytes()
    else:
        assert source.repo is not None
        env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"}
        try:
            done = subprocess.run(  # noqa: S603 - explicit argv, no shell
                ["git", "-C", str(source.repo), "archive", "--format=tar", source.commit],
                capture_output=True, check=False, env=env, timeout=GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MeasurementError(f"git archive failed: {error}") from error
        if done.returncode != 0:
            raise MeasurementError(f"git archive failed: {_tail(done.stderr.decode('utf-8', errors='replace'))}")
        data = done.stdout
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        raise MeasurementError("the source archive is empty or implausibly large")
    _extract(data, destination)
    if not (destination / "pyproject.toml").is_file():
        raise MeasurementError("the source archive has no pyproject.toml at its top level")


def tree_digest(root: Path) -> str:
    """Digest of the source tree: relative paths, kinds, executable bits and content (no timestamps)."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            digest.update(f"L {relative} {os.readlink(path)}\n".encode())
        elif stat.S_ISDIR(info.st_mode):
            digest.update(f"D {relative}\n".encode())
        elif stat.S_ISREG(info.st_mode):
            executable = "x" if info.st_mode & 0o111 else "-"
            digest.update(f"F {relative} {executable} {sboms.sha256_of(path)}\n".encode())
        else:
            raise MeasurementError(f"unsupported file type in the source tree: {relative}")
    return digest.hexdigest()


def project_version(root: Path) -> str:
    try:
        return str(tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    except (OSError, KeyError, ValueError) as error:
        raise MeasurementError(f"cannot read the version of the source commit: {error}") from error


# --- environment and tooling ------------------------------------------------------------------------------------------------


def build_environment(source: Source, scratch: Path, python: str | None) -> dict[str, str]:
    """The declared build contract: private HOME/TMPDIR, fixed locale and zone, commit-time epoch."""
    home, tmp = scratch / "home", scratch / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = {name: os.environ[name] for name in PASSTHROUGH_ENV if name in os.environ}
    env.update({
        "HOME": str(home), "TMPDIR": str(tmp), "LANG": "C.UTF-8", **evidence.BUILD_VARIABLES,
        "SOURCE_DATE_EPOCH": source.epoch,
    })
    if python is not None:
        env["PYTHON_BIN"] = python
        env["PIP_LOG"] = str(scratch / "pip.log")  # records what the isolated build environment installed
    return env


def blocked_reason(group: Group, host: Host, python: str, probe: Callable[[Sequence[str]], bool]) -> str | None:
    """Why the host genuinely cannot build the group, or ``None`` when it can."""
    if group.key == "pypi":
        if host.which(python) is None and not Path(python).is_file():
            return f"the Python interpreter {python!r} was not found"
        if not probe([python, "-c", "import build, twine"]):
            return f"the Python modules 'build' and 'twine' are not installed for {python}"
    elif group.key == "deb":
        if host.which("dpkg-deb") is None:
            return "dpkg-deb was not found on PATH"
    elif group.key == "rpm":
        if host.which("rpmbuild") is None:
            return "rpmbuild was not found on PATH"
    elif group.key == "freebsd_pkg":
        if host.system != "FreeBSD":
            return f"a FreeBSD .pkg can only be measured on a native FreeBSD builder (this host is {host.system})"
        if host.which("pkg") is None:
            return "pkg was not found on PATH"
    return None


VERSION_TOKEN = r"[0-9][0-9A-Za-z.+~_-]*"
BACKEND = "hatchling"


def exact_version(tool: str, line: str) -> str:
    """The exact version in a ``--version`` banner (``... version X`` or a bare ``X``)."""
    match = re.search(rf"\bversion\s+({VERSION_TOKEN})", line) or re.fullmatch(rf"\s*({VERSION_TOKEN})\s*", line)
    if match is None or evidence.EXACT_VERSION_RE.fullmatch(match.group(1)) is None:
        raise MeasurementError(f"cannot determine the exact version of {tool} from {line!r}")
    return match.group(1)


def declared_requirements(root: Path) -> list[str]:
    """The build-system requirements declared in pyproject.toml (a declaration, not a resolution)."""
    try:
        build_system = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["build-system"]
    except (OSError, KeyError, ValueError) as error:
        raise MeasurementError(f"cannot read build-system from pyproject.toml: {error}") from error
    if not str(build_system.get("build-backend", "")).startswith(BACKEND):
        raise MeasurementError(f"unsupported build backend {build_system.get('build-backend')!r}: the harness resolves {BACKEND}")
    return [str(item) for item in build_system["requires"]]


def resolved_backend(log: Path) -> str:
    """The backend version the isolated build environments actually installed, from their pip log."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise MeasurementError(
            f"cannot prove the resolved {BACKEND} version from the build environment: its pip log is unreadable "
            f"({error.strerror or error})"
        ) from error
    versions = {
        token[len(BACKEND) + 1:]
        for line in re.findall(r"Successfully installed (.+)$", text, re.M)
        for token in line.split() if token.startswith(f"{BACKEND}-")
    }
    if len(versions) != 1:
        raise MeasurementError(
            f"cannot prove the resolved {BACKEND} version from the build environment (found {sorted(versions)})"
        )
    version = next(iter(versions))
    if evidence.EXACT_VERSION_RE.fullmatch(version) is None:
        raise MeasurementError(f"the resolved {BACKEND} version is not an exact version: {version!r}")
    return version


def wheel_generator(wheel: Path) -> str:
    """``Generator`` of a built wheel (for example ``hatchling 1.32.4``): what built these very bytes."""
    try:
        with zipfile.ZipFile(wheel) as bundle:
            names = [n for n in bundle.namelist() if n.endswith(".dist-info/WHEEL")]
            if len(names) != 1:
                raise MeasurementError(f"{wheel.name} must contain exactly one .dist-info/WHEEL")
            text = bundle.read(names[0]).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError) as error:
        raise MeasurementError(f"{wheel.name} is not a readable wheel: {error}") from error
    match = re.search(r"^Generator:\s*(.+)$", text, re.M)
    if match is None:
        raise MeasurementError(f"{wheel.name} records no Generator")
    return match.group(1).strip()


def collect_tools(family: str, host: Host, python: str, cwd: Path, env: dict[str, str]) -> dict[str, str]:
    """Exact versions of the real tooling the measured builder uses (the resolved backend is added later)."""
    tools: dict[str, str] = {}
    snippet = "import platform; print(platform.python_version())"
    if family in {"wheel", "sdist"}:
        tools["python"] = exact_version("python", tool_line([python, "-c", snippet], cwd, env))
        for module in ("build", "twine"):
            line = tool_line([python, "-c", f"import importlib.metadata as m; print(m.version({module!r}))"], cwd, env)
            tools[module] = exact_version(module, line)
    elif family == "deb":
        tools["dpkg-deb"] = exact_version("dpkg-deb", tool_line(["dpkg-deb", "--version"], cwd, env))
        if host.which("fakeroot"):
            tools["fakeroot"] = exact_version("fakeroot", tool_line(["fakeroot", "--version"], cwd, env))
    elif family == "rpm":
        tools["rpmbuild"] = exact_version("rpmbuild", tool_line(["rpmbuild", "--version"], cwd, env))
    elif family == "freebsd_pkg":
        tools["pkg"] = exact_version("pkg", tool_line(["pkg", "--version"], cwd, env))
        tools["python"] = exact_version("python", tool_line([python, "-c", snippet], cwd, env))
    return tools


# --- one A/B measurement ---------------------------------------------------------------------------------------------------------------


def locate_outputs(root: Path, group: Group, version: str) -> dict[str, Path]:
    """The canonical artifacts one build produced; names are validated, never taken from the builder."""
    found: dict[str, Path] = {}
    for family in group.families:
        directory = (root / OUTPUT_DIRS[family]).resolve()
        if root.resolve() not in directory.parents and directory != root.resolve():
            raise MeasurementError(f"{family}: the output directory escapes the build root")
        accepted = evidence.expected_artifact(family, version)
        present = [p for p in sorted(directory.iterdir()) if p.name.endswith(OUTPUT_SUFFIXES[family])] if directory.is_dir() else []
        matching = [p for p in present if p.name in accepted]
        unexpected = [p.name for p in present if p.name not in accepted]
        if len(matching) != 1 or unexpected:
            raise MeasurementError(
                f"{family}: the builder must produce exactly one of {list(accepted)}; "
                f"found {[p.name for p in present]}"
            )
        artifact = matching[0]
        if artifact.is_symlink() or not artifact.is_file() or artifact.resolve().parent != directory:
            raise MeasurementError(f"{family}: {artifact.name} is not a regular file inside the build output directory")
        if artifact.stat().st_size == 0:
            raise MeasurementError(f"{family}: {artifact.name} is empty")
        found[family] = artifact
    return found


def describe_difference(first: Path, second: Path) -> str:
    """A bounded, deterministic description of how two non-identical artifacts differ."""
    a, b = first.read_bytes(), second.read_bytes()
    summary = f"sizes {len(a)} and {len(b)} bytes"
    differences: list[str] = []
    if a.startswith(b"!<arch>\n") and b.startswith(b"!<arch>\n"):
        left, right = _ar_members(a), _ar_members(b)
    elif zipfile.is_zipfile(first) and zipfile.is_zipfile(second):
        left, right = _zip_members(first), _zip_members(second)
    elif tarfile.is_tarfile(first) and tarfile.is_tarfile(second):
        left, right = _tar_members(first), _tar_members(second)
    else:
        offset = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))
        return f"{summary}; first differing byte at offset {offset}"
    for name in sorted(set(left) | set(right)):
        if left.get(name) != right.get(name):
            differences.append(name)
    if not differences:
        return f"{summary}; archive members are identical, only container or compression metadata differs"
    shown = ", ".join(differences[:MAX_DIFFERENCES])
    more = f" (+{len(differences) - MAX_DIFFERENCES} more)" if len(differences) > MAX_DIFFERENCES else ""
    return f"{summary}; {len(differences)} differing archive member(s): {shown}{more}"


def _ar_members(data: bytes) -> dict[str, tuple[str, str]]:
    members: dict[str, tuple[str, str]] = {}
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        name = header[:16].decode("ascii", errors="replace").strip().rstrip("/")
        size = int(header[48:58].strip() or b"0")
        body = data[offset + 60:offset + 60 + size]
        members[name] = (header[16:28].decode("ascii", errors="replace").strip(), hashlib.sha256(body).hexdigest())
        offset += 60 + size + (size % 2)
    return members


def _zip_members(path: Path) -> dict[str, tuple[Any, ...]]:
    with zipfile.ZipFile(path) as bundle:
        return {i.filename: (i.CRC, i.file_size, i.date_time, i.external_attr) for i in bundle.infolist()}


def _tar_members(path: Path) -> dict[str, tuple[Any, ...]]:
    members: dict[str, tuple[Any, ...]] = {}
    with tarfile.open(path, "r:*") as bundle:
        for info in bundle:
            body = bundle.extractfile(info) if info.isfile() else None
            digest = hashlib.sha256(body.read()).hexdigest() if body is not None else ""
            members[info.name] = (info.mtime, info.mode, info.uid, info.gid, info.size, digest)
    return members


def measure_group(
    group: Group, families: Sequence[str], source: Source, host: Host, work: Path, *, python: str, timeout: float,
    probe: Callable[[Sequence[str]], bool], version: str,
) -> list[dict[str, Any]]:
    """Two independent builds of one builder group, classified per requested family."""
    blocked = blocked_reason(group, host, python, probe)
    base = {
        "platform": host.system, "platform_release": host.release, "architecture": host.machine,
        "python": host.python,
    }
    if blocked is not None:
        return [_blocked(family, base, blocked, evidence.expected_artifact(family, version)[0]) for family in families]

    roots = {side: work / side / group.key / "src" for side in ("a", "b")}
    outputs: dict[str, dict[str, Path]] = {}
    digests: dict[str, str] = {}
    for side in ("a", "b"):
        root = roots[side]
        materialize(source, root)
        for forbidden in ("dist", "build"):
            if (root / forbidden).exists():
                raise MeasurementError(f"build {side.upper()}: the source tree already contains {forbidden}/")
        digests[side] = tree_digest(root)
        if project_version(root) != version:
            raise MeasurementError("builds A and B read a different version from the source commit")
    if digests["a"] != digests["b"]:
        raise MeasurementError("builds A and B were not made from an identical source tree")
    if roots["a"] == roots["b"] or roots["a"] in roots["b"].parents or roots["b"] in roots["a"].parents:
        raise MeasurementError("builds A and B must use separate, non-nested source/build roots")

    tools: dict[str, str] = {}
    declared: list[str] = []
    backends: dict[str, str] = {}
    for side in ("a", "b"):
        root = roots[side]
        scratch = work / side / group.key / "scratch"
        env = build_environment(source, scratch, python if group.key == "pypi" else None)
        if side == "a":
            for family in families:
                tools.update(collect_tools(family, host, python, root, env))
            if group.key == "pypi":
                declared = declared_requirements(root)
        done = run_bounded(group.argv, root, env, timeout, umask=evidence.BUILD_UMASK)
        if done.returncode != 0:
            raise MeasurementError(
                f"build {side.upper()} of {group.key} failed (exit {done.returncode}): {_tail(done.output)}"
            )
        outputs[side] = locate_outputs(root, group, version)
        if group.key == "pypi":
            backends[side] = resolved_backend(scratch / "pip.log")
            generator = wheel_generator(outputs[side]["wheel"])
            if generator != f"{BACKEND} {backends[side]}":
                raise MeasurementError(
                    f"build {side.upper()}: the wheel was generated by {generator!r} but the build environment "
                    f"resolved {BACKEND} {backends[side]}"
                )
    if group.key == "pypi":
        if backends["a"] != backends["b"]:
            raise MeasurementError(
                f"builds A and B resolved different {BACKEND} versions ({backends['a']} and {backends['b']})"
            )
        tools[BACKEND] = backends["a"]
        base = {**base, "python": tools["python"]}

    results: list[dict[str, Any]] = []
    for family in families:
        first, second = outputs["a"][family], outputs["b"][family]
        if first.name != second.name:
            raise MeasurementError(f"{family}: builds A and B produced different file names")
        if first.resolve() == second.resolve() or os.path.samefile(first, second):
            raise MeasurementError(f"{family}: builds A and B share one output file")
        sha_a, sha_b = sboms.sha256_of(first), sboms.sha256_of(second)
        equal = sha_a == sha_b
        results.append({
            **base,
            "family": family, "artifact": first.name, "builder": evidence.BUILDERS[family],
            "classification": evidence.REPRODUCIBLE if equal else evidence.NON_REPRODUCIBLE,
            "tools": dict(tools), "declared_requirements": list(declared), "source_date_epoch": source.epoch,
            "source_date_epoch_origin": evidence.SDE_ORIGIN,
            "build_a_sha256": sha_a, "build_b_sha256": sha_b, "equal": equal,
            "build_a_source_commit": source.commit, "build_b_source_commit": source.commit,
            "build_a_source_tree_sha256": digests["a"], "build_b_source_tree_sha256": digests["b"],
            "separate_source_roots": True, "separate_output_files": True,
            "release_sha256": None, "release_matches_build_a": None, "release_matches_build_b": None,
            "diagnostic": "" if equal else describe_difference(first, second),
        })
    return results


def _blocked(family: str, base: dict[str, str], reason: str, artifact: str) -> dict[str, Any]:
    return {
        **base,
        "family": family, "artifact": artifact, "builder": evidence.BUILDERS[family],
        "classification": evidence.PLATFORM_BLOCKED, "tools": {}, "declared_requirements": [],
        "source_date_epoch": None, "source_date_epoch_origin": None,
        "build_a_sha256": None, "build_b_sha256": None, "equal": None,
        "build_a_source_commit": None, "build_b_source_commit": None,
        "build_a_source_tree_sha256": None, "build_b_source_tree_sha256": None,
        "separate_source_roots": None, "separate_output_files": None,
        "release_sha256": None, "release_matches_build_a": None, "release_matches_build_b": None,
        "diagnostic": reason,
    }


def bind_release(result: dict[str, Any], release_dir: Path) -> None:
    """Hash the already-staged public artifact and bind it to the measured builds.

    The staged file is only read: nothing is copied into the release tree. A staged artifact
    that equals neither build A nor build B is an error (the evidence would not describe the
    bytes that ship).
    """
    if result["classification"] not in evidence.MEASURED:
        return
    name = result["artifact"]
    path = release_dir / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise MeasurementError(f"{result['family']}: the staged release artifact {name} is missing, empty or not a regular file")
    digest = sboms.sha256_of(path)
    recorded = result["release_sha256"]
    if recorded is not None and recorded != digest:
        raise MeasurementError(f"{result['family']}: the recorded release digest does not match the staged {name}")
    matches_a, matches_b = digest == result["build_a_sha256"], digest == result["build_b_sha256"]
    if not (matches_a or matches_b):
        raise MeasurementError(
            f"{result['family']}: the staged release artifact {name} (sha256 {digest[:12]}...) matches neither "
            f"measured build (A {result['build_a_sha256'][:12]}..., B {result['build_b_sha256'][:12]}...)"
        )
    result.update(release_sha256=digest, release_matches_build_a=matches_a, release_matches_build_b=matches_b)


def measure(
    families: Sequence[str], source: Source, *, host: Host | None = None, python: str | None = None,
    timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS, work_dir: Path | None = None,
    release_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure the requested families and return a validated evidence document."""
    host = host or Host.detect()
    python = python or sys.executable
    requested = [f for f in evidence.FAMILY_ORDER if f in set(families)]
    if not requested or len(set(families)) != len(families):
        raise MeasurementError("choose at least one family, each at most once")

    def probe(argv: Sequence[str]) -> bool:
        try:
            return run_bounded(argv, REPO_ROOT, {"PATH": os.environ.get("PATH", "")}, TOOL_TIMEOUT_SECONDS).returncode == 0
        except MeasurementError:
            return False

    with _work_directory(work_dir) as work:
        probe_root = work / "version"
        materialize(source, probe_root)
        version = project_version(probe_root)
        shutil.rmtree(probe_root)
        results: list[dict[str, Any]] = []
        for group in GROUPS:
            wanted = [f for f in group.families if f in requested]
            if wanted:
                results.extend(measure_group(
                    group, wanted, source, host, work, python=python, timeout=timeout, probe=probe, version=version,
                ))
    results.sort(key=lambda r: evidence.FAMILY_ORDER.index(r["family"]))
    if release_dir is not None:
        for result in results:
            bind_release(result, release_dir)
    document = {
        "schema_version": evidence.SCHEMA_VERSION, "source_commit": source.commit, "version": version,
        "build_environment": dict(evidence.BUILD_ENVIRONMENT), "results": results,
    }
    problems = evidence.check_document(document, mode="local", source_commit=source.commit)
    if problems:
        raise MeasurementError("the harness produced invalid evidence: " + "; ".join(problems))
    return document


@contextlib.contextmanager
def _work_directory(work_dir: Path | None) -> Iterator[Path]:
    if work_dir is None:
        with tempfile.TemporaryDirectory(prefix="pysh-repro-") as name:
            yield Path(name)
        return
    if work_dir.exists() and any(work_dir.iterdir()):
        raise MeasurementError("--work-dir must be empty or absent (builds never reuse a previous tree)")
    work_dir.mkdir(parents=True, exist_ok=True)
    yield work_dir


# --- merge ---------------------------------------------------------------------------------------------------------------------------


def merge_documents(
    documents: Sequence[object], source_commit: str | None, release_dir: Path | None = None
) -> dict[str, Any]:
    """Combine per-platform evidence into one document that must be valid FINAL evidence.

    With ``release_dir`` every measured result is (re)bound to the already-staged public
    artifact; without it, results that were never bound cannot become final evidence.
    """
    if len(documents) < 2:
        raise MeasurementError("merge needs the evidence of at least two platforms")
    first: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    for index, document in enumerate(documents, 1):
        problems = evidence.check_document(document, mode="local", source_commit=source_commit)
        if problems:
            raise MeasurementError(f"evidence input {index} is invalid: " + "; ".join(problems))
        assert isinstance(document, dict)
        first = first or document
        for key in ("schema_version", "source_commit", "version", "build_environment"):
            if document[key] != first[key]:
                raise MeasurementError(f"evidence input {index} disagrees on {key}")
        results.extend(document["results"])
    assert first is not None
    results.sort(key=lambda r: evidence.FAMILY_ORDER.index(r["family"]))
    if release_dir is not None:
        for result in results:
            bind_release(result, release_dir)
    merged = {
        "schema_version": first["schema_version"], "source_commit": first["source_commit"],
        "version": first["version"], "build_environment": first["build_environment"], "results": results,
    }
    problems = evidence.check_document(merged, mode="final", source_commit=source_commit)
    if problems:
        raise MeasurementError("the combined evidence is not valid final evidence: " + "; ".join(problems))
    return merged


# --- command line -----------------------------------------------------------------------------------------------------------------------


def _write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(evidence.canonical_json(document), encoding="utf-8")
    temporary.replace(path)


def _measure_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", action="append", choices=evidence.FAMILY_ORDER, default=[], help="family to measure (repeatable)")
    parser.add_argument("--all", action="store_true", help="measure every family (blocked ones are recorded as PLATFORM_BLOCKED)")
    parser.add_argument("--output", type=Path, required=True, help="evidence JSON to write")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="git repository holding the source commit")
    parser.add_argument("--source-commit", help="exact commit SHA (default: HEAD of --repo-root)")
    parser.add_argument("--source-archive", type=Path, help="tar archive of the exact commit (instead of git archive)")
    parser.add_argument("--source-date-epoch", help="commit timestamp (required with --source-archive)")
    parser.add_argument("--python", help="interpreter with 'build' and 'twine' for wheel/sdist (default: this one)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_BUILD_TIMEOUT_SECONDS, help="seconds per build")
    parser.add_argument("--work-dir", type=Path, help="empty directory for the build roots (default: a temporary one)")
    parser.add_argument("--release-dir", type=Path, help="staged public artifacts to bind the evidence to (dist/release-assets)")
    args = parser.parse_args(list(argv))
    if args.all == bool(args.family):
        print("measure_release_reproducibility: choose either --all or one or more --family", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("measure_release_reproducibility: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        if args.source_archive is not None:
            commit, epoch = args.source_commit, args.source_date_epoch
            if not (commit and evidence.COMMIT_RE.fullmatch(commit) and epoch and evidence.EPOCH_RE.fullmatch(epoch)):
                print("measure_release_reproducibility: --source-archive needs a full --source-commit and a numeric "
                      "--source-date-epoch (the commit timestamp)", file=sys.stderr)
                return 2
            source = Source(commit, epoch, archive=args.source_archive)
        else:
            if args.source_date_epoch is not None:
                print("measure_release_reproducibility: --source-date-epoch is only valid with --source-archive "
                      "(otherwise it is read from the commit)", file=sys.stderr)
                return 2
            source = resolve_source(args.repo_root, args.source_commit)
        families = list(evidence.FAMILY_ORDER) if args.all else args.family
        document = measure(
            families, source, python=args.python, timeout=args.timeout, work_dir=args.work_dir,
            release_dir=args.release_dir,
        )
        _write(args.output, document)
    except (MeasurementError, OSError) as error:
        print(f"measure_release_reproducibility: FAIL: {error}", file=sys.stderr)
        return 1
    for result in document["results"]:
        print(f"{result['family']}: {result['classification']}")
    return 0


def _merge_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="measure_release_reproducibility.py merge")
    parser.add_argument("--input", type=Path, action="append", required=True, help="per-platform evidence (repeatable)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True, help="the exact commit SHA every input must be bound to")
    parser.add_argument("--release-dir", type=Path, help="staged public artifacts every measured result is bound to")
    args = parser.parse_args(list(argv))
    if not evidence.COMMIT_RE.fullmatch(args.source_commit):
        print("measure_release_reproducibility: --source-commit must be a full lowercase 40-hex SHA", file=sys.stderr)
        return 2
    try:
        merged = merge_documents(
            [evidence.load(path) for path in args.input], args.source_commit, args.release_dir
        )
        _write(args.output, merged)
    except (MeasurementError, ValueError, OSError) as error:
        print(f"measure_release_reproducibility: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"merged {len(merged['results'])} families into {args.output.name}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["merge"]:
        return _merge_main(arguments[1:])
    return _measure_main(arguments)


if __name__ == "__main__":
    sys.exit(main())
