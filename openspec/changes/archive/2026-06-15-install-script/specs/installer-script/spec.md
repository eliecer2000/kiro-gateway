# Spec: installer-script

- **Capability:** installer-script
- **Change:** install-script
- **Status:** spec_complete
- **Risk:** Medium

## Purpose

Define the contract for `scripts/install.sh`: a strict-mode POSIX shell one-liner installer that runs preflight checks, fetches a SHA256-verified source tarball, bootstraps a venv, lays out a hidden XDG-compliant install directory, registers a platform service, and prints a post-install summary. The script MUST be safe to pipe from `curl` (no `eval`, fail-closed, no partial state on error).

## Context

- Reference shape: the `gentle-ai` install script (same `set -euo pipefail`, same OS/arch detect, same SHA256 verification pattern, same `--insecure` escape hatch). Diverges by managing a Python venv + app-tree + service, not a Go binary.
- Source distribution: v1 uses GitHub's auto-generated archive `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz`. No `SHA256SUMS` is published for v1, so verification is fail-closed by default and the user must pass `--insecure` to skip.
- The script is the **only** entry point for fresh installs. It MUST be idempotent: a second run on an existing install offers `(r)einstall / (u)pdate / (a)bort / (c)ustom path` rather than destroying state.

## Requirements

### Requirement: One-liner install completes end-to-end

The installer MUST, given network access and a supported platform, end with a working install: venv created, source extracted, service registered, and a post-install summary printed. The happy path MUST NOT prompt for input (other than the pre-existing-install prompt if applicable).

#### Scenario: Fresh install on macOS

- GIVEN macOS 13+ with Python 3.11 system-installed and `~/.local/bin` on `PATH`
- WHEN the user runs `curl -fsSL .../install.sh | bash -s -- install`
- THEN `${HOME}/Library/Application Support/KiroGateway/` is created
- AND a venv exists at `${HOME}/Library/Application Support/KiroGateway/venv/`
- AND the source is extracted at `${HOME}/Library/Application Support/KiroGateway/app/`
- AND `~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist` is loaded with `RunAtLoad=false`
- AND `~/.local/bin/kiro-gateway` is a working symlink to the wrapper
- AND a post-install summary is printed (install path, wrapper path, next steps).

#### Scenario: Fresh install on Linux (systemd)

- GIVEN Ubuntu 24.04 (or any systemd Linux) with Python 3.10+ and `~/.local/bin` on `PATH`
- WHEN the user runs `curl -fsSL .../install.sh | bash -s -- install`
- THEN `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/` is created
- AND a venv, app tree, state dir, and logs dir are laid out
- AND `~/.config/systemd/user/kiro-gateway.service` exists
- AND `systemctl --user daemon-reload` has run (NOT `enable`)
- AND `~/.local/bin/kiro-gateway` is a working symlink.

### Requirement: Usage and version flags

The installer MUST accept `--help` (or `-h`) and `--version X.Y.Z`.

#### Scenario: --help prints usage

- GIVEN the install script
- WHEN the user runs `bash install.sh --help`
- THEN usage is printed to stdout
- AND the script exits 0.

#### Scenario: --version pins a specific release

- GIVEN the user passes `--version 2.5.0`
- WHEN the installer fetches the source
- THEN the fetched tarball is `v2.5.0` (not `latest`).

### Requirement: Pre-flight validation

The installer MUST validate OS, Python ≥3.10, `curl`, `tar`, free disk space ≥200MB, and network reachability to `github.com` before performing any destructive action. Each failure MUST produce an actionable error.

#### Scenario: macOS or Linux detected

- GIVEN `uname -s` is `Darwin` or `Linux`
- WHEN preflight runs
- THEN the platform check passes.

#### Scenario: Python 3.10+ present

- GIVEN a system Python ≥3.10
- WHEN preflight runs
- THEN the Python check passes.

#### Scenario: Python 3.9 found — fail with actionable message

- GIVEN a system Python 3.9.x
- WHEN preflight runs
- THEN the script exits non-zero
- AND prints `Python 3.10 or newer is required. Found 3.9.x. Install via pyenv or your package manager.`

#### Scenario: No network — fail with actionable message

- GIVEN no connectivity to `github.com` (e.g. captive portal, firewalled)
- WHEN preflight runs
- THEN the script exits non-zero
- AND prints `Cannot reach github.com. Check your connection.`

#### Scenario: Run with sudo — fail with actionable message

- GIVEN `EUID=0`
- WHEN the script starts
- THEN the script exits non-zero immediately
- AND prints `Do not run this installer with sudo. Re-run as your normal user.`

### Requirement: Hidden install location with override

The default install location MUST be `~/Library/Application Support/KiroGateway/` on macOS and `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/` on Linux. `--install-dir` MUST override the default.

#### Scenario: macOS default install path

- GIVEN a fresh macOS install with `HOME=/Users/alice`
- WHEN the install completes
- THEN the install root is `/Users/alice/Library/Application Support/KiroGateway/`.

