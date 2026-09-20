# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/config/startup.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Immutable policy for user-controlled shell startup configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupPolicy:
    """Control whether interactive startup may consume user configuration.

    Disabling user configuration is intentionally strict: executable rc files,
    declarative TOML, plugin configuration, plugin discovery, and startup hooks
    are all skipped. This keeps recovery startup deterministic and prevents a
    data-only setting from changing a trust boundary indirectly.
    """

    load_user_configuration: bool = True


DEFAULT_STARTUP_POLICY = StartupPolicy()
NO_RC_STARTUP_POLICY = StartupPolicy(load_user_configuration=False)
