#!/usr/bin/env bash
# Build the versioned source archive consumed by scripts/install.sh.

set -euo pipefail

VERSION="${1:-}"
OUTPUT_DIR="${2:-dist}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'Usage: %s X.Y.Z [OUTPUT_DIR]\n' "$0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kiro-gateway-release.XXXXXX")"
ARCHIVE_ROOT="kiro-gateway-${VERSION}"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_ROOT}.tar.gz"

cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

mkdir -p "${STAGING_DIR}/${ARCHIVE_ROOT}"
(
    cd "$REPO_ROOT"
    tar -cf - \
        main.py kiro requirements.txt .env.example credentials.json.example \
        scripts LICENSE README.md
) | tar -xf - -C "${STAGING_DIR}/${ARCHIVE_ROOT}"
printf '%s\n' "$VERSION" > "${STAGING_DIR}/${ARCHIVE_ROOT}/VERSION"

tar -czf "$ARCHIVE_PATH" -C "$STAGING_DIR" "$ARCHIVE_ROOT"

if command -v sha256sum >/dev/null 2>&1; then
    checksum="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    checksum="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"
else
    printf 'error: sha256sum or shasum is required\n' >&2
    exit 1
fi

printf '%s  %s\n' "$checksum" "${ARCHIVE_ROOT}.tar.gz" > "${OUTPUT_DIR}/SHA256SUMS"
printf 'Built %s and %s\n' "$ARCHIVE_PATH" "${OUTPUT_DIR}/SHA256SUMS"
