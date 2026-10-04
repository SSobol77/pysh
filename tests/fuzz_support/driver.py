# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/driver.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Engine-independent fuzz driver logic: byte mapping, targets, seeds, regressions.

Nothing here imports Atheris. The coverage-guided engine
(``scripts/fuzz_atheris.py``) is a thin adapter over this module, and permanent
regression replay uses only this module, so a platform without Atheris (for
example FreeBSD) still replays every fixed reproducer.

Classification used throughout:

* **expected rejection** - an exception registered for that target in
  ``targets.py`` (class and message pattern); a normal outcome.
* **parser defect** - any other exception, an assertion/property violation, a
  nondeterministic result, a hang, or an engine-detected crash for an input that
  the portable replay reproduces.
* **harness defect** - ``HarnessError`` or a failure the portable replay cannot
  reproduce; never counted as a pass and never silenced.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from scripts.run_language_conformance import CONTRACT_ANCHOR_RE, DEFAULT_SPEC
from tests.fuzz_support import properties as props
from tests.fuzz_support.corpus import load_seeds
from tests.fuzz_support.targets import TARGETS, TARGETS_BY_NAME, Target, TargetContext, hermetic

REPO_ROOT = Path(__file__).resolve().parents[2]
REGRESSION_DIR = REPO_ROOT / "tests" / "fuzz" / "regressions"
SCRIPT = "scripts/fuzz_atheris.py"

#: One canonical bytes -> str mapping. ``surrogateescape`` is deterministic,
#: injective (distinct bytes give distinct str) and lossless: every byte value,
#: including invalid UTF-8, survives and can be recovered with ``text_to_bytes``.
BYTES_ERRORS = "surrogateescape"
MAX_ENGINE_INPUT_BYTES = 256
MAX_REGRESSION_BYTES = 4096

#: Targets that cannot run hermetically under the engine, with the reason.
#: Empty: all registered Slice 1 targets are hermetic (empty temp cwd, cleared
#: environment with pinned HOME, fake substitution runner, subprocess tripwires).
EXCLUDED_TARGETS: dict[str, str] = {}


def decode_bytes(data: bytes) -> str:
    """Map fuzz bytes to the parser's ``str`` domain (canonical, lossless)."""
    return data.decode("utf-8", errors=BYTES_ERRORS)


def text_to_bytes(text: str) -> bytes:
    """Invert :func:`decode_bytes`; raises for text that did not originate from bytes."""
    return text.encode("utf-8", errors=BYTES_ERRORS)


# --- targets ----------------------------------------------------------------


def fuzzable_targets() -> tuple[Target, ...]:
    return tuple(t for t in TARGETS if t.name not in EXCLUDED_TARGETS)


