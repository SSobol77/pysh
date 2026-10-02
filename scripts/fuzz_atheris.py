#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/fuzz_atheris.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Coverage-guided fuzzing and portable replay for the PySH parser targets (Issue #49).

Everything except the engine run is portable and never imports Atheris::

    # replay a permanent regression record (any platform)
    uv run python scripts/fuzz_atheris.py --replay tests/fuzz/regressions/<sha256>.json
    # replay one input
    uv run python scripts/fuzz_atheris.py --target split_chain --input-hex 6120 --encoding bytes-hex
    # materialize the deterministic seed corpus from the #48 corpus + regressions
    uv run python scripts/fuzz_atheris.py --prepare-corpus /tmp/pysh-corpus --target split_chain

The coverage-guided engine is Linux x86_64 only (``fuzz`` dependency group)::

    uv run --group fuzz python scripts/fuzz_atheris.py --target split_chain --max-total-time 5

The engine runs in a child process under a hard wall-clock bound; temporary
directories are removed on success, and any finding is re-checked by the portable
replay so it is classified as a reproducible parser defect or a harness/engine
suspect. Targets run hermetically (empty temp cwd, cleared environment, fake
command-substitution runner, subprocess tripwires): no generated input is ever
executed.

Exit codes: 0 clean, 1 reproduced finding, 2 usage/schema error, 3 engine
unavailable, 4 engine exceeded its hard bound, 5 finding not reproduced by the
portable replay (harness/engine suspect).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

EXIT_CLEAN = 0
EXIT_FINDING = 1
EXIT_USAGE = 2
EXIT_NO_ENGINE = 3
EXIT_TIMEOUT = 4
EXIT_NOT_REPRODUCED = 5

DEFAULT_MAX_TOTAL_TIME = 10
MAX_ALLOWED_TOTAL_TIME = 3600
HANG_SECONDS = 5  # libFuzzer per-input timeout
RSS_LIMIT_MB = 1024
ENGINE_GRACE_SECONDS = 60
REPLAY_TIMEOUT_SECONDS = 30
ARTIFACT_PREFIXES = ("crash-", "timeout-", "oom-", "leak-", "slow-unit-")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--prepare-corpus", metavar="DIR")
    parser.add_argument("--replay", metavar="RECORD.json")
    parser.add_argument("--target", help="registry name or unambiguous short name")
    parser.add_argument("--input-hex")
    parser.add_argument("--input-file", metavar="FILE", help="raw fuzz bytes (an engine artifact)")
    parser.add_argument("--encoding", choices=("bytes-hex", "text-hex"), default="bytes-hex")
    parser.add_argument("--property", default=None)
    parser.add_argument("--max-total-time", type=int, default=None)
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--artifact-dir", metavar="DIR")
    parser.add_argument("--engine-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corpus-dir", help=argparse.SUPPRESS)
    parser.add_argument("--cwd-dir", help=argparse.SUPPRESS)
    return parser


def _fail_usage(message: str) -> int:
    print(f"fuzz: {message}", file=sys.stderr)
    return EXIT_USAGE


def _report(error: BaseException) -> None:
    print(str(error))


# --- portable modes ---------------------------------------------------------------


def _replay_input(args: argparse.Namespace) -> int:
    from tests.fuzz_support import driver
    from tests.fuzz_support.repro import PropertyFailure
    from tests.fuzz_support.targets import HarnessError

    try:
        target = driver.resolve_target(args.target)
    except KeyError as error:
        return _fail_usage(str(error.args[0]))
    if args.input_file is not None:
        text = driver.decode_bytes(Path(args.input_file).read_bytes())
        source, encoding, input_hex = f"file:{Path(args.input_file).name}", "bytes-hex", None
    else:
        try:
            raw = bytes.fromhex(args.input_hex)
        except ValueError:
            return _fail_usage("--input-hex is not valid hex")
        text = driver.decode_bytes(raw) if args.encoding == "bytes-hex" else raw.decode("utf-8", "surrogatepass")
        source, encoding, input_hex = "cli", args.encoding, args.input_hex
    names = [args.property] if args.property else ["totality", "determinism"]
    command = driver.replay_command(target.name, encoding, input_hex) if input_hex is not None else None
    with driver.replay_context(Path(args.cwd_dir) if args.cwd_dir else None) as ctx:
        for name in names:
            if name not in driver.PROPERTIES:
                return _fail_usage(f"unknown property {name!r}")
            try:
                driver.replay_text(target, name, text, ctx, source=source, command=command)
            except PropertyFailure as failure:
                _report(failure)
                return EXIT_FINDING
            except HarnessError as error:
                print(f"fuzz: HARNESS DEFECT: {error}", file=sys.stderr)
                return EXIT_FINDING
    print(f"fuzz: replay ok ({target.name}, {', '.join(names)})")
    return EXIT_CLEAN


