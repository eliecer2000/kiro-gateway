# Tasks: install-script

- **Change:** install-script
- **Capabilities:** `installer-script`, `lifecycle-wrapper`, `service-management`, `source-distribution`
- **Mode:** strict TDD (red → green → refactor) on every task
- **Test runner:** `.venv/bin/pytest tests/unit/install_script/`
- **Integration runner:** `.venv/bin/pytest -m integration tests/integration/install_script/`

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,180 (prod ~525 + tests ~580 + docs ~75) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 = installer-script + source-distribution (foundation, no service manager dependency) → PR 2 = service-management (plist + unit + permissions) → PR 3 = lifecycle-wrapper (consumer of the rest) |
| Delivery strategy | single-pr (cached) |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

> **Forecast rationale.** The four artifacts sum to ~785 LOC of production code; with tests, fixtures, and docs the realistic diff is ~1,180 lines. The four specs land or fail as a unit (the wrapper references the plist, install.sh sources the lib, the plist references the venv path), but the natural seam is: PR 1 can land without the service unit being valid (skip `load_service`); PR 2 can land and require the unit syntax to be valid; PR 3 consumes both. `single-pr` was cached for the change as a whole, so the orchestrator must require `size:exception` OR confirm a `chain_strategy` before apply.

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | `installer-script` + `source-distribution` — installer + lib + 4 excludes + atomic swap + venv hash + SHA256 fail-closed | PR 1 | Base = `main`. Stub `launchctl` / `systemctl` in tests; service load is a no-op in this slice. |
| 2 | `service-management` — plist + unit + permissions + non-systemd refusal + static gates | PR 2 | Base = `main`. Independent: validates rendered templates. |
| 3 | `lifecycle-wrapper` — wrapper dispatcher + status health probe + update/rollback + uninstall | PR 3 | Base = `main`. Resolves real path; can be reviewed against PR 1 + PR 2 outputs. |

> v1 can ship as a single PR only with `size:exception` from a maintainer. Default path: chained PRs to `main` in order PR 1 → PR 2 → PR 3.

---

## Phase 1: Foundation (installer-script + source-distribution shell)

> TDD discipline: every task opens with the red test, then green, then refactor. Tests live in `tests/unit/install_script/installer_script/` and `tests/unit/install_script/source_distribution/`. Fixtures live in `tests/unit/install_script/conftest.py`. The shared shell library `scripts/lib/install-common.sh` is the only production file in this phase; `scripts/install.sh` is a thin orchestrator on top of it.

