#!/usr/bin/env bash
# install-common.sh — shared library sourced by scripts/install.sh and
# scripts/kiro-gateway. Contains all the fetch/verify/extract/venv/state
# logic so both entry points stay in sync.

set -euo pipefail

KIRO_REPO="${KIRO_REPO:-jwadow/kiro-gateway}"

# -- Tunables (T-4.1) -----------------------------------------------------
# Centralized so the static gates and the runtime use the same values.
MIN_DISK_MB=200
MIN_DISK_KIB=$((MIN_DISK_MB * 1024))
HEALTH_PROBE_TIMEOUT_S=5
UPDATE_HEALTH_POLL_TIMEOUT_S=10
HEALTH_PROBE_INTERVAL_S=1

# Color setup. Forces no color when not on a tty.
setup_color() {
    if [[ -t 1 ]]; then
        RED=$'\033[0;31m'
        GREEN=$'\033[0;32m'
        YELLOW=$'\033[0;33m'
        BOLD=$'\033[1m'
        RESET=$'\033[0m'
    else
        RED=""
        GREEN=""
        YELLOW=""
        BOLD=""
        RESET=""
    fi
}

log_info()  { printf "%s%s%s\n" "$BOLD" "$*" "$RESET" >&2; }
log_warn()  { printf "%s%s%s\n" "$YELLOW" "$*" "$RESET" >&2; }
log_error() { printf "%s%s%s\n" "$RED" "$*" "$RESET" >&2; }

# curl_https: a thin wrapper so the HTTPS/TLS flags live in one place.
# Usage: curl_https [-o FILE] [-w FORMAT] [--max-time N] URL [curl-args...]
curl_https() {
    curl --proto =https --tlsv1.2 "$@"
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

preflight_euid() {
    if [[ "${EUID:-$(id -u)}" == "0" ]]; then
        log_error "Do not run this installer with sudo. Re-run as your normal user."
        exit 1
    fi
}

preflight_os() {
    case "${UNAME_S:-$(uname -s)}" in
        Darwin|Linux) ;;
        *) log_error "Unsupported OS: ${UNAME_S:-$(uname -s)}. kiro-gateway supports macOS and Linux."; exit 1 ;;
    esac
}