def resolve_target(name: str) -> Target:
    """Resolve a full registry name or an unambiguous short name (``split_chain``)."""
    if name in TARGETS_BY_NAME:
        return TARGETS_BY_NAME[name]
    matches = [t for t in TARGETS if t.name.rsplit(".", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise KeyError(f"unknown fuzz target {name!r}")
    raise KeyError(f"ambiguous fuzz target {name!r}: {sorted(t.name for t in matches)}")


# --- properties replayable from regression records ------------------------------

PropertyFactory = Callable[[Target], props.Property]


def _redirection_content(target: Target) -> props.Property:
    if target.name != "redirection.parse_redirections":
        raise ValueError("redirection_preserves_quoted_content applies only to parse_redirections")
    return props.redirection_preserves_quoted_content


PROPERTIES: dict[str, PropertyFactory] = {
    "totality": props.totality,
    "determinism": props.determinism,
    "redirection_preserves_quoted_content": _redirection_content,
}
ENGINE_PROPERTY = "determinism"  # includes totality: evaluates twice and compares


@contextlib.contextmanager
def replay_context(cwd: Path | None = None) -> Iterator[TargetContext]:
    """Hermetic context with an empty cwd.

    Without ``cwd`` a private temp directory is created and removed on exit. The
    engine passes a directory owned by its parent instead, because libFuzzer
    ends the child with ``_exit`` and Python cleanup would never run.
    """
    if cwd is not None:
        context = TargetContext(cwd=cwd)
        with hermetic(context):
            yield context
        return
    with tempfile.TemporaryDirectory(prefix="pysh-fuzz-") as root:
        private = Path(root) / "cwd"
        private.mkdir()
        context = TargetContext(cwd=private)
        with hermetic(context):
            yield context


def replay_command(target: str, encoding: str, input_hex: str) -> str:
    return f"uv run python {SCRIPT} --target {target} --encoding {encoding} --input-hex {input_hex}"


def replay_text(
    target: Target,
    property_name: str,
    text: str,
    ctx: TargetContext,
    *,
    source: str,
    engine: str = "stdlib",
    command: str | None = None,
) -> None:
    """Run one named property once; a violation raises ``PropertyFailure``."""
    check = PROPERTIES[property_name](target)
    props.run(
        property_name, check, [props.Case(source, text)], ctx,
        target=target.name, engine=engine, replay_command=command,
    )


# --- regression records ---------------------------------------------------------

SCHEMA_VERSION = 1
RECORD_FIELDS = frozenset({
    "schema_version", "target", "property", "input_encoding", "input",
    "contract_ref", "engine", "seed_or_source", "fixed_in",
})
INPUT_ENCODINGS = frozenset({"bytes-hex", "text-hex"})
ENGINES = frozenset({"atheris", "stdlib", "manual"})
UNSPECIFIED = "unspecified"
_FIXED_IN_RE = re.compile(r"[A-Za-z0-9._/#:@-]{1,80}\Z")
_HEX_RE = re.compile(r"(?:[0-9a-f]{2})*\Z")
_FILENAME_RE = re.compile(r"([0-9a-f]{64})\.json\Z")


class RegressionError(ValueError):
    """A regression record violates its closed schema."""


def canonical_sha256(target: str, text: str) -> str:
    """Identity of a reproducer: SHA-256 of ``target + NUL + canonical text bytes``.

    Canonical text bytes are the ``surrogatepass`` UTF-8 encoding of the parser
    input. Because :func:`decode_bytes` is injective, two records with the same
    target and the same parser input always collide, whichever encoding stored
    them, so duplicates cannot accumulate under different file names.
    """
    material = target.encode("utf-8") + b"\x00" + text.encode("utf-8", "surrogatepass")
    return hashlib.sha256(material).hexdigest()


def _contract_ids() -> frozenset[str]:
    return frozenset(CONTRACT_ANCHOR_RE.findall(DEFAULT_SPEC.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class RegressionRecord:
    """One validated permanent robustness reproducer.

    ``fixed_in`` is informational provenance (commit, PR or issue reference of
    the fix); it is validated for shape only and is never compared with the
    current commit, so history rewrites cannot break the corpus.
    """

    path: Path | None
    target: str
    property_name: str
    input_encoding: str
    input_hex: str
    contract_ref: str
    engine: str
    seed_or_source: str
    fixed_in: str

    @property
    def text(self) -> str:
        raw = bytes.fromhex(self.input_hex)
        if self.input_encoding == "bytes-hex":
            return decode_bytes(raw)
        return raw.decode("utf-8", "surrogatepass")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.target, self.text)

    @property
    def filename(self) -> str:
        return f"{self.sha256}.json"

    def to_json(self) -> str:
        data = {
            "schema_version": SCHEMA_VERSION,
            "target": self.target,
            "property": self.property_name,
            "input_encoding": self.input_encoding,
            "input": self.input_hex,
            "contract_ref": self.contract_ref,
            "engine": self.engine,
            "seed_or_source": self.seed_or_source,
            "fixed_in": self.fixed_in,
        }
        return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _string(data: dict[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise RegressionError(f"{key}: expected a non-empty string")
    return value


def validate_record(data: object, *, path: Path | None = None) -> RegressionRecord:
    """Validate one decoded record against the closed v1 schema."""
    if not isinstance(data, dict):
        raise RegressionError("record: expected a JSON object")
    missing = sorted(RECORD_FIELDS - set(data))
    unknown = sorted(set(data) - RECORD_FIELDS)
    if missing or unknown:
        raise RegressionError(f"record: missing fields {missing!r}; unknown fields {unknown!r}")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        raise RegressionError(f"schema_version: expected {SCHEMA_VERSION}")
    target = _string(data, "target")
    if target not in TARGETS_BY_NAME:  # full registry name: identity must not depend on aliases
        raise RegressionError(f"target: unknown target {target!r}")
    if target in EXCLUDED_TARGETS:
        raise RegressionError(f"target: {target!r} is excluded from fuzzing")
    property_name = _string(data, "property")
    if property_name not in PROPERTIES:
        raise RegressionError(f"property: unknown property {property_name!r}")
    try:
        PROPERTIES[property_name](TARGETS_BY_NAME[target])
    except ValueError as error:
        raise RegressionError(f"property: {error}") from error
    encoding = _string(data, "input_encoding")
    if encoding not in INPUT_ENCODINGS:
        raise RegressionError(f"input_encoding: unsupported {encoding!r}")
    input_hex = data["input"]
    if not isinstance(input_hex, str) or not _HEX_RE.fullmatch(input_hex):
        raise RegressionError("input: expected lowercase hex")
    if len(input_hex) // 2 > MAX_REGRESSION_BYTES:
        raise RegressionError(f"input: larger than {MAX_REGRESSION_BYTES} bytes")
    if encoding == "text-hex":
        try:
            bytes.fromhex(input_hex).decode("utf-8", "surrogatepass")
        except UnicodeDecodeError as error:
            raise RegressionError(f"input: not surrogatepass UTF-8: {error}") from error
    contract_ref = _string(data, "contract_ref")
    if contract_ref != UNSPECIFIED and contract_ref not in _contract_ids():
        raise RegressionError(f"contract_ref: unknown contract {contract_ref!r}")
    engine = _string(data, "engine")
    if engine not in ENGINES:
        raise RegressionError(f"engine: unsupported {engine!r}")
    seed_or_source = _string(data, "seed_or_source")
    fixed_in = _string(data, "fixed_in")
    if not _FIXED_IN_RE.fullmatch(fixed_in):
        raise RegressionError("fixed_in: expected a short commit/PR/issue reference")
    record = RegressionRecord(
        path, target, property_name, encoding, input_hex, contract_ref, engine,
        seed_or_source, fixed_in,
    )
    if path is not None:
        match = _FILENAME_RE.fullmatch(path.name)
        if match is None or match.group(1) != record.sha256:
            raise RegressionError(
                f"filename: expected {record.filename} (canonical SHA-256 of target + NUL + input)"
            )
    return record


def load_record(path: Path) -> RegressionRecord:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegressionError(f"{path.name}: cannot load: {error}") from error
    try:
        return validate_record(data, path=path)
    except RegressionError as error:
        raise RegressionError(f"{path.name}: {error}") from error


def load_regressions(directory: Path | None = None) -> list[RegressionRecord]:
    """Load every ``*.json`` record, rejecting duplicates by canonical identity."""
    directory = REGRESSION_DIR if directory is None else directory
    records: list[RegressionRecord] = []
    seen: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        record = load_record(path)
        if record.sha256 in seen:
            raise RegressionError(f"{path.name}: duplicate of {seen[record.sha256].name}")
        seen[record.sha256] = path
        records.append(record)
    return records


def replay_record(record: RegressionRecord, ctx: TargetContext) -> None:
    command = (
        f"uv run python {SCRIPT} --replay tests/fuzz/regressions/{record.filename}"
        if record.path is not None
        else None
    )
    replay_text(
        TARGETS_BY_NAME[record.target], record.property_name, record.text, ctx,
        source=f"regression:{record.sha256[:12]}", engine=record.engine, command=command,
    )


# --- seed corpus -----------------------------------------------------------------


def seed_texts(target: str | None = None) -> list[str]:
    """Seeds for the engine: every #48 case plus the regression inputs (optionally per target).

    Derived at call time from the authoritative corpus and the regression
    directory; nothing is copied into a checked-in second corpus.
    """
    texts = [seed.text for seed in load_seeds()]
    for record in load_regressions():
        if target is None or record.target == target:
            texts.append(record.text)
    return texts


def materialize_corpus(directory: Path, target: str | None = None) -> int:
    """Write the deterministic seed corpus for libFuzzer into an empty ``directory``.

    Files are named by the SHA-256 of their bytes, so repeated runs produce an
    identical directory and equal seeds collapse. Returns the number of files.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(f"{directory} is not empty")
    written: set[str] = set()
    for text in seed_texts(target):
        data = text_to_bytes(text)[:MAX_ENGINE_INPUT_BYTES]
        digest = hashlib.sha256(data).hexdigest()
        if digest not in written:
            (directory / digest).write_bytes(data)
            written.add(digest)
    return len(written)


def engine_check(target: Target) -> Callable[[bytes, TargetContext], None]:
    """The coverage-guided property: deterministic result or registered rejection."""
    check = PROPERTIES[ENGINE_PROPERTY](target)

    def run(data: bytes, ctx: TargetContext) -> None:
        check(decode_bytes(data[:MAX_ENGINE_INPUT_BYTES]), ctx)

    return run
