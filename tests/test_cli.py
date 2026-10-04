# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_cli.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the pysh CLI entry point."""
from __future__ import annotations

import pytest

from pysh import __version__
from pysh.cli import is_unsupported_system_shell_invocation, main


def test_version_flag_prints_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_short_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_dash_c_runs_command(capfd: pytest.CaptureFixture[str]) -> None:
    status = main(["-c", "echo cli-runs"])
    assert status == 0
    captured = capfd.readouterr()
    assert "cli-runs" in captured.out


@pytest.mark.parametrize("command", ["exit", "quit", "exit ", "exit   ", "quit ", "quit   "])
def test_dash_c_exit_and_quit_return_success_without_internal_error(
    command: str,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert main(["-c", command]) == 0
    captured = capfd.readouterr()
    assert "pysh: internal error" not in captured.err


def test_dash_c_exit_preserves_numeric_status(capfd: pytest.CaptureFixture[str]) -> None:
    assert main(["-c", "exit 7"]) == 7
    captured = capfd.readouterr()
    assert "pysh: internal error" not in captured.err


@pytest.mark.parametrize(
    "argv0",
    ["sh", "/bin/sh", "dash", "/usr/bin/dash", "ash", "/bin/ash"],
)
def test_system_shell_invocation_names_are_rejected(argv0: str) -> None:
    assert is_unsupported_system_shell_invocation(argv0)


@pytest.mark.parametrize("argv0", ["pysh", "/usr/bin/pysh", "__main__.py", "python"])
def test_normal_invocation_names_are_supported(argv0: str) -> None:
    assert not is_unsupported_system_shell_invocation(argv0)


def test_busybox_sh_invocation_is_rejected() -> None:
    assert is_unsupported_system_shell_invocation("busybox", ["sh"])
    assert is_unsupported_system_shell_invocation("/bin/busybox", ["sh"])


def test_busybox_non_sh_invocation_is_not_rejected() -> None:
    assert not is_unsupported_system_shell_invocation("busybox", ["echo", "ok"])
    assert not is_unsupported_system_shell_invocation("/bin/busybox", [])


def test_main_rejects_sh_argv0(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["sh", "-c", "echo should-not-run"])

    assert main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pysh: unsupported invocation mode: sh" in captured.err
    assert "PySH is not a POSIX /bin/sh provider" in captured.err


def test_main_rejects_busybox_sh_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["busybox", "sh", "-c", "echo should-not-run"])

    assert main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pysh: unsupported invocation mode: busybox" in captured.err
    assert "PySH is not a POSIX /bin/sh provider" in captured.err


# --- ``pysh --credits``: an early informational option (PySH 1.0.0) -----------------------------------------------------------

import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pysh.cli as cli  # noqa: E402

EXPECTED_CREDITS = "PySH Project Authors\nSiergej Sobolewski\nJozef Sobolewski\nKarol Sobolewski\n"
AUTHORS = ("Siergej Sobolewski", "Jozef Sobolewski", "Karol Sobolewski")
CONSOLE_SCRIPT = Path(sys.executable).parent / "pysh"


def run_cli(args: list[str], home: Path, *, module: bool = True, stdin: int | None = subprocess.DEVNULL,
            stdout: object = subprocess.PIPE) -> subprocess.CompletedProcess[str]:
    """Run the real CLI with a minimal environment, a disposable HOME and no TTY."""
    command = [sys.executable, "-m", "pysh", *args] if module else [str(CONSOLE_SCRIPT), *args]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "TERM": "dumb", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    return subprocess.run(command, env=env, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, text=True,
                          check=False, cwd=home, timeout=30)


def test_credits_prints_exactly_the_project_authors_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--credits"]) == 0
    captured = capsys.readouterr()
    assert captured.out == EXPECTED_CREDITS and captured.err == ""


def test_the_compatibility_alias_gives_identical_output_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--credits"]) == 0
    canonical = capsys.readouterr()
    assert main(["-credits"]) == 0
    alias = capsys.readouterr()
    assert alias.out == canonical.out == EXPECTED_CREDITS and alias.err == canonical.err == ""


def test_every_author_appears_exactly_once_and_nothing_dynamic_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--credits"])
    out = capsys.readouterr().out
    for author in AUTHORS:
        assert out.count(author) == 1
    assert out.splitlines() == ["PySH Project Authors", *AUTHORS]
    assert not re.search(r"\d|https?:|\x1b|[0-9a-f]{7,}|version|release|candidate", out, re.I)