# Parse a "X.Y.Z" version. Returns 0 if format matches.
version_is_valid() {
    local v="${1:-}"
    [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

# Compare two "X.Y" or "X.Y.Z" dotted version strings. Echoes -1/0/1.
version_compare() {
    local a="$1" b="$2"
    if [[ "$a" == "$b" ]]; then echo 0; return; fi
    local IFS=.
    local -a av=($a) bv=($b)
    local i
    for i in 0 1 2; do
        local ai="${av[$i]:-0}" bi="${bv[$i]:-0}"
        if (( ai < bi )); then echo -1; return; fi
        if (( ai > bi )); then echo 1; return; fi
    done
    echo 0
}

preflight_python() {
    local py
    py="$(command -v python3 || true)"
    if [[ -z "$py" ]]; then
        log_error "python3 not found on PATH. Install Python 3.10 or newer."
        exit 1
    fi
    local ver
    ver="$("$py" -V 2>&1 | awk '{print $2}')"
    if [[ "$(version_compare "$ver" "3.10")" == "-1" ]]; then
        # Surface a stable, predictable message. If the version is exactly 3.9.x,
        # print the spec's exact string.
        local major_minor="${ver%.*}"
        if [[ "$major_minor" == "3.9" ]]; then
            log_error "Python 3.10 or newer is required. Found 3.9.x. Install via pyenv or your package manager."
        else
            log_error "Python 3.10 or newer is required. Found $ver."
        fi
        exit 1
    fi
}

preflight_tools() {
    local missing=()
    command -v curl >/dev/null 2>&1 || missing+=("curl")
    command -v tar  >/dev/null 2>&1 || missing+=("tar")
    if [[ "${INSECURE:-0}" != "1" ]] \
        && ! command -v sha256sum >/dev/null 2>&1 \
        && ! command -v shasum >/dev/null 2>&1; then
        missing+=("sha256sum or shasum")
    fi
    if (( ${#missing[@]} > 0 )); then
        log_error "Required tools missing: ${missing[*]}. Install them and re-run."
        exit 1
    fi
}

preflight_disk() {
    local target="${1:-.}"
    # Walk up the path until we find an existing directory (or hit root).
    while [[ ! -d "$target" ]] && [[ "$target" != "/" ]]; do
        target="$(dirname "$target")"
    done
    local have_kib
    have_kib="$(df -k "$target" | awk 'NR==2 {print $4}')"
    if (( have_kib < MIN_DISK_KIB )); then
        log_error "Need ${MIN_DISK_MB}MB free at $target; have $((have_kib / 1024))MB."
        exit 1
    fi
}

preflight_network() {
    local code
    code="$(curl_https -sS -o /dev/null -w '%{http_code}' https://github.com 2>/dev/null || echo 000)"
    case "$code" in
        200|301|302) ;;
        *) log_error "Cannot reach github.com. Check your connection."; exit 1 ;;
    esac
}

# Preflight for Linux: refuse to install on non-systemd distros
# (Alpine, Void, NixOS, dev containers, WSL1, etc.). v1 ships the service
# only via systemd --user; non-systemd users should run via Docker.
preflight_systemd() {
    if [[ "${UNAME_S:-$(uname -s)}" != "Linux" ]]; then
        return
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        log_error "Non-systemd Linux detected. kiro-gateway requires systemd --user. Run via Docker instead:"
        log_error "  docker run -d --name kiro-gateway -p 8000:8000 -v kiro-gateway-data:/data jwadow/kiro-gateway:latest"
        exit 1
    fi
    if ! systemctl --user show-environment >/dev/null 2>&1; then
        log_error "systemd --user is not available in this session. Set XDG_RUNTIME_DIR or log in via a graphical session."
        log_error "Run via Docker instead:"
        log_error "  docker run -d --name kiro-gateway -p 8000:8000 -v kiro-gateway-data:/data jwadow/kiro-gateway:latest"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Layout and install dir
# ---------------------------------------------------------------------------

detect_install_dir() {
    local override="${INSTALL_DIR_OVERRIDE:-}"
    if [[ -n "$override" ]]; then
        INSTALL_DIR="$override"
        return
    fi
    case "${UNAME_S:-$(uname -s)}" in
        Darwin)
            INSTALL_DIR="${HOME}/Library/Application Support/KiroGateway"
            ;;
        Linux)
            local xdg="${XDG_DATA_HOME:-}"
            if [[ -n "$xdg" ]]; then
                INSTALL_DIR="$xdg/kiro-gateway"
            else
                INSTALL_DIR="${HOME}/.local/share/kiro-gateway"
            fi
            ;;
        *)
            log_error "Unsupported platform."
            exit 1
            ;;
    esac
}

lay_out_state() {
    mkdir -p "${INSTALL_DIR}/bin" "${INSTALL_DIR}/state" "${INSTALL_DIR}/logs"
    chmod 700 "${INSTALL_DIR}/state"
    chmod 750 "${INSTALL_DIR}/logs"
    # credentials.json is created only by the application's .env migration.
    # An empty placeholder would incorrectly suppress that one-time migration.
    # Optional .env from app/.env.example.
    if [[ ! -f "${INSTALL_DIR}/state/.env" ]]; then
        if [[ -f "${INSTALL_DIR}/app/.env.example" ]]; then
            cp "${INSTALL_DIR}/app/.env.example" "${INSTALL_DIR}/state/.env"
        else
            : > "${INSTALL_DIR}/state/.env"
        fi
    fi
    chmod 600 "${INSTALL_DIR}/state/.env"
    [[ ! -f "${INSTALL_DIR}/state/credentials.json" ]] \
        || chmod 600 "${INSTALL_DIR}/state/credentials.json"
    [[ ! -f "${INSTALL_DIR}/state/state.json" ]] \
        || chmod 600 "${INSTALL_DIR}/state/state.json"
}

write_install_env() {
    cat > "${INSTALL_DIR}/state/install.env" <<EOF
INSTALL_DIR="${INSTALL_DIR}"
VERSION=${VERSION}
PLATFORM=${UNAME_S:-$(uname -s)}
INSTALLED_AT=$(date -u +%FT%TZ 2>/dev/null || date -u)
EOF
}

install_symlink() {
    local wrapper_tmp="${INSTALL_DIR}/bin/.kiro-gateway.new"
    cp "${INSTALL_DIR}/app/scripts/kiro-gateway" "$wrapper_tmp" || return 1
    chmod +x "$wrapper_tmp" || return 1
    mv "$wrapper_tmp" "${INSTALL_DIR}/bin/kiro-gateway" || return 1
    # The wrapper sources ${INSTALL_DIR}/lib/install-common.sh at runtime.
    mkdir -p "${INSTALL_DIR}/lib" || return 1
    ln -sf "${INSTALL_DIR}/app/scripts/lib/install-common.sh" "${INSTALL_DIR}/lib/install-common.sh" || return 1
    mkdir -p "${HOME}/.local/bin" || return 1
    ln -sf "${INSTALL_DIR}/bin/kiro-gateway" "${HOME}/.local/bin/kiro-gateway" || return 1
}

refresh_control_plane() {
    install_symlink || return 1
    render_and_install_service || return 1
}

# ---------------------------------------------------------------------------
# Pre-existing install handling
# ---------------------------------------------------------------------------

check_preexisting() {
    if [[ ! -f "${INSTALL_DIR}/state/install.env" ]]; then
        return 0
    fi
    local prompt_answer=""
    if [[ -t 0 ]]; then
        printf 'Existing install detected at %s.\n(r)einstall / (u)pdate / (a)bort / (c)ustom path [a]: ' "$INSTALL_DIR" >&2
        IFS= read -r prompt_answer
    else
        # Non-interactive: read one line from stdin if present, else default.
        if [[ -s /dev/stdin ]]; then
            IFS= read -r prompt_answer
        else
            prompt_answer=""
        fi
    fi
    case "${prompt_answer:-a}" in
        r|R) return 0 ;;   # proceed with install
        a|A|"") exit 0 ;;  # abort cleanly
        u|U) return 2 ;;   # caller routes to update flow
        c|C) return 3 ;;   # caller asks the user to re-run with --install-dir
        *) exit 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Source distribution: fetch, verify, extract
