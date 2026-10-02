# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_fuzz_driver.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #49 Slice 2: engine-independent driver logic (no Atheris required)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import random
from pathlib import Path

import pytest

from scripts import fuzz_atheris
from scripts.run_language_conformance import DEFAULT_CORPUS
from tests.fuzz_support import driver
from tests.fuzz_support import properties as props
from tests.fuzz_support.repro import (
    PropertyFailure,
    Reproduction,
    format_failure,
    input_sha256,
    traceback_fingerprint,
)
from tests.fuzz_support.targets import TARGETS, TARGETS_BY_NAME


def _record_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": 1,
        "target": "grammar.split_chain",
        "property": "totality",
        "input_encoding": "bytes-hex",
        "input": b"a ; b".hex(),
        "contract_ref": "PYSH-LANG-CHAIN-SEQUENCE",
        "engine": "atheris",
        "seed_or_source": "crash-0123456789abcdef",
        "fixed_in": "issue-49",
    }
    data.update(overrides)
    return data


def _write(directory: Path, data: dict[str, object], name: str | None = None) -> Path:
    if name is None:
        text = driver.RegressionRecord(
            None, str(data["target"]), "p", str(data["input_encoding"]), str(data["input"]),
            "c", "e", "s", "f").text
        name = f"{driver.canonical_sha256(str(data['target']), text)}.json"
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- bytes -> str --------------------------------------------------------------


def test_bytes_map_to_str_deterministically_and_losslessly() -> None:
    assert driver.decode_bytes(b"\xff\x00a") == "\udcff\x00a"
    assert driver.decode_bytes("é日".encode()) == "é日"
    assert driver.decode_bytes(b"") == ""
    for value in range(256):
        data = bytes([value])
        assert driver.text_to_bytes(driver.decode_bytes(data)) == data
    rng = random.Random("driver-roundtrip")
    seen: dict[str, bytes] = {}
    for _ in range(500):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        text = driver.decode_bytes(data)
        assert driver.text_to_bytes(text) == data  # never silently drops a byte
        assert seen.setdefault(text, data) == data  # injective
        assert text == driver.decode_bytes(data)  # deterministic


def test_invalid_utf8_is_an_ordinary_input_not_a_harness_error(tmp_path: Path) -> None:
    with driver.replay_context() as ctx:
        for name in ("lexer.strip_comments", "grammar.split_chain"):
            driver.replay_text(TARGETS_BY_NAME[name], "totality", driver.decode_bytes(b"\xff\xfe a;"),
                               ctx, source="test")


# --- targets ---------------------------------------------------------------------


def test_every_target_is_addressable_by_name_and_short_name() -> None:
    shorts = [t.name.rsplit(".", 1)[-1] for t in TARGETS]
    assert len(shorts) == len(set(shorts))
    for target in TARGETS:
        assert driver.resolve_target(target.name) is target
        assert driver.resolve_target(target.name.rsplit(".", 1)[-1]) is target
    with pytest.raises(KeyError, match="unknown"):
        driver.resolve_target("nope")


def test_exclusions_are_explicit_and_complete() -> None:
    fuzzable = {t.name for t in driver.fuzzable_targets()}
    assert fuzzable | set(driver.EXCLUDED_TARGETS) == set(TARGETS_BY_NAME)
    assert fuzzable.isdisjoint(driver.EXCLUDED_TARGETS)
    assert all(reason.strip() for reason in driver.EXCLUDED_TARGETS.values())


# --- seed corpus ------------------------------------------------------------------


def test_seed_materialization_is_deterministic_and_derived_from_the_authoritative_corpus(
    tmp_path: Path,
) -> None:
    before = hashlib.sha256(DEFAULT_CORPUS.read_bytes()).hexdigest()
    first, second = tmp_path / "a", tmp_path / "b"
    count = driver.materialize_corpus(first)
    assert driver.materialize_corpus(second) == count
    assert count == len({s for s in driver.seed_texts()}) >= 64
    assert sorted(p.name for p in first.iterdir()) == sorted(p.name for p in second.iterdir())
    for path in first.iterdir():
        assert path.name == hashlib.sha256(path.read_bytes()).hexdigest()
        assert (second / path.name).read_bytes() == path.read_bytes()
    assert hashlib.sha256(DEFAULT_CORPUS.read_bytes()).hexdigest() == before
    with pytest.raises(FileExistsError):
        driver.materialize_corpus(first)


