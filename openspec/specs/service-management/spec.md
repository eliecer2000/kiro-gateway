# Spec: service-management

- **Capability:** service-management
- **Source change:** install-script (PR #2)
- **Status:** merged

## Purpose

Define the contract for the platform service templates (launchd plist on macOS, systemd --user unit on Linux) and the post-install verification that the service is registered but stopped. The service is intentionally **not** autostarted on reboot; the user invokes `kiro-gateway start` when they want it running.

## Context

- macOS: `~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist`. Loaded with `launchctl bootstrap gui/$(id -u)`, **never** with `launchctl load -w` (the `-w` flag silently flips `RunAtLoad=true`).
- Linux: `~/.config/systemd/user/kiro-gateway.service`. `systemctl --user daemon-reload` runs at install time, **never** `systemctl --user enable`.
- The service runs as the installing user (no `sudo` required at runtime). The `WorkingDirectory` is `${INSTALL_DIR}/state/` so that `credentials.json`, `state.json`, and `.env` resolve to the right place at runtime.

## Requirements

### Requirement: launchd plist template (macOS)

The plist template MUST set `RunAtLoad=false`, `KeepAlive=false`, point `ProgramArguments` at `${INSTALL_DIR}/venv/bin/python main.py`, route stdout/stderr to `${INSTALL_DIR}/logs/`, set `WorkingDirectory` to `${INSTALL_DIR}/state/`, and declare the `KIRO_GATEWAY_HOME`, `ACCOUNTS_CONFIG_FILE`, and `ACCOUNTS_STATE_FILE` environment variables.

#### Scenario: Plist contains RunAtLoad=false

- GIVEN the rendered plist at `~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist`
- WHEN the plist is loaded into `plutil -p`
- THEN `RunAtLoad` is `false`.

#### Scenario: Plist contains KeepAlive=false

- GIVEN the rendered plist
- WHEN the plist is loaded into `plutil -p`
- THEN `KeepAlive` is `false`.

#### Scenario: Plist ProgramArguments points at venv python

- GIVEN the rendered plist
- WHEN the plist is loaded into `plutil -p`
- THEN `ProgramArguments` is `["${INSTALL_DIR}/venv/bin/python", "main.py"]`.

#### Scenario: Plist WorkingDirectory is state dir

- GIVEN the rendered plist
- WHEN the plist is loaded into `plutil -p`
- THEN `WorkingDirectory` is `${INSTALL_DIR}/state/`.

#### Scenario: Plist env vars are present

- GIVEN the rendered plist
- WHEN the plist is loaded into `plutil -p`
- THEN `EnvironmentVariables.KIRO_GATEWAY_HOME == ${INSTALL_DIR}`
- AND `EnvironmentVariables.ACCOUNTS_CONFIG_FILE == ${INSTALL_DIR}/state/credentials.json`
- AND `EnvironmentVariables.ACCOUNTS_STATE_FILE == ${INSTALL_DIR}/state/state.json`.

#### Scenario: Plist is loaded with launchctl bootstrap (not load -w)

- GIVEN the installer has finished
- WHEN the load step is inspected
- THEN `launchctl bootstrap gui/$(id -u) <plist>` is the command
- AND `launchctl load -w` is NEVER used.

### Requirement: systemd --user unit template (Linux)

The unit MUST declare `[Service]` with `ExecStart=${INSTALL_DIR}/venv/bin/python main.py`, `WorkingDirectory=${INSTALL_DIR}/state/`, and the same env vars as the plist; and `[Install]` with `WantedBy=default.target`. The installer MUST run `daemon-reload` and MUST NOT run `enable`.

#### Scenario: Unit ExecStart is venv python

- GIVEN the rendered unit at `~/.config/systemd/user/kiro-gateway.service`
- WHEN the unit is parsed
- THEN `[Service] ExecStart=${INSTALL_DIR}/venv/bin/python main.py`.

#### Scenario: Unit WorkingDirectory is state dir

- GIVEN the rendered unit
- WHEN the unit is parsed
- THEN `[Service] WorkingDirectory=${INSTALL_DIR}/state/`.

#### Scenario: Unit has WantedBy=default.target

- GIVEN the rendered unit
- WHEN the unit is parsed
- THEN `[Install] WantedBy=default.target` is present.

#### Scenario: Unit Environment contains the three vars

- GIVEN the rendered unit
- WHEN the unit is parsed
- THEN `Environment` lines include `KIRO_GATEWAY_HOME=${INSTALL_DIR}`, `ACCOUNTS_CONFIG_FILE=${INSTALL_DIR}/state/credentials.json`, and `ACCOUNTS_STATE_FILE=${INSTALL_DIR}/state/state.json`.

#### Scenario: daemon-reload runs but enable does not

- GIVEN the installer has finished
- WHEN the systemd wiring is inspected
- THEN `systemctl --user daemon-reload` is the only enable-adjacent command
- AND `systemctl --user enable kiro-gateway` is NEVER invoked.

### Requirement: Stopped-after-reboot verification

After a clean install, the service MUST be registered but not running. The installer MUST verify this and report it in the post-install summary.

#### Scenario: macOS — registered but not running

- GIVEN a fresh install
- WHEN `launchctl list | grep kiro-gateway` is run
- THEN the entry shows PID `-` (registered, not running)
- AND the post-install summary prints `Service is registered but not running. Run: kiro-gateway start`.

#### Scenario: Linux — inactive after install

- GIVEN a fresh install
- WHEN `systemctl --user status kiro-gateway` is run
- THEN the status is `inactive (dead)`
- AND the post-install summary prints the same hint.

### Requirement: Service file permissions

The installer MUST set restrictive permissions on the state dir and on the sensitive files inside it.

#### Scenario: state dir is chmod 700

- GIVEN a fresh install
- WHEN `stat -c '%a' ${INSTALL_DIR}/state` (Linux) or `stat -f '%Lp' ${INSTALL_DIR}/state` (macOS) is run
- THEN the mode is `700`.

#### Scenario: .env is chmod 600

- GIVEN a fresh install (and a `.env` exists or is created)
- WHEN the file mode is checked
- THEN it is `600`.

#### Scenario: credentials.json is chmod 600

- GIVEN a fresh install
- WHEN the file mode of `${INSTALL_DIR}/state/credentials.json` is checked
- THEN it is `600`.

#### Scenario: logs dir is chmod 750

- GIVEN a fresh install
- WHEN the file mode of `${INSTALL_DIR}/logs` is checked
- THEN it is `750`.

### Requirement: Non-systemd Linux is refused with a friendly message

If `systemctl --user` is unavailable on Linux, the installer MUST abort with a clear message and recommend Docker. The service is not registered and no install-dir state is created.

#### Scenario: Alpine Linux detected

- GIVEN `command -v systemctl` returns nothing
- WHEN the installer reaches the service-registration step
- THEN the installer exits non-zero
- AND prints `Non-systemd Linux detected. kiro-gateway requires systemd --user. Run via Docker instead: <docker one-liner>.`

## Test scenarios

**T-3.1** `test_plist_renders_with_correct_keys` — render the plist template; assert all keys are present and `RunAtLoad=false`.
**T-3.2** `test_unit_renders_with_correct_keys` — render the unit template; assert all keys are present and `WantedBy=default.target`.
**T-3.3** `test_load_uses_bootstrap_not_load_w` — static gate: `rg 'load -w' install.sh` returns no matches.
**T-3.4** `test_no_systemctl_enable_in_install` — static gate: `rg 'systemctl .* enable' install.sh` returns no matches.
**T-3.5** `test_post_install_status_registered_not_running_macos` — run the installer in a tempdir; assert `launchctl list` (stubbed) shows PID `-`.
**T-3.6** `test_post_install_status_inactive_linux` — same, with `systemctl --user status` stubbed.
**T-3.7** `test_state_dir_chmod_700` — assert `${INSTALL_DIR}/state` has mode `700`.
**T-3.8** `test_credentials_chmod_600` — assert credentials.json has mode `600`.
**T-3.9** `test_logs_chmod_750` — assert logs dir has mode `750`.
**T-3.10** `test_non_systemd_linux_refused` — with `command -v systemctl` returning empty, the installer aborts with the friendly message.

## Acceptance criteria

- AC-3.A: All T-3.x tests pass.
- AC-3.B: `plutil -lint` reports the rendered plist is valid.
- AC-3.C: `systemd-analyze verify` reports the rendered unit is valid.
- AC-3.D: After a clean install, the post-install summary explicitly states the service is NOT running.
- AC-3.E: The four file-mode requirements are covered by automated tests and a smoke check in the install script.