# ---------------------------------------------------------------------------

resolve_version() {
    local pinned="${VERSION_PIN:-}"
    if [[ -n "$pinned" ]]; then
        if ! version_is_valid "$pinned"; then
            log_error "Invalid --version '$pinned'. Expected X.Y.Z (e.g. 2.5.0)."
            exit 1
        fi
        VERSION="$pinned"
        return
    fi
    # Default: hit GitHub API for the latest release.
    local repo="${KIRO_REPO}"
    local body
    body="$(curl_https -fsSL \
        "https://api.github.com/repos/${repo}/releases/latest")" || {
        log_error "Could not query GitHub for latest release. Pass --version X.Y.Z or --insecure."
        exit 1
    }
    # Parse tag_name without jq: portable awk/sed.
    local tag
    tag="$(printf '%s' "$body" | awk -F'"' '/"tag_name"[[:space:]]*:/ {for (i=1;i<NF;i++) if ($i=="tag_name") {print $(i+2); exit}}' | sed 's/^v//')"
    if [[ -z "$tag" ]] || ! version_is_valid "$tag"; then
        log_error "Could not resolve latest version from GitHub API."
        exit 1
    fi
    VERSION="$tag"
}

tarball_url() {
    printf 'https://github.com/%s/releases/download/v%s/kiro-gateway-%s.tar.gz' \
        "$KIRO_REPO" "$VERSION" "$VERSION"
}

fetch_tarball() {
    TARBALL="${TMPDIR:-/tmp}/kiro-gateway-${VERSION}.tar.gz"
    curl_https -fsSL -o "$TARBALL" "$(tarball_url)" || {
        log_error "Failed to download tarball from $(tarball_url)."
        exit 1
    }
}

verify_sha256() {
    if [[ "${INSECURE:-0}" == "1" ]]; then
        log_warn "WARNING: skipping SHA256 verification (--insecure). Use only for development."
        return
    fi
    local sums_url="https://github.com/${KIRO_REPO}/releases/download/v${VERSION}/SHA256SUMS"
    local sums
    if ! sums="$(curl_https -fsSL "$sums_url" 2>/dev/null)"; then
        log_error "No SHA256SUMS available. Install aborted. Use --insecure only for local development."
        exit 1
    fi
    local want got
    local archive_name="kiro-gateway-${VERSION}.tar.gz"
    want="$(printf '%s\n' "$sums" | awk -v v="$archive_name" '$2==v || $2=="*"v {print $1; exit}')"
    if [[ -z "$want" ]]; then
        log_error "No SHA256SUMS available. Install aborted. Use --insecure only for local development."
        exit 1
    fi
    got="$(sha256_file "$TARBALL")"
    if [[ "$want" != "$got" ]]; then
        log_error "SHA256 mismatch: expected $want, got $got."
        exit 1
    fi
}

