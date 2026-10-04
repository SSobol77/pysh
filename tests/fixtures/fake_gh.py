# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fake_gh.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository-owned FAKE GitHub CLI for the release-attestation tests (no network, no real gh).

Only ``gh attestation verify <file> ...`` is implemented, and it compares the identity
flags against a scenario file the way the real command compares them against the
certificate. State lives in the directory named by ``FAKE_GH_STATE``:

``scenario.json``  ``attestations`` (each: ``subjects`` [[name, sha256]], ``predicateType``,
                   ``predicate``, ``repo``, ``workflow``, ``source_digest``,
                   ``invalid_signature``), ``hidden`` (``{basename: n}``: the first n
                   queries answer "no attestations found"), ``malformed`` (basenames whose
                   answer is not JSON) and ``slow`` (basenames whose query hangs).
``calls.jsonl``    one JSON argv list per invocation (written by this fake).
``counts.json``    per-basename query counters (written by this fake).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    state = Path(os.environ["FAKE_GH_STATE"])
    args = argv[1:]
    with (state / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")
    if args[:2] != ["attestation", "verify"]:
        print(f"fake gh: unsupported command {args[:2]}", file=sys.stderr)
        return 1
    target = Path(args[2])
    flags = dict(zip(args[3::2], args[4::2], strict=False))
    scenario = json.loads((state / "scenario.json").read_text(encoding="utf-8"))
    name = target.name
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    counts_path = state / "counts.json"
    counts = json.loads(counts_path.read_text(encoding="utf-8")) if counts_path.exists() else {}
    key = f"{name}|{flags.get('--predicate-type')}"
    counts[key] = counts.get(key, 0) + 1
    counts_path.write_text(json.dumps(counts), encoding="utf-8")
    if name in scenario.get("slow", []):
        time.sleep(60)
    if counts[key] <= scenario.get("hidden", {}).get(name, 0):
        print(f"Error: no attestations found for subject sha256:{digest}", file=sys.stderr)
        return 1
    matching = [
        a for a in scenario["attestations"]
        if a["predicateType"] == flags.get("--predicate-type") and any(s[1] == digest for s in a["subjects"])
    ]
    if not matching:
        print(f"Error: no attestations found with predicate type: {flags.get('--predicate-type')}", file=sys.stderr)
        return 1
    trusted = [
        a for a in matching
        if a["repo"] == flags.get("--repo") and a["workflow"] == flags.get("--signer-workflow")
        and a["source_digest"] == flags.get("--source-digest")
    ]
    if not trusted:
        print("Error: verifying with issuer sigstore.dev: failed to verify certificate identity: "
              "the certificate does not match the expected repository, workflow or source digest",
              file=sys.stderr)
        return 1
    if any(a.get("invalid_signature") for a in trusted):
        print("Error: failed to verify signature: invalid signature", file=sys.stderr)
        return 1
    if name in scenario.get("malformed", []):
        print("{ not json")
        return 0
    print(json.dumps([
        {
            "attestation": {"bundle": {}},
            "verificationResult": {
                "statement": {
                    "_type": "https://in-toto.io/Statement/v1",
                    "predicateType": a["predicateType"],
                    "subject": [{"name": n, "digest": {"sha256": d}} for n, d in a["subjects"]],
                    "predicate": a["predicate"],
                },
            },
        }
        for a in trusted
    ]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
