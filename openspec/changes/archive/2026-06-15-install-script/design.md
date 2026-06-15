# Design: install-script

- **Change:** `install-script`
- **Status:** design_complete
- **Risk:** Medium
- **Capabilities covered:** `installer-script`, `lifecycle-wrapper`, `service-management`, `source-distribution`
- **Stack context:** Python 3.10+ venv, POSIX shell (bash 3.2+ / zsh 5+), launchd (macOS) / systemd --user (Linux), no new Python or JS dependencies

## Context

The current install path (`git clone` + `pip install` + `cp .env.example` + `python main.py`) leaves users with a visible folder, no service, no lifecycle, no logs, no uninstall, and a process that dies when the terminal closes (problem statement in `proposal.md`). This change ships a one-liner `curl | bash` installer plus a `kiro-gateway` lifecycle wrapper plus platform service templates, backed by a hidden XDG-compliant install directory and SHA256-verified source fetch from a pinned GitHub release tag.

The end state: a user runs `curl -fsSL .../install.sh | bash -s -- install` on macOS or Linux and finishes with a registered-but-stopped service managed by `kiro-gateway {start|stop|restart|status|logs|update|uninstall|version|help}`. The service is intentionally **not** autostarted on reboot.

## Goals / non-goals

**Goals.** One-liner install on macOS 13+ (Intel + Apple Silicon) and systemd Linux (glibc). Hidden install root with restrictive permissions on state files. Service registered but not autostarted. SHA256-verified HTTPS source fetch, fail-closed. Atomic update with manual rollback. Clean uninstall that removes the unit/agent, the wrapper, the symlink, and (after confirm) the install dir. Test coverage in strict TDD red-green-refactor order for every behavior in the 4 capability specs.

**Non-goals (v1).** Auto-update. Multi-user / system-wide install. Windows native. Non-systemd Linux (Alpine, Void, NixOS, etc.). Curated release tarball with `SHA256SUMS` (use auto-generated GitHub archive; v2 promotes). GPG signature verification. Auto-rollback on health-check failure. Replacing the existing `git clone` install path (stays supported; installer is additive).

## Architecture overview

```
                curl -fsSL .../install.sh | bash -s -- install
                                       |
                                       v
              +-------------------------------------------------------+
              |              scripts/install.sh (~300 LOC)            |
              |  preflight (OS, Python, network, EUID, disk)           |
              |  version resolve (--version X.Y.Z | latest from API)   |
              |  fetch tarball  (curl --proto =https --tlsv1.2)        |
              |  sha256 verify  (fail-closed | --insecure escape)      |
              |  extract -> ${INSTALL_DIR}/app.new/  (atomic rename)    |
              |  strip excludes (.git, tests, docs, .github)           |
              |  venv bootstrap / refresh  (requirements.sha256 gate)  |
              |  write state/  (chmod 700, .env 600, credentials 600)   |
              |  render + install service template (plist | unit)      |
              |  load with launchctl bootstrap | systemctl daemon-reload|
              |  post-install summary + "not running" verification     |
              +-------------------------------------------------------+
                          |                       |
                          v                       v
        ${INSTALL_DIR}/bin/kiro-gateway    ${INSTALL_DIR}/state/install.env
                          |
                          v
              +-------------------------------------------------------+
              |          scripts/kiro-gateway wrapper (~150 LOC)      |
              |  resolves real path -> reads state/install.env         |
              |  dispatch start|stop|restart|status|logs|              |
              |           update [--rollback]|uninstall|version|help   |
              |  platform: uname -s -> launchctl | systemctl --user    |
              |  status: 5s /health probe (curl)                       |
              |  update: app/ -> app.prev/; fetch+extract+swap+reload  |
              |  uninstall: stop + remove unit + symlink + prompt dir  |
              +-------------------------------------------------------+
                          |
                          v
              +-------------------------------------------------------+
              |   launchd plist (macOS)  |  systemd --user unit (Linux)|
              |   RunAtLoad=false        |  WantedBy=default.target     |
              |   KeepAlive=false        |  (never enable'd)            |
              |   ProgramArguments:      |  ExecStart:                  |
              |     ${INSTALL_DIR}/      |    ${INSTALL_DIR}/           |
              |     venv/bin/python      |    venv/bin/python main.py   |
              |     main.py              |                              |
              |   WorkingDirectory:      |  WorkingDirectory:           |
              |     ${INSTALL_DIR}/state |    ${INSTALL_DIR}/state      |
              +-------------------------------------------------------+
                          |
                          v
                     python main.py (FastAPI/uvicorn on :8000)
```

## Component design

### 1. `installer-script` capability

**File: `scripts/install.sh`** (new, ~300 LOC, POSIX bash, `set -euo pipefail`).

**Layout produced by the installer:**

```
${INSTALL_DIR}/                     # macOS: ~/Library/Application Support/KiroGateway/
├── app/                            # Linux: ${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/
│   ├── kiro_gateway/               # extracted source (with .git, tests, docs, .github stripped)
│   ├── requirements.txt
│   └── main.py
├── app.prev/                       # present only after first update; removed on healthy start
├── venv/                           # PEP 668 isolation
│   └── bin/python -> python3
├── bin/
│   └── kiro-gateway                # wrapper, also symlinked from ~/.local/bin/kiro-gateway
├── state/                          # chmod 700
│   ├── install.env                 # INSTALL_DIR, VERSION, PLATFORM, INSTALLED_AT
│   ├── requirements.sha256         # hash of requirements.txt at last install
│   ├── .env                        # chmod 600; copied from app/.env.example if present
│   ├── credentials.json            # chmod 600; created empty if missing
│   └── state.json                  # chmod 600
└── logs/                           # chmod 750
    └── kiro-gateway.log
```

**Key functions in `install.sh` (one function per concern, sourced in order):**

