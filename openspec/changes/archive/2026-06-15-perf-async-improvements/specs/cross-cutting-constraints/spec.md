# Spec: cross-cutting-constraints

- **Capability:** cross-cutting-constraints
- **Change:** perf-async-improvements
- **Status:** spec_complete

## Purpose

Capture the non-functional requirements, the per-PR acceptance summary, and the explicit out-of-scope items that apply across all three capability PRs of `perf-async-improvements`. These constraints MUST be satisfied by each of `shared-http-client`, `offloop-io`, and `lock-decomposition` in addition to their own capability-specific requirements.

## Non-functional requirements

### Requirement: External API contract frozen

The OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) and Anthropic-compatible (`/v1/messages`) request and response shapes MUST NOT change across any of the three PRs. Verified by the full existing test suite.

#### Scenario: Existing endpoint tests pass unchanged

- GIVEN the full pytest suite, including all OpenAI- and Anthropic-compatible endpoint tests
- WHEN the suite is run after any of the three PRs
- THEN all endpoint tests pass
- AND no request or response shape has changed.

### Requirement: No new dependencies

`asyncio.to_thread` (stdlib), `asyncio.Lock`/`Semaphore` (stdlib), and the existing `httpx` are the only tools used. No `aiosqlite`, `anyio`, or other new packages may be added.

#### Scenario: pyproject.toml / requirements free of new packages

- GIVEN the project's dependency manifest (`pyproject.toml` and/or `requirements*.txt`)
- WHEN a diff of dependency changes across any of the three PRs is inspected
- THEN no new runtime dependency is introduced.

### Requirement: Backwards compatibility of internal interfaces

Any module that calls `AccountManager.get_next_account()`, `report_success()`, or `report_failure()` MUST NOT need changes to its call sites. Method signatures are stable.

#### Scenario: Caller signatures unchanged

- GIVEN the public methods `get_next_account`, `report_success`, and `report_failure` on `AccountManager`
- WHEN the call sites in the codebase are inspected
- THEN no caller has been modified to accommodate new parameters
- AND method signatures are stable.

### Requirement: No event-loop blocking > 1 ms

After PR #2, no save operation may block the event loop thread for more than 1 ms. Verified by T-2.7.

#### Scenario: Heartbeat task advances during every save

- GIVEN a background heartbeat task as in T-2.7
- WHEN any save operation runs (`_save_state`, `_save_credentials_to_file`, `_save_credentials_to_sqlite`)
- THEN the heartbeat task advances at least once during the save
- AND no save blocks the event loop for more than 1 ms.

### Requirement: Each PR independently revertible

Reverting PR #3 MUST leave the codebase in the PR #2 state (functional and test-passing). Reverting PR #2 MUST leave the codebase in the PR #1 state.

#### Scenario: Revert chain leaves green test suite

- GIVEN the merged state of all three PRs
- WHEN PR #3 is reverted
- THEN the codebase matches the post-PR #2 state
- AND the test suite is green.
- WHEN PR #2 is then reverted
- THEN the codebase matches the post-PR #1 state
- AND the test suite is green.

### Requirement: Test suite growth

Each PR MUST add its own test scenarios (min: 2 for PR #1, 4 for PR #2, 6 for PR #3) without deleting existing tests.

#### Scenario: Test counts grow monotonically per PR

- GIVEN the test count baseline before PR #1, before PR #2, and before PR #3
- WHEN each PR is merged
- THEN the test count increases by at least the minimum specified for that PR
- AND no previously-existing test is removed.

### Requirement: Log levels preserved

No existing `logger.debug`, `logger.info`, `logger.warning`, or `logger.error` call site MUST be removed; new log calls MUST use appropriate levels consistent with the surrounding context.

#### Scenario: Existing log call sites preserved

- GIVEN the existing `logger.*` call sites in `kiro/`
- WHEN a diff across any of the three PRs is inspected
- THEN no existing log call site is removed
- AND new log calls use the level that matches their context (debug/info/warning/error).

## Acceptance criteria per PR (summary)

| PR | Gate | Metric |
|----|------|--------|
| #1 | No `httpx.AsyncClient()` in hot path | `rg` returns 0 matches in streaming/refresh handlers |
| #1 | `Connection: close` preserved | T-1.4 passes |
| #1 | No CLOSE_WAIT regression | T-1.6 passes |
| #2 | Saves run off event loop | T-2.1, T-2.3, T-2.4 pass |
| #2 | Atomic write preserved | T-2.2 passes |
| #2 | Load path stays sync | T-2.5 passes |
| #3 | No HTTP under global lock | T-3.1 passes |
| #3 | No TOCTOU on init | T-3.2 Hypothesis passes |
| #3 | Per-account isolation | T-3.3 passes |
| #3 | No deadlock | T-3.7 passes at N=50 |
| All | Full suite passes | `pytest tests/unit/` exits 0 |
| All | API contract unchanged | All existing endpoint tests pass |

## Out of scope

The following are explicitly excluded and MUST NOT appear in any of the three PRs:

- Multi-worker uvicorn / process-level scaling
- Replacing `run_in_executor` with `aiosqlite` or any new async DB dependency
- Rewriting `AwsEventStreamParser` buffer strategy
- Moving `tiktoken` token counting off the event loop
- Connection pooling infrastructure beyond reusing existing `app.state.http_client`
- Any change to the public OpenAI or Anthropic-compatible API request/response contract
- Performance profiling or load testing against real Kiro API endpoints

#### Scenario: None of the excluded items appear in the PRs

- GIVEN the diffs for each of the three PRs
- WHEN the changes are inspected for the excluded items listed above
- THEN none of those items have been introduced.
