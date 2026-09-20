# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_isolated_plugin_manifest.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Manifest and capability contracts for isolated plugins (Issue #44)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pysh.plugins.isolated.capabilities import (
    CapabilityGrant,
    CommandCapability,
    EnvironmentCapability,
    FilesystemAccess,
    FilesystemCapability,
    NetworkCapability,
    format_capability,
    parse_capability,
)
from pysh.plugins.isolated.errors import CapabilityError, ManifestError
from pysh.plugins.isolated.manifest import (
    ISOLATED_MANIFEST_VERSION,
    ISOLATED_PROTOCOL_VERSION,
    load_isolated_plugin_manifest,
    validate_isolated_plugin_manifest,
)


def _manifest_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "manifest_version": ISOLATED_MANIFEST_VERSION,
        "name": "fixture-plugin",
        "plugin_version": "1.2.3",
        "protocol_version": ISOLATED_PROTOCOL_VERSION,
        "entrypoint": [str(Path(sys.executable).resolve()), "--version"],
        "requested_capabilities": [],
    }
    data.update(overrides)
    return data


def test_valid_manifest_keeps_versions_entrypoint_and_resource_class(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    manifest = validate_isolated_plugin_manifest(
        _manifest_data(
            requested_capabilities=[
                f"fs.read:{allowed}",
                "env.read:PYSH_FIXTURE",
                "network.connect:localhost:443",
                "command:report",
            ],
            resource_class="small",
        )
    )

    assert manifest.manifest_version == ISOLATED_MANIFEST_VERSION
    assert manifest.protocol_version == ISOLATED_PROTOCOL_VERSION
    assert manifest.name == "fixture-plugin"
    assert manifest.plugin_version == "1.2.3"
    assert manifest.entrypoint[0] == str(Path(sys.executable).resolve())
    assert manifest.resource_class == "small"
    assert {format_capability(item) for item in manifest.requested_capabilities} == {
        f"fs.read:{allowed.resolve()}",
        "env.read:PYSH_FIXTURE",
        "network.connect:localhost:443",
        "command:report",
    }


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("manifest_version", 2, "unsupported.*manifest version"),
        ("protocol_version", 2, "unsupported.*protocol version"),
        ("name", "../escape", "name is invalid"),
        ("plugin_version", "", "plugin_version"),
        ("entrypoint", ["python"], "absolute path"),
        ("requested_capabilities", "env.read:X", "array of strings"),
        ("resource_class", "../large", "resource_class"),
    ],
)
def test_manifest_rejects_invalid_fields(field: str, value: object, error: str) -> None:
    with pytest.raises(ManifestError, match=error):
        validate_isolated_plugin_manifest(_manifest_data(**{field: value}))


def test_manifest_rejects_missing_and_unknown_fields() -> None:
    missing = _manifest_data()
    del missing["name"]
    with pytest.raises(ManifestError, match="missing.*name"):
        validate_isolated_plugin_manifest(missing)

    with pytest.raises(ManifestError, match="unknown.*surprise"):
        validate_isolated_plugin_manifest(_manifest_data(surprise=True))


def test_manifest_rejects_unknown_and_duplicate_capabilities(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="unknown capability"):
        validate_isolated_plugin_manifest(
            _manifest_data(requested_capabilities=["process.spawn:anything"])
        )

    declaration = f"fs.read:{tmp_path}"
    with pytest.raises(ManifestError, match="must not contain duplicates"):
        validate_isolated_plugin_manifest(
            _manifest_data(requested_capabilities=[declaration, declaration])
        )


def test_manifest_loader_is_bounded_and_non_executing(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    manifest_path = tmp_path / "isolated.toml"
    manifest_path.write_text(
        "manifest_version = 1\n"
        'name = "fixture-plugin"\n'
        'plugin_version = "1.0"\n'
        "protocol_version = 1\n"
        f'entrypoint = ["{Path(sys.executable).resolve()}", "--version"]\n'
        f'requested_capabilities = ["fs.write:{marker}"]\n',
        encoding="utf-8",
    )

    manifest = load_isolated_plugin_manifest(manifest_path)

    assert manifest.name == "fixture-plugin"
    assert not marker.exists()
    with pytest.raises(ManifestError, match="exceeds 8 bytes"):
        load_isolated_plugin_manifest(manifest_path, max_bytes=8)


def test_capability_parser_returns_typed_canonical_objects(tmp_path: Path) -> None:
    root = tmp_path / "directory" / ".." / "allowed"

    assert parse_capability(f"fs.read:{root}") == FilesystemCapability(
        access=FilesystemAccess.READ,
        root=root.resolve(),
    )
    assert parse_capability("env.read:SAFE_NAME") == EnvironmentCapability("SAFE_NAME")
    assert parse_capability("network.connect:Example.COM:8443") == NetworkCapability(
        "example.com", 8443
    )
    assert parse_capability("command:status") == CommandCapability("status")


@pytest.mark.parametrize(
    "declaration",
    [
        "fs.read:relative/path",
        "env.read:BAD-NAME",
        "network.connect:host:not-a-port",
        "network.connect:host:70000",
        "command:../escape",
        "unknown:value",
    ],
)
def test_capability_parser_fails_closed(declaration: str) -> None:
    with pytest.raises(CapabilityError):
        parse_capability(declaration)


def test_capability_grant_is_default_deny_and_rejects_self_escalation() -> None:
    requested = frozenset({EnvironmentCapability("VISIBLE")})
    grant = CapabilityGrant.create("fixture-plugin", requested)

    assert grant.granted == frozenset()
    assert not grant.allows(EnvironmentCapability("VISIBLE"))

    with pytest.raises(CapabilityError, match="undeclared"):
        CapabilityGrant.create(
            "fixture-plugin",
            requested,
            frozenset({EnvironmentCapability("SECRET")}),
        )
