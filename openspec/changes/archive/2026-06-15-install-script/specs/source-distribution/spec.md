# Spec: source-distribution

- **Capability:** source-distribution
- **Change:** install-script
- **Status:** spec_complete
- **Risk:** Medium

## Purpose

Define the contract for how the installer fetches, verifies, extracts, and updates the kiro-gateway source. v1 uses GitHub's auto-generated archive at `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz`. SHA256 verification is fail-closed by default; `--insecure` is the explicit escape hatch.

## Context

- The auto-generated archive ships with `.git/`, `tests/`, `docs/`, `.github/` inside the tarball. The installer MUST strip these after extraction.
- v1 has no curated `SHA256SUMS` file. v2 will publish one alongside the curated release tarball.
- The `requirements.txt` hash is stored in `${INSTALL_DIR}/state/requirements.sha256`. On update, if the hash changes, the venv is recreated (`pip install --force-reinstall -r requirements.txt`).

## Requirements

### Requirement: Auto-generated GitHub source archive (v1)

The installer MUST resolve the version (default `latest`, or pinned via `--version`), fetch the matching tarball, and verify it. The tarball URL MUST be `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz`.

#### Scenario: Default version is latest

- GIVEN no `--version` is passed
- WHEN the installer resolves the version
- THEN `https://api.github.com/repos/Jwadow/kiro-gateway/releases/latest` is queried
- AND the `tag_name` (stripped of the leading `v`) is used as the version.

#### Scenario: --version pins a specific tag

- GIVEN the user passes `--version 2.5.0`
- WHEN the installer fetches the source
- THEN the URL is `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v2.5.0.tar.gz`.

#### Scenario: No SHA256SUMS for v1 — fail closed by default

- GIVEN v1 has no published `SHA256SUMS`
- WHEN SHA256 verification runs
- THEN the installer exits non-zero with `No SHA256SUMS available. Re-run with --insecure to skip verification.`
- AND no extraction happens.

#### Scenario: --insecure skips verification

- GIVEN the user passes `--insecure`
- WHEN the tarball is fetched
- THEN the SHA256 check is skipped
- AND a warning is printed: `WARNING: skipping SHA256 verification (--insecure). Use only for development.`

### Requirement: Tarball excludes after extraction

After the tarball is extracted to `${INSTALL_DIR}/app.new/`, the installer MUST remove `.git/`, `tests/`, `docs/`, and `.github/` to keep the install tree small and avoid leaking CI config.

#### Scenario: Excludes are removed

- GIVEN a freshly extracted auto-generated archive
- WHEN the cleanup step runs
- THEN `${INSTALL_DIR}/app.new/.git` does NOT exist
- AND `${INSTALL_DIR}/app.new/tests` does NOT exist
- AND `${INSTALL_DIR}/app.new/docs` does NOT exist
- AND `${INSTALL_DIR}/app.new/.github` does NOT exist
- AND `${INSTALL_DIR}/app.new/LICENSE` (or `LICENSE.md`) DOES exist.

### Requirement: Atomic move into place

The installer MUST `mv ${INSTALL_DIR}/app.new ${INSTALL_DIR}/app` as a single operation. The previous `app/` MUST be moved to `app.prev/` first, so a failed update can be rolled back.

#### Scenario: Successful update

- GIVEN a previous `app/` and a freshly extracted `app.new/`
- WHEN the swap runs
- THEN `app.prev/` is the previous version
- AND `app/` is the new version
- AND `app.new/` no longer exists.

### Requirement: requirements.txt hash triggers venv refresh

The installer MUST compute the SHA256 of `requirements.txt` and store it in `${INSTALL_DIR}/state/requirements.sha256`. On update, if the stored hash differs from the new hash, the venv MUST be recreated.

#### Scenario: requirements.txt unchanged — venv preserved

- GIVEN a stored hash matching the new `requirements.txt`
- WHEN update runs
- THEN the venv is NOT recreated.

#### Scenario: requirements.txt changed — venv recreated

- GIVEN a stored hash differing from the new `requirements.txt`
- WHEN update runs
- THEN the venv is removed and recreated
- AND the new hash is stored.

