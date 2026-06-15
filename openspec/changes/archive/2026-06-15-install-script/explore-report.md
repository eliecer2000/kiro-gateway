# Explore Report — install-script for kiro-gateway

## Status
exploration_complete

## Executive Summary

The user wants a one-liner `curl | bash` installer for kiro-gateway that detects the host OS, validates prerequisites (Python 3.10+, curl/git, disk), creates a virtualenv with `requirements.txt`, installs the app as a managed service (launchd on macOS, systemd --user on Linux) at a HIDDEN install location (XDG / `Library/Application Support`), and ships with lifecycle subcommands (`start`/`stop`/`restart`/`status`/`logs`/`update`/`uninstall`). The service must be installed but explicitly **not** start on reboot — the user invokes `kiro-gateway start` when they want it running. The current install path (`git clone` + `pip install` + `cp .env.example` + `python main.py`) drops files into a visible folder and leaves no service, which is the gap this change fills.

The reference shape is gentle-ai's one-liner — same OS/arch detection, same `set -euo pipefail` strictness, same `sha256sum` verification, same fail-closed defaults with `--insecure` escape hatch. The reference diverges in two important ways: (1) gentle-ai installs a Go binary into `/usr/local/bin` and manages no service; (2) kiro-gateway is a Python venv + app-tree that needs runtime state (`credentials.json`, `state.json`, `.env`) co-located with the install. The new script will look like gentle-ai's at the top (preflight, platform detect, color setup) but must grow a venv bootstrap, a state-dir layout, and a service-manager step.

The recommended distribution model is a **source tarball from GitHub Releases** (`kiro-gateway-${VERSION}.tar.gz`), not a git clone — the user said "no git clone in $HOME" and a release tarball is deterministic and version-pinned.

## Current State (friction points)

- No service: process dies when terminal closes
- System pip errors on modern Python (PEP 668)
- State files at CWD (not chmod'd)
- Logs to stderr only
- No uninstall path
- Docker works but user wants non-Docker

## Target State (one-liner)

`curl -fsSL https://raw.githubusercontent.com/Jwadow/kiro-gateway/main/scripts/install.sh | bash -s -- install`

## Findings (the 7 the proposal must address)

1. **Service manager per platform**: launchd (macOS) plist in `~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist` with `RunAtLoad=false`; systemd --user unit (Linux) in `~/.config/systemd/user/kiro-gateway.service` NOT enabled.
2. **Hidden install location**: macOS `${HOME}/Library/Application Support/KiroGateway/`, Linux `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/`. Layout: `app/`, `venv/`, `bin/`, `state/` (chmod 700), `logs/`.
3. **Source distribution**: GitHub Releases tarball + SHA256SUMS (preferred) OR auto-generated source tarball fallback.
4. **Pre-flight validation**: OS, Python ≥3.10, curl, tar, disk ≥200MB, network.
5. **"Stopped after reboot"**: launchd `RunAtLoad=false` + `launchctl bootstrap` (not `load -w`); systemd `WantedBy=default.target` but `daemon-reload` only (no `enable`).
6. **Update and uninstall**: `kiro-gateway update` (atomic extract to `app.new/`, hash-check requirements.txt, reload); `kiro-gateway uninstall` (bootout, remove plist/unit, prompt for install dir).
7. **Security**: HTTPS only, SHA256, chmod 600 on `.env`/`credentials.json`, chmod 700 on state dir, abort on `EUID 0`, `set -euo pipefail`, no `eval`.

## Risks (top 3)

- `launchctl load -w` silently flips `RunAtLoad=true` and breaks the "stopped after reboot" contract
- PEP 668 errors if venv is not used
- Running installer with sudo creates root-owned state the service can't write to

## Open Questions (the proposal must resolve)

- Q1: Tarball source — release workflow vs auto-generated GitHub archive? → RESOLVE: **auto-generated GitHub archive** for v1 (no release workflow required, one less moving piece); promote to release tarball in v2.
- Q2: Auto-rollback on update? → RESOLVE: v1 ships with manual rollback (`update --rollback`); v2 adds auto-rollback.
- Q3: Pre-existing install handling? → RESOLVE: prompt with `(r)einstall / (u)pdate / (a)bort / (c)ustom path`.
- Q4: Wrapper path — symlink in `~/.local/bin/` plus canonical `${INSTALL_DIR}/bin/`. → RESOLVE: yes to both.
- Q5: Non-systemd Linux distros? → RESOLVE: detect, refuse with friendly message, recommend Docker.
