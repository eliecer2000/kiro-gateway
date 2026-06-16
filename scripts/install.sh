#!/usr/bin/env bash
# install.sh — the one-liner installer for kiro-gateway.
# Sources the shared library and dispatches install / update / uninstall.

set -euo pipefail

# Bootstrap: when run via `curl ... | bash`, BASH_SOURCE[0] is empty
# (verified empirically on macOS bash 3.2 and bash 5). In that case we
# can't find a sibling `lib/install-common.sh`, so fetch it from the
# same GitHub origin into a temp dir and source it from there. When run
# from a local checkout (`./scripts/install.sh`), BASH_SOURCE[0] points
# to a real file on disk and we source the sibling — no network needed.
KIRO_REPO="${KIRO_REPO:-jwadow/kiro-gateway}"
KIRO_BRANCH="${KIRO_BRANCH:-main}"
INSTALL_COMMON_URL="https://raw.githubusercontent.com/${KIRO_REPO}/${KIRO_BRANCH}/scripts/lib/install-common.sh"

SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" ]] && [[ -f "$SELF" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
    # shellcheck source=scripts/lib/install-common.sh
    source "${SCRIPT_DIR}/lib/install-common.sh"
else
    # stdin bootstrap (curl|bash). Fetch the lib to a temp dir and
    # source it from there. Clean up the temp dir on exit.
    if [[ -z "${KIRO_INSTALL_TMPDIR:-}" ]]; then
        KIRO_INSTALL_TMPDIR="$(mktemp -d -t kiro-install.XXXXXX)"
        trap 'rm -rf "${KIRO_INSTALL_TMPDIR:-}"' EXIT
    fi
    INSTALL_COMMON_SH="${KIRO_INSTALL_TMPDIR}/install-common.sh"
    CURL_ERROR_FILE="${KIRO_INSTALL_TMPDIR}/curl-error.log"
    if ! curl -fsSL --proto '=https' --tlsv1.2 \
            "$INSTALL_COMMON_URL" -o "$INSTALL_COMMON_SH" 2>"$CURL_ERROR_FILE"; then
        echo "error: failed to fetch install library from ${INSTALL_COMMON_URL}" >&2
        echo "       curl said: $(cat "$CURL_ERROR_FILE" 2>/dev/null || echo 'unknown')" >&2
        echo "       set KIRO_REPO and KIRO_BRANCH to a reachable fork, or" >&2
        echo "       download scripts/lib/install-common.sh manually" >&2
        exit 1
    fi
    # shellcheck source=scripts/lib/install-common.sh
    source "$INSTALL_COMMON_SH"
fi

install_trap

# Defaults; overridden by arg parsing.
SUBCOMMAND="install"
INSTALL_DIR_OVERRIDE=""
VERSION_PIN=""
INSECURE=0
VERSION=""

usage() {
    cat <<'EOF'
Usage: install.sh [--help] [--version X.Y.Z] [--install-dir PATH] [--insecure] [install|update|uninstall|--rollback]

Default subcommand: install

  --help, -h           Show this help and exit 0.
  --version X.Y.Z      Pin a specific release (default: latest from GitHub).
  --install-dir PATH   Override the default install location.
  --insecure           Skip SHA256 verification (development only).
  install              Fresh install.
  update               Update an existing install.
  uninstall            Remove the service and (after prompt) the install dir.
  --rollback           Roll back to the previous version (used with `update`).

EOF
}

# Arg parse (runs before preflight so --help and --version short-circuit).
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --version) VERSION_PIN="${2:-}"; shift 2 ;;
        --install-dir) INSTALL_DIR_OVERRIDE="${2:-}"; shift 2 ;;
        --insecure) INSECURE=1; shift ;;
        install|update|uninstall|--rollback) SUBCOMMAND="$1"; shift ;;
        *) log_error "Unknown argument: $1"; usage; exit 1 ;;
    esac
done

# Pre-flight (install subcommand only).
if [[ "$SUBCOMMAND" == "install" ]]; then
    setup_color
    preflight_euid
    preflight_os
    preflight_python
    preflight_tools
    preflight_systemd
fi

detect_install_dir

dispatch_lifecycle_action() {
    local action="$1"
    local control="${INSTALL_DIR}/bin/kiro-gateway"
    if [[ ! -x "$control" ]]; then
        log_error "Cannot run '${action}': installed control command not found at ${control}."
        log_error "Repair the install with: scripts/install.sh --install-dir \"${INSTALL_DIR}\" install"
        exit 1
    fi
    case "$action" in
        update) exec "$control" update ;;
        uninstall) exec "$control" uninstall ;;
        --rollback) exec "$control" update --rollback ;;
        *) log_error "Unsupported lifecycle action: ${action}"; exit 1 ;;
    esac
}

if [[ "$SUBCOMMAND" != "install" ]]; then
    dispatch_lifecycle_action "$SUBCOMMAND"
fi

preflight_disk "$(dirname "$INSTALL_DIR")"

if [[ "$SUBCOMMAND" == "install" ]]; then
    # Check for pre-existing install; default to abort on empty input.
    if check_preexisting; then
        :
    else
        preexisting_action=$?
        case "$preexisting_action" in
            2) dispatch_lifecycle_action update ;;
            3)
                log_error "Choose a custom path with --install-dir PATH and run the installer again."
                exit 1
                ;;
            *) exit "$preexisting_action" ;;
        esac
    fi
    preflight_network
    resolve_version
    fetch_tarball
    verify_sha256
    extract_atomic
fi

# State layout and venv always run for install.
if [[ "$SUBCOMMAND" == "install" ]]; then
    lay_out_state
    venv_bootstrap_or_refresh
    write_install_env
    install_symlink
    render_and_install_service
    post_install_summary
fi