| Function | Purpose | Failure mode |
|----------|---------|--------------|
| `preflight_euid` | Abort immediately if `EUID=0` | exit 1, "Do not run with sudo." |
| `preflight_os` | Accept `Darwin` or `Linux`; reject Windows/BSD/other | exit 1, platform-specific message |
| `preflight_python` | Find `python3` on `PATH` or `command -v python3.10..3.13`; require `>=3.10` | exit 1, exact message from spec T-1.5 |
| `preflight_tools` | `command -v curl tar`; both required | exit 1, "curl/tar not found" |
| `preflight_disk` | `df -k ${INSTALL_DIR_PARENT}`; require `>=200*1024` KiB | exit 1, "need 200MB free" |
| `preflight_network` | `curl --proto =https -sI -o /dev/null -w '%{http_code}' https://github.com`; require `200\|301\|302` | exit 1, "Cannot reach github.com" |
| `preflight_systemd` (Linux only) | `command -v systemctl` and `systemctl --user show-environment` returns 0 | exit 1, recommend Docker |
| `setup_color` | Detect `isatty(stdout)`; set `RED/GREEN/YELLOW/BOLD/RESET`; force no-color when piped | always safe |
| `resolve_version` | `GET https://api.github.com/repos/Jwadow/kiro-gateway/releases/latest` -> `tag_name` strip `v`; override via `--version X.Y.Z`; reject non-`vX.Y.Z` shape | exit 1, "invalid version" |
| `detect_install_dir` | macOS: `$HOME/Library/Application Support/KiroGateway`; Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway`; override via `--install-dir PATH` | exit 1 if parent not writable |
| `check_preexisting` | `${INSTALL_DIR}/state/install.env` exists -> interactive prompt `(r)einstall / (u)pdate / (a)bort / (c)ustom path`; default to abort on empty input | exits 0 on `a`, hands off to update on `u`, restarts install on `r`, restarts detect_install_dir on `c` |
| `fetch_tarball` | `curl --proto =https --tlsv1.2 -fsSL -o ${TARBALL} ${URL}` with `-E` and `-w`; never `http://`; refuse downgrade | exit 1 on network/HTTP error |
| `verify_sha256` | Compute `sha256sum ${TARBALL}`; compare against `SHA256SUMS` (v2 only). v1: if `SHA256SUMS` URL is 404 -> exit 1 with the exact message from spec T-4.3, unless `--insecure` is passed (then print warning) | exit 1 by default |
| `extract_atomic` | `mkdir -p ${INSTALL_DIR}/app.new`; `tar -xzf ${TARBALL} -C ${INSTALL_DIR}/app.new --strip-components=1`; `rm -rf .git tests docs .github`; `mv ${INSTALL_DIR}/app ${INSTALL_DIR}/app.prev 2>/dev/null`; `mv ${INSTALL_DIR}/app.new ${INSTALL_DIR}/app` | `trap` on EXIT removes `app.new/` on failure |
| `venv_bootstrap_or_refresh` | Compute SHA256 of `requirements.txt`; compare to `${INSTALL_DIR}/state/requirements.sha256`; on match: `venv` untouched; on mismatch or fresh install: `python3 -m venv ${INSTALL_DIR}/venv` + `${INSTALL_DIR}/venv/bin/pip install --upgrade pip` + `pip install -r requirements.txt` | exit 1 on venv failure |
| `lay_out_state` | `mkdir -p ${INSTALL_DIR}/{bin,state,logs}`; `chmod 700 state`; `chmod 750 logs`; `cp app/.env.example state/.env` if present; `chmod 600 state/.env state/credentials.json state/state.json`; `touch state/credentials.json state/state.json` | exit 1 on `chmod` failure |
| `render_and_install_service` | Pick template (`scripts/system/kiro-gateway.plist` for Darwin, `.service` for Linux); substitute `${INSTALL_DIR}` and `${HOME}`; install to platform path; load with `launchctl bootstrap gui/$(id -u) <plist>` or `systemctl --user daemon-reload` (NEVER `load -w` / `enable`) | exit 1 on platform command failure |
| `write_install_env` | Write `INSTALL_DIR`, `VERSION`, `PLATFORM`, `INSTALLED_AT=$(date -u +%FT%TZ)` to `${INSTALL_DIR}/state/install.env` | exit 1 on write failure |
| `install_symlink` | `mkdir -p ~/.local/bin`; `ln -sf ${INSTALL_DIR}/bin/kiro-gateway ~/.local/bin/kiro-gateway` | exit 1 if symlink fails |
| `post_install_summary` | Print install path, wrapper path, next steps, **explicit "Service is registered but not running"** message; verify `launchctl list` shows PID `-` (macOS) or `systemctl --user status` shows `inactive (dead)` (Linux) | non-fatal: warn if verification fails |

**Traps and error model.**

- `trap 'rm -rf "${INSTALL_DIR}/app.new" "${TARBALL}"' EXIT` — clean up partial state on any failure.
- `set -euo pipefail` is the first non-comment line.
- Color codes are guarded by `[[ -t 1 ]]`; piped-from-curl always disables color (so logs are clean).
- `--insecure` is the single explicit escape hatch for SHA256 verification; it is the only path that proceeds without `SHA256SUMS` in v1.
- `--help` and `--version` exit 0 and never reach preflight.

