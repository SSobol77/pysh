# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/reference.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Legacy-shell differential laboratory (Issue #54, Slice 3): test equipment only.

Reference shells (Bash, Zsh, Fish) are installed by CI as test dependencies,
located only at the absolute path named by their pinned profile, started through
the executor, which controls the environment and files it hands over, with a
verified user-startup-isolation policy, and used to
*observe* a small set of #48 cases. PySH remains the only semantic authority:

1. PySH runs the case under ``--no-rc`` and is checked against the #48
   ``pysh_expected`` block first; a violation is a REGRESSION that no reference
   shell can excuse (the reference is then not even run).
2. Only then is the reference observation compared, on the case's declared
   dimensions, and classified with the Slice 1 oracle.

Nothing here is imported by ``src/pysh``, and nothing resolves a program through
``PATH`` or a shell.
"""
from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from scripts.run_language_conformance import REPO_ROOT as _REPO_ROOT
from scripts.run_language_conformance import _expand_input, _fixture_environment, load_corpus
from tests.differential import oracle
from tests.differential.corpus import load_migration
from tests.differential.executor import (
    ExecutionResult,
    ExecutorError,
    HermeticTree,
    Termination,
    run_hermetic,
)
from tests.differential.model import (
    Dimension,
    LegacyProfile,
    MigrationCase,
    Observation,
    Outcome,
)
from tests.differential.startup import (
    FORBIDDEN_REFERENCE_ENV,
    HOSTILE_MARKER,
    POLICIES,
    StartupPolicy,
    hostile_home_files,
)

DEFAULT_CASES = Path(__file__).with_name("reference-cases-v1.json")
SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
CASE_TIMEOUT_SECONDS = 20.0
SELF_TEST_TIMEOUT_SECONDS = 15.0
MAX_CASE_OUTPUT_BYTES = 1 << 16
#: Classification written for a discovery run when a reference differs and no
#: reviewed migration-v1.json entry exists yet. It is never an accepted state.
UNDECLARED_DIFFERENCE = "UNDECLARED_DIFFERENCE"

EXECUTABLE_ENV_PREFIX = "PYSH_REFERENCE_"
PACKAGE_PROBES: dict[str, tuple[str, tuple[str, ...]]] = {
    "debian": ("/usr/bin/dpkg-query", ("-W", "-f=${Version}")),
    "freebsd": ("/usr/sbin/pkg", ("query", "%v")),
}
LAB_ENV = "PYSH_LEGACY_LAB"  # unset: skip real-shell tests; "1": run what is available; "required": fail if missing


class LabError(RuntimeError):
    """Infrastructure problem: the laboratory cannot produce trustworthy evidence."""


class ReferenceUnavailable(LabError):
    """A configured reference shell is not installed where its profile says."""


class VersionDriftError(LabError):
    """The installed reference differs from its pinned profile."""

    def __init__(self, profile: LegacyProfile, field_name: str, expected: str | None, actual: str | None):
        self.profile_id, self.field_name, self.expected, self.actual = (
            profile.profile_id, field_name, expected, actual,
        )
        super().__init__(
            f"version drift for profile {profile.profile_id} on {profile.platform}: "
            f"{field_name} expected {expected!r}, actual {actual!r}"
        )


class IsolationError(LabError):
    """A startup-isolation self-test failed."""


# --- platform -----------------------------------------------------------------------------------


def _arch(machine: str) -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(machine.lower(), machine.lower())


def detect_platform_id(os_release: Path = Path("/etc/os-release")) -> str:
    """Tier-1 style platform ID such as ``debian13-amd64`` or ``freebsd14.4-amd64``."""
    system = platform.system()
    arch = _arch(platform.machine())
    if system == "FreeBSD":
        match = re.match(r"([0-9]+\.[0-9]+)", platform.release())
        return f"freebsd{match.group(1) if match else platform.release().lower()}-{arch}"
    if system == "Linux":
        try:
            fields = dict(
                line.split("=", 1)
                for line in os_release.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
        except OSError:
            fields = {}
        distro = fields.get("ID", "linux").strip('"').lower()
        version = fields.get("VERSION_ID", "").strip('"')
        return f"{distro}{version}-{arch}"
    return f"{system.lower()}-{arch}"


def platform_family(platform_id: str) -> str:
    return re.match(r"[a-z]+", platform_id).group(0) if re.match(r"[a-z]+", platform_id) else ""


# --- reference cases (selection, not expectations) -----------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceCase:
    """A #48 case selected for differential observation, with shell applicability."""

    case_id: str
    shells: frozenset[str]
    dimensions: frozenset[Dimension]
    rationale: str


