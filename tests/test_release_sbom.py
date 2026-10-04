# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_release_sbom.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Issue #51 Slice 2: SPDX 2.3 JSON SBOM generation, validation and checksum policy.

Hermetic: a repository-owned fake SBOM tool stands in for Syft (no network, no real tool).
An optional real-Syft smoke runs only when ``PYSH_REAL_SYFT`` names an executable.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts import generate_release_sboms as gen
from scripts.check_reproducibility_evidence import canonical_json
from tests.repro_support import final_document

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE = REPO_ROOT / "tests" / "fixtures" / "fake_syft.py"
VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
ARTIFACTS = {
    "wheel": f"pysh_shell-{VERSION}-py3-none-any.whl",
    "sdist": f"pysh_shell-{VERSION}.tar.gz",
    "deb": f"pysh-shell_{VERSION}-1_all.deb",
    "rpm": f"pysh-shell-{VERSION}-1.noarch.rpm",
    "freebsd_pkg": f"pysh-shell-{VERSION}.pkg",
}


def _tar_gz(path: Path) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        data = b"payload\n"
        info = tarfile.TarInfo("pkg/payload.txt")
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))


@pytest.fixture
def release(tmp_path: Path) -> Path:
    """A flat release-assets directory with the five canonical package artifacts."""
    directory = tmp_path / "release-assets"
    directory.mkdir()
    with zipfile.ZipFile(directory / ARTIFACTS["wheel"], "w") as wheel:
        wheel.writestr("pysh/__init__.py", "x = 1\n")
    _tar_gz(directory / ARTIFACTS["sdist"])
    _tar_gz(directory / ARTIFACTS["freebsd_pkg"])
    (directory / ARTIFACTS["deb"]).write_bytes(b"!<arch>\ndeb-bytes")
    (directory / ARTIFACTS["rpm"]).write_bytes(b"rpm-bytes")
    return directory


@pytest.fixture
def fake_tool(tmp_path: Path):
    source = FAKE.read_text(encoding="utf-8")
    body = source.split("\n", 1)[1] if source.startswith("#!") else source

    def make(name: str = "syft") -> Path:
        directory = tmp_path / "tool"
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path

    return make


def generated(release: Path, fake_tool, name: str = "syft", out: Path | None = None) -> Path:
    target = out or release
    gen.generate(release, target, fake_tool(name), VERSION)
    return target


def publish_evidence(directory: Path) -> None:
    """The reproducibility evidence is a published asset created after the SBOMs (Slice 4)."""
    if not (directory / gen.EVIDENCE).exists():
        (directory / gen.EVIDENCE).write_text(canonical_json(final_document(version=VERSION)), encoding="utf-8")


def finalize(directory: Path) -> subprocess.CompletedProcess[str]:
    """The real bash finalizer, run on a fixture dist tree (directory is dist/release-assets)."""
    publish_evidence(directory)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "check_release_artifacts.sh"), "--finalize-release-assets",
         str(directory.parent)],
        capture_output=True, text=True, check=False,
    )


# --- positive -----------------------------------------------------------------------------------


def test_five_sboms_are_generated_with_exact_basename_names_in_deterministic_order(release, fake_tool) -> None:
    before = {p.name: p.read_bytes() for p in release.iterdir()}
    produced = gen.generate(release, release, fake_tool(), VERSION)
    assert [p.name for p in produced] == [f"{ARTIFACTS[f]}.spdx.json" for f in
                                          ("wheel", "sdist", "deb", "rpm", "freebsd_pkg")]
    assert all(p.stat().st_size > 0 for p in produced)
    for name, content in before.items():  # artifact bytes are never modified
        assert (release / name).read_bytes() == content
    assert sorted(p.name for p in release.iterdir()) == sorted([*before, *(p.name for p in produced)])