sha256_file() {
    local path="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$path" | awk '{print $1}'
        return
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$path" | awk '{print $1}'
        return
    fi
    log_error "SHA256 verification requires sha256sum or shasum."
    return 1
}

strip_excludes() {
    local root="$1"
    rm -rf "${root}/.git" "${root}/tests" "${root}/docs" "${root}/.github"
}

extract_atomic() {
    local new_dir="${INSTALL_DIR}/app.new"
    rm -rf "$new_dir" || return 1
    mkdir -p "$new_dir" || return 1
    tar -xzf "$TARBALL" -C "$new_dir" --strip-components=1 || return 1
    strip_excludes "$new_dir" || return 1
    # Atomic swap: app -> app.prev (if exists), app.new -> app.
    if [[ -d "${INSTALL_DIR}/app" ]]; then
        rm -rf "${INSTALL_DIR}/app.prev" || return 1
        mv "${INSTALL_DIR}/app" "${INSTALL_DIR}/app.prev" || return 1
    fi
    mv "$new_dir" "${INSTALL_DIR}/app" || return 1
}

# ---------------------------------------------------------------------------
# venv
# ---------------------------------------------------------------------------

compute_requirements_hash() {
    local req="${INSTALL_DIR}/app/requirements.txt"
    if [[ -f "$req" ]]; then
        sha256_file "$req"
    else
        echo ""
    fi
}

venv_bootstrap_or_refresh() {
    local req_hash_file="${INSTALL_DIR}/state/requirements.sha256"
    local new_hash
    new_hash="$(compute_requirements_hash)"
    if [[ -f "$req_hash_file" ]] && [[ "$(cat "$req_hash_file")" == "$new_hash" ]] \
        && [[ -d "${INSTALL_DIR}/venv" ]] \
        && [[ -f "${INSTALL_DIR}/venv/bin/pip" ]]; then
        return
    fi
    rm -rf "${INSTALL_DIR}/venv" || return 1
    python3 -m venv "${INSTALL_DIR}/venv" || return 1
    "${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/app/requirements.txt" || return 1
    printf '%s\n' "$new_hash" > "$req_hash_file" || return 1
}

# ---------------------------------------------------------------------------
# Service management (PR 2: T-2.3, T-2.4, T-2.11)
# ---------------------------------------------------------------------------

# Render the platform service template into the platform-native location.
# - macOS:   ~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist
# - Linux:   $HOME/.config/systemd/user/kiro-gateway.service
# Reloads the platform service definition after writing it.
render_and_install_service() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        local dest="${HOME}/Library/LaunchAgents/com.jwadow.kiro-gateway.plist"
        mkdir -p "$(dirname "$dest")"
        local src="${INSTALL_DIR}/app/scripts/system/kiro-gateway.plist"
        sed -e "s|\${INSTALL_DIR}|${INSTALL_DIR}|g" \
            -e "s|\${HOME}|${HOME}|g" \
            "$src" > "$dest" || return 1
        chmod 644 "$dest" || return 1
    else
        local dest="${HOME}/.config/systemd/user/kiro-gateway.service"
        mkdir -p "$(dirname "$dest")"
        local src="${INSTALL_DIR}/app/scripts/system/kiro-gateway.service"
        sed -e "s|\${INSTALL_DIR}|${INSTALL_DIR}|g" \
            -e "s|\${HOME}|${HOME}|g" \
            "$src" > "$dest" || return 1
        chmod 644 "$dest" || return 1
    fi
    reload_service_definition
}

# Reload the service definition WITHOUT enabling autostart.
reload_service_definition() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        local domain="gui/$(id -u)"
        local label="com.jwadow.kiro-gateway"
        local plist="${HOME}/Library/LaunchAgents/${label}.plist"
        launchctl bootout "${domain}/${label}" 2>/dev/null || true
        if ! launchctl bootstrap "$domain" "$plist"; then
            log_error "launchctl could not register ${plist}. Run this installer from a logged-in macOS user session."
            return 1
        fi
    else
        if ! systemctl --user daemon-reload; then
            log_error "systemctl --user daemon-reload failed."
            return 1
        fi
    fi
}