class ReferenceCaseError(ValueError):
    pass


def parse_reference_cases(data: object, language: Mapping[str, Any]) -> tuple[ReferenceCase, ...]:
    """Validate the selection file against the closed schema and the #48 corpus."""
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"}:
        raise ReferenceCaseError("root: expected exactly schema_version and cases")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise ReferenceCaseError("unsupported schema_version")
    by_id = {case["id"]: case for case in language["cases"]}
    seen: set[str] = set()
    cases: list[ReferenceCase] = []
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise ReferenceCaseError("cases: expected a non-empty list")
    for index, raw in enumerate(data["cases"]):
        context = f"cases[{index}]"
        if not isinstance(raw, dict) or set(raw) != {"case_id", "shells", "compared_dimensions", "rationale"}:
            raise ReferenceCaseError(f"{context}: unexpected fields")
        case_id = raw["case_id"]
        if case_id not in by_id:
            raise ReferenceCaseError(f"{context}.case_id: unknown #48 case {case_id!r}")
        if case_id in seen:
            raise ReferenceCaseError(f"{context}: duplicate case {case_id!r}")
        seen.add(case_id)
        if by_id[case_id]["surface"] != "command":
            raise ReferenceCaseError(f"{context}: only command-surface cases can run via -c")
        shells = raw["shells"]
        if (not isinstance(shells, list) or not shells or len(set(shells)) != len(shells)
                or not set(shells) <= {"bash", "zsh", "fish"}):
            raise ReferenceCaseError(f"{context}.shells: expected a non-empty unique subset of bash/zsh/fish")
        raw_dims = raw["compared_dimensions"]
        if not isinstance(raw_dims, list) or not raw_dims or len(set(raw_dims)) != len(raw_dims):
            raise ReferenceCaseError(f"{context}.compared_dimensions: expected a non-empty unique list")
        try:
            dims = frozenset(Dimension(d) for d in raw_dims)
        except ValueError as error:
            raise ReferenceCaseError(f"{context}.compared_dimensions: {error}") from error
        rationale = raw["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise ReferenceCaseError(f"{context}.rationale: expected a non-empty string")
        cases.append(ReferenceCase(case_id, frozenset(shells), dims, rationale))
    return tuple(cases)


def load_reference_cases(path: Path = DEFAULT_CASES) -> tuple[ReferenceCase, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceCaseError(f"cannot load {path}: {error}") from error
    return parse_reference_cases(data, load_corpus())


# --- probing and version drift ------------------------------------------------------------------


def resolve_executable(profile: LegacyProfile, environ: Mapping[str, str] | None = None) -> Path:
    """The profile's absolute executable, or an explicit absolute override for local use."""
    env = os.environ if environ is None else environ
    override = env.get(f"{EXECUTABLE_ENV_PREFIX}{profile.legacy_shell.upper()}")
    path = Path(override or profile.executable)
    if not path.is_absolute():
        raise LabError(f"reference executable for {profile.profile_id} must be an absolute path")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ReferenceUnavailable(
            f"reference shell for profile {profile.profile_id} is not installed at {path}"
        )
    return path


@dataclass(frozen=True, slots=True)
class Probe:
    version_line: str
    package_version: str | None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def probe_reference(profile: LegacyProfile, executable: Path) -> Probe:
    """Executable-reported version (first ``--version`` line) and OS package version."""
    result = run_hermetic(executable, ["--version"], timeout=SELF_TEST_TIMEOUT_SECONDS)
    line = _first_line(result.stdout) or _first_line(result.stderr)
    if result.termination is not Termination.EXIT or result.returncode != 0 or not line:
        raise LabError(f"cannot read the version of {profile.profile_id}")
    package: str | None = None
    probe = PACKAGE_PROBES.get(platform_family(profile.platform))
    if probe is not None and Path(probe[0]).is_file():
        out = run_hermetic(probe[0], [*probe[1], profile.legacy_shell], timeout=SELF_TEST_TIMEOUT_SECONDS)
        if out.termination is Termination.EXIT and out.returncode == 0:
            package = _first_line(out.stdout) or None
    return Probe(line, package)


def check_version(profile: LegacyProfile, probe: Probe) -> None:
    """Fail loudly before any semantic result is interpreted when a pinned profile drifted."""
    if profile.version_status != "pinned":
        return
    if probe.version_line != profile.version:
        raise VersionDriftError(profile, "version", profile.version, probe.version_line)
    if probe.package_version != profile.package_version:
        raise VersionDriftError(profile, "package_version", profile.package_version, probe.package_version)


# --- controlled case trees and runs ---------------------------------------------------------------


@contextlib.contextmanager
def case_tree() -> Iterator[tuple[HermeticTree, dict[str, str], dict[str, str]]]:
    """A fresh #48 fixture tree: (tree, process environment, placeholder map)."""
    with tempfile.TemporaryDirectory(prefix="pysh-differential-") as name:
        root = Path(name)
        env, placeholders = _fixture_environment(root)
        tmp = root / "tmp"
        tmp.mkdir()
        yield HermeticTree(root, root / "home", root / "work", root / "bin", tmp), env, placeholders


def _normalize(text: str, tree: HermeticTree, placeholders: Mapping[str, str]) -> str:
    """Replace this run's absolute paths by their #48 placeholder tokens (then a tree token)."""
    pairs = sorted(((v, f"{{{{{k}}}}}") for k, v in placeholders.items()), key=lambda p: -len(p[0]))
    for value, token in pairs:
        text = text.replace(value, token)
    return text.replace(str(tree.root), "{{TREE}}")


def _observation(result: ExecutionResult, tree: HermeticTree, placeholders: Mapping[str, str]) -> Observation:
    observed = result.to_observation()  # raises for timeout / output limit
    return Observation(
        observed.status,
        _normalize(observed.stdout, tree, placeholders),
        _normalize(observed.stderr, tree, placeholders),
    )


IDENTITY_PLACEHOLDERS = {name: f"{{{{{name}}}}}" for name in ("FIXTURE_BIN", "NOEXEC", "WORK", "HOME")}


def observe_pysh(command: str) -> Observation:
    """Run one #48 command case under PySH (``--no-rc``); never through any other shell."""
    with case_tree() as (tree, env, placeholders):
        text = _expand_input(command, placeholders)
        result = run_hermetic(
            sys.executable, ["-m", "pysh", "--no-rc", "-c", text], tree=tree,
            environment=env, timeout=CASE_TIMEOUT_SECONDS, max_output_bytes=MAX_CASE_OUTPUT_BYTES,
        )
        return _observation(result, tree, placeholders)


def reference_environment(env: Mapping[str, str]) -> dict[str, str]:
    """The environment handed to a reference shell: fixture variables only.

    Anything that only PySH needs (``PYTHONPATH``) is dropped. A variable that
    names shell startup code (``BASH_ENV``, ``ZDOTDIR``, ``XDG_CONFIG_HOME``, ...)
    is never accepted: passing one would let a hook bypass the startup-isolation
    flags, so it is a laboratory error rather than something to filter silently.
    """
    forbidden = sorted(FORBIDDEN_REFERENCE_ENV & set(env))
    if forbidden:
        raise LabError(f"startup-hook variables must not reach a reference shell: {forbidden}")
    return {k: v for k, v in env.items() if k != "PYTHONPATH"}


def observe_reference(profile: LegacyProfile, executable: Path, command: str) -> Observation:
    """Run one #48 command case under a pinned reference shell with its startup policy."""
    policy = POLICIES[profile.startup_policy]
    with case_tree() as (tree, env, placeholders):
        text = _expand_input(command, placeholders)
        result = run_hermetic(
            executable, policy.argv(text), tree=tree, environment=reference_environment(env),
            home_files=hostile_home_files(policy),  # plant hostile startup files in every run
            timeout=CASE_TIMEOUT_SECONDS, max_output_bytes=MAX_CASE_OUTPUT_BYTES,
        )
        return _observation(result, tree, placeholders)


# --- startup-isolation self-test -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def _quote(path: str) -> str:
    if "'" in path:
        raise LabError("interpreter path must not contain a single quote")
    return f"'{path}'"


def isolation_checks(profile: LegacyProfile, executable: Path) -> list[Check]:
    """Executable evidence that USER startup configuration cannot influence runs of this exact installed shell.

    The scope is deliberately narrow: platform-global startup code (for Zsh the
    installation-wide zshenv) is only checked for observable contamination.
    """
    policy: StartupPolicy = POLICIES[profile.startup_policy]
    checks: list[Check] = []
    hostile = hostile_home_files(policy)

    def run(argv: list[str], *, tree: HermeticTree, env: Mapping[str, str], **kw: Any) -> ExecutionResult:
        return run_hermetic(
            executable, argv, tree=tree, environment=reference_environment(env),
            timeout=kw.pop("timeout", SELF_TEST_TIMEOUT_SECONDS), **kw,
        )

    def marker_seen(result: ExecutionResult, name: str | None = None) -> bool:
        needle = HOSTILE_MARKER if name is None else f"{HOSTILE_MARKER}:{name}"
        return needle in result.stdout or needle in result.stderr

    with case_tree() as (tree, env, _ph):
        control = run(policy.control_argv("echo control"), tree=tree, env=env, home_files=hostile)
    missing = [n for n in policy.control_must_fire if not marker_seen(control, n)]
    checks.append(Check(
        "positive-control-reads-hostile-startup-files", not missing,
        "hostile user startup files must run when isolation is OFF (otherwise the negative checks "
        f"prove nothing); did not fire: {missing}" if missing else "",
    ))
    with case_tree() as (tree, env, _ph):
        isolated = run(policy.argv("echo ok"), tree=tree, env=env, home_files=hostile)
    checks.append(Check(
        "isolated-run-ignores-hostile-startup-files",
        not marker_seen(isolated) and isolated.stdout == "ok\n" and isolated.returncode == 0,
        f"argv={policy.argv('echo ok')!r}",
    ))
    with case_tree() as (tree, env, _ph):
        eager = run(policy.isolated_control_argv("echo ok"), tree=tree, env=env, home_files=hostile)
    checks.append(Check(
        "isolation-flags-win-over-eager-startup-flags",
        not marker_seen(eager) and eager.stdout == "ok\n",
        f"argv={policy.isolated_control_argv('echo ok')!r}",
    ))
    checks.extend(_startup_hook_checks(policy, executable))
    # Platform-global startup (for Zsh the installation-wide zshenv) cannot be disabled
    # portably. The claim is only: it caused no observable contamination of this run.
    with case_tree() as (tree, env, _ph):
        quiet = run(policy.argv("true"), tree=tree, env=env)
        checks.append(Check(
            "platform-startup-baseline-is-silent",
            quiet.termination is Termination.EXIT and quiet.returncode == 0
            and quiet.stdout == "" and quiet.stderr == "",
            "an empty isolated run must print nothing (this does not prove global startup files did not run)",
        ))
    with case_tree() as (tree, env, _ph):
        home = run(policy.argv("fixture-env HOME"), tree=tree, env=env)
        checks.append(Check("home-is-the-controlled-directory", home.stdout.strip() == str(tree.home)))
        os.environ["PYSH_LAB_HOST_LEAK"] = "leaked"
        try:
            leak = run(policy.argv("fixture-env PYSH_LAB_HOST_LEAK"), tree=tree, env=env)
        finally:
            os.environ.pop("PYSH_LAB_HOST_LEAK", None)
        checks.append(Check("host-environment-is-not-inherited", leak.stdout.strip() == ""))
        cwd = run(policy.argv("pwd"), tree=tree, env=env)
        checks.append(Check(
            "cwd-is-the-controlled-directory",
            os.path.realpath(cwd.stdout.strip() or "?") == os.path.realpath(tree.work),
        ))
        if policy.global_startup_limitation is not None:
            path = run(policy.argv("fixture-env PATH"), tree=tree, env=env)
            zdotdir = run(policy.argv("fixture-env ZDOTDIR"), tree=tree, env=env)
            checks.append(Check(
                "global-startup-left-controlled-state-intact",
                path.stdout.strip() == str(tree.bin) and zdotdir.stdout.strip() == ""
                and home.stdout.strip() == str(tree.home),
                "PATH, HOME and ZDOTDIR as seen by the shell must be the controlled values",
            ))
    py = _quote(sys.executable)
    with case_tree() as (tree, env, _ph):
        start = time.monotonic()
        slow = run(policy.argv(f"{py} -c 'import time; time.sleep(60)'"), tree=tree, env=env, timeout=1.5)
        checks.append(Check(
            "timeout-terminates-the-tree",
            slow.termination is Termination.TIMEOUT and time.monotonic() - start < 20,
        ))
    with case_tree() as (tree, env, _ph):
        flood = run(
            policy.argv(f"{py} -c 'print(\"x\" * 200000)'"), tree=tree, env=env, max_output_bytes=1000,
        )
        checks.append(Check(
            "output-is-bounded",
            flood.termination is Termination.OUTPUT_LIMIT and flood.truncated and len(flood.stdout) <= 1000,
        ))
    return checks


#: Hooks whose startup code the positive control can really trigger, and how.
HOOK_TRIGGERS = {"BASH_ENV": "isolated", "ZDOTDIR": "control", "XDG_CONFIG_HOME": "control"}


def _hook_value(hook: str, policy: StartupPolicy, tree: HermeticTree) -> str:
    """Plant hostile startup code reachable through ``hook`` and return the value to set."""
    body = f"echo {HOSTILE_MARKER}:{hook}\n".encode()
    if hook == "BASH_ENV":
        target = tree.home / ".hostile-bash-env"
        target.write_bytes(body)
        return str(target)
    if hook in {"ZDOTDIR", "XDG_CONFIG_HOME"}:
        base = tree.home / f"hostile-{hook.lower()}"
        for name in policy.hostile_files:
            relative = name[len(".config/"):] if name.startswith(".config/") else name
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"echo {HOSTILE_MARKER}:{hook}:{relative}\n".encode())
        return str(base)
    return "hostile"


def _startup_hook_checks(policy: StartupPolicy, executable: Path) -> list[Check]:
    """Prove startup-hook variables can neither leak in from the host nor be passed through."""
    checks: list[Check] = []
    for hook in policy.startup_env_hooks:
        marker = f"{HOSTILE_MARKER}:{hook}"
        with case_tree() as (tree, env, _ph):
            value = _hook_value(hook, policy, tree)
            previous = os.environ.get(hook)
            os.environ[hook] = value  # a hostile value in the HOST process
            try:
                echoed = run_hermetic(
                    executable, policy.argv(f"fixture-env {hook}"), tree=tree,
                    environment=reference_environment(env), timeout=SELF_TEST_TIMEOUT_SECONDS,
                )
                ran = run_hermetic(
                    executable, policy.argv("echo ok"), tree=tree,
                    environment=reference_environment(env), timeout=SELF_TEST_TIMEOUT_SECONDS,
                )
            finally:
                if previous is None:
                    os.environ.pop(hook, None)
                else:
                    os.environ[hook] = previous
            leaked = marker in ran.stdout or marker in ran.stderr or echoed.stdout.strip() != ""
            checks.append(Check(
                f"host-{hook}-is-not-inherited-or-executed", not leaked and ran.stdout == "ok\n",
            ))
            try:
                reference_environment({**env, hook: value})
                rejected = False
            except LabError:
                rejected = True
            checks.append(Check(f"explicit-{hook}-is-rejected-by-the-laboratory", rejected))
            mode = HOOK_TRIGGERS.get(hook)
            if mode is not None:
                # Positive control: bypass the laboratory guard on purpose to prove the hook
                # really would execute hostile code, so the negative checks above mean something.
                argv = policy.argv("echo ok") if mode == "isolated" else policy.control_argv("echo ok")
                forced = run_hermetic(
                    executable, argv, tree=tree,
                    environment={**reference_environment(env), hook: value},
                    timeout=SELF_TEST_TIMEOUT_SECONDS,
                )
                checks.append(Check(
                    f"{hook}-positive-control-would-execute-hostile-code",
                    marker in forced.stdout or marker in forced.stderr,
                    f"argv={argv!r}",
                ))
    return checks


def require_isolation(profile: LegacyProfile, executable: Path) -> list[Check]:
    checks = isolation_checks(profile, executable)
    failed = [c for c in checks if not c.ok]
    if failed:
        raise IsolationError(
            f"startup isolation failed for {profile.profile_id}: "
            + ", ".join(f"{c.name} ({c.detail})" if c.detail else c.name for c in failed)
        )
    return checks


# --- classification and evidence ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseRecord:
    case_id: str
    profile_id: str
    compared_dimensions: tuple[str, ...]
    pysh_observation: Observation
    reference_observation: Observation | None
    classification: str
    contract_ref: str
    migration_anchor: str | None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        def obs(value: Observation | None) -> dict[str, object] | None:
            return None if value is None else {
                "status": value.status, "stdout": value.stdout, "stderr": value.stderr,
            }

        return {
            "case_id": self.case_id,
            "profile_id": self.profile_id,
            "compared_dimensions": list(self.compared_dimensions),
            "pysh_observation": obs(self.pysh_observation),
            "reference_observation": obs(self.reference_observation),
            "classification": self.classification,
            "contract_ref": self.contract_ref,
            "migration_anchor": self.migration_anchor,
            "detail": self.detail,
        }


def classify_pair(
    selected: ReferenceCase,
    case48: Mapping[str, Any],
    profile: LegacyProfile,
    pysh_obs: Observation,
    reference_obs: Observation | None,
    declared: MigrationCase | None,
) -> CaseRecord:
    """Pipeline steps 2-5: PySH vs #48 first, then (only then) the reference."""
    expected = case48["pysh_expected"]
    dims = tuple(sorted(d.value for d in selected.dimensions))
    base = dict(
        case_id=selected.case_id, profile_id=profile.profile_id, compared_dimensions=dims,
        pysh_observation=pysh_obs, contract_ref=case48["contract_ref"],
        migration_anchor=declared.migration_anchor if declared else None,
    )
    own = oracle.mismatches(expected, pysh_obs, selected.dimensions, IDENTITY_PLACEHOLDERS)
    if own:
        return CaseRecord(
            reference_observation=None, classification=Outcome.REGRESSION.value,
            detail="PySH violates its own #48 expectation: " + "; ".join(own), **base,
        )
    if reference_obs is None:
        raise LabError("a reference observation is required once PySH satisfies #48")
    if declared is not None:
        verdict = oracle.classify(declared, expected, pysh_obs, reference_obs, IDENTITY_PLACEHOLDERS)
        return CaseRecord(
            reference_observation=reference_obs, classification=verdict.outcome.value,
            detail=verdict.detail, **base,
        )
    differences = oracle.mismatches(expected, reference_obs, selected.dimensions, IDENTITY_PLACEHOLDERS)
    if not differences:
        return CaseRecord(
            reference_observation=reference_obs, classification=Outcome.MATCH.value,
            detail="unreviewed: no migration-v1 entry; reference satisfies the #48 expectation", **base,
        )
    return CaseRecord(
        reference_observation=reference_obs, classification=UNDECLARED_DIFFERENCE,
        detail="unreviewed difference; document a divergence or fix PySH: " + "; ".join(differences), **base,
    )


def pysh_version() -> str:
    try:
        return metadata.version("pysh-shell")
    except metadata.PackageNotFoundError:
        return "unknown"


def canonical_json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


@dataclass
class ProfileReport:
    profile: LegacyProfile
    probe: Probe | None = None
    checks: list[Check] = field(default_factory=list)
    records: list[CaseRecord] = field(default_factory=list)
    #: Controlled-PTY records (see ``pty_lab``), kept apart from the command-surface ``records``.
    pty_records: list[Any] = field(default_factory=list)
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        p = self.profile
        return {
            "profile_id": p.profile_id,
            "legacy_shell": p.legacy_shell,
            "platform": p.platform,
            "startup_policy": p.startup_policy,
            "startup_isolation_scope": POLICIES[p.startup_policy].guarantee,
            "global_startup_limitation": POLICIES[p.startup_policy].global_startup_limitation,
            "version_status": p.version_status,
            "pinned_version": p.version,
            "pinned_package_version": p.package_version,
            "observed_version": self.probe.version_line if self.probe else None,
            "observed_package_version": self.probe.package_version if self.probe else None,
            "isolation_checks": [{"name": c.name, "ok": c.ok} for c in sorted(self.checks, key=lambda c: c.name)],
            "skipped_reason": self.skipped_reason,
            "records": [r.to_dict() for r in sorted(self.records, key=lambda r: r.case_id)],
            "pty_records": [r.to_dict() for r in sorted(self.pty_records, key=lambda r: r.case_id)],
        }


def evidence_document(platform_id: str, reports: list[ProfileReport], commit: str | None) -> dict[str, object]:
    """Deterministic evidence: no HOME, usernames, environment, absolute paths or timestamps."""
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "pysh_version": pysh_version(),
        "pysh_commit": commit,
        "platform": platform_id,
        "profiles": [r.to_dict() for r in sorted(reports, key=lambda r: r.profile.profile_id)],
    }