def test_generated_documents_validate_and_bind_the_artifact_digest(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert set(gen.validate_set(release, VERSION)) == set(ARTIFACTS)
    document = json.loads((release / f"{ARTIFACTS['wheel']}.spdx.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((release / ARTIFACTS["wheel"]).read_bytes()).hexdigest()
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["packages"][0]["versionInfo"] == f"sha256:{digest}"
    assert document["packages"][0]["name"] == ARTIFACTS["wheel"]


def test_the_cli_validate_and_bundle_commands(release, fake_tool, capsys) -> None:
    generated(release, fake_tool)
    assert gen.main(["validate", "--dir", str(release), "--version", VERSION]) == 0
    assert finalize(release).returncode == 0
    assert gen.main(["validate-bundle", "--dir", str(release), "--version", VERSION]) == 0
    assert "validate-bundle OK" in capsys.readouterr().out


def test_final_checksums_cover_every_published_file_except_themselves(release, fake_tool) -> None:
    generated(release, fake_tool)
    done = finalize(release)
    assert done.returncode == 0, done.stderr
    lines = (release / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    names = [line.split()[1].lstrip("*") for line in lines]
    assert names == sorted(names) and len(names) == 11
    assert "SHA256SUMS" not in names
    assert set(names) == {p.name for p in release.iterdir()} - {"SHA256SUMS"}
    gen.validate_checksums(release)


def test_a_preliminary_package_only_manifest_is_replaced_by_the_final_one(release, fake_tool) -> None:
    (release / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256((release / n).read_bytes()).hexdigest()}  {n}\n" for n in ARTIFACTS.values()),
        encoding="utf-8",
    )
    generated(release, fake_tool)
    with pytest.raises(gen.SbomError, match="must cover every published file"):
        gen.validate_checksums(release)  # the preliminary manifest omits the SBOMs
    assert finalize(release).returncode == 0
    gen.validate_checksums(release)


def test_the_tool_runs_in_a_minimal_environment_without_host_variables(
    release, fake_tool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_" + "a" * 36)
    monkeypatch.setenv("PYSH_HOST_SECRET", "secret-value-123456")
    generated(release, fake_tool, "syft_env")
    names = json.loads(json.loads((release / f"{ARTIFACTS['deb']}.spdx.json").read_text())["documentComment"])
    assert "GITHUB_TOKEN" not in names and "PYSH_HOST_SECRET" not in names
    assert set(names) <= {"HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "LANG", "LC_ALL",
                          "SYFT_CHECK_FOR_APP_UPDATE", "LC_CTYPE"}
    assert "SYFT_CHECK_FOR_APP_UPDATE" in names


def test_artifact_name_templates_match_the_packaging_contract() -> None:
    script = (REPO_ROOT / "scripts" / "check_release_artifacts.sh").read_text(encoding="utf-8")
    owner = {
        "wheel": re.search(r'^EXPECTED_WHEEL_NAME="(.+)"$', script, re.M).group(1),
        "deb": re.search(r'^EXPECTED_DEB="(.+)"$', script, re.M).group(1),
        "rpm": re.search(r'^EXPECTED_RPM="(.+)"$', script, re.M).group(1),
        "freebsd_pkg": re.search(r'^EXPECTED_FREEBSD_PKG="(.+)"$', script, re.M).group(1),
    }

    def render(template: str) -> str:
        return template.replace("${PKG_NAME}", "pysh-shell").replace("${PKG_RELEASE}", "1").replace("${VERSION}", "{v}")

    families = {f.family_id: f for f in gen.FAMILIES}
    for family_id, template in owner.items():
        assert families[family_id].names == (render(template),), family_id
    sdist = {re.search(r'^EXPECTED_SDIST_UNDER="(.+)"$', script, re.M).group(1),
             re.search(r'^EXPECTED_SDIST_HYPHEN="(.+)"$', script, re.M).group(1)}
    assert {render(n) for n in sdist} == set(families["sdist"].names)
    assert re.search(r'^SBOM_SUFFIX="\.spdx\.json"$', script, re.M) and gen.SBOM_SUFFIX == ".spdx.json"


def test_sbom_names_are_the_artifact_basename_plus_a_fixed_suffix() -> None:
    for name in ARTIFACTS.values():
        assert gen.sbom_name(name) == name + ".spdx.json"


def test_the_pinned_tool_is_documented_and_never_mutable() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", gen.SYFT_VERSION)
    assert re.fullmatch(r"[0-9a-f]{64}", gen.SYFT_LINUX_AMD64_SHA256)
    assert re.fullmatch(r"[0-9a-f]{40}", gen.SYFT_TAG_COMMIT)
    assert f"v{gen.SYFT_VERSION}/" in gen.SYFT_URL and "latest" not in gen.SYFT_URL
    doc = (REPO_ROOT / "docs" / "security" / "supply-chain.md").read_text(encoding="utf-8")
    assert f"Anchore Syft {gen.SYFT_VERSION}" in doc


@pytest.mark.skipif(not os.environ.get("PYSH_REAL_SYFT"), reason="set PYSH_REAL_SYFT to a pinned Syft to run")
def test_real_syft_smoke(release) -> None:
    out = release.parent / "real-out"
    gen.generate(release, out, Path(os.environ["PYSH_REAL_SYFT"]), VERSION)
    assert len(list(out.iterdir())) == 5
    for p in out.iterdir():
        assert json.loads(p.read_text())["spdxVersion"] == "SPDX-2.3"


# --- negative: completeness and naming ----------------------------------------------------------


@pytest.mark.parametrize("family", sorted(ARTIFACTS))
def test_a_missing_sbom_for_any_family_fails(release, fake_tool, family: str) -> None:
    generated(release, fake_tool)
    (release / f"{ARTIFACTS[family]}.spdx.json").unlink()
    with pytest.raises(gen.SbomError, match=f"missing SBOM for the {family} artifact"):
        gen.validate_set(release, VERSION)


@pytest.mark.parametrize("family", sorted(ARTIFACTS))
def test_a_missing_package_artifact_fails_generation(release, fake_tool, family: str) -> None:
    (release / ARTIFACTS[family]).unlink()
    with pytest.raises(gen.SbomError, match=f"missing mandatory {family} artifact"):
        gen.generate(release, release, fake_tool(), VERSION)


def test_duplicate_artifact_aliases_are_rejected(release, fake_tool) -> None:
    (release / f"pysh-shell-{VERSION}.tar.gz").write_bytes(b"alias")
    with pytest.raises(gen.SbomError, match="ambiguous sdist"):
        gen.generate(release, release, fake_tool(), VERSION)


def test_a_duplicate_sbom_under_the_alias_name_is_unexpected(release, fake_tool) -> None:
    generated(release, fake_tool)
    original = release / f"{ARTIFACTS['sdist']}.spdx.json"
    (release / f"pysh-shell-{VERSION}.tar.gz.spdx.json").write_bytes(original.read_bytes())
    with pytest.raises(gen.SbomError, match="unexpected files"):
        gen.validate_set(release, VERSION)


def test_an_unexpected_sibling_sbom_or_file_is_rejected(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / "sbom.json").write_text("{}", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="unexpected files"):
        gen.validate_set(release, VERSION)


def test_unexpected_input_aliases_and_empty_or_non_regular_artifacts_are_rejected(release, fake_tool) -> None:
    (release / ARTIFACTS["deb"]).write_bytes(b"")
    with pytest.raises(gen.SbomError, match="empty"):
        gen.generate(release, release, fake_tool(), VERSION)
    (release / ARTIFACTS["deb"]).unlink()
    (release / ARTIFACTS["deb"]).symlink_to(release / ARTIFACTS["rpm"])
    with pytest.raises(gen.SbomError, match="not a regular file"):
        gen.generate(release, release, fake_tool(), VERSION)


def test_a_zero_byte_sbom_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / f"{ARTIFACTS['wheel']}.spdx.json").write_bytes(b"")
    with pytest.raises(gen.SbomError, match="empty or missing"):
        gen.validate_set(release, VERSION)


def test_malformed_json_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / f"{ARTIFACTS['wheel']}.spdx.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="malformed JSON"):
        gen.validate_set(release, VERSION)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(spdxVersion="SPDX-2.2"), "spdxVersion must be SPDX-2.3"),
        (lambda d: d.update(dataLicense="MIT"), "dataLicense"),
        (lambda d: d.pop("creationInfo"), "creationInfo"),
        (lambda d: d["creationInfo"].update(creators=[]), "creationInfo"),
        (lambda d: d.pop("documentNamespace"), "documentNamespace"),
        (lambda d: d.update(SPDXID="SPDXRef-OTHER"), "SPDXID"),
        (lambda d: d.update(packages=[]), "packages and relationships"),
        (lambda d: d.update(relationships=[]), "not bound to this artifact"),
        (lambda d: d["packages"][0].update(name="pysh_shell-0.0.1-py3-none-any.whl"), "not bound to this artifact"),
        (lambda d: d["packages"][0].update(versionInfo="sha256:" + "0" * 64), "not bound to this artifact"),
        (lambda d: d.update(documentComment="built in /home/maintainer/work/x"), "embeds host or secret data"),
        (lambda d: d.update(documentComment="token ghp_" + "a" * 36), "embeds host or secret data"),
        (lambda d: d.update(documentComment="-----BEGIN OPENSSH PRIVATE KEY-----"), "embeds host or secret data"),
    ],
)
def test_structural_and_leak_violations_fail(release, fake_tool, mutate, message: str) -> None:
    generated(release, fake_tool)
    path = release / f"{ARTIFACTS['wheel']}.spdx.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(gen.SbomError, match=re.escape(message)):
        gen.validate_set(release, VERSION)


