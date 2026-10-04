# SPDX-License-Identifier: GPL-2.0-only
# File: tests/differential/startup.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Startup-isolation policies for the legacy reference shells (test equipment only).

Each policy is a *claim* about how to start one shell so that **user-controlled**
startup configuration (files under ``HOME``/``ZDOTDIR``/``XDG_CONFIG_HOME`` and
startup hooks such as ``BASH_ENV``) cannot influence the run. A claim is only
accepted when the live isolation self-test in ``reference.py`` proves it with a
hostile ``HOME`` and a positive control, on the exact installed version.

This is *user-startup isolation*, not *complete system startup isolation*: a
platform's installation-wide startup code (notably Zsh's global ``zshenv``, which
is read before ``-f`` can suppress anything) cannot be disabled portably and is an
explicit baseline limitation, checked for observable contamination only.
Nothing here is a PySH feature.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupPolicy:
    """How to start one reference shell non-interactively without user configuration."""

    policy_id: str
    shell: str
    isolation_flags: tuple[str, ...]  # placed before ``-c``
    #: Flags that make this shell *eager* to read startup files, used only by the
    #: positive control (the same hostile HOME must be read when isolation is off).
    control_flags: tuple[str, ...]
    #: Startup files planted in the hostile HOME.
    hostile_files: tuple[str, ...]
    #: Files whose markers MUST appear in the positive control (else it proves nothing).
    control_must_fire: tuple[str, ...]
    #: Environment variables that can name startup code. They must never be passed to
    #: a reference shell; a positive control proves the hook would otherwise work.
    startup_env_hooks: tuple[str, ...]
    #: Honest scope of the isolation guarantee.
    guarantee: str = "user startup configuration"
    #: Known startup code the policy cannot suppress (``None`` if none is known).
    global_startup_limitation: str | None = None

    def argv(self, command: str) -> list[str]:
        """Arguments after the executable for a controlled one-command run."""
        return [*self.isolation_flags, "-c", command]

    def control_argv(self, command: str) -> list[str]:
        return [*self.control_flags, "-c", command]

    def isolated_control_argv(self, command: str) -> list[str]:
        """Isolation flags combined with the eager flags: still must read nothing."""
        return [*self.isolation_flags, *self.control_flags, "-c", command]


POLICIES: dict[str, StartupPolicy] = {
    policy.policy_id: policy
    for policy in (
        StartupPolicy(
            "bash-noprofile-norc-v1", "bash", ("--noprofile", "--norc"), ("-l",),
            (".bash_profile", ".bash_login", ".profile", ".bashrc", ".bash_logout"),
            (".bash_profile",), ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"),
        ),
        StartupPolicy(
            "zsh-no-rcs-v1", "zsh", ("-f",), ("-l",),
            (".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout"),
            (".zshenv",), ("ZDOTDIR",),
            global_startup_limitation=(
                "the installation-wide zshenv is read before -f can suppress later startup files; "
                "user files under HOME/ZDOTDIR are isolated, platform-global startup is only "
                "checked for observable contamination"
            ),
        ),
        StartupPolicy(
            "fish-no-config-v1", "fish", ("--no-config",), (),
            (".config/fish/config.fish", ".config/fish/conf.d/hostile.fish"),
            (".config/fish/config.fish", ".config/fish/conf.d/hostile.fish"),
            ("XDG_CONFIG_HOME", "XDG_DATA_HOME"),
        ),
    )
}

HOSTILE_MARKER = "HOSTILE-STARTUP-FILE-EXECUTED"


#: Names that must never reach a reference shell's environment (they name startup code).
FORBIDDEN_REFERENCE_ENV: frozenset[str] = frozenset(
    hook for policy in POLICIES.values() for hook in policy.startup_env_hooks
)


def hostile_home_files(policy: StartupPolicy) -> dict[str, bytes]:
    """Startup files that print a marker if (and only if) the shell runs them."""
    body = f"echo {HOSTILE_MARKER}:{{name}}\n"
    return {name: body.format(name=name).encode() for name in policy.hostile_files}