def test_seed_corpus_includes_only_matching_regressions(tmp_path: Path, monkeypatch) -> None:
    regressions = tmp_path / "reg"
    regressions.mkdir()
    _write(regressions, _record_data(input=b"zq1 ; zq2".hex()))
    _write(regressions, _record_data(target="lexer.strip_comments", input=b"zq3 #x".hex(),
                                     contract_ref="PYSH-LANG-COMMENT-BOUNDARY"))
    monkeypatch.setattr(driver, "REGRESSION_DIR", regressions)
    chain = driver.seed_texts("grammar.split_chain")
    assert "zq1 ; zq2" in chain and "zq3 #x" not in chain
    assert "zq3 #x" in driver.seed_texts("lexer.strip_comments")
    assert {"zq1 ; zq2", "zq3 #x"} <= set(driver.seed_texts())


# --- regression records ---------------------------------------------------------------


def test_valid_records_load_and_encodings_share_one_identity(tmp_path: Path) -> None:
    by_bytes = driver.validate_record(_record_data())
    by_text = driver.validate_record(_record_data(input_encoding="text-hex"))
    assert by_bytes.text == by_text.text == "a ; b"
    assert by_bytes.sha256 == by_text.sha256
    expected = hashlib.sha256(b"grammar.split_chain\x00a ; b").hexdigest()
    assert by_bytes.sha256 == expected and by_bytes.filename == f"{expected}.json"
    path = _write(tmp_path, _record_data())
    assert driver.load_record(path).sha256 == expected
    assert driver.validate_record(_record_data(contract_ref="unspecified")).contract_ref == "unspecified"


def test_identity_covers_target_nul_and_surrogates() -> None:
    assert driver.canonical_sha256("a", "bc") != driver.canonical_sha256("ab", "c")  # NUL separates
    assert driver.canonical_sha256("a", "x") != driver.canonical_sha256("b", "x")
    lone = driver.validate_record(_record_data(input=b"\xff\x00".hex()))
    assert lone.text == "\udcff\x00"
    text_form = driver.validate_record(
        _record_data(input_encoding="text-hex", input="\ud800".encode("utf-8", "surrogatepass").hex()))
    assert text_form.text == "\ud800"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"extra": 1}, "unknown fields"),
        ({"schema_version": 2}, "schema_version"),
        ({"schema_version": True}, "schema_version"),
        ({"target": "grammar.nope"}, "unknown target"),
        ({"target": "split_chain"}, "unknown target"),  # short names are not stored identities
        ({"property": "magic"}, "unknown property"),
        ({"property": "redirection_preserves_quoted_content"}, "applies only"),
        ({"input_encoding": "base64"}, "input_encoding"),
        ({"input": "ABCD"}, "lowercase hex"),
        ({"input": "abc"}, "lowercase hex"),
        ({"input": "00" * (driver.MAX_REGRESSION_BYTES + 1)}, "larger than"),
        ({"contract_ref": "PYSH-LANG-NOPE-X"}, "unknown contract"),
        ({"engine": "afl"}, "engine"),
        ({"seed_or_source": ""}, "seed_or_source"),
        ({"fixed_in": "has spaces"}, "fixed_in"),
        ({"fixed_in": ""}, "fixed_in"),
    ],
)
def test_malformed_records_are_rejected(override: dict[str, object], message: str) -> None:
    with pytest.raises(driver.RegressionError, match=message):
        driver.validate_record(_record_data(**override))


def test_missing_field_non_object_and_bad_json_are_rejected(tmp_path: Path) -> None:
    data = _record_data()
    del data["contract_ref"]
    with pytest.raises(driver.RegressionError, match="missing fields"):
        driver.validate_record(data)
    with pytest.raises(driver.RegressionError, match="JSON object"):
        driver.validate_record([])
    bad = tmp_path / "x.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(driver.RegressionError, match="cannot load"):
        driver.load_record(bad)
    with pytest.raises(driver.RegressionError, match="not surrogatepass"):
        driver.validate_record(_record_data(input_encoding="text-hex", input="ff"))


def test_filename_must_be_the_canonical_hash_so_duplicates_cannot_accumulate(tmp_path: Path) -> None:
    good = _write(tmp_path, _record_data())
    assert driver.load_regressions(tmp_path)[0].path == good
    renamed = _write(tmp_path, _record_data(input_encoding="text-hex"), name="duplicate.json")
    with pytest.raises(driver.RegressionError, match="filename"):
        driver.load_regressions(tmp_path)
    renamed.unlink()
    wrong = _write(tmp_path, _record_data(input=b"zz".hex()), name=f"{'0' * 64}.json")
    with pytest.raises(driver.RegressionError, match="filename"):
        driver.load_record(wrong)


# --- replay and reproduction --------------------------------------------------------------


