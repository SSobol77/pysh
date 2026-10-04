# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/isolated/launcher.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Trusted POSIX launcher that applies rlimits and then execs the real plugin.

INTERNAL: not a public API. The parent spawns this file as a script::

    python -I launcher.py --cpu-seconds N --memory-bytes N \\
        --file-descriptors N [--processes N] -- /abs/plugin arg...

The launcher validates the numeric policy again, applies ``setrlimit`` and
replaces itself with the plugin via ``os.execve`` (no shell, no
``preexec_fn``). It therefore never remains as a supervisor, and the plugin
cannot execute before its limits are in force. Limits are only ever lowered:
an inherited hard limit is never relaxed. The plugin cannot choose its limits;
they come from the parent-owned argv only.

Exit codes: ``78`` policy rejected, ``71`` platform cannot apply it, the
applied hard limit is relaxable by the current privilege, or exec failed. Nothing is written to stdout (it is the IPC pipe).
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX only; absence is reported as "unsupported", never skipped
    import resource
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None  # type: ignore[assignment]

if __name__ == "__main__":  # script mode under ``-I``: locate pysh next to this file
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pysh.plugins.isolated.errors import ResourcePolicyError  # noqa: E402
from pysh.plugins.isolated.resources import (  # noqa: E402
    MIN_ENFORCED_FILE_DESCRIPTORS,
    MIN_ENFORCED_MEMORY_BYTES,
    ResourceBudget,
)

EXIT_POLICY_REJECTED = 78
EXIT_APPLY_FAILED = 71
LAUNCHER_PATH = Path(__file__).resolve()

_OPTIONS = {
    "--cpu-seconds": "cpu_seconds",
    "--memory-bytes": "memory_bytes",
    "--file-descriptors": "file_descriptors",
    "--processes": "processes",
}
_REQUIRED = ("cpu_seconds", "memory_bytes", "file_descriptors")
_INTEGER_RE = re.compile(r"[1-9][0-9]{0,18}")


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """Validated limits plus the exact plugin argv to exec."""

    cpu_seconds: int
    memory_bytes: int
    file_descriptors: int
    processes: int | None
    entrypoint: tuple[str, ...]


def _rlimit_names() -> dict[str, int | None]:
    """Map budget fields to this platform's RLIMIT constants by feature detection."""
    if resource is None:
        return {}
    address_space = getattr(resource, "RLIMIT_AS", None)
    if address_space is None:  # FreeBSD naming alias
        address_space = getattr(resource, "RLIMIT_VMEM", None)
    return {
        "cpu_seconds": getattr(resource, "RLIMIT_CPU", None),
        "memory_bytes": address_space,
        "file_descriptors": getattr(resource, "RLIMIT_NOFILE", None),
        "processes": getattr(resource, "RLIMIT_NPROC", None),
    }


def check_platform_support(fields: tuple[str, ...]) -> None:
    """Raise ``ResourcePolicyError`` if any requested field has no primitive here."""
    if resource is None:
        raise ResourcePolicyError("the resource module is unavailable on this platform")
    names = _rlimit_names()
    for field in fields:
        if names.get(field) is None:
            raise ResourcePolicyError(f"{field} has no supported rlimit primitive here")


def build_launcher_argv(
    limits: Mapping[str, int],
    entrypoint: tuple[str, ...],
    *,
    python: str | None = None,
) -> list[str]:
    """Return the parent-owned argv that launches ``entrypoint`` under ``limits``."""
    values = dict(limits)
    check_platform_support(tuple(values))
    argv = [python or sys.executable, "-I", str(LAUNCHER_PATH)]
    for option, field in _OPTIONS.items():
        if field in values:
            argv += [option, str(values[field])]
    unknown = set(values) - set(_OPTIONS.values())
    if unknown or not set(_REQUIRED) <= set(values) or not entrypoint:
        raise ResourcePolicyError("launcher policy is incomplete or has unknown limits")
    return [*argv, "--", *entrypoint]


