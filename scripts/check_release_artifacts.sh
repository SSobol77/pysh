#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# File: scripts/check_release_artifacts.sh
#
# Copyright (C) 2026 Siergej Sobolewski

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

# --- mode / artifact directory -----------------------------------------
#
# Default (no args): validates the real ${REPO_ROOT}/dist tree produced by
# scripts/build_release_artifacts.sh. This is the native/full release path
# used by scripts/check_release_quality.sh and
# .github/workflows/release-artifacts.yml and its behavior is unchanged.
#
# --contract-only [ARTIFACT_DIR]: validates artifact naming, presence,
# non-zero size, and checksum completeness only. It performs exactly the
# same checks as the default mode -- no check is skipped or weakened -- but
# is explicitly labeled so its PASS can never be mistaken for native
# package validation (dpkg/rpm/pkg install, wheel/sdist install smoke).
# ARTIFACT_DIR lets ordinary CI point this at an isolated, disposable
# directory (which may contain a clearly-labeled non-native fixture for the
# one artifact family that cannot be produced on the host, e.g. a FreeBSD
# .pkg on Linux) instead of the real dist/. See
# docs/architecture/release-quality-gate-2-audit.md for the rationale.
#
# --finalize-release-assets [ARTIFACT_DIR]: the last step of the release-asset
# pipeline (Issue #51). It runs AFTER scripts/generate_release_sboms.py has added
# the five SPDX SBOMs and the reproducibility evidence (REPRODUCIBILITY.json) to
# ARTIFACT_DIR/release-assets, and (re)writes the one public SHA256SUMS over every
# published release file except SHA256SUMS itself (packages, SBOMs and the evidence),
# then verifies it. It never builds, never generates an
# SBOM and never uploads anything.
CONTRACT_ONLY=0
FINALIZE_RELEASE_ASSETS=0
while [ $# -gt 0 ]; do
    case "$1" in
        --contract-only) CONTRACT_ONLY=1 ;;
        --finalize-release-assets) FINALIZE_RELEASE_ASSETS=1 ;;
        -*)
            echo "usage: check_release_artifacts.sh [--contract-only | --finalize-release-assets] [ARTIFACT_DIR]" >&2
            exit 2
            ;;
        *) break ;;
    esac
    shift
