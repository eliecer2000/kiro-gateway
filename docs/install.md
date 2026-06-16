# Installing kiro-gateway

## One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/jwadow/kiro-gateway/main/scripts/install.sh | bash -s -- install
```

The installer:
- Pre-flights OS, Python (>= 3.10), `curl`/`tar`, network reachability, and (on Linux) systemd --user.
- Fetches `kiro-gateway-X.Y.Z.tar.gz` and verifies it against the same release's `SHA256SUMS` file.
- Lays out `${INSTALL_DIR}/` (macOS: `~/Library/Application Support/KiroGateway/`, Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/kiro-gateway/`).
- Bootstraps a `venv` and installs requirements (PEP 668 isolation).
- Writes `state/install.env` (chmod 700 on `state/`, 600 on `.env`, 750 on `logs/`). It does not create empty credential or runtime-state files.
- Renders `scripts/system/kiro-gateway.{plist,service}` into the platform-native location and loads it (registered but NOT enabled).
- Symlinks `~/.local/bin/kiro-gateway -> ${INSTALL_DIR}/bin/kiro-gateway`.

At runtime the service uses `${INSTALL_DIR}/state` as its working directory and sets `KIRO_ENV_FILE=${INSTALL_DIR}/state/.env`. This makes installed configuration explicit while local development continues to load `./.env`.

## After install

```bash
# 1. Edit credentials
${EDITOR:-vi} ~/Library/Application\ Support/KiroGateway/state/.env   # macOS
# or
${EDITOR:-vi} ~/.local/share/kiro-gateway/state/.env                 # Linux

# 2. Start the gateway
kiro-gateway start

# 3. Check status + /health
kiro-gateway status

# 4. Tail logs
kiro-gateway logs
```

## Update

```bash
kiro-gateway update                  # fetch + extract + atomic swap
kiro-gateway update --rollback       # restore the previous version
```

The update flow snapshots `app/` to `app.prev/` before swapping. After a healthy `/health` probe (within 10s), `app.prev/` is removed. If the new version fails the health probe, the previous version is preserved for manual rollback.

Update and rollback replace the lifecycle command, shared install library, and service definition from the selected release. A running service is stopped before the swap and restarted afterward; a stopped service remains stopped.

## Uninstall

```bash
kiro-gateway uninstall
```

You'll be prompted: `Remove install dir ${INSTALL_DIR}? [y/N]`. With `y`, everything is removed (including `state/` and `logs/`). With `N` (the default), the service is stopped and the unit/agent is removed, but the install dir is preserved (so you can inspect logs or recover state).

## Manual verification

| Check | macOS | Linux |
|-------|-------|-------|
| Service registered but not running | `launchctl list \| grep com.jwadow.kiro-gateway` (PID column should be `-`) | `systemctl --user is-active kiro-gateway` (should print `inactive`) |
| Health endpoint | `curl -sS http://localhost:8000/health` | `curl -sS http://localhost:8000/health` |
| Logs | `tail -f ~/Library/Logs/kiro-gateway.log` (or `${INSTALL_DIR}/logs/kiro-gateway.log`) | `tail -f ${INSTALL_DIR}/logs/kiro-gateway.log` |

## Log rotation (v1)

v1 does not ship automated log rotation. On Linux, drop the following into `~/.config/logrotate.d/kiro-gateway`:

```
${INSTALL_DIR}/logs/kiro-gateway.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
```

`${INSTALL_DIR}` is `~/.local/share/kiro-gateway` on Linux or `~/Library/Application Support/KiroGateway` on macOS. Replace with the absolute path on your system.

On macOS, use `newsyslog` (built into `/etc/newsyslog.d/`) or your preferred rotation tool.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `preflight_python` fails | Python < 3.10 | Install via `pyenv install 3.12` or your package manager |
| `No SHA256SUMS available` | The GitHub release is incomplete or was published incorrectly | Do not install it; report the affected release |
| `Non-systemd Linux detected` | Alpine / Void / NixOS / WSL1 | Run via Docker (the installer's hint includes the one-liner) |
| `kiro-gateway is not installed` | Wrapper invoked before `install.sh` ran, or after `uninstall` | Run the installer first |
| Health probe times out | The gateway is not running on `:8000` | Run `kiro-gateway start` and `kiro-gateway logs` to diagnose |

## Development install (fallback)

```bash
git clone https://github.com/jwadow/kiro-gateway
cd kiro-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Kiro credentials
.venv/bin/python main.py
```

This path is supported but does not register a service, does not survive logout, and is the user's responsibility to manage.