def test_credits_come_from_the_one_authoritative_data_structure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.PROJECT_AUTHORS == AUTHORS and cli.CREDITS_TITLE == "PySH Project Authors"
    monkeypatch.setattr(cli, "PROJECT_AUTHORS", ("A One", "B Two"))
    for option in ("--credits", "-credits"):
        main([option])
        assert capsys.readouterr().out == "PySH Project Authors\nA One\nB Two\n"


def test_credits_never_start_a_shell_or_any_startup_machinery(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the shell must not be constructed for --credits")

    monkeypatch.setattr(cli, "PyShell", boom)
    monkeypatch.setattr(cli, "AuditLogSink", boom)
    for option in ("--credits", "-credits"):
        assert main([option]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("module", [True, False])
@pytest.mark.parametrize("option", ["--credits", "-credits"])
def test_real_cli_prints_the_credits_without_a_tty_banner_or_prompt(tmp_path: Path, option: str, module: bool) -> None:
    if not module and not CONSOLE_SCRIPT.exists():
        pytest.skip("console script not installed in this environment")
    done = run_cli([option], tmp_path, module=module)
    assert done.returncode == 0 and done.stdout == EXPECTED_CREDITS and done.stderr == ""
    assert "❯" not in done.stdout and "py3." not in done.stdout and "Welcome" not in done.stdout


def test_real_cli_works_with_redirected_stdout_and_closed_stdin(tmp_path: Path) -> None:
    target = tmp_path / "credits.txt"
    with target.open("w", encoding="utf-8") as handle:
        done = run_cli(["--credits"], tmp_path, stdin=subprocess.DEVNULL, stdout=handle)
    assert done.returncode == 0 and target.read_text(encoding="utf-8") == EXPECTED_CREDITS and done.stderr == ""
    piped = subprocess.run([sys.executable, "-m", "pysh", "--credits"], capture_output=True,
                           text=True, input="", env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
                           check=False, timeout=30)
    assert piped.returncode == 0 and piped.stdout == EXPECTED_CREDITS


def test_module_and_console_script_output_are_identical(tmp_path: Path) -> None:
    if not CONSOLE_SCRIPT.exists():
        pytest.skip("console script not installed in this environment")
    assert run_cli(["--credits"], tmp_path, module=True).stdout == run_cli(["--credits"], tmp_path, module=False).stdout


def test_credits_do_not_load_startup_configuration_or_create_any_file(tmp_path: Path) -> None:
    marker = tmp_path / "rc-was-loaded"
    (tmp_path / ".pyshrc.py").write_text(f"open({str(marker)!r}, 'w').write('loaded')\nprint('RC-BANNER')\n", encoding="utf-8")
    (tmp_path / ".pyshrc").write_text(f"echo RC-SHELL > {marker}.shell\n", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    for option in ("--credits", "-credits"):
        done = run_cli([option], tmp_path)
        assert done.returncode == 0 and done.stdout == EXPECTED_CREDITS and "RC-BANNER" not in done.stdout + done.stderr
    assert not marker.exists() and not (tmp_path / f"{marker.name}.shell").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no history, lock, config or cache was created


def test_credits_win_before_the_audit_log_is_opened_or_diagnostics_are_started(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    done = run_cli(["--audit-log", str(log), "--debug", "--no-rc", "--credits"], tmp_path)
    assert done.returncode == 0 and done.stdout == EXPECTED_CREDITS and done.stderr == "" and not log.exists()


def test_version_still_behaves_exactly_as_before(tmp_path: Path) -> None:
    for option in ("--version", "-V"):
        done = run_cli([option], tmp_path)
        assert done.returncode == 0 and done.stdout == f"pysh {__version__}\n" and done.stderr == ""


def test_help_still_works_and_mentions_the_canonical_option(tmp_path: Path) -> None:
    done = run_cli(["--help"], tmp_path)
    assert done.returncode == 0 and "--credits prints the project authors and exits." in " ".join(done.stdout.split())
    assert "-credits" not in done.stdout.replace("--credits", "")  # the alias is not the documented syntax


def test_version_and_help_take_precedence_when_they_come_first(tmp_path: Path) -> None:
    done = run_cli(["--version", "--credits"], tmp_path)
    assert done.returncode == 0 and done.stdout == f"pysh {__version__}\n"
    assert "usage: pysh" in run_cli(["-h", "--credits"], tmp_path).stdout
    assert run_cli(["--credits", "--version"], tmp_path).stdout == EXPECTED_CREDITS


@pytest.mark.parametrize("near_miss", ["--credit", "--cred", "--creditss", "--credits=1", "--Credits", "-credit"])
def test_near_matches_are_not_credits(tmp_path: Path, near_miss: str) -> None:
    done = run_cli([near_miss], tmp_path)
    assert "PySH Project Authors" not in done.stdout and "Siergej Sobolewski" not in done.stdout


@pytest.mark.parametrize("near_miss", ["--credit", "--cred", "--creditss", "--credits=1", "--Credits"])
def test_long_near_matches_remain_argument_errors(tmp_path: Path, near_miss: str) -> None:
    done = run_cli([near_miss], tmp_path)
    assert done.returncode == 2 and "unrecognized arguments" in done.stderr and done.stdout == ""


def test_dash_c_semantics_are_unchanged(tmp_path: Path) -> None:
    assert run_cli(["--no-rc", "-c", "echo hi"], tmp_path).stdout == "hi\n"
    done = run_cli(["--no-rc", "-c", "credits"], tmp_path)  # the command word "credits" is just a command
    assert "PySH Project Authors" not in done.stdout and done.returncode == 127
    done = run_cli(["-c", "--credits"], tmp_path)  # -c needs a value: still an argparse usage error
    assert done.returncode == 2 and "PySH Project Authors" not in done.stdout


def test_script_arguments_are_never_interpreted_as_credits(tmp_path: Path) -> None:
    script = tmp_path / "args.pysh"
    script.write_text('echo "$1"\n', encoding="utf-8")
    for option in ("--credits", "-credits"):
        done = run_cli(["--no-rc", str(script), option], tmp_path)
        assert done.returncode == 0 and done.stdout == f"{option}\n"


def test_the_early_scan_only_accepts_the_exact_tokens() -> None:
    assert cli._requests_credits(["--credits"]) and cli._requests_credits(["-credits"])
    assert cli._requests_credits(["--no-rc", "--debug", "--credits"])
    assert cli._requests_credits(["-c", "x", "--credits"])  # a value token is skipped, then the option is seen
    assert cli._requests_credits(["--audit-log", "p", "-credits"])
    for argv in ([], ["--credit"], ["--version", "--credits"], ["-V", "--credits"], ["script.pysh", "--credits"],
                 ["--", "--credits"], ["-c", "--credits"], ["--vers", "--credits"], ["-"], ["--credits=x"]):
        assert not cli._requests_credits(argv), argv


def test_the_early_scan_resolves_argparse_abbreviations(tmp_path: Path) -> None:
    # A value-taking abbreviation skips its value, exactly like the parser reads it.
    for argv in (["--audit", "p", "--credits"], ["--a", "p", "-credits"], ["--audit-lo", "p", "--credits"],
                 ["--audit=p", "--credits"], ["--audit-log=p", "--credits"], ["--no", "--credits"]):
        assert cli._requests_credits(argv), argv
    # Every short or long help/version abbreviation the parser accepts answers first.
    for argv in (["--v", "--credits"], ["--h", "--credits"], ["--he", "--credits"], ["--ve", "--credits"],
                 ["--hel", "--credits"], ["-h", "--credits"], ["-V", "--credits"],
                 ["--no-rc", "--v", "--credits"], ["--audit", "p", "--v", "--credits"]):
        assert not cli._requests_credits(argv), argv
    # Ambiguous abbreviations are left to argparse's own error.
    assert not cli._requests_credits(["--d", "--credits"])
    # End to end: the real parser agrees with the early scan.
    done = run_cli(["--audit", str(tmp_path / "audit.jsonl"), "--credits"], tmp_path)
    assert done.returncode == 0 and done.stdout == cli.credits_text() and done.stderr == ""
    assert not (tmp_path / "audit.jsonl").exists()
    for abbreviation in ("--v", "--ve", "--ver"):
        done = run_cli([abbreviation, "--credits"], tmp_path)
        assert done.returncode == 0 and done.stdout == f"pysh {__version__}\n", abbreviation
    for abbreviation in ("--h", "--he", "--hel"):
        done = run_cli([abbreviation, "--credits"], tmp_path)
        assert done.returncode == 0 and done.stdout.startswith("usage: pysh"), abbreviation
        assert "PySH Project Authors" not in done.stdout


def test_the_early_scan_long_options_match_the_parser() -> None:
    parser_options = {
        option for option in cli._build_parser()._option_string_actions if option.startswith("--")
    }
    assert set(cli._LONG_OPTIONS) == parser_options
    assert cli._OPTIONS_WITH_VALUE <= parser_options | {"-c"}