- [x] **T-1.0** [red-only] Create `tests/unit/install_script/conftest.py` with shared fixtures: `temp_install_dir`, `stub_curl` (writes a fake tarball + a fake `SHA256SUMS` response), `stub_platform` (parametrized `Darwin` / `Linux`), `fake_github_api` (returns `tag_name=v2.5.0`), `fake_tarball` (creates a real tarball with `.git/`, `tests/`, `docs/`, `.github/`, and a `LICENSE` file). No production code yet.
- [x] **T-1.1** [red] Write `test_install_fresh_macos_layout` in `tests/unit/install_script/installer_script/test_fresh_macos.py` asserting the full directory layout for macOS (`Library/Application Support/KiroGateway/{app,app.prev,venv,bin,state,logs}`). **Run:** `pytest tests/unit/install_script/installer_script/test_fresh_macos.py -x` → fails with `ModuleNotFoundError` / file missing. [green] Create `scripts/lib/install-common.sh` with `setup_color`, `detect_install_dir`, `preflight_*` (euid, os, python, tools, disk, network, systemd), `lay_out_state` (chmod 700 on `state/`, 750 on `logs/`, 600 on `.env` / `credentials.json` / `state.json`), `write_install_env`, `install_symlink`. `scripts/install.sh` is a 30-line orchestrator that sources the lib, parses `--install-dir` / `--version` / `--insecure` / `--help`, and dispatches. Verify the macOS layout exists. [refactor] extract `--install-dir` resolution to a single function. [verify] `bash -n scripts/install.sh && bash -n scripts/lib/install-common.sh && shellcheck -S error scripts/install.sh scripts/lib/install-common.sh && pytest tests/unit/install_script/installer_script/test_fresh_macos.py -x`.
- [x] **T-1.2** [red] Write `test_install_fresh_linux_layout` mirroring T-1.1 for Linux + `XDG_DATA_HOME` override. [green] Add the `XDG_DATA_HOME` branch to `detect_install_dir`; reuse the macOS path. [refactor] dedupe. [verify] re-run shell lint + the two layout tests.
- [x] **T-1.3** [red] Write `test_install_help_exits_zero`. [green] Add `--help` / `-h` short-circuit that prints usage and exits 0 BEFORE preflight. [refactor] keep the usage text in a single `usage()` function. [verify] `bash install.sh --help` → exit 0, stdout contains all flags.
- [x] **T-1.4** [red] Write `test_install_version_flag_pins` — with `--version 2.5.0`, assert the tarball URL fetched is `…/tags/v2.5.0.tar.gz` (inspect the stubbed `curl` call log). [green] Implement `resolve_version`: `latest` → GitHub API call; pinned → pass through after `^[0-9]+\.[0-9]+\.[0-9]+$` regex. [refactor] move the URL builder to a single function. [verify] both cases (`--version 2.5.0` and default `latest`).
- [x] **T-1.5** [red] Write `test_preflight_python_39_fails` — stub `python3` to print `Python 3.9.18`. [green] Implement `preflight_python` with the exact failure string from spec: `Python 3.10 or newer is required. Found 3.9.x. Install via pyenv or your package manager.` [refactor] extract the version-compare helper. [verify] exit 1 + exact message.
- [x] **T-1.6** [red] Write `test_preflight_no_network_fails` — stub `curl` to return non-200 for the github.com probe. [green] Implement `preflight_network` with the exact message: `Cannot reach github.com. Check your connection.` [refactor] none. [verify] exit 1 + exact message.
- [x] **T-1.7** [red] Write `test_preflight_root_fails` — simulate `EUID=0`. [green] Add `preflight_euid` as the FIRST executable line, exit 1 with: `Do not run this installer with sudo. Re-run as your normal user.` [refactor] keep it at the top before `setup_color`. [verify] exit 1 + exact message, no side effects.
- [x] **T-1.8** [red] Write `test_install_dir_override` — `--install-dir /tmp/x` lands the install at `/tmp/x/`. [green] `detect_install_dir` honors the override flag. [refactor] none. [verify] `state/install.env` written to `/tmp/x/state/`.
- [x] **T-1.9** [red] Write `test_preexisting_install_reinstall_preserves_state` — pre-populate `${INSTALL_DIR}/state/credentials.json` with sentinel content; run installer with stdin `r\n`; assert `credentials.json` is unchanged byte-for-byte. [green] Implement `check_preexisting` reading from stdin; on `r` proceed, on `a` exit 0, on `u` hand off to update flow, on `c` re-prompt for path. [refactor] extract the prompt loop. [verify] also test `a` (exit 0, no changes) and empty input (defaults to `a`).
- [x] **T-1.10** [red] Write `test_atomic_extract_failure_cleans_up` — feed a corrupt tarball; assert `${INSTALL_DIR}/app.new/` is absent afterward and `app/` (pre-existing) is intact. [green] Add the `trap 'rm -rf "${INSTALL_DIR}/app.new" "${TARBALL}"' EXIT` and the `extract_atomic` function. [refactor] move the trap to the very top of `install.sh`. [verify] exit 1 + cleanup assertion.
- [x] **T-1.11** [red] Write `test_https_only` — assert every `curl` invocation in the codebase includes `--proto =https --tlsv1.2`. [green] Add the flag to every `curl` call. [refactor] extract a `curl_https` wrapper in the lib so the flag lives in one place. [verify] `rg 'http://' scripts/install.sh scripts/lib/install-common.sh` → zero matches.
- [x] **T-1.12** [red] Write `test_idempotent_second_run` — second invocation with default answer aborts; `state/` byte-identical. [green] Wire `check_preexisting` into the install flow before any destructive action. [refactor] none. [verify] SHA256 of `state/install.env` matches before/after.
- [x] **T-1.13** [red] Write `test_default_version_resolves_to_latest` (in `tests/unit/install_script/source_distribution/`) — stub GitHub API to return `tag_name=v2.5.0`; assert the URL is `v2.5.0.tar.gz`. [green] `resolve_version` already handles it from T-1.4; just move it to the lib. [refactor] add JSON parsing via `python3 -c` or a portable awk/sed shim. [verify] pinned + latest both work.
- [x] **T-1.14** [red] Write `test_version_flag_pins_tag` — `--version 2.4.0` → URL `v2.4.0.tar.gz`. [green] Reuse `resolve_version`. [refactor] none. [verify] both.
- [x] **T-1.15** [red] Write `test_no_shasums_fails_closed` — stub `SHA256SUMS` 404. [green] `verify_sha256` exits 1 with: `No SHA256SUMS available. Re-run with --insecure to skip verification.` [refactor] separate the `fetch_sha256sums` step from the compare step. [verify] exit 1 + exact message, no extraction occurred.
- [x] **T-1.16** [red] Write `test_insecure_skips_verification` — `--insecure` flag skips SHA256 and prints the warning. [green] Wire the flag. [refactor] none. [verify] warning present in stdout, install proceeds.
- [x] **T-1.17** [red] Write `test_tarball_excludes_removed` — assert post-extract `${INSTALL_DIR}/app.new/.git`, `/tests`, `/docs`, `/.github` are gone and `LICENSE` exists. [green] Implement `strip_excludes` (or inline `rm -rf`). [refactor] make the excludes list a single variable. [verify] four paths absent, LICENSE present.
- [x] **T-1.18** [red] Write `test_atomic_swap_creates_app_prev` — pre-existing `app/`; run install; assert `app.prev/` matches the old `app/` and `app.new/` is gone. [green] `extract_atomic` does `mv app app.prev` then `mv app.new app`. [refactor] keep the `app.new → app` rename as the last step. [verify] file list diff confirms the swap.
- [x] **T-1.19** [red] Write `test_requirements_unchanged_preserves_venv` — `state/requirements.sha256` matches new hash; venv untouched. [green] `venv_bootstrap_or_refresh` computes hash, compares, short-circuits on match. [refactor] extract `compute_requirements_hash`. [verify] venv `mtime` unchanged.
- [x] **T-1.20** [red] Write `test_requirements_changed_recreates_venv` — hash differs; venv is wiped and re-bootstrapped; new hash stored. [green] Same function, mismatch branch. [refactor] none. [verify] new hash in `state/requirements.sha256`.