def _replay_record(path: Path) -> int:
    from tests.fuzz_support import driver
    from tests.fuzz_support.repro import PropertyFailure
    from tests.fuzz_support.targets import HarnessError

    try:
        record = driver.load_record(path)
    except driver.RegressionError as error:
        return _fail_usage(str(error))
    with driver.replay_context() as ctx:
        try:
            driver.replay_record(record, ctx)
        except PropertyFailure as failure:
            _report(failure)
            return EXIT_FINDING
        except HarnessError as error:
            print(f"fuzz: HARNESS DEFECT: {error}", file=sys.stderr)
            return EXIT_FINDING
    print(f"fuzz: replay ok ({record.target}, {record.property_name}, {record.sha256[:12]})")
    return EXIT_CLEAN


def _prepare_corpus(directory: str, target_name: str | None) -> int:
    from tests.fuzz_support import driver

    target = None
    if target_name is not None:
        try:
            target = driver.resolve_target(target_name).name
        except KeyError as error:
            return _fail_usage(str(error.args[0]))
    try:
        count = driver.materialize_corpus(Path(directory), target)
    except FileExistsError as error:
        return _fail_usage(str(error))
    except driver.RegressionError as error:
        return _fail_usage(str(error))
    print(f"fuzz: wrote {count} seeds to {directory}")
    return EXIT_CLEAN


# --- engine -------------------------------------------------------------------------


def _engine_child(args: argparse.Namespace) -> int:
    """Run libFuzzer through Atheris in this process (invoked only by the parent)."""
    import atheris

    with atheris.instrument_imports():  # coverage feedback for the parser modules
        from tests.fuzz_support import driver

    target = driver.resolve_target(args.target)
    check = driver.engine_check(target)
    libfuzzer = [
        args.corpus_dir,
        f"-max_total_time={args.max_total_time}",
        f"-seed={args.seed}",
        f"-max_len={driver.MAX_ENGINE_INPUT_BYTES}",
        f"-timeout={HANG_SECONDS}",
        f"-rss_limit_mb={RSS_LIMIT_MB}",
        f"-artifact_prefix={args.artifact_dir}{os.sep}",
        "-print_final_stats=0",
    ]
    if args.runs is not None:
        libfuzzer.append(f"-runs={args.runs}")
    with driver.replay_context(Path(args.cwd_dir)) as ctx:

        def one_input(data: bytes) -> None:
            check(data, ctx)

        atheris.Setup([sys.argv[0], *libfuzzer], one_input)
        atheris.Fuzz()
    return EXIT_CLEAN