def parse_launcher_argv(argv: list[str]) -> LaunchPlan:
    """Strictly parse launcher argv; raise ``ResourcePolicyError`` on any deviation."""
    if "--" not in argv:
        raise ResourcePolicyError("launcher argv requires a '--' separator")
    split = argv.index("--")
    options, entrypoint = argv[:split], argv[split + 1 :]
    if not entrypoint or not entrypoint[0]:
        raise ResourcePolicyError("launcher argv requires a plugin entrypoint")
    if len(options) % 2:
        raise ResourcePolicyError("launcher options must be option/value pairs")
    values: dict[str, int] = {}
    for option, text in zip(options[::2], options[1::2], strict=True):
        field = _OPTIONS.get(option)
        if field is None:
            raise ResourcePolicyError(f"unknown launcher option {option!r}")
        if field in values:
            raise ResourcePolicyError(f"duplicate launcher option {option!r}")
        if not _INTEGER_RE.fullmatch(text):
            raise ResourcePolicyError(f"{option} must be a canonical positive integer")
        values[field] = int(text)
    missing = [field for field in _REQUIRED if field not in values]
    if missing:
        raise ResourcePolicyError(f"missing launcher limits: {', '.join(missing)}")
    budget = ResourceBudget(**values)  # re-validates positivity and hard ceilings
    if budget.file_descriptors < MIN_ENFORCED_FILE_DESCRIPTORS:  # type: ignore[operator]
        raise ResourcePolicyError("file_descriptors is below the enforceable minimum")
    if budget.memory_bytes < MIN_ENFORCED_MEMORY_BYTES:  # type: ignore[operator]
        raise ResourcePolicyError("memory_bytes is below the enforceable minimum")
    return LaunchPlan(
        cpu_seconds=values["cpu_seconds"],
        memory_bytes=values["memory_bytes"],
        file_descriptors=values["file_descriptors"],
        processes=values.get("processes"),
        entrypoint=tuple(entrypoint),
    )


def _ensure_irrevocable(field: str, which: int, applied: int) -> None:
    """Fail closed unless the OS refuses to raise the hard limit just applied.

    ``soft == hard`` is only irreversible for a process that lacks the
    privilege to raise hard limits. This probes the actual behaviour (no
    uid/capability inspection): a finite raise by one must be rejected. If the
    OS accepts it, the limit is restored and enforcement fails before the
    plugin is exec'd, because the plugin would inherit the same ability.
    """
    assert resource is not None  # established by check_platform_support
    try:
        resource.setrlimit(which, (applied, applied + 1))
    except (ValueError, OSError):
        return  # rejected: the limit cannot be relaxed from this process
    try:
        resource.setrlimit(which, (applied, applied))
    except (ValueError, OSError):
        pass  # best effort; the launcher exits without exec either way
    raise ResourcePolicyError(f"{field} hard limit is relaxable by this process")


def apply_limits(plan: LaunchPlan) -> None:
    """Apply the plan with ``setrlimit``; soft == hard, never above the inherited hard.

    After each limit is applied it is proven irrevocable (see
    :func:`_ensure_irrevocable`); a relaxable limit raises ``ResourcePolicyError``
    so the launcher exits before exec.
    """
    wanted = {
        "cpu_seconds": plan.cpu_seconds,
        "memory_bytes": plan.memory_bytes,
        "file_descriptors": plan.file_descriptors,
    }
    if plan.processes is not None:
        wanted["processes"] = plan.processes
    check_platform_support(tuple(wanted))
    names = _rlimit_names()
    assert resource is not None  # established by check_platform_support
    for field, value in wanted.items():
        which = names[field]
        assert which is not None
        _soft, inherited_hard = resource.getrlimit(which)
        limit = value if inherited_hard == resource.RLIM_INFINITY else min(value, inherited_hard)
        try:
            resource.setrlimit(which, (limit, limit))
        except (ValueError, OSError) as exc:
            raise ResourcePolicyError(f"cannot apply {field}: {exc}") from exc
        _ensure_irrevocable(field, which, limit)


def main(argv: list[str]) -> int:
    """Validate, apply limits, then replace this process with the plugin."""
    try:
        plan = parse_launcher_argv(argv)
    except ResourcePolicyError:
        return EXIT_POLICY_REJECTED
    try:
        apply_limits(plan)
    except ResourcePolicyError:
        return EXIT_APPLY_FAILED
    try:
        os.execve(plan.entrypoint[0], list(plan.entrypoint), dict(os.environ))  # noqa: S606
    except OSError:
        return EXIT_APPLY_FAILED
    return EXIT_APPLY_FAILED  # pragma: no cover - execve does not return


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