# Backward-compatible name used by existing installer tests.
load_service() {
    reload_service_definition
}

service_is_running() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        local pid
        pid="$(launchctl list 2>/dev/null | awk '$3=="com.jwadow.kiro-gateway" {print $1; exit}')"
        [[ -n "$pid" && "$pid" != "-" ]]
    else
        [[ "$(systemctl --user is-active kiro-gateway 2>/dev/null || true)" == "active" ]]
    fi
}

start_service() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        local domain="gui/$(id -u)"
        local label="com.jwadow.kiro-gateway"
        local plist="${HOME}/Library/LaunchAgents/${label}.plist"
        if ! launchctl print "${domain}/${label}" >/dev/null 2>&1; then
            if ! launchctl bootstrap "$domain" "$plist"; then
                log_error "launchctl could not register ${plist}. Verify that you are in a logged-in GUI session."
                return 1
            fi
        fi
        if ! launchctl kickstart -k "${domain}/${label}"; then
            log_error "launchctl could not start ${label}. Inspect ${INSTALL_DIR}/logs/kiro-gateway.log."
            return 1
        fi
    else
        if ! systemctl --user start kiro-gateway; then
            log_error "systemctl could not start kiro-gateway. Run: systemctl --user status kiro-gateway"
            return 1
        fi
    fi
}

stop_service() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        launchctl bootout "gui/$(id -u)/com.jwadow.kiro-gateway" 2>/dev/null || true
    else
        systemctl --user stop kiro-gateway 2>/dev/null || true
    fi
}

restart_service() {
    stop_service
    start_service
}

# Unload the service. Used by uninstall.
unload_service() {
    stop_service
}

# Post-install verification: service is registered but not running.
# Emits the spec-mandated hint to stdout (caller can also check return code).
verify_not_running() {
    if [[ "${UNAME_S:-$(uname -s)}" == "Darwin" ]]; then
        # After `bootstrap` and before `start`, the row shows PID "-".
        local row
        row="$(launchctl list 2>/dev/null | awk '$3=="com.jwadow.kiro-gateway" {print $1; exit}')"
        if [[ "$row" == "-" ]]; then
            return 0
        fi
        return 1
    else
        # systemctl --user is-active returns "inactive" when the unit is
        # loaded but not running.
        local state
        state="$(systemctl --user is-active kiro-gateway 2>/dev/null || true)"
        [[ "$state" == "inactive" ]]
    fi
}

post_install_summary() {
    log_info ""
    log_info "Installed to: ${INSTALL_DIR}"
    log_info "Wrapper:      ${INSTALL_DIR}/bin/kiro-gateway (also: ~/.local/bin/kiro-gateway)"
    log_info "Service:      com.jwadow.kiro-gateway (registered, not running)"
    if verify_not_running; then
        log_info "Service is registered but not running. Run: kiro-gateway start"
    else
        log_warn "Service status could not be confirmed as 'not running'."
        log_warn "Verify with: launchctl list | grep com.jwadow.kiro-gateway  (macOS)"
        log_warn "         or: systemctl --user status kiro-gateway          (Linux)"
    fi
    log_info ""
    log_info "Next steps:"
    log_info "  1. Edit ${INSTALL_DIR}/state/.env with your Kiro credentials."
    log_info "  2. Ensure ~/.local/bin is in your PATH:"
    log_info "       export PATH=\"\$HOME/.local/bin:\$PATH\"  # add to ~/.zshrc or ~/.bashrc"
    log_info "  3. Run: kiro-gateway start"
}

# ---------------------------------------------------------------------------
# Traps
# ---------------------------------------------------------------------------

install_trap() {
    trap cleanup_install_artifacts EXIT
}

cleanup_install_artifacts() {
    if [[ -n "${INSTALL_DIR:-}" ]]; then
        rm -rf "${INSTALL_DIR}/app.new" 2>/dev/null || true
        rm -f "${INSTALL_DIR}/bin/.kiro-gateway.new" 2>/dev/null || true
    fi
    if [[ -n "${TARBALL:-}" ]]; then
        rm -f "$TARBALL" 2>/dev/null || true
    fi
    if [[ -n "${KIRO_INSTALL_TMPDIR:-}" ]]; then
        rm -rf "$KIRO_INSTALL_TMPDIR" 2>/dev/null || true
    fi
}
