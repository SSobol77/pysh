# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_completion_engine.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Completion Engine v1 tests (Issue #12)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pysh.editor.lineedit.completion import (
    CompletionCandidate,
    CompletionKind,
    CompletionMatchType,
    _PathCache,
    apply_single_completion,
    common_completion_prefix,
    complete_line,
    parse_completion_context,
)

BUILTINS = ("cd", "echoish", "fg", "bg", "source", "pushd")


def test_context_command_position() -> None:
    context = parse_completion_context("ec", 2)
    assert context.command_position
    assert context.prefix == "ec"


def test_context_command_position_after_operators() -> None:
    for line in ("echo x | gi", "echo x; gi", "true && gi", "false || gi"):
        context = parse_completion_context(line, len(line))
        assert context.command_position
        assert context.prefix == "gi"


def test_context_argument_position() -> None:
    context = parse_completion_context("echo RE", 7)
    assert not context.command_position
    assert context.command_name == "echo"
    assert context.prefix == "RE"


def test_context_after_redirection() -> None:
    context = parse_completion_context("cat > ou", 8)
    assert context.after_redirection
    assert context.prefix == "ou"


def test_context_quoted_token() -> None:
    context = parse_completion_context('echo "REA', 9)
    assert context.quote == '"'
    assert context.prefix == "REA"


def test_context_escaped_space() -> None:
    context = parse_completion_context(r"echo file\ na", 13)
    assert context.prefix == "file na"


def test_context_variable_plain_and_brace() -> None:
    plain = parse_completion_context("echo $HO", 8)
    brace = parse_completion_context("echo ${HO", 9)
    assert plain.variable_style == "plain"
    assert plain.variable_prefix == "HO"
    assert brace.variable_style == "brace"
    assert brace.variable_prefix == "HO"


def test_context_job_command() -> None:
    context = parse_completion_context("fg %", 4)
    assert context.command_name == "fg"
    assert context.argument_index == 1
    assert context.prefix == "%"