**Argument parsing** (long-form only; matches gentle-ai's idiom):

```
bash install.sh [--help | -h] \
                [--version X.Y.Z] \
                [--install-dir PATH] \
                [--insecure] \
                [install | update | uninstall | --rollback]
```

The default subcommand is `install` if none is given (so the one-liner is `... | bash` with no args).

**Self-update hook.** The installer does NOT self-update; `kiro-gateway update` reuses the same fetch path (`fetch_tarball` + `verify_sha256` + `extract_atomic` are all sourced from a shared `scripts/lib/install-common.sh`, see component 4). This is the only way the two entry points stay in sync.

**Uninstall hook.** `kiro-gateway uninstall` is the only sanctioned removal path (calls `uninstall_service` + `remove_symlink` + `remove_install_dir` from the shared lib). `install.sh` does NOT remove a previous install; the pre-existing-install prompt is the contract.

### 2. `lifecycle-wrapper` capability

**File: `scripts/kiro-gateway`** (new, ~150 LOC, POSIX bash, `set -euo pipefail`).

**Path resolution.** On every invocation, the wrapper resolves its own real path with `readlink -f "$0" || realpath "$0"`, so it works whether invoked via:
- `${INSTALL_DIR}/bin/kiro-gateway` (canonical)
- `~/.local/bin/kiro-gateway` (symlink)

It then derives `${INSTALL_DIR}` as `$(dirname $(dirname $REAL))` and sources `${INSTALL_DIR}/state/install.env` for `INSTALL_DIR`, `VERSION`, `PLATFORM`. If `install.env` is missing, it prints the one-liner install command and exits 1 (spec T-2.6).

**Subcommand dispatcher (single `case` on `${1:-help}`):**

| Subcommand | Platform dispatch | Implementation |
|------------|-------------------|----------------|
| `start` | macOS: `launchctl bootstrap gui/$(id -u) ${HOME}/Library/LaunchAgents/com.jwadow.kiro-gateway.plist`; Linux: `systemctl --user start kiro-gateway` | exit 0 on success |
| `stop` | macOS: `launchctl bootout gui/$(id -u)/com.jwadow.kiro-gateway`; Linux: `systemctl --user stop kiro-gateway` | exit 0 on success |
| `restart` | `stop` then `start`; `set +e` around stop (it can fail if not running) | exit code from `start` |
| `status` | `launchctl list \| grep com.jwadow.kiro-gateway` (macOS) or `systemctl --user is-active kiro-gateway` (Linux); then `curl --proto =https -fsS --max-time 5 http://localhost:8000/health` | exit 0 only when active AND health 2xx; else exit 1 with hint to run `kiro-gateway logs` |
| `logs` | `tail -f ${INSTALL_DIR}/logs/kiro-gateway.log` | passthrough |
| `update` | source `scripts/lib/install-common.sh`; call `fetch_tarball` + `verify_sha256` + `extract_atomic` (preserves `state/`); `venv_bootstrap_or_refresh`; `systemctl --user daemon-reload` / `launchctl bootout && launchctl bootstrap` | exit 1 on any failure |
| `update --rollback` | reverse `app/` and `app.prev/`; reload service | exit 1 if `app.prev/` missing (spec T-4.10) |
| `uninstall` | `stop`; `launchctl bootout gui/$(id -u)/com.jwadow.kiro-gateway && rm ${HOME}/Library/LaunchAgents/com.jwadow.kiro-gateway.plist` (macOS) or `systemctl --user disable --now kiro-gateway && rm ~/.config/systemd/user/kiro-gateway.service && systemctl --user daemon-reload` (Linux); `rm ~/.local/bin/kiro-gateway`; prompt `Remove install dir ${INSTALL_DIR}? [y/N]`; on `y` `rm -rf ${INSTALL_DIR}`; on `N` preserve | exit 0 in both paths |
| `version` | `cat ${INSTALL_DIR}/state/install.env \| grep VERSION` | exit 0 |
| `help` / `--help` / (none) | print usage to stdout listing all subcommands with one-line description | exit 0 |

**Health probe on `status` (spec T-2.3).** The probe uses `curl --max-time 5 --proto =https`; it is a local loopback URL so the HTTPS-only flag is essentially a no-op but keeps the gate consistent. A 2xx response plus an active service manager status yields `running (healthy)`. A non-2xx or timeout yields `running (unhealthy)` (if the service is active) or `stopped` (if not), with exit 1 and a hint.

**Snapshot cleanup on `update` (spec T-4.11, T-4.12).** After a successful `mv ${INSTALL_DIR}/app.new ${INSTALL_DIR}/app` and a service restart, the wrapper polls `GET /health` for up to 10 seconds. If 2xx: `rm -rf ${INSTALL_DIR}/app.prev` and print `Update successful. Old version removed.`. If not 2xx: print the hint and preserve `app.prev/`.

### 3. `service-management` capability

**Files: `scripts/system/kiro-gateway.plist` (new, macOS) and `scripts/system/kiro-gateway.service` (new, Linux).**

**macOS plist template (rendered with `sed` substitution of `${INSTALL_DIR}` and `${HOME}`):**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.jwadow.kiro-gateway</string>
  <key>ProgramArguments</key>
  <array>
    <string>${INSTALL_DIR}/venv/bin/python</string>
    <string>main.py</string>
  </array>
  <key>WorkingDirectory</key> <string>${INSTALL_DIR}/state</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KIRO_GATEWAY_HOME</key>     <string>${INSTALL_DIR}</string>
    <key>ACCOUNTS_CONFIG_FILE</key>  <string>${INSTALL_DIR}/state/credentials.json</string>
    <key>ACCOUNTS_STATE_FILE</key>   <string>${INSTALL_DIR}/state/state.json</string>
  </dict>
  <key>RunAtLoad</key>      <false/>
  <key>KeepAlive</key>      <false/>
  <key>StandardOutPath</key> <string>${INSTALL_DIR}/logs/kiro-gateway.log</string>
  <key>StandardErrorPath</key><string>${INSTALL_DIR}/logs/kiro-gateway.log</string>
  <key>ProcessType</key>    <string>Background</string>
</dict>
</plist>
```

**Linux systemd --user unit template:**

```ini
[Unit]
Description=Kiro Gateway (proxy for Kiro API)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/.local/share/kiro-gateway/state
ExecStart=%h/.local/share/kiro-gateway/venv/bin/python main.py
Environment=KIRO_GATEWAY_HOME=%h/.local/share/kiro-gateway
Environment=ACCOUNTS_CONFIG_FILE=%h/.local/share/kiro-gateway/state/credentials.json
Environment=ACCOUNTS_STATE_FILE=%h/.local/share/kiro-gateway/state/state.json
StandardOutput=append:%h/.local/share/kiro-gateway/logs/kiro-gateway.log
StandardError=append:%h/.local/share/kiro-gateway/logs/kiro-gateway.log

[Install]
WantedBy=default.target
```

(The installer substitutes `${INSTALL_DIR}` and `%h` in the unit before writing it. `WantedBy=default.target` is present so a user who *manually* runs `systemctl --user enable` gets the desired behavior — but the installer never invokes `enable`.)

**Static gates (CI).** Two `rg` static checks at lint time:
- `rg 'load -w' scripts/install.sh scripts/kiro-gateway` must return zero matches.
- `rg 'systemctl .* enable' scripts/install.sh scripts/kiro-gateway` must return zero matches.

These are part of the bash test suite (T-3.3, T-3.4).

**Stopped-after-reboot verification.** A `verify_not_running` function in the shared lib:
- macOS: `launchctl print gui/$(id -u)/com.jwadow.kiro-gateway | awk '/state =/ {print $3}' | grep -q '^waiting$'` (after `bootstrap` but before `start`, the state is `waiting`).
- Linux: `systemctl --user is-active kiro-gateway` returns `inactive`.

This is called in `post_install_summary` and the result is in the printed summary.

**Log rotation hook.** No automated rotation in v1. The `logs/` dir is `chmod 750` and lives on the user's filesystem; users on macOS get `newsyslog` if they want it, Linux users can drop a `logrotate` config in `~/.config/logrotate.d/`. v2 may add a built-in `logrotate` template. (Documented in `docs/install.md` as a v2 note.)

### 4. `source-distribution` capability

**Files: `scripts/lib/install-common.sh` (new, shared) + `pyproject.toml` (existing, possibly extended).**

The shared lib is the SINGLE source of truth for:
- `preflight_*` (installer-only; `update` skips)
- `setup_color`
- `resolve_version`
- `detect_install_dir`
- `check_preexisting` (installer-only)
- `fetch_tarball`
- `verify_sha256`
- `extract_atomic`
- `strip_excludes` (`.git`, `tests`, `docs`, `.github`)
- `venv_bootstrap_or_refresh`
- `lay_out_state`
- `render_service_template` (pick plist vs unit, substitute vars)
- `load_service` (the `bootstrap` / `daemon-reload` step)
- `uninstall_service`
- `remove_symlink`
- `verify_not_running`

Both `scripts/install.sh` and `scripts/kiro-gateway` source this lib via a relative path resolved with `readlink -f`.

**Tarball URL.** `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz`. Default version is `latest` resolved via `https://api.github.com/repos/Jwadow/kiro-gateway/releases/latest` -> `tag_name` stripped of `v`.

**Source distribution decision: do NOT ship a curated release tarball in v1.** Rationale (ADR-1 below). v2 will add a release workflow that publishes `SHA256SUMS` next to a curated `kiro-gateway-${VERSION}.tar.gz` (a `git archive`-style tarball without `.git/`, `tests/`, `docs/`, `.github/` baked in). v1 lives with the auto-generated archive and the excludes step.

**Checksum + signing decision.** v1: SHA256 verification is fail-closed when `SHA256SUMS` is unreachable; `--insecure` is the explicit escape hatch. v3: GPG signature verification. v1 explicitly does NOT publish `SHA256SUMS` for the auto-generated archive (GitHub's archive hash is deterministic per tag but the user is expected to either trust GitHub's TLS or use `--insecure` once).

**Excludes step (spec T-4.5).** After extraction to `${INSTALL_DIR}/app.new/`, the wrapper removes:
- `${INSTALL_DIR}/app.new/.git`
- `${INSTALL_DIR}/app.new/tests`
- `${INSTALL_DIR}/app.new/docs`
- `${INSTALL_DIR}/app.new/.github`

The presence of `LICENSE` (or `LICENSE.md`) is asserted in T-4.5.

**Requirements hash trigger (spec T-4.7, T-4.8).** `${INSTALL_DIR}/state/requirements.sha256` holds the SHA256 of the `requirements.txt` from the last install. The venv refresh decision is:
- Fresh install (file missing): always bootstrap.
- Update: compute new hash; if equal -> venv untouched; if different -> remove `venv/`, bootstrap fresh, store new hash.

**Where the tarball lives on the install-server.** v1: GitHub Releases (auto-generated, no server-side work). v2: a curated `kiro-gateway-${VERSION}.tar.gz` attached to the same GitHub Release, with `SHA256SUMS` next to it. The installer URLs change in v2; the wrapper's `fetch_tarball` is the only call site that needs to be updated.

## Data flow: `curl ... | bash -s -- install` step-by-step

1. **Browser shell.** User runs `curl -fsSL https://raw.githubusercontent.com/Jwadow/kiro-gateway/main/scripts/install.sh | bash -s -- install`. Curl fetches `install.sh` over HTTPS and pipes to bash.
2. **Bash receives the script on stdin.** The `curl | bash` pattern means the script's parent process is `curl`; stdout is the user's terminal (color enabled), stdin is `bash`'s inherited tty (interactive prompts work).
3. **`set -euo pipefail`** is set immediately.
4. **`preflight_euid`** aborts if `EUID=0`. Message: `Do not run this installer with sudo. Re-run as your normal user.`
5. **`setup_color`** detects `isatty(stdout)`. If false, all color escapes are stripped.
6. **Argument parse.** `install` is the default subcommand; the user did not pass `--help`, `--version`, or `--install-dir`. Args after the subcommand: none.
7. **Preflight sequence** runs: `preflight_os`, `preflight_python`, `preflight_tools`, `preflight_disk`, `preflight_network`, `preflight_systemd` (Linux). On any failure: print actionable error and exit 1.
8. **`resolve_version`** queries `https://api.github.com/repos/Jwadow/kiro-gateway/releases/latest`. (v1 uses the JSON API even though it adds a request; this is the only way to resolve `latest` to a pinned tag without scraping HTML.) Returns e.g. `2.5.0`.
9. **`detect_install_dir`** computes the platform default. macOS: `$HOME/Library/Application Support/KiroGateway/`. Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/`.
10. **`check_preexisting`** checks for `${INSTALL_DIR}/state/install.env`. Absent on fresh install: skip. Present: prompt `(r)einstall / (u)pdate / (a)bort / (c)ustom path` (default `a` on empty).
11. **`fetch_tarball`** downloads `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v2.5.0.tar.gz` to `${TMPDIR}/kiro-gateway-2.5.0.tar.gz` with `curl --proto =https --tlsv1.2 -fsSL`.
12. **`verify_sha256`** attempts to fetch `https://github.com/Jwadow/kiro-gateway/releases/download/v2.5.0/SHA256SUMS`. v1: 404 -> exit 1 with `No SHA256SUMS available. Re-run with --insecure to skip verification.` unless `--insecure` is passed.
13. **`extract_atomic`** extracts to `${INSTALL_DIR}/app.new/`, runs `strip_excludes`, then `mv ${INSTALL_DIR}/app ${INSTALL_DIR}/app.prev 2>/dev/null || true` + `mv ${INSTALL_DIR}/app.new ${INSTALL_DIR}/app`. Failure path: `trap` removes `app.new/` and the tarball.
14. **`venv_bootstrap_or_refresh`** computes hash of `${INSTALL_DIR}/app/requirements.txt`. Fresh install: bootstrap venv. On update with changed hash: recreate. Stores hash in `${INSTALL_DIR}/state/requirements.sha256`.
15. **`lay_out_state`** creates `bin/`, `state/` (chmod 700), `logs/` (chmod 750). Copies `app/.env.example` to `state/.env` if present. Touches `state/credentials.json` and `state/state.json`. Chmods 600 on `.env`, `credentials.json`, `state.json`.
16. **`render_and_install_service`** picks the template, substitutes `${INSTALL_DIR}` (and `%h` in the systemd unit), writes to the platform path, and loads: `launchctl bootstrap gui/$(id -u) <plist>` (macOS) or `systemctl --user daemon-reload` (Linux). NEVER `launchctl load -w` or `systemctl --user enable`.
17. **`write_install_env`** writes `INSTALL_DIR`, `VERSION`, `PLATFORM`, `INSTALLED_AT` to `${INSTALL_DIR}/state/install.env`.
18. **`install_symlink`** creates `~/.local/bin/kiro-gateway -> ${INSTALL_DIR}/bin/kiro-gateway`.
19. **`post_install_summary`** prints:
    - Install path: `${INSTALL_DIR}`
    - Wrapper: `${INSTALL_DIR}/bin/kiro-gateway` (also `~/.local/bin/kiro-gateway`)
    - Service label / unit
    - "Service is registered but not running. Run: kiro-gateway start"
    - Verification line: `launchctl list | grep com.jwadow.kiro-gateway` shows PID `-` (macOS) or `systemctl --user status kiro-gateway` is `inactive (dead)` (Linux).
20. **`trap`** removes the tarball from `${TMPDIR}`. `app.new/` does not exist (renamed in step 13). Exit 0.

## Cross-platform handling

| Concern | macOS | Linux |
|---------|-------|-------|
| Install dir | `$HOME/Library/Application Support/KiroGateway/` | `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/` |
| Service file | `~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist` | `~/.config/systemd/user/kiro-gateway.service` |
| Service load | `launchctl bootstrap gui/$(id -u) <plist>` | `systemctl --user daemon-reload` |
| Service start | `launchctl bootstrap gui/$(id -u) <plist>` | `systemctl --user start kiro-gateway` |
| Service stop | `launchctl bootout gui/$(id -u)/com.jwadow.kiro-gateway` | `systemctl --user stop kiro-gateway` |
| Service status | `launchctl print gui/$(id -u)/com.jwadow.kiro-gateway` | `systemctl --user is-active kiro-gateway` |
| Shell | bash 3.2+ (system default) | bash 4+ (most distros) |
| `readlink -f` | available on BSD `readlink` only since macOS 12 | GNU `readlink -f` |
| `stat` mode | `stat -f '%Lp' PATH` | `stat -c '%a' PATH` |
| `df` free check | `df -k PARENT \| awk 'NR==2{print $4}'` (KiB) | same |
| `date -u +%FT%TZ` | works on BSD date too | works |

**`readlink -f` portability.** macOS's BSD `readlink` did not support `-f` until Monterey (12.0). For broader compatibility, the wrapper falls back: `readlink -f "$0" 2>/dev/null || (cd $(dirname "$0") && pwd)/$(basename "$0")`. This is the only platform-specific shim the wrapper needs.

**Shell quirks.** The installer and wrapper are tested with bash 3.2 (macOS system), bash 5.x (Linux), and zsh 5.x (only via `bash` shebang — both scripts use `#!/usr/bin/env bash` so the user's interactive shell does not matter). They avoid bashisms like `[[ -v name ]]` and use `[[ -n "${name:-}" ]` instead.

**PATH assumptions.** The wrapper assumes `~/.local/bin` is on `PATH` (XDG default). If not, the post-install summary prints a hint to add it. The wrapper is also reachable at its canonical path, so the symlink is a convenience, not a requirement.

## Security & integrity

| Concern | Mitigation |
|---------|-----------|
| Plaintext HTTP downgrade | Every `curl` invocation includes `--proto =https --tlsv1.2`. A downgrade attempt is rejected by curl. Static gate: T-1.11. |
| Tarball tampering | SHA256 verification is fail-closed in v1; `SHA256SUMS` is the only authoritative source. `--insecure` is the explicit escape hatch and prints a warning. |
| `eval` of downloaded content | The script body is fetched by `curl`; bash interprets the script, not the result of any subcommand. `rg 'eval\b' install.sh` returns no matches (AC-1.D). |
| Running as root | `preflight_euid` aborts at the very top of the script. Tested in T-1.7. |
| World-readable state | `state/` is `chmod 700`, `.env` and `credentials.json` are `chmod 600`, `logs/` is `chmod 750`. Tested in T-3.7, T-3.8, T-3.9. |
| Service runs as the right user | launchd plist inherits the user's session (no `UserName` key); systemd --user unit runs as the user's session. No `sudo` at runtime. |
| `set -euo pipefail` discipline | First non-comment line of every script. Treated as a precondition by every test. |
| Trapping partial installs | `trap 'rm -rf "${INSTALL_DIR}/app.new" "${TARBALL}"' EXIT` ensures no half-extracted state survives. |
| Health endpoint spoofing | The status health probe uses loopback (`http://localhost:8000/health`); no external exposure. |
| Logs leaking credentials | The plist and unit route stdout/stderr to `logs/kiro-gateway.log` (chmod 750 dir). `credentials.json` is never logged (verified by the existing logging discipline in `kiro_gateway`). |
| Principle of least privilege | User-level service (LaunchAgent / systemd --user). No system-wide plist/unit. No `sudo` after install. No setuid binaries. |

## Error handling & idempotency

| Scenario | Behavior |
|----------|----------|
| Run installer twice on a healthy install | `check_preexisting` finds `state/install.env`; prompts `(r/u/a/c)`; default `a` (abort) on empty input. No files modified. Tested T-1.12. |
| Network failure during fetch | `curl -fsSL` fails non-zero on HTTP errors; `set -e` exits. `trap` cleans `app.new/` and tarball. User sees curl error. |
| Corrupt tarball | `tar -xzf` fails; `set -e` exits; `trap` cleans. `app/` and `app.prev/` are untouched. Tested T-1.10. |
| Python 3.9 or older | `preflight_python` exits with the exact error string. Tested T-1.5. |
| No systemd on Linux | `preflight_systemd` exits with the Docker recommendation. No state dir is created. Tested T-3.10. |
| `EUID=0` | `preflight_euid` exits immediately. Tested T-1.7. |
| Failed `pip install` in venv | `set -e` exits; install dir is partially created; user can re-run; `check_preexisting` will prompt (default abort). State is not corrupted because `state/.env` etc. are only written after venv bootstrap succeeds. |
| `update` with no `app.prev/` | `update --rollback` exits non-zero with `No previous version to roll back to.` Tested T-4.10. |
| `update` with changed `requirements.txt` | venv is recreated; service is reloaded. Tested T-4.8. |
| `update` with unchanged `requirements.txt` | venv is untouched. Tested T-4.7. |
| New version fails health check after update | `app.prev/` is preserved for manual rollback; hint printed. Tested T-4.12. |
| `uninstall` with `N` to "remove install dir" | Service is stopped and the unit/agent is removed; the install dir is preserved (so the user can inspect logs or recover state). |
| `uninstall` with `y` to "remove install dir" | Everything is removed, including `state/`. The user has been warned by the prompt. |

## File changes

| File | Action | Description |
|------|--------|-------------|
| `scripts/install.sh` | Create | The one-liner installer. Sources `scripts/lib/install-common.sh`. ~300 LOC. |
| `scripts/kiro-gateway` | Create | The lifecycle wrapper. Sources `scripts/lib/install-common.sh`. ~150 LOC. |
| `scripts/lib/install-common.sh` | Create | Shared functions for fetch, verify, extract, venv, state, service render/load. ~250 LOC. |
| `scripts/system/kiro-gateway.plist` | Create | launchd template. ~25 LOC. |
| `scripts/system/kiro-gateway.service` | Create | systemd --user unit template. ~20 LOC. |
| `tests/scripts/test_install.py` | Create | pytest-based tests that drive `install.sh` in a tempdir with stubbed `curl`, `uname`, `systemctl`, `launchctl`. ~200 LOC. |
| `tests/scripts/test_wrapper.py` | Create | pytest-based tests for the wrapper subcommands. ~150 LOC. |
| `tests/scripts/conftest.py` | Create | Fixtures: `temp_install_dir`, `stub_curl`, `stub_platform`. |
| `tests/scripts/fixtures/` | Create | Sample plist, sample unit, sample `state/install.env`, sample `requirements.txt`. |
| `docs/install.md` | Create | End-user install / update / uninstall walkthrough. ~80 LOC. |
| `README.md` | Modify | Replace the "git clone" section with the one-liner; keep the `git clone` section as a fallback under a heading. |
| `openspec/changes/install-script/design.md` | Create | This file. |
| `openspec/changes/install-script/tasks.md` | (sdd-tasks) | Created by the next phase. |
| `pyproject.toml` | Optional modify | Add `build` and `setuptools-scm` only if a curated sdist workflow is added in v2; v1 does NOT modify it. |

## Testing strategy

Strict TDD is active for this project. Every behavior in the 4 specs gets a test, and every test goes through **red → green → refactor**.

### Layer 1: bash syntax / lint (fast, no test framework)

- `bash -n scripts/install.sh` (AC-1.B)
- `bash -n scripts/kiro-gateway` (AC-2.B)
- `bash -n scripts/lib/install-common.sh`
- `shellcheck scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` (AC-1.C, AC-2.C) at severity `error`
- `rg 'eval\b' scripts/install.sh` returns no matches (AC-1.D)
- `rg 'load -w' scripts/install.sh scripts/kiro-gateway` returns no matches (T-3.3)
- `rg 'systemctl .* enable' scripts/install.sh scripts/kiro-gateway` returns no matches (T-3.4)
- `rg 'http://' scripts/install.sh` returns no matches (AC-4.B)

### Layer 2: bash unit tests with `pytest` + `subprocess`

`pytest` is the project's existing test runner. We drive the shell scripts via `subprocess.run` against a `temp_install_dir` fixture, with stubs in `PATH` for `uname`, `systemctl`, `launchctl`, `curl`, `python3`, and a small mock `https://api.github.com/...` responder.

Each test follows strict TDD:
1. **Red**: write the test that asserts the spec scenario (given/when/then from the spec). Run it. It fails because the function under test does not exist.
2. **Green**: implement the minimum code in `install.sh` / `kiro-gateway` / `install-common.sh` to make the test pass.
3. **Refactor**: extract duplication, rename, simplify. Re-run all tests.

### Test matrix (one pytest per spec scenario)

**`installer-script` (T-1.x).** T-1.1 fresh-macos-layout, T-1.2 fresh-linux-layout, T-1.3 help-exits-zero, T-1.4 version-pins, T-1.5 preflight-python-39, T-1.6 preflight-no-network, T-1.7 preflight-root, T-1.8 install-dir-override, T-1.9 preexisting-reinstall-preserves-state, T-1.10 atomic-extract-failure-cleans-up, T-1.11 https-only, T-1.12 idempotent-second-run.

**`lifecycle-wrapper` (T-2.x).** T-2.1 start-launchctl, T-2.2 start-systemctl, T-2.3 status-health-probe, T-2.4 update-rollback-restores-prev, T-2.5 uninstall-prompt, T-2.6 missing-install-exits-nonzero, T-2.7 help-exits-zero.

**`service-management` (T-3.x).** T-3.1 plist-renders, T-3.2 unit-renders, T-3.3 load-uses-bootstrap (static gate), T-3.4 no-enable (static gate), T-3.5 post-install-status-macos, T-3.6 post-install-status-linux, T-3.7 state-chmod-700, T-3.8 credentials-chmod-600, T-3.9 logs-chmod-750, T-3.10 non-systemd-refused.

**`source-distribution` (T-4.x).** T-4.1 default-version-latest, T-4.2 version-pins-tag, T-4.3 no-shasums-fails-closed, T-4.4 insecure-skips-verification, T-4.5 tarball-excludes-removed, T-4.6 atomic-swap-creates-app-prev, T-4.7 requirements-unchanged-preserves-venv, T-4.8 requirements-changed-recreates-venv, T-4.9 update-rollback-restores-prev, T-4.10 rollback-no-prev-fails, T-4.11 snapshot-removed-on-healthy-start, T-4.12 snapshot-preserved-on-unhealthy-start.

### Layer 3: integration tests in a container

A second suite, gated by a marker (`pytest -m integration`), runs in a Docker container (`ubuntu:24.04` for the Linux path; the macOS path is verified manually because we cannot run launchd in CI). The container:
- Stubs `github.com` with a local HTTP server (Python's `http.server`) that serves a real kiro-gateway tarball + a `SHA256SUMS` file.
- Runs the full installer end-to-end.
- Asserts the post-install state matches the spec (directory layout, permissions, service file, symlink).
- Runs `kiro-gateway start`, polls `/health`, runs `kiro-gateway stop`, runs `kiro-gateway uninstall`, asserts clean state.

This suite is opt-in (`pytest -m integration`) so the unit suite stays under 30s in CI.

### Test discipline

- Every PR opens with a failing test. No "write the code, then add a test" commits.
- The static gates (T-3.3, T-3.4, AC-1.D, AC-4.B) run on every commit, not just before merge.
- The integration suite runs on the `main` branch push and on PRs to `main`.

## Architecture decisions

### Decision: Hide the install root under `Library/Application Support` / `XDG_DATA_HOME`

**Choice.** macOS: `$HOME/Library/Application Support/KiroGateway/`. Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/`.
**Alternatives.** `~/.kiro-gateway/` (simple, hidden, but not XDG-compliant); `~/.local/opt/kiro-gateway/` (XDG-adjacent but unconventional for app data); `/opt/kiro-gateway` (system-wide, needs `sudo`).
**Rationale.** XDG Base Directory Specification is the standard for user-level app data on Linux; `Library/Application Support` is the macOS equivalent. Both keep state out of the user's CWD and out of the home directory listing.

### Decision: Auto-generated GitHub archive, not a curated release tarball (v1)

**Choice.** Source distribution in v1 is the auto-generated `https://github.com/Jwadow/kiro-gateway/archive/refs/tags/v${VERSION}.tar.gz`; the installer strips `.git/`, `tests/`, `docs/`, `.github/` post-extraction.
**Alternatives.** Curated release tarball with `SHA256SUMS` (requires a release workflow; v2); git clone (no version pinning; the user explicitly rejected this).
**Rationale.** v1 has no `SHA256SUMS` -> fail-closed by default -> `--insecure` is the explicit escape hatch. v1's `strip_excludes` step makes the auto-generated archive usable despite the noise. v2 promotes to a curated tarball with `SHA256SUMS`, which removes the need for the excludes step AND enables fail-open SHA256 verification.

### Decision: Use `readlink -f` with fallback in the wrapper

**Choice.** `readlink -f "$0" 2>/dev/null || (cd $(dirname "$0") && pwd)/$(basename "$0")`.
**Alternatives.** `realpath` (not in POSIX; not on macOS by default); a Python one-liner (overkill); `BASH_SOURCE[0]` (only works when sourced, not when invoked).
**Rationale.** macOS's BSD `readlink` did not support `-f` until Monterey (12.0). The fallback works on every POSIX system and avoids introducing a Python dependency for path resolution.

### Decision: Service is registered but not autostarted

**Choice.** `RunAtLoad=false` (launchd), `KeepAlive=false` (launchd), `WantedBy=default.target` (systemd) but NEVER `systemctl --user enable` at install time.
**Alternatives.** `RunAtLoad=true` + `launchctl load -w` (breaks the "user controls when it runs" contract; explicitly rejected by the user); `KeepAlive=true` (same problem in a different form); no service file at all (user has to manage the process themselves; loses the lifecycle story).
**Rationale.** The user said "I do not want a daemon that starts on every reboot." `WantedBy=default.target` is left in the unit for users who MANUALLY want to enable it, but the installer never runs `enable`. The static gates in T-3.3 and T-3.4 enforce this forever.

### Decision: `app.prev/` snapshot for manual rollback (v1)

**Choice.** `update` moves `app/` to `app.prev/` before swapping in `app.new/`. `update --rollback` reverses the swap. Snapshot is removed only after a healthy start, otherwise preserved.
**Alternatives.** Keep N snapshots (e.g. `app.prev.1`, `app.prev.2`) for a history of versions (more disk, more complexity); auto-rollback on health check failure (v2); no rollback (v0, unacceptable).
**Rationale.** Manual rollback is the minimum viable safety net. The snapshot is removed on healthy start to avoid disk bloat. v2 adds auto-rollback on health-check failure (already spec'd in `proposal.md`).

### Decision: Shared `scripts/lib/install-common.sh`

**Choice.** A single library file is sourced by both `install.sh` and `kiro-gateway` for fetch, verify, extract, venv, state, and service operations.
**Alternatives.** Duplicate the logic in each entry point (drift risk); write the operations in Python (extra runtime dependency); generate a single combined shell script (loses the separation of concerns).
**Rationale.** The fetch + verify + extract + venv + state pipeline is identical between install and update; duplicating it invites bugs. Sourcing the lib is the POSIX idiomatic way to share functions.

### Decision: venv bootstrap, not system pip

**Choice.** `${INSTALL_DIR}/venv/` is created with `python3 -m venv` and `pip install` runs against `${INSTALL_DIR}/venv/bin/pip`.
**Alternatives.** `pip install --user` (works on older Pythons, deprecated on modern ones; global to the user, not the install); `pipx` (extra dependency, not installed everywhere); system-wide install with `sudo` (the user explicitly rejected sudo).
**Rationale.** PEP 668 forbids system-wide `pip install` on modern Python distributions. A venv at a known path is the only zero-sudo path that works on macOS 13+ and Ubuntu 24.04 out of the box.

## Migration / compatibility

**Existing `git clone` users.** Unaffected. The `git clone` install path stays in `README.md` under a "Development install" heading. The new one-liner is the recommended path for end users.

**Existing installs in the wrong place (CWD).** Out of scope for v1. Users with an existing CWD install can `cp .env credentials.json state.json ${INSTALL_DIR}/state/` after running the one-liner, then `kiro-gateway start`. A `migrate-cwd` subcommand is a candidate v2 feature but is NOT in this change.

**Coexistence window.** The two install paths can coexist on the same machine (different install roots). v1 does NOT detect or warn about a CWD install.

**Version upgrade from a CWD install.** Manually: stop the CWD process, run the one-liner, copy the state files, `kiro-gateway start`. A `kiro-gateway import` flow is a candidate v2 feature.

**Deprecation.** None. The `git clone` path is not deprecated.

## Open questions

- [ ] **Curated `SHA256SUMS` URL for v1 fallback.** When the GitHub Releases page does not have a `SHA256SUMS` for the auto-generated archive (which is the v1 default), the installer fails closed. Should we also support fetching `SHA256SUMS` from a separate location (e.g. a dedicated S3 bucket) for v1, or accept that v1 requires `--insecure` until v2 ships the curated tarball? **Recommendation: accept the `--insecure` requirement for v1; v2 fixes this.**
- [ ] **Health endpoint path.** The wrapper probes `http://localhost:8000/health` and `main.py` is the entry point. We need to confirm the health endpoint path matches what uvicorn/FastAPI exposes. **Action for sdd-apply: read `kiro_gateway/main.py` and assert the route is `/health`. If not, update the design and the wrapper.**
- [ ] **zsh on macOS.** The scripts use `#!/usr/bin/env bash` and avoid bashisms, but they have not been tested under zsh. **Action for sdd-apply: run `shellcheck -s bash` and add a `bash -n` check; zsh is not a target.**
- [ ] **macOS BSD `date` portability.** `date -u +%FT%TZ` works on both GNU and BSD `date`. **Action for sdd-apply: smoke test on a macOS 13 runner if available; otherwise document in `docs/install.md` as a tested platform.**
- [ ] **logrotate integration.** No automated log rotation in v1. Should we ship a sample `logrotate` config in `docs/install.md` as a copy-paste, or wait for v2? **Recommendation: ship the sample in `docs/install.md` so v1 users have a one-liner.**

## References

- Proposal: `/Users/eliezerrangel/kiro-gateway/openspec/changes/install-script/proposal.md`
- Specs:
  - `openspec/changes/install-script/specs/installer-script/spec.md`
  - `openspec/changes/install-script/specs/lifecycle-wrapper/spec.md`
  - `openspec/changes/install-script/specs/service-management/spec.md`
  - `openspec/changes/install-script/specs/source-distribution/spec.md`
- Explore: `openspec/changes/install-script/explore-report.md`
- gentle-ai install pattern (reference for shape, OS/arch detect, SHA256 verify, fail-closed defaults): external project, not in this repo
- macOS launchd reference: `launchctl bootstrap` / `launchctl bootout` (replaces deprecated `load` / `unload`); `man launchctl` on macOS 13+
- systemd --user reference: `man systemd.unit`, `man systemctl`
- XDG Base Directory Specification: `https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html`
- PEP 668: `https://peps.python.org/pep-0668/`
