# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_pyinit.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the PyInit service metadata parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.services.pyinit import (
    ServiceMetadataError,
    discover_services,
    parse_service_file,
    parse_service_text,
)


def test_parse_minimum_valid_service() -> None:
    meta = parse_service_text(
        "name: example\n"
        "command: python3.13 -m http.server 8080\n"
    )
    assert meta.name == "example"
    assert meta.command == "python3.13 -m http.server 8080"
    assert meta.depends == ()


def test_parse_with_single_dependency_bracketed() -> None:
    meta = parse_service_text(
        "name: example\n"
        "command: /usr/bin/true\n"
        "depends: [network]\n"
    )
    assert meta.depends == ("network",)


def test_parse_with_multiple_dependencies() -> None:
    meta = parse_service_text(
        "name: example\n"
        "command: /usr/bin/true\n"
        "depends: [network, dbus, syslog]\n"
    )
    assert meta.depends == ("network", "dbus", "syslog")


def test_parse_with_comma_dependency_form() -> None:
    meta = parse_service_text(
        "name: example\n"
        "command: /usr/bin/true\n"
        "depends: network, dbus\n"
    )
    assert meta.depends == ("network", "dbus")


def test_parse_rejects_unterminated_depends_bracket() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text(
            "name: example\n"
            "command: /usr/bin/true\n"
            "depends: [network\n"
        )


def test_parse_rejects_invalid_dependency_name() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text(
            "name: example\n"
            "command: /usr/bin/true\n"
            "depends: [bad name with space]\n"
        )


def test_parse_rejects_empty_dependency() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text(
            "name: example\n"
            "command: /usr/bin/true\n"
            "depends: [network, ]\n"
        )


def test_parse_requires_name() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text("command: /usr/bin/true\n")


def test_parse_requires_command() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text("name: example\n")


def test_parse_rejects_empty_command() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text("name: example\ncommand:\n")


def test_parse_rejects_duplicate_field() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text(
            "name: a\n"
            "name: b\n"
            "command: /usr/bin/true\n"
        )


def test_parse_rejects_missing_colon() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text("just a line\n")


def test_parse_rejects_invalid_service_name() -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_text(
            "name: 9bad@name\n"
            "command: /usr/bin/true\n"
        )


def test_parse_ignores_comments_and_blanks() -> None:
    meta = parse_service_text(
        "# a comment\n"
        "\n"
        "name: example\n"
        "command: /usr/bin/true\n"
    )
    assert meta.name == "example"


def test_parse_service_file_reads_disk(tmp_path: Path) -> None:
    target = tmp_path / "example.service"
    target.write_text(
        "name: example\n"
        "command: /usr/bin/true\n"
        "depends: [network]\n",
        encoding="utf-8",
    )
    meta = parse_service_file(target)
    assert meta.depends == ("network",)


def test_parse_service_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ServiceMetadataError):
        parse_service_file(tmp_path / "absent.service")


def test_discover_services_finds_service_files(tmp_path: Path) -> None:
    (tmp_path / "a.service").write_text(
        "name: a\ncommand: /bin/true\n", encoding="utf-8"
    )
    (tmp_path / "b.service").write_text(
        "name: b\ncommand: /bin/true\n", encoding="utf-8"
    )
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")
    found = discover_services(tmp_path)
    assert [p.name for p in found] == ["a.service", "b.service"]


def test_discover_services_missing_dir(tmp_path: Path) -> None:
    assert discover_services(tmp_path / "missing") == []