#### Scenario: Linux default install path honors XDG

- GIVEN `XDG_DATA_HOME=/srv/data`
- WHEN the install completes
- THEN the install root is `/srv/data/kiro-gateway/`.

#### Scenario: --install-dir override

- GIVEN the user passes `--install-dir /opt/kiro-gateway`
- WHEN the install completes
- THEN the install root is `/opt/kiro-gateway/`.

### Requirement: Pre-existing install handling

If an install is detected at the target path, the installer MUST prompt for `(r)einstall / (u)pdate / (a)bort / (c)ustom path` and respect the choice.

#### Scenario: Existing install — user picks reinstall

- GIVEN an existing install at the target path
- WHEN the user types `r`
- THEN the installer preserves `${INSTALL_DIR}/state/` and replaces `app/` and `venv/`.

#### Scenario: Existing install — user picks update

- GIVEN an existing install
- WHEN the user types `u`
- THEN the installer hands off to the update flow (atomic extract, venv refresh, service reload).

#### Scenario: Existing install — user picks abort

- GIVEN an existing install
- WHEN the user types `a` (or hits Enter)
- THEN the installer exits 0 without changes.

### Requirement: Atomic extraction

The source MUST be extracted to `${INSTALL_DIR}/app.new/` first, then atomically renamed to `${INSTALL_DIR}/app/`. On extraction failure, `app.new/` MUST be removed and the installer MUST exit non-zero.

#### Scenario: Successful extract

- GIVEN a valid tarball at `${INSTALL_DIR}/app.new.tar.gz`
- WHEN extraction runs
- THEN `${INSTALL_DIR}/app.new/` contains the source
- AND an `mv` renames it to `${INSTALL_DIR}/app/` in a single step.

#### Scenario: Extraction failure cleans up

- GIVEN a corrupt tarball
- WHEN extraction runs
- THEN `${INSTALL_DIR}/app.new/` does NOT exist after the failure
- AND the previous `${INSTALL_DIR}/app/` is intact.

### Requirement: HTTPS-only with SHA256 verification

The installer MUST use HTTPS for the source download and MUST enforce `--proto =https --tlsv1.2` on every `curl` invocation. SHA256 verification MUST be the default.

#### Scenario: HTTPS enforced on download

- GIVEN the installer fetching the tarball
- WHEN `curl` is invoked
- THEN `--proto =https --tlsv1.2` is in the argument list
- AND a downgrade attempt (e.g. `http://` URL) is rejected by curl.

#### Scenario: --insecure skips SHA256 check

- GIVEN the user passes `--insecure`
- WHEN the tarball is fetched
- THEN the SHA256 check is skipped
- AND a warning is printed: `WARNING: skipping SHA256 verification (--insecure).`

### Requirement: Idempotency

Running the installer a second time on a healthy install MUST NOT corrupt state. The pre-existing-install prompt is the contract for idempotency.

#### Scenario: Second run on a healthy install

- GIVEN a working install at the target path
- WHEN the installer is invoked again
- THEN the pre-existing-install prompt appears
- AND no files are modified before the user answers.

## Test scenarios

**T-1.1** `test_install_fresh_macos_layout` — run the installer against a tempdir with macOS stubs; assert the full directory layout matches spec.
**T-1.2** `test_install_fresh_linux_layout` — same as T-1.1 for Linux + systemd.
**T-1.3** `test_install_help_exits_zero` — `bash install.sh --help` exits 0 and prints usage.
**T-1.4** `test_install_version_flag_pins` — `--version 2.5.0` results in a tarball fetch of `v2.5.0`.
**T-1.5** `test_preflight_python_39_fails` — with Python 3.9 stubbed, preflight fails with the exact error string from the spec.
**T-1.6** `test_preflight_no_network_fails` — with `github.com` unreachable, preflight fails with the exact error string.
**T-1.7** `test_preflight_root_fails` — with `EUID=0` simulated, script exits non-zero immediately.
**T-1.8** `test_install_dir_override` — `--install-dir /tmp/x` lands the install at `/tmp/x`.
**T-1.9** `test_preexisting_install_reinstall_preserves_state` — choose `r`; `state/` files (`.env`, `credentials.json`) are unchanged.
**T-1.10** `test_atomic_extract_failure_cleans_up` — corrupt tarball leaves no `app.new/`.
**T-1.11** `test_https_only` — every `curl` invocation includes `--proto =https --tlsv1.2`.
**T-1.12** `test_idempotent_second_run` — second run with default answer (`a`) does not modify the install.

## Acceptance criteria

- AC-1.A: All T-1.x tests pass.
- AC-1.B: `bash -n install.sh` reports no syntax errors.
- AC-1.C: `shellcheck install.sh` reports no errors at severity `error`.
- AC-1.D: `rg 'eval\b' install.sh` returns no matches.
- AC-1.E: Full pytest suite passes (no existing test regresses).