## Phase 2: Service management

> Plist + unit templates, permissions, non-systemd refusal. Lives in `scripts/system/`. Tests in `tests/unit/install_script/service_management/`.

- [x] **T-2.0** [red-only] Create `tests/unit/install_script/service_management/conftest.py` with `render_plist(install_dir)` and `render_unit(install_dir, home)` helpers that template-substitute into the assets.
- [x] **T-2.1** [red] Write `test_plist_renders_with_correct_keys` — assert `RunAtLoad=false`, `KeepAlive=false`, `ProgramArguments = [INSTALL_DIR/venv/bin/python, main.py]`, `WorkingDirectory = INSTALL_DIR/state/`, `EnvironmentVariables.KIRO_GATEWAY_HOME`, `ACCOUNTS_CONFIG_FILE`, `ACCOUNTS_STATE_FILE`. [green] Create `scripts/system/kiro-gateway.plist` with the design's literal content. [refactor] none. [verify] `plutil -lint` if available; otherwise structural assertion.
- [x] **T-2.2** [red] Write `test_unit_renders_with_correct_keys` — assert `ExecStart`, `WorkingDirectory`, `Environment=KIRO_GATEWAY_HOME=…`, `Environment=ACCOUNTS_CONFIG_FILE=…`, `Environment=ACCOUNTS_STATE_FILE=…`, `WantedBy=default.target`. [green] Create `scripts/system/kiro-gateway.service` with the design's literal content. [refactor] none. [verify] parse via `systemd-analyze verify` if available; otherwise structural assertion.
- [x] **T-2.3** [red] Write `test_load_uses_bootstrap_not_load_w` — static gate: `rg 'load -w' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` returns zero matches. [green] Use `launchctl bootstrap gui/$(id -u) <plist>` and `systemctl --user daemon-reload`. [refactor] none. [verify] `rg` returns empty; explicit assertion in pytest that no `load -w` substring appears in any rendered command.
- [x] **T-2.4** [red] Write `test_no_systemctl_enable_in_install` — static gate: `rg 'systemctl .* enable' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` returns zero matches. [green] Never call `systemctl --user enable`. [refactor] none. [verify] `rg` empty; pytest asserts the substring is absent.
- [x] **T-2.5** [red] Write `test_post_install_status_registered_not_running_macos` — stubbed `launchctl list` returns a row with PID `-`; post-install summary contains the literal `Service is registered but not running. Run: kiro-gateway start`. [green] Implement `verify_not_running` and the post-install summary block. [refactor] none. [verify] exact substring in stdout.
- [x] **T-2.6** [red] Write `test_post_install_status_inactive_linux` — stubbed `systemctl --user status` returns `inactive (dead)`. [green] Linux branch of `verify_not_running`. [refactor] dedupe with the macOS branch. [verify] exact substring.
- [x] **T-2.7** [red] Write `test_state_dir_chmod_700` — assert `stat -c '%a' state` (Linux) / `stat -f '%Lp' state` (macOS) returns `700`. [green] `lay_out_state` already chmods 700; assert the call path. [refactor] none. [verify] mode `700` in both stats.
- [x] **T-2.8** [red] Write `test_credentials_chmod_600`. [green] `lay_out_state` chmods 600 on `credentials.json`. [refactor] none. [verify] mode `600`.
- [x] **T-2.9** [red] Write `test_logs_chmod_750`. [green] `lay_out_state` chmods 750 on `logs/`. [refactor] none. [verify] mode `750`.
- [x] **T-2.10** [red] Write `test_non_systemd_linux_refused` — stub `command -v systemctl` returns empty; installer aborts with the literal message: `Non-systemd Linux detected. kiro-gateway requires systemd --user. Run via Docker instead: <docker one-liner>.` [green] `preflight_systemd` branch. [refactor] none. [verify] exit 1 + exact message; no `state/` dir created.
- [x] **T-2.11** [red] Write `test_install_renders_and_loads_service` — full installer run in tempdir; assert plist/unit exists at the right path AND that `verify_not_running` is called. [green] Wire `render_and_install_service` + `load_service` to use `launchctl bootstrap` / `daemon-reload`. [refactor] keep template-substitution in one helper. [verify] re-run all T-2.x tests.