### Requirement: Update via the same archive URL

`kiro-gateway update` MUST reuse the same fetch path as the installer: same URL shape, same SHA256 verification, same excludes, same atomic move. The only difference is the working directory and the absence of the preflight checks (preflight is installer-only).

#### Scenario: Update reuses fetch path

- GIVEN `kiro-gateway update` is invoked
- WHEN the fetch runs
- THEN the URL is `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz` (default `latest`)
- AND SHA256 verification runs (or `--insecure` is honored)
- AND excludes are removed.

### Requirement: Rollback to previous version

`kiro-gateway update --rollback` MUST restore `${INSTALL_DIR}/app.prev/` to `${INSTALL_DIR}/app/` and reload the service.

#### Scenario: Successful rollback

- GIVEN `${INSTALL_DIR}/app.prev/` exists with a previous version
- WHEN `kiro-gateway update --rollback` is invoked
- THEN `${INSTALL_DIR}/app/` is the previous version
- AND `${INSTALL_DIR}/app.prev/` is removed
- AND the service is reloaded.

#### Scenario: Rollback with no previous version

- GIVEN `${INSTALL_DIR}/app.prev/` does not exist
- WHEN `kiro-gateway update --rollback` is invoked
- THEN the wrapper exits non-zero with `No previous version to roll back to.`

### Requirement: Old snapshot cleanup

After a successful update, the wrapper MUST remove `app.prev/` once the new version is verified to start (a `/health` check). If no health check has run within 10 seconds, the snapshot is preserved (manual rollback remains possible).

#### Scenario: New version starts — snapshot removed

- GIVEN update completed and `GET /health` returned 200 within 10 seconds
- WHEN the snapshot-cleanup step runs
- THEN `app.prev/` no longer exists.

#### Scenario: New version unhealthy — snapshot preserved

- GIVEN update completed but `GET /health` did not return 200 within 10 seconds
- WHEN the snapshot-cleanup step runs
- THEN `app.prev/` is preserved
- AND a hint is printed: `Health check did not pass within 10s. Previous version preserved at app.prev/. Run: kiro-gateway update --rollback.`

## Test scenarios

**T-4.1** `test_default_version_resolves_to_latest` — stub the GitHub API to return `tag_name=v2.5.0`; assert the fetched URL matches `v2.5.0`.
**T-4.2** `test_version_flag_pins_tag` — `--version 2.4.0` results in fetching `v2.4.0.tar.gz`.
**T-4.3** `test_no_shasums_fails_closed` — with no `SHA256SUMS` reachable, the installer aborts with the documented message.
**T-4.4** `test_insecure_skips_verification` — `--insecure` produces the warning and proceeds.
**T-4.5** `test_tarball_excludes_removed` — after extraction, `.git`, `tests`, `docs`, `.github` are absent; `LICENSE` is present.
**T-4.6** `test_atomic_swap_creates_app_prev` — after `mv`, the previous `app/` is at `app.prev/`.
**T-4.7** `test_requirements_unchanged_preserves_venv` — identical hashes; venv untouched.
**T-4.8** `test_requirements_changed_recreates_venv` — different hashes; venv is recreated.
**T-4.9** `test_update_rollback_restores_prev` — `update --rollback` swaps `app/` and `app.prev/`.
**T-4.10** `test_rollback_no_prev_fails` — with no `app.prev/`, `update --rollback` exits non-zero.
**T-4.11** `test_snapshot_removed_on_healthy_start` — with `/health` returning 200 within 10s, `app.prev/` is removed.
**T-4.12** `test_snapshot_preserved_on_unhealthy_start` — with `/health` failing, `app.prev/` is preserved and the hint is printed.

## Acceptance criteria

- AC-4.A: All T-4.x tests pass.
- AC-4.B: The default install uses HTTPS exclusively; no HTTP fallback path exists in the source code.
- AC-4.C: The four excludes (`.git`, `tests`, `docs`, `.github`) are removed by the install script and verified by T-4.5.
- AC-4.D: The `requirements.sha256` workflow is covered end-to-end by T-4.7 and T-4.8.
- AC-4.E: The rollback path is covered by T-4.9 and T-4.10.