def test_a_wrong_sbom_filename_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    path = release / f"{ARTIFACTS['wheel']}.spdx.json"
    wrong = release / "pysh.whl.spdx.json"
    path.rename(wrong)
    with pytest.raises(gen.SbomError, match="missing SBOM for the wheel"):
        gen.validate_set(release, VERSION)
    with pytest.raises(gen.SbomError, match="does not map to artifact"):
        gen.validate_document(wrong, release / ARTIFACTS["wheel"])


def test_an_artifact_changed_after_its_sbom_was_made_is_detected(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / ARTIFACTS["deb"]).write_bytes(b"tampered")
    with pytest.raises(gen.SbomError, match="not bound to this artifact"):
        gen.validate_set(release, VERSION)


def test_a_sensitive_environment_value_in_an_sbom_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    path = release / f"{ARTIFACTS['rpm']}.spdx.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["documentComment"] = "value super-secret-value-9999"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(gen.SbomError, match="environment variable"):
        gen.validate_set(release, VERSION, environ={"DEPLOY_PASSWORD": "super-secret-value-9999"})


# --- negative: tool behavior -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        ("syft_fail", "the SBOM tool failed with exit 1"),
        ("syft_partial", f"pysh-shell-{VERSION}-1.noarch.rpm: the SBOM tool failed"),
        ("syft_badjson", "malformed JSON"),
        ("syft_empty", "produced no document"),
        ("syft_wrongver", "spdxVersion must be SPDX-2.3"),
        ("syft_nocreation", "creationInfo"),
        ("syft_wrongroot", "not bound to this artifact"),
        ("syft_leak", "embeds host or secret data"),
        ("syft_badversion", "SBOM tool version mismatch"),
    ],
)
def test_generator_failures_name_the_artifact_and_leave_no_partial_output(
    release, fake_tool, tmp_path: Path, variant: str, message: str
) -> None:
    out = tmp_path / "out"
    with pytest.raises(gen.SbomError, match=re.escape(message)):
        gen.generate(release, out, fake_tool(variant), VERSION)
    assert not out.exists() or list(out.iterdir()) == [], "no silent partial success"