def _run_engine(args: argparse.Namespace) -> int:
    from tests.fuzz_support import driver

    try:
        target = driver.resolve_target(args.target)
    except KeyError as error:
        return _fail_usage(str(error.args[0]))
    if target.name in driver.EXCLUDED_TARGETS:
        return _fail_usage(f"{target.name} is excluded: {driver.EXCLUDED_TARGETS[target.name]}")
    max_time = args.max_total_time
    if max_time is None:
        max_time = DEFAULT_MAX_TOTAL_TIME
    if not 1 <= max_time <= MAX_ALLOWED_TOTAL_TIME:
        return _fail_usage(f"--max-total-time must be within 1..{MAX_ALLOWED_TOTAL_TIME}")

    if importlib.util.find_spec("atheris") is None:
        print(
            "fuzz: Atheris is not installed (Linux x86_64 'fuzz' group): "
            "run `uv run --group fuzz python scripts/fuzz_atheris.py ...`. "
            "Portable replay (--replay/--input-hex) does not need it.",
            file=sys.stderr,
        )
        return EXIT_NO_ENGINE
    work = Path(tempfile.mkdtemp(prefix="pysh-fuzz-run-"))
    corpus = work / "corpus"
    cwd = work / "cwd"
    cwd.mkdir()
    artifacts = Path(args.artifact_dir) if args.artifact_dir else work / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    keep = False
    try:
        seeds = driver.materialize_corpus(corpus, target.name)
        print(f"fuzz: {target.name}: {seeds} seeds, {max_time}s bound, seed {args.seed}", flush=True)
        command = [
            sys.executable, str(Path(__file__).resolve()), "--engine-child",
            "--target", target.name, "--corpus-dir", str(corpus), "--artifact-dir", str(artifacts),
            "--cwd-dir", str(cwd),
            "--max-total-time", str(max_time), "--seed", str(args.seed),
        ]
        if args.runs is not None:
            command += ["--runs", str(args.runs)]
        process = subprocess.Popen(command, start_new_session=True)  # noqa: S603 - fixed argv
        try:
            code = process.wait(timeout=max_time + ENGINE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            print("fuzz: engine exceeded its hard time bound and was killed", file=sys.stderr)
            return EXIT_TIMEOUT
        found = sorted(p for p in artifacts.iterdir() if p.name.startswith(ARTIFACT_PREFIXES))
        if code == 0 and not found:
            print("fuzz: no findings")
            return EXIT_CLEAN
        keep = True
        replay_cwd = work / "replay-cwd"
        replay_cwd.mkdir()
        return _classify_findings(target.name, found, replay_cwd, code)
    finally:
        if keep and not args.artifact_dir:
            shutil.rmtree(corpus, ignore_errors=True)
            shutil.rmtree(cwd, ignore_errors=True)
            shutil.rmtree(work / "replay-cwd", ignore_errors=True)
            print(f"fuzz: artifacts kept in {artifacts}", file=sys.stderr)
        elif args.artifact_dir:
            shutil.rmtree(work, ignore_errors=True)
        else:
            shutil.rmtree(work, ignore_errors=True)


def _classify_findings(
    target: str, artifacts_found: list[Path], replay_cwd: Path, code: int
) -> int:
    if not artifacts_found:
        print(f"fuzz: engine exited {code} without an artifact (engine/harness suspect)", file=sys.stderr)
        return EXIT_NOT_REPRODUCED
    status = EXIT_NOT_REPRODUCED
    for artifact in artifacts_found:
        print(f"fuzz: finding {artifact.name} -> portable replay")
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv
                [sys.executable, str(Path(__file__).resolve()), "--target", target,
                 "--input-file", str(artifact), "--cwd-dir", str(replay_cwd)],
                capture_output=True, text=True, timeout=REPLAY_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired:
            print("fuzz: classification: HANG reproduced by replay (parser defect candidate)")
            status = EXIT_FINDING
            continue
        print(done.stdout, end="")
        print(done.stderr, end="", file=sys.stderr)
        if done.returncode == EXIT_FINDING:
            print("fuzz: classification: REPRODUCED - parser/runtime defect candidate. "
                  "Do not filter the input; minimize it, add a failing regression record, then fix.")
            status = EXIT_FINDING
        elif done.returncode == EXIT_CLEAN:
            print("fuzz: classification: NOT reproduced by portable replay - harness/engine suspect")
    return status


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.engine_child:
        return _engine_child(args)
    if args.list_targets:
        from tests.fuzz_support import driver

        for target in driver.fuzzable_targets():
            print(target.name)
        for name, reason in sorted(driver.EXCLUDED_TARGETS.items()):
            print(f"{name}  (excluded: {reason})")
        return EXIT_CLEAN
    if args.prepare_corpus is not None:
        return _prepare_corpus(args.prepare_corpus, args.target)
    if args.replay is not None:
        return _replay_record(Path(args.replay))
    if args.target is None:
        return _fail_usage("a mode is required: --list-targets, --prepare-corpus, --replay, or --target")
    if args.input_hex is not None or args.input_file is not None:
        return _replay_input(args)
    return _run_engine(args)


if __name__ == "__main__":
    sys.exit(main())