done
DIST_DIR="${1:-${REPO_ROOT}/dist}"
if [ $# -gt 1 ] || { [ "${CONTRACT_ONLY}" -eq 1 ] && [ "${FINALIZE_RELEASE_ASSETS}" -eq 1 ]; }; then
    echo "usage: check_release_artifacts.sh [--contract-only | --finalize-release-assets] [ARTIFACT_DIR]" >&2
    exit 2
fi

if [ "${CONTRACT_ONLY}" -eq 1 ]; then
    MODE_LABEL="contract-only"
else
    MODE_LABEL="full"
fi

echo "==> check_release_artifacts.sh (${MODE_LABEL} mode): validating ${DIST_DIR}"
if [ "${CONTRACT_ONLY}" -eq 1 ]; then
    echo "==> contract-only mode validates artifact naming, presence, non-zero size,"
    echo "==> and checksum completeness ONLY. It does not perform, and its PASS must"
    echo "==> never be read as, native package installation or platform-specific"
    echo "==> validation (dpkg/rpm/pkg install). See"
    echo "==> docs/architecture/release-quality-gate-2-audit.md for the full contract."
fi

# shellcheck source=scripts/_pysh_version.sh
. "${REPO_ROOT}/scripts/_pysh_version.sh"

VERSION="$(pysh_read_version "${REPO_ROOT}/pyproject.toml")"
if [ -z "${VERSION}" ]; then
    echo "check_release_artifacts.sh: failed to read version" >&2
    exit 1
fi

PKG_NAME="pysh-shell"
PKG_RELEASE="1"

EXPECTED_WHEEL_NAME="pysh_shell-${VERSION}-py3-none-any.whl"
EXPECTED_SDIST_HYPHEN="pysh-shell-${VERSION}.tar.gz"
EXPECTED_SDIST_UNDER="pysh_shell-${VERSION}.tar.gz"
EXPECTED_DEB="${PKG_NAME}_${VERSION}-${PKG_RELEASE}_all.deb"
EXPECTED_RPM="${PKG_NAME}-${VERSION}-${PKG_RELEASE}.noarch.rpm"
EXPECTED_FREEBSD_PKG="${PKG_NAME}-${VERSION}.pkg"

SBOM_SUFFIX=".spdx.json"
EVIDENCE_FILE="REPRODUCIBILITY.json"

WHEEL_PATH="${DIST_DIR}/${EXPECTED_WHEEL_NAME}"
DEB_PATH="${DIST_DIR}/os/deb/${EXPECTED_DEB}"
RPM_PATH="${DIST_DIR}/os/rpm/${EXPECTED_RPM}"
FREEBSD_PKG_PATH="${DIST_DIR}/os/freebsd/${EXPECTED_FREEBSD_PKG}"
RELEASE_ASSETS_DIR="${DIST_DIR}/release-assets"

missing=0

# --- final SHA256SUMS over the complete published set (Issue #51) -------------
#
# SBOM file names derive mechanically from the artifact basename. The manifest
# covers every published file except itself, so there is no checksum recursion,
# and it is written only once the complete release asset set exists.
if [ "${FINALIZE_RELEASE_ASSETS}" -eq 1 ]; then
    ASSETS="${RELEASE_ASSETS_DIR}"
    echo "==> check_release_artifacts.sh (finalize mode): ${ASSETS}"
    if [ ! -d "${ASSETS}" ]; then
        echo "check_release_artifacts.sh: missing release assets directory: ${ASSETS}" >&2
        exit 1
    fi
    SDIST_BASENAME=""
    if [ -f "${ASSETS}/${EXPECTED_SDIST_UNDER}" ]; then
        SDIST_BASENAME="${EXPECTED_SDIST_UNDER}"
    elif [ -f "${ASSETS}/${EXPECTED_SDIST_HYPHEN}" ]; then
        SDIST_BASENAME="${EXPECTED_SDIST_HYPHEN}"
    else
        echo "check_release_artifacts.sh: missing sdist in ${ASSETS}" >&2
        exit 1
    fi
    PACKAGES=(
        "${EXPECTED_WHEEL_NAME}" "${SDIST_BASENAME}" "${EXPECTED_DEB}"
        "${EXPECTED_RPM}" "${EXPECTED_FREEBSD_PKG}"
    )
    ALLOWED=("SHA256SUMS")
    for package in "${PACKAGES[@]}"; do
        for required in "${package}" "${package}${SBOM_SUFFIX}"; do
            if [ ! -f "${ASSETS}/${required}" ]; then
                echo "check_release_artifacts.sh: missing release asset: ${required}" >&2
                missing=1
            elif [ ! -s "${ASSETS}/${required}" ]; then
                echo "check_release_artifacts.sh: release asset is empty: ${required}" >&2
                missing=1
            fi
            ALLOWED+=("${required}")
        done
    done
    # The reproducibility evidence (Issue #51 Slice 4) is a published release asset that
    # exists before this step, so it is covered by the final SHA256SUMS like every other file.
    if [ ! -f "${ASSETS}/${EVIDENCE_FILE}" ]; then
        echo "check_release_artifacts.sh: missing release asset: ${EVIDENCE_FILE}" >&2
        missing=1
    elif [ ! -s "${ASSETS}/${EVIDENCE_FILE}" ]; then
        echo "check_release_artifacts.sh: release asset is empty: ${EVIDENCE_FILE}" >&2
        missing=1
    fi
    ALLOWED+=("${EVIDENCE_FILE}")
    for path in "${ASSETS}"/*; do
        base="$(basename "${path}")"
        found=0
        for allowed in "${ALLOWED[@]}"; do
            if [ "${base}" = "${allowed}" ]; then found=1; fi
        done
        if [ "${found}" -ne 1 ]; then
            echo "check_release_artifacts.sh: unexpected release asset: ${base}" >&2
            missing=1
        fi
    done
    if [ "${missing}" -ne 0 ]; then
        echo "check_release_artifacts.sh: aborting: the release asset set is incomplete." >&2
        exit 1
    fi
    TMP_SUMS="$(mktemp)"
    mapfile -t PUBLISHED < <(cd "${ASSETS}" && ls -1 | grep -vx SHA256SUMS | LC_ALL=C sort)
    (cd "${ASSETS}" && sha256sum -- "${PUBLISHED[@]}") >"${TMP_SUMS}"
    mv "${TMP_SUMS}" "${ASSETS}/SHA256SUMS"
    (cd "${ASSETS}" && sha256sum -c SHA256SUMS)
    for published in "${PUBLISHED[@]}"; do
        if ! awk '{print $2}' "${ASSETS}/SHA256SUMS" | sed 's/^\*//' | grep -Fxq "${published}"; then
            echo "check_release_artifacts.sh: SHA256SUMS missing: ${published}" >&2
            missing=1
        fi
    done
    if awk '{print $2}' "${ASSETS}/SHA256SUMS" | sed 's/^\*//' | grep -Fxq SHA256SUMS; then
        echo "check_release_artifacts.sh: SHA256SUMS must not list itself" >&2
        missing=1
    fi
    if [ "${missing}" -ne 0 ]; then
        exit 1
    fi
    echo "==> Final SHA256SUMS covers ${#PUBLISHED[@]} published files (packages + SBOMs + evidence), excluding itself."
    exit 0
fi

# Fails on a missing artifact (contract items 1-5) AND on a present-but-empty
# artifact (contract item 9: a zero-byte placeholder must never be accepted
# as a real release artifact).
check_present() {
    local path="$1"
    if [ ! -f "${path}" ]; then
        echo "check_release_artifacts.sh: missing artifact: ${path}" >&2
        missing=1
        return
    fi
    if [ ! -s "${path}" ]; then
        echo "check_release_artifacts.sh: artifact is present but empty (0 bytes);" \
            "refusing to treat a placeholder as a real release artifact: ${path}" >&2
        missing=1
    fi
}

check_present "${WHEEL_PATH}"
check_present "${DEB_PATH}"
check_present "${RPM_PATH}"
check_present "${FREEBSD_PKG_PATH}"

# Accept either backend filename form for the sdist.
SDIST_PATH=""
if [ -f "${DIST_DIR}/${EXPECTED_SDIST_UNDER}" ]; then
    SDIST_PATH="${DIST_DIR}/${EXPECTED_SDIST_UNDER}"
elif [ -f "${DIST_DIR}/${EXPECTED_SDIST_HYPHEN}" ]; then
    SDIST_PATH="${DIST_DIR}/${EXPECTED_SDIST_HYPHEN}"
else
    echo "check_release_artifacts.sh: missing sdist (${EXPECTED_SDIST_UNDER} or ${EXPECTED_SDIST_HYPHEN})" >&2
    missing=1
fi
if [ -n "${SDIST_PATH}" ] && [ ! -s "${SDIST_PATH}" ]; then
    echo "check_release_artifacts.sh: artifact is present but empty (0 bytes);" \
        "refusing to treat a placeholder as a real release artifact: ${SDIST_PATH}" >&2
    missing=1
fi

if [ "${missing}" -ne 0 ]; then
    echo "check_release_artifacts.sh: aborting due to missing artifacts." >&2
    exit 1
fi

# Hard-fail if any sibling .deb / .rpm / .pkg violates naming (contract item
# 6: any artifact filename drift from canonical version-derived naming, and
# item 12: unexpected sibling artifact naming).
for f in "${DIST_DIR}/os/deb"/*.deb; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_DEB}" ]; then
        echo "check_release_artifacts.sh: unexpected .deb filename: ${base}" >&2
        echo "check_release_artifacts.sh: canonical name must be ${EXPECTED_DEB}" >&2
        exit 1
    fi
done

for f in "${DIST_DIR}/os/rpm"/*.rpm; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_RPM}" ]; then
        echo "check_release_artifacts.sh: unexpected .rpm filename: ${base}" >&2
        echo "check_release_artifacts.sh: canonical name must be ${EXPECTED_RPM}" >&2
        exit 1
    fi
done

for f in "${DIST_DIR}/os/freebsd"/*.pkg; do
    base="$(basename "${f}")"
    if [ "${base}" != "${EXPECTED_FREEBSD_PKG}" ]; then
        echo "check_release_artifacts.sh: unexpected .pkg filename: ${base}" >&2
        echo "check_release_artifacts.sh: canonical name must be ${EXPECTED_FREEBSD_PKG}" >&2
        exit 1
    fi
done

# Fails if SHA256SUMS does not list every expected artifact (contract item 7).
require_checksum_entry() {
    local sum_file="$1"
    local relative="$2"
    if ! awk '{print $2}' "${sum_file}" | sed 's/^\*//' | grep -Fxq "${relative}"; then
        echo "check_release_artifacts.sh: ${sum_file} missing expected artifact: ${relative}" >&2
        missing=1
    fi
}

