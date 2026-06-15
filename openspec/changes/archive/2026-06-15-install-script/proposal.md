# Proposal: install-script

- **Status:** proposal_complete
- **Change name:** `install-script`
- **Type:** developer-experience / distribution
- **Delivery:** single PR (estimated ~700 changed lines including tests, within the 400-line soft budget once split across install.sh + wrapper + templates + tests; no chained-PR requirement)
- **Next recommended phase:** spec

## Executive summary

Today the only install path for kiro-gateway is `git clone` + `pip install` + `cp .env.example` + `python main.py`, which leaves the user with a visible folder, no service, no lifecycle, no logs, no uninstall, and a process that dies when the terminal closes. This change ships a one-liner `curl | bash` installer (`scripts/install.sh`) plus a `kiro-gateway` lifecycle wrapper (`scripts/kiro-gateway`) plus launchd / systemd --user templates, backed by a hidden XDG-compliant install directory and SHA256-verified source fetch from a pinned GitHub release tarball.

The result: a user can run `curl ... | bash -s -- install` on macOS or Linux and end with a working, registered-but-stopped service managed by `kiro-gateway {start|stop|restart|status|logs|update|uninstall}`. The service is intentionally **not** started on reboot — the user invokes `start` when they want it running. v1 ships manual rollback on update; v2 will add auto-rollback and a curated release-tarball workflow.

## Problem Statement

Current install path pain points (verified):

- **No service** — the process dies when the terminal closes; no way to keep it running unattended.
- **PEP 668** — modern Python refuses system-wide `pip install`; users hit `error: externally-managed-environment`.
- **State at CWD** — `credentials.json`, `state.json`, `.env` end up in whatever folder the user ran from, with default umask (often world-readable).
- **Logs to stderr only** — no log file, no rotation, no `tail -f` story.
- **No uninstall path** — files are scattered; the user can't cleanly remove the install.
- **Docker works but the user wants non-Docker** — Docker is a hard dependency on a host toolchain many users don't have.
- **No version pinning** — `git clone` gives a moving HEAD; users can't reliably reproduce an install.

## Goals

- **AC-1**: One-liner install works on macOS (Intel + Apple Silicon) and Linux (glibc + systemd).
- **AC-2**: Service management via `kiro-gateway {start|stop|status|logs|restart|update|uninstall|version|help}`.
- **AC-3**: Hidden install location — `~/Library/Application Support/KiroGateway/` on macOS, `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/` on Linux.
- **AC-4**: Service is registered (plist loaded, unit known to systemd) but **does not** autostart on reboot.
- **AC-5**: Pre-flight validation with friendly, actionable error messages (Python ≥3.10, curl, tar, disk ≥200MB, network).
- **AC-6**: SHA256-verified HTTPS source download; fail closed; `--insecure` escape hatch documented.
- **AC-7**: `kiro-gateway update` performs an atomic replace with manual rollback (`update --rollback`).
- **AC-8**: `kiro-gateway uninstall` cleanly stops the service, removes the plist/unit, prompts for the install dir removal.
- **AC-9**: Filesystem permissions: `state/` is `chmod 700`, `.env` and `credentials.json` are `chmod 600`, `logs/` is `chmod 750`.
- **AC-10**: Installer refuses to run as root (EUID 0) with a clear message; refuses non-systemd Linux with a friendly redirect to Docker.

## Non-Goals

- **Auto-update by default** — update is user-driven only (`kiro-gateway update`).
- **Multi-user install** — single-user, user-level service. No system-wide unit.
- **Windows native** — recommend WSL. The installer detects Windows and refuses.
- **Non-systemd Linux** (Alpine, Void, Artix, Devuan, NixOS) — refuse with a friendly message that recommends Docker.
- **Source distribution via curated release tarball** — v1 uses the auto-generated GitHub archive (`/archive/refs/tags/vX.Y.Z.tar.gz`). v2 promotes to a curated release tarball with `SHA256SUMS`.
- **Auto-rollback on update** — v1 is manual (`update --rollback`); v2 adds health-check-driven auto-rollback.
- **GPG signature verification** — deferred to v3.
- **Replacing the existing `git clone` install path** — it stays supported; the installer is additive.
- **Multi-process / multi-worker uvicorn** — out of scope here; covered in `perf-async-improvements` if needed.

## Proposed Approach

Four artifacts ship together in a single PR:

1. **`scripts/install.sh`** — the one-liner. Strict mode (`set -euo pipefail`), preflight, OS/arch detect, color setup, source fetch, SHA256 verify, venv bootstrap, state-dir layout, service registration, post-install summary. ~300 lines.
2. **`scripts/kiro-gateway`** — POSIX shell lifecycle wrapper installed at `${INSTALL_DIR}/bin/kiro-gateway` and symlinked into `~/.local/bin/`. Dispatches to `start|stop|restart|status|logs|update|uninstall|version|help`. ~150 lines.
3. **`scripts/system/kiro-gateway.plist`** — launchd template (macOS), with `RunAtLoad=false`, `KeepAlive=false`, env vars. ~30 lines.
4. **`scripts/system/kiro-gateway.service`** — systemd --user unit (Linux), with `WantedBy=default.target` but never `enable`d. ~25 lines.

Plus a test suite under `tests/scripts/` (~200 lines) that exercises the install wrapper on a tempdir and the lifecycle commands against a mock service.