## Phase 3: Lifecycle wrapper

> `scripts/kiro-gateway` (~150 LOC). Tests in `tests/unit/install_script/lifecycle_wrapper/`. Sourced from `scripts/lib/install-common.sh`.

- [x] **T-3.0** [red-only] Create `tests/unit/install_script/lifecycle_wrapper/conftest.py` with `installed_env` fixture (writes `state/install.env` + `state/credentials.json` + `app/` + `bin/kiro-gateway`) and a `mock_health_server` (binds to a free port, returns 200 or 500 on `/health`).
- [x] **T-3.1** [red] Write `test_wrapper_start_dispatches_launchctl_on_macos` — stub `uname -s=Darwin`; assert `launchctl bootstrap gui/$(id -u) <plist>` is invoked. [green] Implement the `start` branch in the wrapper dispatcher. [refactor] dedupe the platform branch into a single `case` table. [verify] command log contains the exact `launchctl` line.
- [x] **T-3.2** [red] Write `test_wrapper_start_dispatches_systemctl_on_linux` — same for `systemctl --user start kiro-gateway`. [green] Linux branch. [refactor] none. [verify] exact `systemctl` line.
- [x] **T-3.3** [red] Write `test_wrapper_status_health_probe` — start the mock health server on 200; assert exit 0 and `running (healthy)` in stdout. Then 500 → exit 1 and `running (unhealthy)`. Then the server down → exit 1 and `stopped`. [green] Implement `status` with a 5s `curl --max-time 5` probe to `http://localhost:${PORT}/health`. [refactor] extract the health-probe helper. [verify] all three cases.
- [x] **T-3.4** [red] Write `test_wrapper_update_rollback_restores_prev` — pre-populate `app/` and `app.prev/` with distinct sentinel files; run `kiro-gateway update --rollback`; assert `app/` now matches `app.prev/` and `app.prev/` is removed. [green] Implement `update --rollback` via `mv app app.new && mv app.prev app && rm -rf app.new`. [refactor] none. [verify] byte-level diff confirms the swap.
- [x] **T-3.5** [red] Write `test_wrapper_uninstall_prompt` — with `y`, the plist/unit and install dir are removed; with `N`, only the service is removed and the install dir preserved. [green] Implement `uninstall` with the prompt. [refactor] none. [verify] both paths.
- [x] **T-3.6** [red] Write `test_wrapper_missing_install_exits_nonzero` — point the wrapper at a non-existent install dir; assert it prints: `kiro-gateway is not installed. Run the installer first:` + the one-liner. [green] Guard at the top of the wrapper. [refactor] none. [verify] exit 1 + exact two-line output.
- [x] **T-3.7** [red] Write `test_wrapper_help_exits_zero` — `kiro-gateway help` exits 0 and prints all subcommands. [green] `help` branch in the dispatcher. [refactor] none. [verify] exact substrings.
- [x] **T-3.8** [red] Write `test_wrapper_symlink_resolution` — invoke via a symlink at `${TMP}/bin/kiro-gateway`; assert `install.env` is read from the resolved path. [green] `readlink -f "$0" 2>/dev/null || (cd $(dirname "$0") && pwd)/$(basename "$0")`. [refactor] extract the resolver. [verify] both invocation paths produce identical `install.env` reads.
- [x] **T-3.9** [red] Write `test_wrapper_update_fetches_and_swaps` — call `kiro-gateway update`; assert fetch → verify → extract → atomic swap → venv refresh on hash change → service reload. [green] Wire the update flow through the lib. [refactor] keep the lib the single source of truth. [verify] `state/install.env` VERSION bumped; `app/` updated.
- [x] **T-3.10** [red] Write `test_rollback_no_prev_fails` — with no `app.prev/`, `update --rollback` exits 1 with: `No previous version to roll back to.` [green] Guard. [refactor] none. [verify] exit 1 + exact message.
- [x] **T-3.11** [red] Write `test_snapshot_removed_on_healthy_start` — `GET /health` returns 200 within 10s; `app.prev/` is removed. [green] Add the post-update health-poll-and-cleanup step. [refactor] extract the health-poll loop. [verify] `app.prev/` absent; stdout contains `Update successful. Old version removed.`
- [x] **T-3.12** [red] Write `test_snapshot_preserved_on_unhealthy_start` — health never 200s in 10s; `app.prev/` preserved; hint printed. [green] Failure branch of the cleanup step. [refactor] none. [verify] `app.prev/` present; stdout contains the hint string.

