# Spec: lifecycle-wrapper

- **Capability:** lifecycle-wrapper
- **Change:** install-script
- **Status:** spec_complete
- **Risk:** Low

## Purpose

Define the contract for the `kiro-gateway` POSIX shell wrapper installed at `${INSTALL_DIR}/bin/kiro-gateway` and symlinked into `~/.local/bin/`. The wrapper dispatches to `start|stop|restart|status|logs|update|uninstall|version|help` and translates each into the right `launchctl` (macOS) or `systemctl --user` (Linux) call, with a `status` health probe and a `update --rollback` path.

## Context

- The wrapper reads `${INSTALL_DIR}/state/install.env` to discover its install root, version, and platform. This file is created at install time.
- Platform dispatch is driven by `uname -s`: `Darwin` → `launchctl`, `Linux` → `systemctl --user`. Other platforms are out of scope.
- The wrapper MUST be safe to run from any CWD. It MUST NOT depend on the user's `PATH` to find `curl`, `python`, etc. beyond POSIX-required utilities.

## Requirements

### Requirement: Subcommand dispatcher

The wrapper MUST accept a subcommand as `$1` and dispatch to the corresponding lifecycle action. Unknown subcommands MUST print usage and exit non-zero.

#### Scenario: kiro-gateway start

- GIVEN the service is stopped
- WHEN the user runs `kiro-gateway start`
- THEN `launchctl bootstrap gui/$(id -u) <plist>` (macOS) or `systemctl --user start kiro-gateway` (Linux) is invoked
- AND the script exits 0 on success.

#### Scenario: kiro-gateway stop

- GIVEN the service is running
- WHEN the user runs `kiro-gateway stop`
- THEN `launchctl bootout gui/$(id -u)/<label>` (macOS) or `systemctl --user stop kiro-gateway` (Linux) is invoked.

#### Scenario: kiro-gateway restart

- WHEN `kiro-gateway restart` is invoked
- THEN `stop` followed by `start` runs in sequence
- AND the script exits 0 only if `start` succeeds.

#### Scenario: kiro-gateway status

- WHEN `kiro-gateway status` is invoked
- THEN a service-status line is printed
- AND a 5-second health probe against `http://localhost:8000/health` is performed
- AND the script exits 0 iff the service is running AND the health probe succeeds.

#### Scenario: kiro-gateway logs

- WHEN `kiro-gateway logs` is invoked
- THEN `${INSTALL_DIR}/logs/kiro-gateway.log` is tailed via `tail -f`.

#### Scenario: kiro-gateway update

- WHEN `kiro-gateway update` is invoked
- THEN the current version is snapshotted to `${INSTALL_DIR}/app.prev/`
- AND the latest source is fetched, extracted atomically, and swapped in
- AND the venv is refreshed if `requirements.txt` hash changed
- AND the service is reloaded.

#### Scenario: kiro-gateway update --rollback

- WHEN `kiro-gateway update --rollback` is invoked
- THEN `${INSTALL_DIR}/app.prev/` is restored to `${INSTALL_DIR}/app/`
- AND the service is reloaded.

#### Scenario: kiro-gateway uninstall

- WHEN `kiro-gateway uninstall` is invoked
- THEN the user is prompted: `Remove install dir ${INSTALL_DIR}? [y/N]`
- AND on `y`, the service is stopped, the plist/unit is removed, the symlink is removed, and the install dir is deleted
- AND on `N`, the service is stopped and the plist/unit is removed, but the install dir is preserved.

#### Scenario: kiro-gateway version

- WHEN `kiro-gateway version` is invoked
- THEN the installed version is printed (read from `${INSTALL_DIR}/state/install.env`).

#### Scenario: kiro-gateway help

- WHEN `kiro-gateway help` (or `kiro-gateway --help` or no subcommand) is invoked
- THEN usage is printed to stdout and the script exits 0.

### Requirement: Health check on status

`status` MUST poll the gateway's health endpoint for up to 5 seconds before declaring the service healthy.

#### Scenario: Status with healthy service

- GIVEN the service is running and `GET /health` returns 200
- WHEN `kiro-gateway status` is invoked
- THEN the wrapper prints `running (healthy)` and exits 0.

#### Scenario: Status with running but unhealthy service

- GIVEN the service is registered but `GET /health` fails or times out
- WHEN `kiro-gateway status` is invoked
- THEN the wrapper prints `running (unhealthy)` and exits 1
- AND a hint to run `kiro-gateway logs` is printed.

### Requirement: Guard against missing install

If `${INSTALL_DIR}` does not exist (the wrapper is run before any install, or after an uninstall), the wrapper MUST print an actionable error and exit non-zero.

#### Scenario: Wrapper run with no install

- GIVEN `${INSTALL_DIR}` does not exist
- WHEN `kiro-gateway start` is invoked
- THEN the wrapper prints `kiro-gateway is not installed. Run the installer first:`
- AND prints the one-liner install command
- AND exits 1.

### Requirement: Symlink and canonical path both work

The wrapper MUST work when invoked via the symlink at `~/.local/bin/kiro-gateway` OR via its canonical path at `${INSTALL_DIR}/bin/kiro-gateway`. The wrapper MUST resolve its own real path to find `install.env`.

#### Scenario: Invoked via symlink

- GIVEN the symlink `~/.local/bin/kiro-gateway` -> `${INSTALL_DIR}/bin/kiro-gateway`
- WHEN the user runs `kiro-gateway status`
- THEN the wrapper locates `install.env` via the resolved real path
- AND the command succeeds.

## Test scenarios

**T-2.1** `test_wrapper_start_dispatches_launchctl_on_macos` — stub `uname -s=Darwin`; assert `launchctl bootstrap` is invoked with the plist path.
**T-2.2** `test_wrapper_start_dispatches_systemctl_on_linux` — stub `uname -s=Linux`; assert `systemctl --user start kiro-gateway` is invoked.
**T-2.3** `test_wrapper_status_health_probe` — start a mock HTTP server returning 200 on `/health`; assert exit 0. With a 500, assert exit 1.
**T-2.4** `test_wrapper_update_rollback_restores_prev` — pre-populate `app/` and `app.prev/` with distinct markers; run `update --rollback`; assert `app/` now matches the old marker.
**T-2.5** `test_wrapper_uninstall_prompt` — with `y`, the plist/unit and install dir are removed; with `N`, only the service is removed.
**T-2.6** `test_wrapper_missing_install_exits_nonzero` — point the wrapper at a non-existent install dir; assert it prints the actionable error and exits 1.
**T-2.7** `test_wrapper_help_exits_zero` — `kiro-gateway help` exits 0 and prints all subcommands.

## Acceptance criteria

- AC-2.A: All T-2.x tests pass.
- AC-2.B: `bash -n kiro-gateway` reports no syntax errors.
- AC-2.C: `shellcheck kiro-gateway` reports no errors at severity `error`.
- AC-2.D: The wrapper resolves its own real path with `readlink -f` (or `realpath`) before reading `install.env`.
- AC-2.E: No subcommand leaks a non-zero exit when the underlying command succeeds.
