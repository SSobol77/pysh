# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_command_substitution_native.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #54 Slice 2.5: command substitution executes through PySH, never a legacy shell."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pysh.parsing import expansion

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPANSION = REPO_ROOT / "src" / "pysh" / "parsing" / "expansion.py"
LEGACY_NAMES = {"sh", "bash", "zsh", "fish", "dash", "ksh", "/bin/sh", "/bin/bash", "/bin/zsh"}


class _Spy:
    """Record every process-creation attempt made by the default runner."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.shell_flags: list[object] = []


def _spy_on_processes(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    spy = _Spy()
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):
            spy.argvs.append(list(args) if not isinstance(args, str) else [args])
            spy.shell_flags.append(kw.get("shell", False))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    return spy


def test_default_runner_does_not_use_a_legacy_shell_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Architecture assertion: the production path never launches /bin/sh or another shell."""
    spy = _spy_on_processes(monkeypatch)
    real_run = subprocess.run

    def spying_run(args, *a, **kw):
        spy.argvs.append(list(args) if not isinstance(args, str) else [args])
        spy.shell_flags.append(kw.get("shell", False))
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spying_run)
    assert expansion.expand_command_substitution("echo $(printf hi)") == "echo hi"
    assert spy.argvs, "the default runner must execute something"
    for argv, shell_flag in zip(spy.argvs, spy.shell_flags, strict=True):
        assert shell_flag is not True
        assert Path(argv[0]).name not in LEGACY_NAMES, argv
        assert not set(argv) & LEGACY_NAMES, argv


# --- behavior: the nested command is PySH ---------------------------------------------------


@pytest.fixture
def shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pysh.config.startup import NO_RC_STARTUP_POLICY
    from pysh.core.shell import PyShell

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYSH_ZSH_FALLBACK", raising=False)
    monkeypatch.delenv(expansion.SUBSTITUTION_DEPTH_ENV, raising=False)
    return PyShell(startup_policy=NO_RC_STARTUP_POLICY)


def _out(shell, capfd: pytest.CaptureFixture[str], line: str) -> tuple[int, str, str]:
    capfd.readouterr()
    status = shell.execute(line)
    captured = capfd.readouterr()
    return status, captured.out, captured.err


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo $(printf hello)", "hello\n"),
        ("echo `printf hello`", "hello\n"),
        ('echo "[$(printf hello)]"', "[hello]\n"),
        ("echo $(printf a) $(printf b)", "a b\n"),
        ("echo x$(printf y)z", "xyz\n"),
        ("echo [$(printf 'a\\n\\n')]", "[a]\n"),
        ("echo '$(printf no)'", "$(printf no)\n"),
        ("echo $(echo $(printf nested))", "nested\n"),
        ('echo "$(echo "$(printf deep)")"', "deep\n"),
        ("echo $(printf hello | tr a-z A-Z)", "HELLO\n"),
        ("echo $(printf one; printf two)", "onetwo\n"),
    ],
)
def test_substitution_forms_run_through_pysh(shell, capfd, line: str, expected: str) -> None:
    status, out, err = _out(shell, capfd, line)
    assert (status, out, err) == (0, expected, "")


def test_nested_command_is_parsed_by_pysh_not_a_posix_shell(shell, capfd) -> None:
    # Shell control flow is unsupported PySH syntax (#48 PYSH-LANG-ERROR-UNSUPPORTED);
    # a POSIX shell would happily print "x".
    status, out, err = _out(shell, capfd, "echo [$(if true; then printf x; fi)]")
    assert (status, out, err) == (0, "[]\n", "")
    assert "unsupported syntax" in expansion._run_nested("if true; then printf x; fi", 20.0).stderr


def test_nested_redirections_follow_pysh_rules(shell, capfd, tmp_path: Path) -> None:
    (tmp_path / "in.txt").write_text("from-file\n", encoding="utf-8")
    assert _out(shell, capfd, "echo $(cat < in.txt)") == (0, "from-file\n", "")
    status, out, err = _out(shell, capfd, "echo [$(printf data > out.txt)]")
    assert (status, out, err) == (0, "[]\n", "")
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "data"