def test_the_cli_reports_a_generator_failure_with_a_nonzero_exit(release, fake_tool, tmp_path, capsys) -> None:
    code = gen.main(["generate", "--input", str(release), "--output", str(tmp_path / "o"),
                     "--syft", str(fake_tool("syft_fail")), "--version", VERSION])
    assert code == 1 and "generate_release_sboms:" in capsys.readouterr().err


def test_generation_never_overwrites_and_requires_an_absolute_executable(release, fake_tool) -> None:
    generated(release, fake_tool)
    with pytest.raises(gen.SbomError, match="refusing to overwrite"):
        gen.generate(release, release, fake_tool(), VERSION)
    with pytest.raises(gen.SbomError, match="absolute path"):
        gen.generate(release, release.parent / "elsewhere", Path("syft"), VERSION)


def test_unsafe_archives_are_rejected_before_scanning(release, fake_tool, tmp_path: Path) -> None:
    with zipfile.ZipFile(release / ARTIFACTS["wheel"], "w") as wheel:
        wheel.writestr("../escape.py", "x")
    with pytest.raises(gen.SbomError, match="unsafe member path"):
        gen.generate(release, release.parent / "o1", fake_tool(), VERSION)
    with tarfile.open(release / ARTIFACTS["sdist"], "w:gz") as bundle:
        info = tarfile.TarInfo("/etc/evil")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(Exception, match="(?i)absolute|outside|member"):
        gen.generate(release, release.parent / "o2", fake_tool(), VERSION)


# --- negative: checksum policy -------------------------------------------------------------------------


def test_a_manifest_that_omits_a_published_sbom_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    manifest = release / "SHA256SUMS"
    kept = [line for line in manifest.read_text().splitlines() if ".whl.spdx.json" not in line]
    manifest.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="must cover every published file"):
        gen.validate_checksums(release)