SUM_FILE="${DIST_DIR}/SHA256SUMS"
if [ -f "${SUM_FILE}" ]; then
    # A SHA256SUMS was supplied rather than freshly generated by this run
    # (e.g. a contract-mode fixture, or a stale file from a partial local
    # rebuild). Verify it as-is instead of silently overwriting it, so a
    # corrupted or incomplete manifest fails loudly (contract item 8)
    # rather than being masked by regeneration.
    echo "==> Verifying pre-supplied SHA256SUMS"
    (
        cd "${DIST_DIR}"
        sha256sum -c SHA256SUMS
    )
else
    echo "==> Generating local SHA256SUMS"
    (
        cd "${DIST_DIR}"
        : >"${SUM_FILE}"
        # List the artifacts in a stable order using paths relative to dist/.
        sha256sum \
            "${EXPECTED_WHEEL_NAME}" \
            "$(basename "${SDIST_PATH}")" \
            "os/deb/${EXPECTED_DEB}" \
            "os/rpm/${EXPECTED_RPM}" \
            "os/freebsd/${EXPECTED_FREEBSD_PKG}" \
            >"${SUM_FILE}"
    )

    echo "==> Verifying SHA256SUMS"
    (
        cd "${DIST_DIR}"
        sha256sum -c SHA256SUMS
    )
