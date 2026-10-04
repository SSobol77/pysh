# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fake_syft.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository-owned FAKE SBOM tool for the release-SBOM unit tests (no network, no real Syft).

Selected by file name: ``syft`` behaves correctly; ``syft_<variant>`` adds one defect:
``fail`` (always exit 1), ``partial`` (fail only for the .rpm artifact), ``leak`` (embed
the scanned host path), ``badjson``, ``wrongver`` (SPDX-2.2), ``nocreation``,
``empty`` (empty document), ``wrongroot`` (root named after another artifact),
``badversion`` (reports an unpinned tool version), ``env`` (records its environment names).
"""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str]) -> int:
    _tool, _, variant = os.path.basename(argv[0]).partition("_")
    args = argv[1:]
    if args[:1] == ["version"]:
        print("Application: syft")
        print("Version:       " + ("1.0.0" if variant == "badversion" else "1.54.0"))
        return 0
    source = next(a for a in args if a.startswith("dir:"))[4:]
    name = args[args.index("--source-name") + 1]
    version = args[args.index("--source-version") + 1]
    out = next(a for a in args if a.startswith("spdx-json="))[len("spdx-json="):]
    if variant == "fail" or (variant == "partial" and name.endswith(".rpm")):
        print(f"fake syft: failing for {name}", file=sys.stderr)
        return 1
    document = {
        "spdxVersion": "SPDX-2.2" if variant == "wrongver" else "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": "https://example.invalid/spdx/" + name,
        "creationInfo": {"creators": ["Tool: fake-syft"], "created": "2026-01-01T00:00:00Z"},
        "packages": [{"name": "other.whl" if variant == "wrongroot" else name,
                      "SPDXID": "SPDXRef-Root", "versionInfo": version}],
        "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": "SPDXRef-Root",
                           "relationshipType": "DESCRIBES"}],
    }
    if variant == "nocreation":
        del document["creationInfo"]
    if variant == "leak":
        document["documentComment"] = f"scanned {source}"
        document["name"] = name
    if variant == "env":
        document["documentComment"] = json.dumps(sorted(os.environ))
    with open(out, "w", encoding="utf-8") as handle:
        if variant == "badjson":
            handle.write("{ not json")
        elif variant == "empty":
            handle.write("")
        else:
            json.dump(document, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