def test_exported_environment_and_cwd_are_visible_and_unexported_locals_are_not(
    shell, capfd, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYSH_T_EXPORTED", "exported-value")
    assert _out(shell, capfd, "echo $(echo $PYSH_T_EXPORTED)")[1] == "exported-value\n"
    out = _out(shell, capfd, "echo $(pwd)")[1].strip()
    assert Path(out).resolve() == tmp_path.resolve()
    # Characterization (unspecified by #48, unchanged since the /bin/sh backend):
    # a session-local, unexported variable is not visible to the nested process.
    shell.local_vars["PYSH_T_LOCAL"] = "secret"
    assert _out(shell, capfd, "echo [$(echo $PYSH_T_LOCAL)]")[1] == "[]\n"


def test_nested_cd_and_exports_do_not_change_the_outer_shell(shell, capfd, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _out(shell, capfd, "echo $(cd sub; export PYSH_T_LEAK=1; pwd)")
    assert Path.cwd().resolve() == tmp_path.resolve()
    assert "PYSH_T_LEAK" not in os.environ


def test_failures_are_contained_and_nested_stderr_is_not_forwarded(shell, capfd) -> None:
    # Nested stderr was captured and discarded before Slice 2.5; that stays true.
    cases = {
        "echo [$(nonexistent_cmd_xyz)]": "command not found",
        "echo [$(printf x > /nonexistent-dir-xyz/f)]": "No such file",
        "echo [$(| x)]": "parse error",
        "echo [$(false)]": "",
        "echo [$({py} -c 'import sys; sys.stderr.write(\"ERRONLY\")')]": "ERRONLY",
    }
    for line, diagnostic in cases.items():
        line = line.replace("{py}", sys.executable)
        status, out, err = _out(shell, capfd, line)
        assert (status, out, err) == (0, "[]\n", ""), (line, err)
        inner = line[line.index("$(") + 2 : line.rindex(")")]
        captured = expansion._run_nested(inner, 20.0)
        assert diagnostic in captured.stderr and "Traceback" not in captured.stderr, inner
    assert _out(shell, capfd, "echo $(printf hello)")[1] == "hello\n"  # shell still healthy


def test_empty_stdout_and_multiple_trailing_newlines(shell, capfd) -> None:
    assert _out(shell, capfd, "echo [$(true)]") == (0, "[]\n", "")
    assert _out(shell, capfd, "echo [$(printf 'a\\n\\n\\n')]") == (0, "[a]\n", "")


def test_signal_terminated_nested_command_yields_empty_text(shell, capfd) -> None:
    fixture = Path(__file__).parent / "fixtures" / "differential_reference_child.py"
    line = f"echo [$({sys.executable} {fixture} signal 9)]"
    assert _out(shell, capfd, line) == (0, "[]\n", "")


def test_startup_configuration_is_never_read_by_the_nested_process(shell, capfd, tmp_path: Path) -> None:
    (tmp_path / ".pyshrc.py").write_text('print("RC-LOADED")\n', encoding="utf-8")
    status, out, err = _out(shell, capfd, "echo [$(printf x)]")
    assert (status, out, err) == (0, "[x]\n", "")


def test_substitution_does_not_use_the_legacy_zsh_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd
) -> None:
    from pysh.config.startup import NO_RC_STARTUP_POLICY
    from pysh.core.shell import PyShell

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_zsh = bin_dir / "zsh"
    fake_zsh.write_text("#!/bin/sh\necho ZSH-USED\n", encoding="utf-8")
    fake_zsh.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYSH_ZSH_FALLBACK", "1")
    shell = PyShell(startup_policy=NO_RC_STARTUP_POLICY)
    assert shell.zsh_fallback_enabled
    # Control: the armed outer shell does fall back to zsh for an unknown command.
    assert "ZSH-USED" in _out(shell, capfd, "nonexistent_cmd_xyz")[1]
    # The nested substitution is PySH-native: the fallback is not armed inside it.
    status, out, err = _out(shell, capfd, "echo [$(nonexistent_cmd_xyz)]")
    assert out == "[]\n" and "ZSH-USED" not in out
    assert "command not found" in expansion._run_nested("nonexistent_cmd_xyz", 20.0).stderr
    assert "PYSH_ZSH_FALLBACK" not in expansion._nested_environment(0)


# --- recursion, timeout, resources -----------------------------------------------------------


def test_nesting_depth_is_bounded_with_a_controlled_diagnostic(
    shell, capfd, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(expansion.SUBSTITUTION_DEPTH_ENV, str(expansion.MAX_SUBSTITUTION_DEPTH))
    status, out, err = _out(shell, capfd, "echo [$(printf x)]")
    assert (status, out) == (0, "[]\n")
    assert "nesting deeper than" in err and "Traceback" not in err
    assert os.environ[expansion.SUBSTITUTION_DEPTH_ENV] == str(expansion.MAX_SUBSTITUTION_DEPTH)
    monkeypatch.setenv(expansion.SUBSTITUTION_DEPTH_ENV, str(expansion.MAX_SUBSTITUTION_DEPTH - 1))
    assert _out(shell, capfd, "echo [$(printf x)]")[1] == "[x]\n"
    monkeypatch.setenv(expansion.SUBSTITUTION_DEPTH_ENV, "garbage")
    assert _out(shell, capfd, "echo [$(printf x)]")[1] == "[x]\n"


def test_timeout_terminates_the_whole_nested_process_group(shell, capfd) -> None:
    import time

    start = time.monotonic()
    out = expansion.expand_command_substitution("X=$(sleep 4)", timeout=1.5)
    assert out == "X="
    assert time.monotonic() - start < 10
    assert "timed out" in capfd.readouterr().err


def test_repeated_substitutions_leak_no_descriptors_or_children(shell, capfd) -> None:
    from tests.fuzz_support import fdprobe
    from tests.fuzz_support.execution import unreaped_child

    _out(shell, capfd, "echo $(printf warm)")
    before = fdprobe.open_fds()
    for _ in range(8):
        assert _out(shell, capfd, "echo $(printf a | cat) $(echo b)")[1] == "a b\n"
    expansion.expand_command_substitution("X=$(sleep 4)", timeout=0.5)
    assert fdprobe.open_fds() == before
    assert unreaped_child() is None
    capfd.readouterr()


# --- test seams ------------------------------------------------------------------------------


def test_explicit_fake_runner_injection_still_works() -> None:
    seen: list[str] = []

    def fake(command: str, _timeout: float) -> str:
        seen.append(command)
        return "FAKE"

    assert expansion.expand_command_substitution("echo $(any thing) `x`", runner=fake) == "echo FAKE FAKE"
    assert seen == ["any thing", "x"]


def test_patching_the_default_runner_still_isolates_runner_less_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(expansion, "_default_runner", lambda command, timeout: f"<{command}>")
    assert expansion.expand_command_substitution("echo $(hi)") == "echo <hi>"


# --- architecture guard ----------------------------------------------------------------------


def test_production_substitution_module_has_no_legacy_shell_reference() -> None:
    from tests.differential import boundaries

    source = EXPANSION.read_text(encoding="utf-8")
    # The single permitted token is the defensive scrub of the fallback variable name.
    assert boundaries.scan_source(source) == frozenset({"<module>"})
    tree = ast.parse(source)
    legacy_constants = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and boundaries._is_legacy_constant(n.value)
    ]
    assert legacy_constants == ["PYSH_ZSH_FALLBACK"]
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert isinstance(node.value, ast.Constant) and node.value.value is False
        if isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            assert name not in {"ZshBridge", "zsh_bridge", "_run_zsh_fallback", "zsh_fallback_enabled"}
    runners = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in {"_default_runner", "_run_nested"}
    ]
    assert len(runners) == 2
    constants = {
        n.value for r in runners for n in ast.walk(r)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert {"-m", "pysh", "--no-rc", "-c"} <= constants
    assert not constants & LEGACY_NAMES
    assert sys.executable  # the nested interpreter is the running Python


# --- process-tree containment ----------------------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "differential_reference_child.py"


def _beat_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _wait_for_beat(path: Path, deadline_seconds: float = 20.0) -> None:
    import time

    deadline = time.monotonic() + deadline_seconds
    while _beat_size(path) == 0:
        assert time.monotonic() < deadline, "the grandchild never started"
        time.sleep(0.01)


def _assert_beat_stopped(path: Path) -> None:
    import time

    first = _beat_size(path)
    assert first > 0, "the descendant never ran"
    time.sleep(0.4)
    assert _beat_size(path) == first, "a descendant of the substitution survived it"


@pytest.mark.parametrize(
    "template",
    [
        "{py} {fixture} heartbeat {beat}",  # external grandchild of the nested PySH
        "{py} {fixture} heartbeat {beat} | cat",  # forked pipeline stage
    ],
)
def test_timeout_leaves_no_descendant(tmp_path: Path, template: str) -> None:
    from tests.fuzz_support.execution import unreaped_child

    beat = tmp_path / "beat"
    command = template.format(py=sys.executable, fixture=FIXTURE, beat=beat)
    assert expansion.expand_command_substitution(f"X=$({command})", timeout=2.5) == "X="
    _assert_beat_stopped(beat)
    assert unreaped_child() is None


def test_normal_completion_leaves_no_descendant(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    command = f"{sys.executable} {FIXTURE} spawn-exit {beat}"
    out = expansion.expand_command_substitution(f"X=$({command})", timeout=30.0)
    assert out.startswith("X=") and out[2:].strip().isdigit()  # the fixture printed a pid
    _assert_beat_stopped(beat)


def test_cancellation_leaves_no_descendant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    beat = tmp_path / "beat"
    real_wait = expansion._wait_exited

    def cancelled(process, timeout):
        _wait_for_beat(beat)
        raise KeyboardInterrupt

    monkeypatch.setattr(expansion, "_wait_exited", cancelled)
    with pytest.raises(KeyboardInterrupt):
        expansion.expand_command_substitution(f"X=$({sys.executable} {FIXTURE} heartbeat {beat})")
    monkeypatch.setattr(expansion, "_wait_exited", real_wait)
    _assert_beat_stopped(beat)


def test_launch_failure_is_contained(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def refuse(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    assert expansion.expand_command_substitution("X=$(printf x)") == "X="
    assert "substitution error" in capsys.readouterr().err


PROBE = "import os; print(os.getpid(), os.getpgrp(), os.getppid())"


def _probe_groups(env_extra: dict[str, str], pass_fds: tuple[int, ...] = ()) -> tuple[int, int, int]:
    """Run an external command under a top-level ``pysh -c`` and report (pid, pgid, ppid)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYSH_SUBSTITUTION")}
    env.update(env_extra)
    done = subprocess.run(
        [sys.executable, "-m", "pysh", "--no-rc", "-c", f"{sys.executable} -c '{PROBE}'"],
        capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, check=True,
        pass_fds=pass_fds,
    )
    pid, pgid, ppid = map(int, done.stdout.split())
    return pid, pgid, ppid


def test_ordinary_pysh_gives_each_external_command_its_own_process_group() -> None:
    pid, pgid, _ppid = _probe_groups({})
    assert pgid == pid


def test_depth_variable_alone_cannot_change_job_control() -> None:
    for depth in ("1", "5", "garbage"):
        pid, pgid, _ = _probe_groups({expansion.SUBSTITUTION_DEPTH_ENV: depth})
        assert pgid == pid, depth


def test_forged_capability_values_never_grant_containment() -> None:
    token = "0" * 32
    wrong_content_r, wrong_content_w = os.pipe()
    os.write(wrong_content_w, b"unrelated bytes")
    os.close(wrong_content_w)
    regular = os.open(__file__, os.O_RDONLY)
    try:
        forged = [
            ({expansion.CAPABILITY_ENV: "garbage"}, ()),
            ({expansion.CAPABILITY_ENV: f"99:{token}"}, ()),  # descriptor does not exist
            ({expansion.CAPABILITY_ENV: f"1:{token}"}, ()),  # not a FIFO / wrong content
            ({expansion.CAPABILITY_ENV: f"{regular}:{token}"}, (regular,)),  # not a FIFO
            ({expansion.CAPABILITY_ENV: f"{wrong_content_r}:{token}"}, (wrong_content_r,)),  # wrong token
            ({expansion.CAPABILITY_ENV: f"{wrong_content_r}:{token}",
              expansion.SUBSTITUTION_DEPTH_ENV: "3"}, (wrong_content_r,)),
        ]
        for env_extra, fds in forged:
            pid, pgid, _ = _probe_groups(env_extra, fds)
            assert pgid == pid, env_extra
    finally:
        os.close(wrong_content_r)
        os.close(regular)


def test_capability_validation_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "ab" * 16
    good = expansion._CAPABILITY_MAGIC + token.encode()

    def pipe_with(data: bytes) -> int:
        r, w = os.pipe()
        os.write(w, data)
        os.close(w)
        return r

    def closed(fd: int) -> bool:
        try:
            os.fstat(fd)
        except OSError:
            return True
        return False

    monkeypatch.delenv(expansion.CAPABILITY_ENV, raising=False)
    assert expansion._consume_capability() is False  # no variable
    r = pipe_with(good)
    monkeypatch.setenv(expansion.CAPABILITY_ENV, f"{r}:{token}")
    assert expansion._consume_capability() is True
    assert closed(r) and expansion.CAPABILITY_ENV not in os.environ  # consumed and scrubbed
    r = pipe_with(b"other")
    monkeypatch.setenv(expansion.CAPABILITY_ENV, f"{r}:{token}")
    assert expansion._consume_capability() is False
    # An unrelated descriptor is never closed (validation had to read a bounded prefix).
    assert not closed(r) and expansion.CAPABILITY_ENV not in os.environ
    os.close(r)
    r = pipe_with(good)
    monkeypatch.setenv(expansion.CAPABILITY_ENV, f"{r}:{'cd' * 16}")  # right fd, wrong token
    assert expansion._consume_capability() is False and not closed(r)
    os.close(r)


def test_ordinary_in_process_shell_is_not_contained(shell) -> None:
    assert shell._descendants_contained is False


def test_real_substitution_runs_externals_in_the_substitution_process_group() -> None:
    result = expansion._run_nested(f"{sys.executable} -c '{PROBE}'", 30.0)
    pid, pgid, ppid = map(int, result.stdout.split())
    assert pgid == ppid != pid  # stays in the nested PySH's group instead of its own


def test_nested_pipeline_stage_stays_in_the_substitution_group() -> None:
    result = expansion._run_nested(f"{sys.executable} -c '{PROBE}' | cat", 30.0)
    pid, pgid, ppid = map(int, result.stdout.split())
    assert pgid != pid


def test_capability_is_not_visible_to_nested_descendants(shell, capfd) -> None:
    import json

    out = _out(shell, capfd, f"echo $({sys.executable} {FIXTURE} openfds)")[1]
    assert json.loads(out) == [0, 1, 2]
    probe = expansion._run_nested(f"{sys.executable} {FIXTURE} env {expansion.CAPABILITY_ENV}", 30.0)
    assert json.loads(probe.stdout) == {expansion.CAPABILITY_ENV: None}
    assert expansion.CAPABILITY_ENV not in os.environ


def test_deeper_nested_levels_are_killed_with_the_outermost_domain(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    inner = f"{sys.executable} {FIXTURE} heartbeat {beat}"
    assert expansion.expand_command_substitution(f"X=$(echo $({inner}))", timeout=4.0) == "X="
    _assert_beat_stopped(beat)


def test_depth_two_substitution_works_and_is_bounded(shell, capfd, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _out(shell, capfd, "echo $(echo $(echo $(printf deep)))")[1] == "deep\n"
    monkeypatch.setenv(expansion.SUBSTITUTION_DEPTH_ENV, str(expansion.MAX_SUBSTITUTION_DEPTH))
    status, out, err = _out(shell, capfd, "echo [$(printf x)]")
    assert (status, out) == (0, "[]\n") and "nesting deeper than" in err and "Traceback" not in err


def test_repeated_substitutions_leave_no_temporary_files(
    shell, capfd, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    for _ in range(6):
        assert _out(shell, capfd, "echo $(printf a) `printf b`")[1] == "a b\n"
    expansion.expand_command_substitution("X=$(sleep 4)", timeout=0.5)
    assert list(scratch.iterdir()) == []


def test_depth_state_never_leaks_into_the_outer_environment(shell, capfd) -> None:
    assert expansion.SUBSTITUTION_DEPTH_ENV not in os.environ
    assert _out(shell, capfd, "echo $(echo $(printf x))")[1] == "x\n"
    assert expansion.SUBSTITUTION_DEPTH_ENV not in os.environ