fi

require_checksum_entry "${SUM_FILE}" "${EXPECTED_WHEEL_NAME}"
require_checksum_entry "${SUM_FILE}" "$(basename "${SDIST_PATH}")"
require_checksum_entry "${SUM_FILE}" "os/deb/${EXPECTED_DEB}"
require_checksum_entry "${SUM_FILE}" "os/rpm/${EXPECTED_RPM}"
require_checksum_entry "${SUM_FILE}" "os/freebsd/${EXPECTED_FREEBSD_PKG}"

if [ "${missing}" -ne 0 ]; then
    echo "check_release_artifacts.sh: aborting due to SHA256SUMS problems." >&2
    exit 1
fi

echo "==> Staging flat GitHub Release assets"
rm -rf "${RELEASE_ASSETS_DIR}"
mkdir -p "${RELEASE_ASSETS_DIR}"
cp "${WHEEL_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_WHEEL_NAME}"
cp "${SDIST_PATH}" "${RELEASE_ASSETS_DIR}/$(basename "${SDIST_PATH}")"
cp "${DEB_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_DEB}"
cp "${RPM_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_RPM}"
cp "${FREEBSD_PKG_PATH}" "${RELEASE_ASSETS_DIR}/${EXPECTED_FREEBSD_PKG}"

RELEASE_SUM_FILE="${RELEASE_ASSETS_DIR}/SHA256SUMS"
echo "==> Generating flat GitHub Release SHA256SUMS"
(
    cd "${RELEASE_ASSETS_DIR}"
    sha256sum \
        "${EXPECTED_WHEEL_NAME}" \
        "$(basename "${SDIST_PATH}")" \
        "${EXPECTED_DEB}" \
        "${EXPECTED_RPM}" \
        "${EXPECTED_FREEBSD_PKG}" \
        >"${RELEASE_SUM_FILE}"
)

echo "==> Verifying flat GitHub Release SHA256SUMS"
(
    cd "${RELEASE_ASSETS_DIR}"
    sha256sum -c SHA256SUMS
)

require_checksum_entry "${RELEASE_SUM_FILE}" "${EXPECTED_WHEEL_NAME}"
require_checksum_entry "${RELEASE_SUM_FILE}" "$(basename "${SDIST_PATH}")"
require_checksum_entry "${RELEASE_SUM_FILE}" "${EXPECTED_DEB}"
require_checksum_entry "${RELEASE_SUM_FILE}" "${EXPECTED_RPM}"
require_checksum_entry "${RELEASE_SUM_FILE}" "${EXPECTED_FREEBSD_PKG}"

if [ "${missing}" -ne 0 ]; then
    echo "check_release_artifacts.sh: aborting due to SHA256SUMS problems." >&2
    exit 1
fi

echo "==> Release artifacts (${MODE_LABEL} mode, ${DIST_DIR}):"
ls -1 "${DIST_DIR}"
echo "----"
ls -1 "${DIST_DIR}/os/deb"
ls -1 "${DIST_DIR}/os/rpm"
ls -1 "${DIST_DIR}/os/freebsd"
echo "----"
echo "Local SHA256SUMS:"
cat "${SUM_FILE}"
echo "----"
echo "Flat GitHub Release assets:"
ls -1 "${RELEASE_ASSETS_DIR}"
echo "----"
echo "Flat GitHub Release SHA256SUMS:"
cat "${RELEASE_SUM_FILE}"

if [ "${CONTRACT_ONLY}" -eq 1 ]; then
    echo "==> Artifact contract PASSED (contract-only mode)."
    echo "==> This did not perform native package installation or platform-specific"
    echo "==> validation. See .github/workflows/release-artifacts.yml and"
    echo "==> scripts/check_release_quality.sh for native/full validation."
fi