def test_a_manifest_that_hashes_itself_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    manifest = release / "SHA256SUMS"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    manifest.write_text(manifest.read_text() + f"{digest}  SHA256SUMS\n", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="must not list itself"):
        gen.validate_checksums(release)


def test_digest_mismatch_and_malformed_manifest_lines_fail(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    (release / ARTIFACTS["rpm"]).write_bytes(b"changed")
    with pytest.raises(gen.SbomError, match="digest mismatch"):
        gen.validate_checksums(release)
    (release / "SHA256SUMS").write_text("not a checksum line\n", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="malformed line"):
        gen.validate_checksums(release)


def test_the_bash_finalizer_refuses_an_incomplete_asset_set(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / f"{ARTIFACTS['freebsd_pkg']}.spdx.json").unlink()
    done = finalize(release)
    assert done.returncode == 1 and "missing release asset" in done.stderr
    assert not (release / "SHA256SUMS").exists()


def test_the_bash_finalizer_rejects_unexpected_assets_and_writes_no_manifest(release, fake_tool) -> None:
    generated(release, fake_tool)
    (release / "notes.txt").write_text("x", encoding="utf-8")
    done = finalize(release)
    assert done.returncode == 1 and "unexpected release asset: notes.txt" in done.stderr
    assert not (release / "SHA256SUMS").exists()


def test_the_default_artifact_check_still_stages_the_package_only_manifest() -> None:
    script = (REPO_ROOT / "scripts" / "check_release_artifacts.sh").read_text(encoding="utf-8")
    assert "Generating flat GitHub Release SHA256SUMS" in script  # pre-SBOM behavior unchanged


# --- no runtime coupling -------------------------------------------------------------------------------------


def test_the_generator_never_uploads_or_uses_a_shell_and_is_not_imported_by_the_product() -> None:
    source = (REPO_ROOT / "scripts" / "generate_release_sboms.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "shell=True" not in code and "os.system" not in code
    assert not re.search(r"gh\s+release|upload-release|softprops", code)
    for path in (REPO_ROOT / "src").rglob("*.py"):
        assert "generate_release_sboms" not in path.read_text(encoding="utf-8")


# --- the published reproducibility evidence (Issue #51 Slice 4) -------------------------------------------------


def test_the_evidence_is_a_published_file_covered_by_the_final_checksums(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    names = [line.split()[1] for line in (release / "SHA256SUMS").read_text(encoding="utf-8").splitlines()]
    assert gen.EVIDENCE in names and len(names) == 11 and "SHA256SUMS" not in names
    gen.validate_bundle(release, VERSION)
    assert gen.main(["validate-bundle", "--dir", str(release), "--version", VERSION]) == 0


def test_the_sbom_set_validation_tolerates_the_evidence_but_does_not_require_it(release, fake_tool) -> None:
    generated(release, fake_tool)
    gen.validate_set(release, VERSION)  # before the evidence exists (workflow: the validate step)
    publish_evidence(release)
    gen.validate_set(release, VERSION)  # after it exists


def test_a_bundle_without_the_published_evidence_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    (release / gen.EVIDENCE).unlink()
    write = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in sorted(release.iterdir()) if p.name != "SHA256SUMS"
    ]
    (release / "SHA256SUMS").write_text("".join(write), encoding="utf-8")
    with pytest.raises(gen.SbomError, match="REPRODUCIBILITY.json is missing or empty"):
        gen.validate_bundle(release, VERSION)


def test_a_manifest_that_omits_the_published_evidence_fails(release, fake_tool) -> None:
    generated(release, fake_tool)
    assert finalize(release).returncode == 0
    manifest = release / "SHA256SUMS"
    kept = [line for line in manifest.read_text().splitlines() if gen.EVIDENCE not in line]
    manifest.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(gen.SbomError, match="must cover every published file"):
        gen.validate_checksums(release)


def test_the_bash_finalizer_requires_the_published_evidence(release, fake_tool) -> None:
    generated(release, fake_tool)
    done = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "check_release_artifacts.sh"), "--finalize-release-assets",
         str(release.parent)],
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 1 and "missing release asset: REPRODUCIBILITY.json" in done.stderr
    assert not (release / "SHA256SUMS").exists()
    (release / gen.EVIDENCE).write_bytes(b"")
    done = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "check_release_artifacts.sh"), "--finalize-release-assets",
         str(release.parent)],
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 1 and "release asset is empty: REPRODUCIBILITY.json" in done.stderr