def test_builtin_completion_at_command_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("ec", 2, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("echoish",)
    assert result.rich_candidates[0].kind is CompletionKind.BUILTIN


def test_alias_completion_has_alias_kind(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("gs", 2, builtins=BUILTINS, aliases=("gs",), path="")
    assert result.candidates == ("gs",)
    assert result.rich_candidates[0].kind is CompletionKind.ALIAS
    assert result.rich_candidates[0].labeled_menu_text == "gs [alias]"


def test_duplicate_command_names_are_deduplicated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line(
        "ec",
        2,
        builtins=("echo",),
        aliases=("echo",),
        path="",
    )
    assert result.candidates == ("echo",)


def test_command_completion_uses_prefix_without_substring_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    prefix = complete_line(
        "so",
        2,
        builtins=("source", "also"),
        aliases=("sortit",),
        path="",
    )
    assert prefix.candidates == ("sortit", "source")
    assert all(
        candidate.match_type is CompletionMatchType.PREFIX
        for candidate in prefix.rich_candidates
    )

    substring = complete_line(
        "our",
        3,
        builtins=("source", "elsewhere"),
        aliases=(),
        path="",
    )
    assert substring.candidates == ()


def test_case_insensitive_matching_and_deterministic_sort(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("so", 2, builtins=("Source", "sort", "Socks"), aliases=(), path="")
    assert result.candidates == ("Socks", "sort", "Source")


def test_case_sensitive_command_matching(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line(
        "so",
        2,
        builtins=("Source", "sort"),
        aliases=(),
        path="",
        case_sensitive=True,
    )
    assert result.candidates == ("sort",)


def test_no_builtin_completion_in_argument_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo ec", 7, builtins=BUILTINS, aliases=(), path="")
    assert "echoish" not in result.candidates


def test_external_command_completion_dedupes_and_ignores_non_executable(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    missing = tmp_path / "missing"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        exe = directory / "tool"
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    non_exe = first / "torn"
    non_exe.write_text("", encoding="utf-8")
    result = complete_line(
        "to",
        2,
        builtins=(),
        aliases=(),
        path=os.pathsep.join([str(first), str(missing), str(second)]),
    )
    assert result.candidates == ("tool",)


def test_path_cache_ttl_invalidation_uses_fake_clock(tmp_path: Path) -> None:
    now = 0.0

    def monotonic() -> float:
        return now

    bindir = tmp_path / "bin"
    bindir.mkdir()
    first = bindir / "alpha"
    first.write_text("#!/bin/sh\n", encoding="utf-8")
    first.chmod(first.stat().st_mode | stat.S_IXUSR)
    cache = _PathCache(ttl=5.0, monotonic=monotonic)
    path_value = str(bindir)

    assert cache.commands(path_value) == ("alpha",)

    second = bindir / "beta"
    second.write_text("#!/bin/sh\n", encoding="utf-8")
    second.chmod(second.stat().st_mode | stat.S_IXUSR)
    assert cache.commands(path_value) == ("alpha",)

    now = 6.0
    assert cache.commands(path_value) == ("alpha", "beta")

    third = bindir / "gamma"
    third.write_text("#!/bin/sh\n", encoding="utf-8")
    third.chmod(third.stat().st_mode | stat.S_IXUSR)
    cache.invalidate()
    assert cache.commands(path_value) == ("alpha", "beta", "gamma")


def test_path_cache_is_keyed_by_path_not_prefix(tmp_path: Path) -> None:
    now = 0.0
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("alpha", "beta"):
        exe = bindir / name
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    cache = _PathCache(ttl=5.0, monotonic=lambda: now)
    path_value = str(bindir)
    alpha = complete_line("al", 2, builtins=(), aliases=(), path=path_value, path_cache=cache)
    beta = complete_line("be", 2, builtins=(), aliases=(), path=path_value, path_cache=cache)
    assert alpha.candidates == ("alpha",)
    assert beta.candidates == ("beta",)
    assert tuple(cache._cache) == (path_value,)


def test_path_completion_files_dirs_and_hidden_policy(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / ".secret").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo ", 5, builtins=(), aliases=(), path="")
    assert "README.md" in result.candidates
    assert "src/" in result.candidates
    assert ".secret" not in result.candidates
    hidden = complete_line("echo .s", 7, builtins=(), aliases=(), path="")
    assert hidden.candidates == (".secret",)


def test_unicode_path_completion(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "źródło").mkdir()
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo ź", 6, builtins=(), aliases=(), path="")
    assert result.candidates == ("źródło/",)


def test_tilde_completion_preserves_tilde_prefix(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "alpha").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    result = complete_line("echo ~/a", 8, builtins=(), aliases=(), path="")
    assert result.candidates == ("~/alpha",)


def test_path_with_space_is_escaped_unquoted(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "file name.txt").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo file", 9, builtins=(), aliases=(), path="")
    assert result.candidates == (r"file\ name.txt",)
    assert apply_single_completion("echo file", result) == ("echo file\\ name.txt ", 20)


def test_quoted_path_completion_preserves_quote_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "file name.txt").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line('echo "file', 10, builtins=(), aliases=(), path="")
    assert result.candidates == ("file name.txt",)
    assert apply_single_completion('echo "file', result) == ('echo "file name.txt ', 20)


def test_directory_only_completion_after_cd(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "script.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("cd s", 4, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("src/",)


def test_variable_completion_names_only(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "do-not-show")
    result = complete_line(
        "echo $HO",
        8,
        builtins=(),
        aliases=(),
        env={"HOME": "secret"},
        locals={"HOSTNAME": "also-secret"},
        path="",
    )
    assert result.candidates == ("$HOME", "$HOSTNAME")
    assert all("secret" not in candidate for candidate in result.candidates)


def test_braced_variable_completion() -> None:
    result = complete_line(
        "echo ${HO",
        9,
        builtins=(),
        aliases=(),
        env={"HOME": "secret"},
        locals={},
        path="",
    )
    assert result.candidates == ("${HOME}",)


def test_job_completion_with_and_without_provider() -> None:
    none = complete_line("fg ", 3, builtins=BUILTINS, aliases=(), path="")
    jobs = complete_line("fg %", 4, builtins=BUILTINS, aliases=(), job_ids=(1, 12), path="")
    bg_jobs = complete_line("bg %", 4, builtins=BUILTINS, aliases=(), job_ids=(2,), path="")
    assert none.candidates == ()
    assert jobs.candidates == ("%1", "%12")
    assert jobs.rich_candidates[0].kind is CompletionKind.JOB
    assert bg_jobs.candidates == ("%2",)


def test_directory_only_completion_after_pushd(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "script.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = complete_line("pushd s", 7, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ("src/",)
    assert "script.py" not in result.candidates


def test_no_completion_in_comment_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("echo hi # co", 12, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ()


def test_single_quotes_suppress_variable_completion(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    result = complete_line(
        "echo '$HO",
        9,
        builtins=(),
        aliases=(),
        env={"HOME": "do-not-complete"},
        locals={},
        path="",
    )
    assert result.candidates == ()
    assert result.context is not None
    assert result.context.variable_style is None


def test_zero_match_apply_leaves_buffer_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = complete_line("zz", 2, builtins=BUILTINS, aliases=(), path="")
    assert result.candidates == ()
    assert apply_single_completion("zz", result) == ("zz", 2)


def test_common_prefix_for_repeated_tab() -> None:
    result = complete_line(
        "so",
        2,
        builtins=("source", "source_zsh", "source_sh_aliases"),
        aliases=(),
        path="",
    )
    assert common_completion_prefix(result) == "source"


def test_python_symbol_completion_bare_names() -> None:
    result = complete_line(
        "os",
        2,
        builtins=(),
        aliases=(),
        path="",
        python_namespace={"os": object(), "open_file": object(), "value": 1},
    )
    assert result.candidates == ("os",)
    assert result.rich_candidates[0].kind is CompletionKind.PYTHON_SYMBOL


def test_python_dotted_completion_does_not_trigger_user_getattr_or_property() -> None:
    class Hazard:
        def __init__(self) -> None:
            self.side_effects = 0
            self.safe_instance_name = 1

        @property
        def dangerous_property(self) -> int:
            self.side_effects += 1
            return 1

        def __getattr__(self, _name: str) -> object:
            self.side_effects += 1
            raise AttributeError

    hazard = Hazard()
    result = complete_line(
        "obj.safe",
        8,
        builtins=(),
        aliases=(),
        path="",
        python_namespace={"obj": hazard},
    )
    assert "obj.safe_instance_name" in result.candidates
    assert hazard.side_effects == 0


def test_python_dotted_completion_skips_slotted_dynamic_attributes_safely() -> None:
    class Trap:
        __slots__ = ("called",)

        def __init__(self) -> None:
            self.called = False

        def __getattr__(self, name: str) -> object:
            self.called = True
            raise AttributeError(name)

    trap = Trap()
    complete_line(
        "obj.pa",
        6,
        builtins=(),
        aliases=(),
        path="",
        python_namespace={"obj": trap},
    )
    assert trap.called is False


def test_candidate_labels_include_alias_and_job_id() -> None:
    alias_candidate = CompletionCandidate("gs", CompletionKind.ALIAS)
    job_candidate = CompletionCandidate("%1", CompletionKind.JOB)
    assert alias_candidate.labeled_menu_text == "gs [alias]"
    assert job_candidate.labeled_menu_text == "%1 [job]"


# --------------------------------------------- Issue #32 integration commands
#
# PySH does not implement any Issue #32-specific completion code. External
# integration commands (pip, docker, kubectl, ecli, guardbsd, aeronerve)
# participate in command-position completion purely through the existing,
# generic ``_PathCache``/``_path_command_candidates`` PATH executable
# discovery already exercised above for arbitrary tools -- the same
# prefix-only, deduplicated, non-executing contract BUG-020 locked in.
# These tests prove that generic contract also covers the Issue #32 tools,
# without adding a single line of tool-specific production code.


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _integration_bin_dir(tmp_path: Path) -> Path:
    """A PATH directory with stub executables for representative tools.

    Includes pre-existing (uv, git) and Issue #32 (pip, docker, kubectl,
    ecli, guardbsd, aeronerve) tools side by side to prove none of them is
    treated specially by the completion engine.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("uv", "pip", "git", "ecli", "docker", "kubectl", "guardbsd", "aeronerve"):
        _make_executable(bindir / name)
    return bindir


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("u", "uv"),
        ("pi", "pip"),
        ("gi", "git"),
        ("doc", "docker"),
        ("kub", "kubectl"),
        ("ec", "ecli"),
        ("gua", "guardbsd"),
        ("aero", "aeronerve"),
    ],
)
def test_issue32_integration_commands_match_by_prefix(
    tmp_path: Path, prefix: str, expected: str
) -> None:
    bindir = _integration_bin_dir(tmp_path)
    result = complete_line(prefix, len(prefix), builtins=(), aliases=(), path=str(bindir))
    assert expected in result.candidates


@pytest.mark.parametrize(
    ("prefix", "excluded"),
    [
        ("ock", "docker"),
        ("ctl", "kubectl"),
        ("cli", "ecli"),
    ],
)
def test_issue32_integration_commands_never_match_by_substring(
    tmp_path: Path, prefix: str, excluded: str
) -> None:
    """A substring occurring mid-name must never produce a completion match."""
    bindir = _integration_bin_dir(tmp_path)
    result = complete_line(prefix, len(prefix), builtins=(), aliases=(), path=str(bindir))
    assert excluded not in result.candidates
    assert result.candidates == ()


def test_issue32_integration_candidates_are_deterministic_and_deduplicated(
    tmp_path: Path,
) -> None:
    bindir = _integration_bin_dir(tmp_path)
    first = complete_line("d", 1, builtins=(), aliases=(), path=str(bindir))
    second = complete_line("d", 1, builtins=(), aliases=(), path=str(bindir))
    assert first.candidates == second.candidates
    assert len(first.candidates) == len(set(first.candidates))


def test_issue32_completion_never_calls_subprocess(monkeypatch, tmp_path: Path) -> None:
    """Command-position completion must never shell out to find a candidate.

    Only filesystem inspection (``Path.iterdir``/``os.access``, used
    internally by ``_PathCache``) is allowed, even for integration-looking
    prefixes.
    """
    import subprocess  # noqa: PLC0415

    def explode(*_args, **_kwargs):  # noqa: ANN002,ANN003,ANN202
        raise AssertionError("completion must not invoke subprocess.run")

    monkeypatch.setattr(subprocess, "run", explode)
    bindir = _integration_bin_dir(tmp_path)
    for prefix in ("pi", "doc", "kub", "ec", "gua", "aero"):
        complete_line(prefix, len(prefix), builtins=(), aliases=(), path=str(bindir))


def test_issue32_absent_integration_executable_does_not_appear(tmp_path: Path) -> None:
    """A tool absent from PATH must not be offered as a command candidate."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir / "docker")  # only docker is "installed"
    result = complete_line("gua", 3, builtins=(), aliases=(), path=str(bindir))
    assert result.candidates == ()
    result = complete_line("aero", 4, builtins=(), aliases=(), path=str(bindir))
    assert result.candidates == ()


def test_issue32_integration_commands_use_ordinary_command_ranking(
    tmp_path: Path,
) -> None:
    """Integration executables are ordinary COMMAND candidates.

    No new ``CompletionKind`` and no ranking exception exists merely because
    a command happens to be an Issue #32 integration.
    """
    bindir = _integration_bin_dir(tmp_path)
    result = complete_line("doc", 3, builtins=(), aliases=(), path=str(bindir))
    assert result.rich_candidates[0].kind is CompletionKind.COMMAND
    assert result.rich_candidates[0].match_type is CompletionMatchType.PREFIX