def test_replay_passes_for_a_fixed_reproducer_and_reports_a_regression(tmp_path: Path, monkeypatch) -> None:
    path = _write(tmp_path, _record_data())
    record = driver.load_record(path)
    with driver.replay_context() as ctx:
        driver.replay_record(record, ctx)

        def failing(_target):
            def check(text: str, _ctx) -> None:
                raise AssertionError("regressed")
            return check

        monkeypatch.setitem(driver.PROPERTIES, "totality", failing)
        with pytest.raises(PropertyFailure) as caught:
            driver.replay_record(record, ctx)
    report = str(caught.value)
    assert f"--replay tests/fuzz/regressions/{record.filename}" in report
    assert input_sha256("a ; b") in report and "engine:     atheris" in report
    assert caught.value.reproduction.traceback_fingerprint


def test_reproduction_report_has_exact_replay_metadata_and_no_environment(monkeypatch) -> None:
    monkeypatch.setenv("PYSH_TEST_SECRET", "s3cret-value")
    monkeypatch.setenv("HOME", "/home/someone")

    def raise_twice() -> BaseException:
        try:
            raise ValueError("boom")
        except ValueError as error:
            return error

    first, second = raise_twice(), raise_twice()
    assert traceback_fingerprint(first) == traceback_fingerprint(second)
    assert traceback_fingerprint(first) != traceback_fingerprint(KeyError("boom"))
    assert "/" not in traceback_fingerprint(first)
    report = format_failure(Reproduction(
        "grammar.split_chain", "totality", "a\x00;", "file:crash-x", engine="atheris",
        exception_type="ValueError", exception_message="boom",
        traceback_fingerprint=traceback_fingerprint(first),
        replay_command=driver.replay_command("grammar.split_chain", "bytes-hex", "6100")))
    for needle in ("grammar.split_chain", "totality", "atheris", input_sha256("a\x00;"), "Python"[:0],
                   "python:", "platform:", "pysh:", "ValueError: boom", traceback_fingerprint(first),
                   "--target grammar.split_chain --encoding bytes-hex --input-hex 6100"):
        assert needle in report
    assert "s3cret-value" not in report and "/home/someone" not in report


# --- command line (portable modes, in process) ---------------------------------------------


def test_cli_list_prepare_and_replay_modes(tmp_path: Path, capsys) -> None:
    assert fuzz_atheris.main(["--list-targets"]) == 0
    listed = capsys.readouterr().out.splitlines()
    assert "grammar.split_chain" in listed and len(listed) >= len(driver.fuzzable_targets())

    corpus = tmp_path / "corpus"
    assert fuzz_atheris.main(["--prepare-corpus", str(corpus), "--target", "split_chain"]) == 0
    assert capsys.readouterr().out.startswith(f"fuzz: wrote {len(list(corpus.iterdir()))} seeds")
    assert fuzz_atheris.main(["--prepare-corpus", str(corpus)]) == 2  # non-empty
    capsys.readouterr()

    record = _write(tmp_path, _record_data())
    assert fuzz_atheris.main(["--replay", str(record)]) == 0
    assert fuzz_atheris.main(["--target", "split_chain", "--input-hex", "6120" + "3b"]) == 0
    assert fuzz_atheris.main(["--target", "split_chain", "--input-hex", "zz"]) == 2
    assert fuzz_atheris.main(["--target", "nope", "--input-hex", "61"]) == 2
    assert fuzz_atheris.main(["--replay", str(tmp_path / "missing.json")]) == 2


def test_cli_replay_reports_a_failure_with_exit_code_one(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setitem(
        driver.PROPERTIES, "determinism",
        lambda _t: (lambda text, _c: (_ for _ in ()).throw(AssertionError("nondeterministic"))))
    assert fuzz_atheris.main(["--target", "split_chain", "--input-hex", "61"]) == 1
    out = capsys.readouterr().out
    assert "FUZZ PROPERTY FAILURE" in out and "--input-hex 61" in out


def test_engine_mode_validates_arguments_and_reports_a_missing_engine(monkeypatch, capsys) -> None:
    assert fuzz_atheris.main(["--target", "split_chain", "--max-total-time", "0"]) == 2
    assert fuzz_atheris.main(["--target", "split_chain", "--max-total-time", "99999"]) == 2
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert fuzz_atheris.main(["--target", "split_chain", "--max-total-time", "1"]) == 3
    assert "Atheris is not installed" in capsys.readouterr().err
    assert fuzz_atheris.main([]) == 2


def test_engine_property_includes_totality_and_determinism() -> None:
    assert driver.ENGINE_PROPERTY == "determinism"
    target = TARGETS_BY_NAME["grammar.split_chain"]
    with driver.replay_context() as ctx:
        driver.engine_check(target)(b"a ; b \xff" * 60, ctx)  # input is truncated to the bound
        assert props.determinism(target) is not None