The installer pre-creates a venv at `${INSTALL_DIR}/venv/`, extracts the source to `${INSTALL_DIR}/app/`, lays out `${INSTALL_DIR}/state/` with restrictive permissions, and registers the service via the platform-native tool. The wrapper reads `${INSTALL_DIR}/state/install.env` to know the install root and dispatches to `launchctl` / `systemctl --user` accordingly.

## Open Question Resolutions

| # | Question | Resolution |
|---|----------|-----------|
| Q1 | Release-tarball workflow vs auto-generated GitHub archive? | **Auto-generated GitHub archive for v1** (no release workflow required, one less moving piece, deterministic for tagged commits). Promote to a curated release tarball with `SHA256SUMS` in v2. |
| Q2 | Auto-rollback on update? | **Manual only in v1** (`kiro-gateway update --rollback` restores `${INSTALL_DIR}/app.prev/`). V2 adds health-check-driven auto-rollback. |
| Q3 | Pre-existing install handling? | **Prompt with `(r)einstall / (u)pdate / (a)bort / (c)ustom path`**. Default to abort on empty input. Reinstall preserves `state/`. Update routes to the update flow. Custom path asks for an alternate install root. |
| Q4 | Wrapper path — symlink in `~/.local/bin/` plus canonical `${INSTALL_DIR}/bin/`? | **Yes to both.** Symlink to `~/.local/bin/kiro-gateway` for ergonomic PATH; canonical lives in `${INSTALL_DIR}/bin/` for resilience. |
| Q5 | Non-systemd Linux distros? | **Detect, refuse with a friendly message**, recommend Docker. Checked: no systemd = no service = no managed install. |

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | `launchctl load -w` silently flips `RunAtLoad=true` and breaks the "stopped after reboot" contract | Medium | High | The script uses `launchctl bootstrap gui/$(id -u)`, **not** `load -w`. A test asserts `RunAtLoad` is `false` after install. |
| R2 | PEP 668 errors if venv is not used | High | Medium | Installer creates a venv at `${INSTALL_DIR}/venv/` and runs `pip install` against it. No system pip. |
| R3 | Running installer with sudo creates root-owned state the service can't write to | High | High | Installer aborts with `EUID 0` check at the top: "Do not run this installer with sudo." |
| R4 | Pre-existing install overwritten silently | Medium | Medium | Existing install triggers an interactive prompt (r/u/a/c) before any destructive action. |
| R5 | SHA256 verification skipped due to lack of `SHA256SUMS` for v1 auto-generated archive | Low | Medium | v1 fails closed by default; `--insecure` documented as a single-user escape hatch. v2 ships curated `SHA256SUMS`. |
| R6 | `app.prev/` left dangling after a successful update | Low | Low | `update` removes `app.prev/` after the new version is verified to start; wrapper trims stale snapshots older than 2. |
| R7 | User on non-systemd Linux | Medium | Low | Detection + friendly error pointing to Docker. Logged but not blocking the install attempt. |

## Out of Scope (linked follow-ups)

- **v2**: GitHub release workflow with curated `SHA256SUMS` and per-version checksums.
- **v2**: Auto-rollback on update health-check failure (poll `/health` for 10s after restart; on failure, swap `app/` <-> `app.prev/`).
- **v3**: GPG signature verification of release tarballs.
- **v3**: Optional symlink placement in `~/bin/` for users without `~/.local/bin/` on `PATH`.

## Estimated Size

| Artifact | Lines |
|----------|------:|
| `scripts/install.sh` | ~300 |
| `scripts/kiro-gateway` (wrapper) | ~150 |
| `scripts/system/kiro-gateway.plist` | ~30 |
| `scripts/system/kiro-gateway.service` | ~25 |
| `tests/scripts/test_install.sh` | ~200 |
| Docs (`README.md` install section + `docs/install.md`) | ~80 |
| **Total** | **~785** |

Single PR is the right shape here — the four artifacts are tightly coupled (the wrapper references the plist path, the install.sh references the wrapper, the plist references the venv path). Splitting would create review confusion for a change that lands or fails as a unit.

## Success criteria

- [ ] `curl -fsSL .../install.sh | bash -s -- install` succeeds on a fresh macOS 14 box and a fresh Ubuntu 24.04 box, ending with a registered-but-stopped service.
- [ ] `kiro-gateway start` brings the gateway up; `kiro-gateway status` reports it running and healthy; `kiro-gateway stop` brings it down.
- [ ] After a clean install, `launchctl list | grep kiro-gateway` shows PID `-` (registered, not running) on macOS, and `systemctl --user status kiro-gateway` shows `inactive (dead)` on Linux.
- [ ] After reboot, the service is **not** running on either platform.
- [ ] `kiro-gateway update` swaps in a new version atomically; `kiro-gateway update --rollback` restores the previous version.
- [ ] `kiro-gateway uninstall` removes the plist, the unit, the symlink, and (after a confirm prompt) the install dir.
- [ ] `state/` is `chmod 700`; `.env` and `credentials.json` are `chmod 600`; `logs/` is `chmod 750`.
- [ ] No new Python or JS dependencies introduced.

## Next Phase

`sdd-spec` (4 capability delta specs: `installer-script`, `lifecycle-wrapper`, `service-management`, `source-distribution`).
