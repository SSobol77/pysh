# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_config_schema.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for declarative TOML schema validation and application."""
from __future__ import annotations

from pathlib import Path

from pysh.config.diagnostics import SECRET_KEY_MARKERS, is_secret_like
from pysh.config.schema import load_plugin_config, merge_toml_documents, validate_plugin_name
from pysh.core.shell import PyShell
from pysh.diagnostics.redaction import DEFAULT_REDACTION_POLICY, SENSITIVE_NAME_TOKENS


def test_unknown_section_and_key_are_diagnostics(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [
            (
                tmp_path / "config.toml",
                {"unknown": {}, "prompt": {"not_real": True}},
            )
        ]
    )
    reasons = [diag.reason for diag in config.diagnostics]
    assert "unknown top-level section" in reasons
    assert any("unknown prompt option" in reason for reason in reasons)


def test_invalid_type_and_enum_are_diagnostics(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [
            (
                tmp_path / "config.toml",
                {"prompt": {"show_git_branch": "yes", "prompt_layout": "stacked"}},
            )
        ]
    )
    text = "\n".join(diag.reason for diag in config.diagnostics)
    assert "expects bool" in text
    assert "must be one of" in text


def test_conf_d_later_values_override_earlier(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [
            (tmp_path / "config.toml", {"prompt": {"symbol": ">"}}),
            (tmp_path / "conf.d" / "10-symbol.toml", {"prompt": {"symbol": "$"}}),
        ]
    )
    assert config.prompt["symbol"] == "$"


def test_env_validation_and_secret_masking(tmp_path: Path) -> None:
    config = merge_toml_documents(
        [
            (
                tmp_path / "config.toml",
                {"env": {"BAD-NAME": "x", "API_TOKEN": 123}},
            )
        ]
    )
    formatted = "\n".join(diag.format() for diag in config.diagnostics)
    assert "invalid environment variable name" in formatted
    assert "API_TOKEN" in formatted
    assert "<redacted>" in formatted
    assert "123" not in formatted


def test_validate_plugin_name_accepts_valid(tmp_path: Path) -> None:
    assert validate_plugin_name("myplugin") is True
    assert validate_plugin_name("my-plugin") is True
    assert validate_plugin_name("plugin.v2") is True


def test_validate_plugin_name_rejects_invalid(tmp_path: Path) -> None:
    assert validate_plugin_name("") is False
    assert validate_plugin_name("MyPlugin") is False
    assert validate_plugin_name("../evil") is False


def test_load_plugin_config_valid_data(tmp_path: Path) -> None:
    path = tmp_path / "myplugin.toml"
    path.write_text("[plugin]\nname = 'myplugin'\n[settings]\nfoo = 1\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    assert pc.name == "myplugin"
    assert pc.data["settings"]["foo"] == 1
    assert pc.diagnostics == ()


def test_load_plugin_config_name_mismatch_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "real.toml"
    path.write_text("[plugin]\nname = 'different'\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    assert any("does not match file stem" in d.reason for d in pc.diagnostics)


def test_no_execution_from_toml_alias_values(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    shell = PyShell()
    config = merge_toml_documents(
        [(tmp_path / "config.toml", {"aliases": {"boom": f"touch {marker}"}})]
    )
    from pysh.config.schema import apply_config

    apply_config(shell, config)
    assert shell.aliases["boom"] == f"touch {marker}"
    assert not marker.exists()


def test_config_diagnostics_secret_markers_match_canonical_redaction_policy() -> None:
    """Issue #50: config diagnostics must use the single canonical sensitive-name list."""
    assert SECRET_KEY_MARKERS == SENSITIVE_NAME_TOKENS


def test_config_diagnostics_is_secret_like_delegates_to_canonical_policy() -> None:
    for name in ("API_TOKEN", "db_password", "SESSION_ID", "OAUTH_HEADER", "plain_name"):
        assert is_secret_like(name) == DEFAULT_REDACTION_POLICY.is_sensitive_name(name)


def test_config_diagnostics_classification_was_strengthened_not_weakened() -> None:
    """Names the old, narrower marker list missed must now be classified sensitive."""
    assert is_secret_like("SESSION_ID") is True
    assert is_secret_like("OAUTH_HEADER") is True
    assert is_secret_like("color_scheme") is False
