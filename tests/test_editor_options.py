from __future__ import annotations

import pytest

from pysh.config_api import (
    DEFAULT_EDITOR_OPTIONS,
    ConfigError,
    ShellConfigAPI,
    validate_editor_option,
)
from pysh.shell import PyShell


def test_editor_options_defaults_exact() -> None:
    assert DEFAULT_EDITOR_OPTIONS == {
        "autosuggest": True,
        "syntax_highlight": True,
        "line_editor": "auto",
    }


def test_set_editor_option_valid() -> None:
    shell = PyShell()
    ShellConfigAPI(shell).set_editor_option("line_editor", "readline")
    assert shell.editor_options["line_editor"] == "readline"


def test_editor_option_invalid_name_type_value() -> None:
    with pytest.raises(ConfigError):
        validate_editor_option("missing", True)
    with pytest.raises(ConfigError):
        validate_editor_option("autosuggest", "yes")
    with pytest.raises(ConfigError):
        validate_editor_option("line_editor", "ansi")


def test_pyshell_protocol_has_set_editor_option() -> None:
    shell = PyShell()
    shell.set_editor_option("syntax_highlight", False)
    assert shell.editor_options["syntax_highlight"] is False