## Phase 4: Cleanup, docs, and final verification

- [x] **T-4.1** Refactor pass: dedupe the four `preflight_*` functions, collapse duplicated `set -euo pipefail` boilerplate, extract magic numbers (200MB, 5s, 10s) into named constants at the top of the lib. Re-run the full unit suite.
- [x] **T-4.2** Add the v1 logrotate sample to `docs/install.md` (per design open question). [red] Write `test_docs_install_mentions_logrotate` that greps the doc. [green] Add the section. [refactor] none. [verify] substring present.
- [x] **T-4.3** Update `README.md`: replace the top-of-file install section with the one-liner; keep the `git clone` path under a `### Development install` heading. [red] Write `test_readme_one_liner_top` that asserts the curl command is in the first 60 lines. [green] Rewrite the section. [refactor] none. [verify] substring present.
- [x] **T-4.4** [integration] Add `tests/integration/install_script/test_docker_e2e_linux.py` (gated by `-m integration`). Stub `github.com` with a local `http.server`; run the full installer end-to-end; assert post-install state, then `start` → health 200 → `stop` → `uninstall`. macOS path is verified manually (cannot run launchd in CI).
- [x] **T-4.5** [final verification] Run all static gates and the full test matrix. The orchestrator confirms each gate before marking apply complete.

---

## Final verification checklist (T-5)

> Run in order; each gate must pass before the next.

- [x] **T-5.1** `bash -n scripts/install.sh && bash -n scripts/kiro-gateway && bash -n scripts/lib/install-common.sh` → exit 0 (AC-1.B, AC-2.B).
- [x] **T-5.2** `shellcheck -S error scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` → exit 0 (AC-1.C, AC-2.C).
- [x] **T-5.3** `rg 'eval\b' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` → zero matches (AC-1.D).
- [x] **T-5.4** `rg 'http://' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` → zero matches (AC-4.B).
- [x] **T-5.5** `rg 'load -w' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` → zero matches (T-2.3).
- [x] **T-5.6** `rg 'systemctl .* enable' scripts/install.sh scripts/kiro-gateway scripts/lib/install-common.sh` → zero matches (T-2.4).
- [x] **T-5.7** `.venv/bin/pytest tests/unit/install_script/ -v` → all unit tests pass.
- [x] **T-5.8** `.venv/bin/pytest -m integration tests/integration/install_script/` → Docker e2e passes (Linux path).
- [x] **T-5.9** Full project test suite: `.venv/bin/pytest tests/unit/` → no regression on existing tests.