def _evaluate_pty(
    profile: LegacyProfile, executable: Path, cache: dict[str, Any], corpus: Any
) -> tuple[list[Any], list[str]]:
    """Controlled-PTY evidence for one profile (indirection so unit tests can stub it)."""
    from tests.differential import pty_lab

    cases, divergences = corpus
    return pty_lab.evaluate_profile(profile, executable, cache, cases, divergences)


def lab_mode() -> str:
    """``off`` (real-shell tests skip), ``available`` or ``required`` (missing shell fails)."""
    value = os.environ.get(LAB_ENV, "")
    return {"1": "available", "required": "required"}.get(value, "off")


def repo_root() -> Path:
    return _REPO_ROOT


def run_lab(
    *,
    platform_id: str | None = None,
    require_all: bool = False,
    strict: bool = False,
    commit: str | None = None,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Run the whole laboratory for the current platform.

    Returns (evidence document, problems). Infrastructure problems (missing
    required shell, version drift, failed isolation) and classification failures
    (a REGRESSION, a stale/violated declared state, and with ``strict`` any
    unreviewed difference) are listed in ``problems``.

    ``progress`` receives the evidence document after each profile's discovery
    (executable and package version, isolation checks) and again after each case,
    so version/pin information is persisted before any semantic step can fail.
    """
    platform_id = platform_id or detect_platform_id()
    migration = load_migration()
    selected = load_reference_cases()
    language = {case["id"]: case for case in load_corpus()["cases"]}
    profiles = [p for p in migration.profiles.values() if p.platform == platform_id]
    declared = {(c.case_id, c.legacy_profile): c for c in migration.cases}
    problems: list[str] = []
    reports: list[ProfileReport] = []
    if not profiles:
        problems.append(f"no legacy reference profiles are configured for platform {platform_id}")

    def publish() -> None:
        if progress is not None:
            progress(evidence_document(platform_id, reports, commit))

    from tests.differential import pty_lab

    pty_cases, pty_data = pty_lab.load_pty_corpus()
    pty_corpus = (pty_cases, pty_lab.declared_divergences(pty_data, pty_cases))
    pty_cache: dict[str, Any] = {}
    pysh_cache: dict[str, Observation] = {}
    for profile in profiles:
        report = ProfileReport(profile)
        reports.append(report)
        try:
            executable = resolve_executable(profile)
        except ReferenceUnavailable as error:
            report.skipped_reason = str(error)
            if require_all:
                problems.append(str(error))
            continue
        try:
            report.probe = probe_reference(profile, executable)
            publish()  # the pin proposal survives any later failure
            check_version(profile, report.probe)
            report.checks = isolation_checks(profile, executable)
            publish()
            failed = [c for c in report.checks if not c.ok]
            if failed:
                raise IsolationError(
                    f"startup isolation failed for {profile.profile_id}: "
                    + ", ".join(f"{c.name} ({c.detail})" if c.detail else c.name for c in failed)
                )
        except (ExecutorError, LabError) as error:
            problems.append(str(error))
            publish()
            continue
        for case in selected:
            if profile.legacy_shell not in case.shells:
                continue
            case48 = language[case.case_id]
            try:
                if case.case_id not in pysh_cache:
                    pysh_cache[case.case_id] = observe_pysh(case48["input"])
                pysh_obs = pysh_cache[case.case_id]
                own = oracle.mismatches(case48["pysh_expected"], pysh_obs, case.dimensions, IDENTITY_PLACEHOLDERS)
                reference_obs = None if own else observe_reference(profile, executable, case48["input"])
                record = classify_pair(
                    case, case48, profile, pysh_obs, reference_obs, declared.get((case.case_id, profile.profile_id)),
                )
            except oracle.StaleDivergenceError as error:
                problems.append(str(error))
                continue
            except (ExecutorError, LabError) as error:
                problems.append(f"{case.case_id}/{profile.profile_id}: {error}")
                continue
            report.records.append(record)
            publish()
            if record.classification == Outcome.REGRESSION.value:
                problems.append(f"REGRESSION {case.case_id}/{profile.profile_id}: {record.detail}")
            elif record.classification == UNDECLARED_DIFFERENCE and (strict or profile.version_status == "pinned"):
                problems.append(f"UNREVIEWED {case.case_id}/{profile.profile_id}: {record.detail}")
            elif (profile.version_status == "pinned"
                  and (case.case_id, profile.profile_id) not in declared):
                problems.append(
                    f"UNREVIEWED {case.case_id}/{profile.profile_id}: pinned profile without a migration-v1 entry"
                )
        # Controlled-PTY migration evidence, recorded apart from the command-surface records.
        try:
            report.pty_records, pty_problems = _evaluate_pty(profile, executable, pty_cache, pty_corpus)
        except (ExecutorError, LabError) as error:
            pty_problems = [f"PTY {profile.profile_id}: {error}"]
        problems.extend(pty_problems)
        publish()
    return evidence_document(platform_id, reports, commit), problems
