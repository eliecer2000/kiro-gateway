# Spec: perf-async-improvements

- **Status:** spec_complete
- **Change name:** `perf-async-improvements`
- **Type:** architecture / performance
- **Delivery:** Chained PRs, stacked to main (#1 → #2 → #3)
- **Next recommended phase:** design

---

## Overview

This spec formalizes the requirements and test scenarios for three stacked pull requests that remove the top concurrency bottlenecks in kiro-gateway. The external API contract (OpenAI-compatible and Anthropic-compatible endpoints) is frozen for all PRs — no request or response shape may change.

**Concurrency baseline definition (applies to all PRs)**

Concurrency improvement is measured with a pytest fixture that issues `N` concurrent requests via `asyncio.gather()` against a fully-mocked Kiro API (no real network). The fixture uses `httpx.AsyncClient` with `transport=httpx.MockTransport(...)` or `respx` mocks. The metric is "maximum observed parallelism" (number of coroutines progressing simultaneously inside the gateway logic) and wall-clock time for `N=10` requests against `M=3` accounts. Baseline is captured by running the fixture against the pre-change code; post-change targets are specified per PR below.

---

## PR #1 — Shared streaming client + auth singleton

### Context

- `kiro/routes_openai.py:351` and `kiro/routes_anthropic.py:603` create `KiroHttpClient(auth_manager, shared_client=None)` for streaming requests, discarding TCP/TLS connection reuse.
- Non-streaming branches already pass `shared_client=request.app.state.http_client`.
- `kiro/auth.py:708` and `kiro/auth.py:825` each open `async with httpx.AsyncClient(...)` per token-refresh call, constructing and destroying a client on every refresh.
- `kiro/http_client.py:229` sets `Connection: close` on streaming requests to prevent CLOSE_WAIT socket leaks (issue #38).

### Functional requirements

**FR-1.1** — The streaming branch in `routes_openai.py` MUST pass `shared_client=request.app.state.http_client` to `KiroHttpClient`, matching the non-streaming branch.

**FR-1.2** — The streaming branch in `routes_anthropic.py` MUST pass `shared_client=request.app.state.http_client` to `KiroHttpClient`, matching the non-streaming branch.

**FR-1.3** — A module-level singleton `httpx.AsyncClient` MUST be created at application startup and registered on `app.state` (e.g. `app.state.auth_http_client`). Token-refresh code in `auth.py` (both `_refresh_kiro_desktop_token` and `_refresh_aws_sso_oidc_token`) MUST use this singleton instead of constructing a new client per call.

**FR-1.4** — The singleton auth client MUST be closed at application shutdown (lifespan or shutdown event). No use-after-close MUST occur.

**FR-1.5** — Streaming requests MUST continue to send `Connection: close` in the request headers (the existing line at `http_client.py:229` MUST be preserved and covered by a regression test).

**FR-1.6** — No `httpx.AsyncClient` constructor call MAY remain inside the hot path of a streaming request or a token-refresh call after this PR.

**FR-1.7** — The fallback behavior when `app.state.http_client` is `None` (e.g. in unit tests that do not configure the app) MUST not raise an `AttributeError`; it MUST fall back to a locally-scoped client with a warning log.

### Test scenarios

**T-1.1** `test_streaming_openai_uses_shared_client`
- Arrange: configure app with a mock `app.state.http_client`; mock the Kiro API to return a streaming response.
- Act: call the streaming OpenAI endpoint.
- Assert: `KiroHttpClient.__init__` receives the same object reference as `app.state.http_client`; no new `httpx.AsyncClient()` is constructed during the request.
- Label: `unit`

**T-1.2** `test_streaming_anthropic_uses_shared_client`
- Same as T-1.1 but targeting the Anthropic streaming endpoint.
- Label: `unit`

**T-1.3** `test_auth_refresh_uses_singleton_client`
- Arrange: patch `app.state.auth_http_client` with a mock; trigger `force_refresh()`.
- Assert: the mock client's `post` method is called; no new `httpx.AsyncClient()` is constructed inside the refresh path.
- Label: `unit`

**T-1.4** `test_connection_close_header_on_stream`
- Arrange: intercept the outgoing request via a mock transport.
- Act: call `http_client.request_with_retry(..., stream=True)`.
- Assert: the captured request headers contain `Connection: close`.
- Label: `unit`, regression for issue #38

**T-1.5** `test_auth_singleton_lifecycle`
- Arrange: start the FastAPI app via `httpx.AsyncClient(app=app, base_url=...)`.
- Assert: `app.state.auth_http_client` is not None after startup and is closed (`.is_closed == True`) after shutdown.
- Label: `integration`

**T-1.6** `test_no_close_wait_regression`
- Arrange: create 5 concurrent streaming requests via `asyncio.gather()` with a mock transport that counts active connections.
- Assert: no connection is left open (in ESTABLISHED or CLOSE_WAIT state) after all responses are consumed; active connection count returns to 0.
- Label: `unit`, regression for issue #38

### Acceptance criteria

- AC-1.A: All T-1.x tests pass.
- AC-1.B: `rg 'httpx.AsyncClient(' kiro/auth.py kiro/routes_openai.py kiro/routes_anthropic.py` returns no matches inside hot-path request handlers (only module-level or startup wiring is permitted).
- AC-1.C: Full pytest suite (1673 baseline + new tests) passes.
- AC-1.D: No `CLOSE_WAIT` socket leak observed under T-1.6 scenario.

---

## PR #2 — Async file/SQLite I/O via run_in_executor

### Context

- `account_manager.py:373` `_save_state`: synchronous `open(tmp_path, 'w') + json.dump + os.replace` runs on the event loop; uses atomic tmp+rename.
- `auth.py:489` `_save_credentials_to_file`: synchronous `open` + `json.dump` on the event loop.
- `auth.py:524` `_save_credentials_to_sqlite`: synchronous `sqlite3` operations on the event loop.
- `auth.py:248` `_load_credentials_from_sqlite`: synchronous, called from `Auth.__init__` (sync context). The sync load path MUST remain sync. Only async call sites (if any) get the executor wrapper.

No new dependencies are permitted. `asyncio.to_thread` (Python 3.9+, available on 3.14) is the preferred spelling over `loop.run_in_executor(None, ...)`.

### Functional requirements

**FR-2.1** — `_save_state` MUST delegate its blocking body (the `json.dump` + `os.replace` sequence) to a thread via `asyncio.to_thread`. The full tmp-write + atomic-rename sequence MUST execute as a single callable inside the thread (atomicity preserved).

**FR-2.2** — `_save_credentials_to_file` MUST delegate its blocking body to a thread via `asyncio.to_thread`. The method signature MUST become `async def`.

**FR-2.3** — `_save_credentials_to_sqlite` MUST delegate its blocking SQLite read-merge-write body to a thread via `asyncio.to_thread`. The method signature MUST become `async def`. The `SQLITE_READONLY` guard MUST be checked before entering the thread (cheap in-memory check stays on the loop).

**FR-2.4** — `_load_credentials_from_sqlite` MUST remain a synchronous method (`def`, not `async def`) because it is called from `Auth.__init__` which is a synchronous constructor. No change to call signature.

**FR-2.5** — A dedicated in-memory `asyncio.Lock` (e.g. `self._save_lock`) MUST serialize concurrent save operations for the same auth object, preventing interleaved writes to the same file or SQLite row.

**FR-2.6** — All callers of the newly-async save methods MUST `await` them. All call sites in `auth.py` that call `_save_credentials_to_file` or `_save_credentials_to_sqlite` MUST be in async context and use `await`.

**FR-2.7** — The event loop MUST NOT block for more than 1 ms during any save operation. A concurrent coroutine (e.g. a no-op async heartbeat task) MUST remain schedulable while a save is in progress.

**FR-2.8** — The `SQLITE_READONLY` environment flag behavior in `_save_credentials_to_sqlite` MUST be preserved: when set, the method returns immediately without entering the thread.

### Test scenarios

**T-2.1** `test_save_state_runs_off_event_loop`
- Arrange: patch `asyncio.to_thread` to record calls; create an `AccountManager` instance with a temp state file.
- Act: call `await account_manager._save_state()`.
- Assert: `asyncio.to_thread` was called with a callable (the blocking body); the event loop was not blocked (a concurrent `asyncio.sleep(0)` task completes before the save callable finishes).
- Label: `unit`

**T-2.2** `test_save_state_atomic_write`
- Arrange: set up a temp directory; create an `AccountManager` with real files.
- Act: call `await account_manager._save_state()` with a simulated crash injected mid-write (patch `os.replace` to raise after `json.dump`).
- Assert: the original state file is intact (not corrupted); the `.tmp` file may or may not exist.
- Label: `unit`

**T-2.3** `test_save_credentials_to_file_runs_off_event_loop`
- Arrange: patch `asyncio.to_thread`; create an `Auth` instance with a temp credentials file.
- Act: call `await auth._save_credentials_to_file()`.
- Assert: `asyncio.to_thread` was called; no synchronous `open()` call occurs on the calling coroutine's frame.
- Label: `unit`

**T-2.4** `test_save_credentials_to_sqlite_runs_off_event_loop`
- Arrange: patch `asyncio.to_thread`; create an `Auth` instance with a temp SQLite database.
- Act: call `await auth._save_credentials_to_sqlite()`.
- Assert: `asyncio.to_thread` was called; `sqlite3.connect` is not called from the event loop thread.
- Label: `unit`

**T-2.5** `test_load_credentials_from_sqlite_remains_sync`
- Assert: `auth._load_credentials_from_sqlite` is a regular function (not a coroutine function): `not asyncio.iscoroutinefunction(auth._load_credentials_from_sqlite)`.
- Act: call it directly from a non-async context without `await`.
- Assert: no `RuntimeWarning` is raised.
- Label: `unit`

**T-2.6** `test_concurrent_saves_serialized`
- Arrange: create an `Auth` instance; patch `asyncio.to_thread` to record call order with timestamps; issue 5 concurrent `_save_credentials_to_sqlite()` calls via `asyncio.gather()`.
- Assert: no two save callables overlap in execution (the `_save_lock` serializes them); the final state is one of the 5 valid states, not a corrupt merge.
- Label: `unit`

**T-2.7** `test_event_loop_unblocked_during_save`
- Arrange: start a background task that appends a timestamp every `asyncio.sleep(0)` iteration.
- Act: trigger a `_save_state()` call that takes at least 20 ms (use `asyncio.to_thread` with a real `time.sleep(0.02)` inside).
- Assert: the background task was scheduled at least once during the save (it appended a timestamp), proving the event loop was not blocked.
- Label: `unit`

**T-2.8** `test_sqlite_readonly_flag_skips_write`
- Arrange: set `SQLITE_READONLY=true` in environment; create an `Auth` instance with a SQLite DB.
- Act: call `await auth._save_credentials_to_sqlite()`.
- Assert: `asyncio.to_thread` is NOT called (no write attempted); DB is unchanged.
- Label: `unit`

### Acceptance criteria

- AC-2.A: All T-2.x tests pass.
- AC-2.B: `_save_state`, `_save_credentials_to_file`, `_save_credentials_to_sqlite` are all `async def` and delegate blocking work to `asyncio.to_thread`.
- AC-2.C: `_load_credentials_from_sqlite` remains `def` (synchronous).
- AC-2.D: `rg 'sqlite3\.connect|open\(' kiro/account_manager.py kiro/auth.py` shows no blocking I/O calls in async functions outside of `asyncio.to_thread` wrappers.
- AC-2.E: Full pytest suite passes.

---

## PR #3 — Global lock decomposition + per-account semaphores

### Context

- `account_manager.py:210`: `self._lock = asyncio.Lock()` — single global lock.
- `get_next_account()`: acquires `_lock`, may call `_refresh_account_models()` (outbound HTTP) while lock is held.
- `_refresh_account_models()` at `account_manager.py:604`: creates a new `KiroHttpClient(auth_manager, shared_client=None)` and makes an HTTP GET — this is the HTTP-under-lock violation.
- `report_success()` / `report_failure()`: acquire `_lock` for in-memory counter updates.
- After PR #1: shared client available for refresh. After PR #2: save-after-refresh no longer blocks. PR #3 builds on both.

### Lock acquisition order (MUST be documented and enforced)

To prevent deadlock, locks MUST always be acquired in this order when multiple are needed:

1. `AccountManager._coordination_lock` (global, in-memory mutations only)
2. Per-account `asyncio.Lock` or `asyncio.Semaphore` (for TTL refresh serialization)
3. `Auth._lock` (auth-object internal state — never acquire `_coordination_lock` while holding `Auth._lock`)

No coroutine MAY hold two cross-component locks across an `await` of an HTTP call. The rule is: release all locks before any `await client.request(...)` or `await client.send(...)`.

### Functional requirements

**FR-3.1** — The global `AccountManager._lock` MUST be renamed `_coordination_lock` and its scope restricted to in-memory state reads and writes only. It MUST NOT be held while any `await` of an outbound HTTP call is pending.

**FR-3.2** — `get_next_account()` MUST NOT perform HTTP (call `_refresh_account_models`) while holding `_coordination_lock`. The decision to refresh (check TTL) MUST happen under the lock; the actual HTTP call MUST happen after the lock is released.

**FR-3.3** — After `_refresh_account_models()` completes outside the lock, the results (updated model list and `models_cached_at`) MUST be committed to in-memory state under a brief re-acquisition of `_coordination_lock`.

**FR-3.4** — A **double-checked locking** pattern MUST guard lazy account initialization in `get_next_account()` to prevent TOCTOU races introduced by the lock split:
  1. Check initialized state under `_coordination_lock`; if not initialized, release lock.
  2. Acquire per-account lock, re-check initialized state under per-account lock.
  3. Perform initialization; release per-account lock.
  4. Re-acquire `_coordination_lock` to register the account.

**FR-3.5** — Each account MUST have a dedicated `asyncio.Lock` (or `asyncio.Semaphore(1)`) stored in a dict keyed by `account_id` (e.g. `self._account_locks: Dict[str, asyncio.Lock]`). A TTL refresh for account A MUST NOT block requests for account B.

**FR-3.6** — Concurrent TTL refresh attempts for the same account MUST be deduplicated: the second coroutine to arrive MUST wait on the per-account lock and then observe the already-updated cache (not trigger a second HTTP call). An in-flight marker (e.g. `self._refresh_in_flight: Set[str]`) MAY be used to short-circuit the second call.

**FR-3.7** — `report_success()` and `report_failure()` MUST acquire only `_coordination_lock` (in-memory counter mutation) and MUST NOT trigger any HTTP call or file I/O while the lock is held.

**FR-3.8** — Serving a stale model cache during an in-flight refresh for the same account is acceptable. Requests MUST NOT be blocked waiting for the refresh to complete; they MUST use the cached (possibly stale) model list and proceed.

**FR-3.9** — The lock acquisition order defined above (coordination → per-account → auth) MUST be documented in a code comment at the point where the locks are declared. Violating this order in any code path is a spec violation.

**FR-3.10** — `get_next_account()` MUST never make an HTTP call while holding `_coordination_lock`. This constraint MUST be statically verifiable by code inspection (no `await` inside the lock window except for the per-account lock acquisition).

### Test scenarios

**T-3.1** `test_no_http_under_global_lock`
- Arrange: patch `_refresh_account_models` to record whether `_coordination_lock.locked()` is True at the moment of the HTTP call; set up an account with an expired model TTL.
- Act: call `await account_manager.get_next_account(model="test-model")`.
- Assert: `_coordination_lock.locked()` was `False` at the moment `_refresh_account_models` began its HTTP work.
- Label: `unit`, key correctness test

**T-3.2** `test_double_checked_locking_no_toctou`
- Arrange: 10 concurrent coroutines all call `get_next_account()` for a model with an uninitialized account; patch `_initialize_account` to track call count.
- Act: `asyncio.gather(*[get_next_account() for _ in range(10)])`.
- Assert: `_initialize_account` is called exactly once despite 10 concurrent callers.
- Label: `unit`, Hypothesis property test over N in range [2, 20]

**T-3.3** `test_per_account_refresh_isolation`
- Arrange: 2 accounts (A, B); patch HTTP for account A to take 100 ms (simulate slow refresh); set both accounts' model caches as expired.
- Act: issue concurrent requests for both accounts.
- Assert: account B's request completes without waiting for account A's refresh; wall-clock time for B is < 50 ms.
- Label: `unit`

**T-3.4** `test_concurrent_refresh_deduplication`
- Arrange: 1 account with expired TTL; patch `_refresh_account_models` to count HTTP call invocations and take 50 ms each.
- Act: 5 concurrent `get_next_account()` calls for that account via `asyncio.gather()`.
- Assert: `_refresh_account_models` HTTP is called exactly once (not 5 times); all 5 callers receive a valid account.
- Label: `unit`

**T-3.5** `test_stale_cache_served_during_refresh`
- Arrange: 1 account with expired TTL; slow HTTP mock (200 ms); capture the model list served to the first request.
- Act: issue a request; while refresh is in flight, issue a second request.
- Assert: the second request is served (not blocked) using the stale model list; no `TimeoutError` or deadlock.
- Label: `unit`

**T-3.6** `test_report_success_no_http`
- Assert: `report_success()` does not trigger any `await` of an HTTP call; it only mutates in-memory counters and calls `_save_state` (which is now off-loop per PR #2).
- Label: `unit`

**T-3.7** `test_no_deadlock_concurrent_multi_account`
- Arrange: 3 accounts; 20 concurrent requests spread across all accounts; all accounts have expired TTL.
- Act: `asyncio.gather(*requests)` with a timeout of 5 s.
- Assert: all 20 requests complete within the timeout; no `asyncio.TimeoutError`.
- Label: `unit`, Hypothesis property test over account count in [2, 5] and request count in [10, 50]

**T-3.8** `test_lock_acquisition_order_documented`
- Assert: the source file `account_manager.py` contains the string `# Lock acquisition order:` (or equivalent marker) near the lock declarations. This is a code-review gate encoded as a grep-based test.
- Label: `unit`

**T-3.9** `test_concurrency_throughput_improvement`
- Arrange: baseline fixture — run 10 concurrent requests against a 3-account mock under the old single-lock code path (captured via a feature flag or separate fixture).
- Post-change fixture — same 10 concurrent requests with lock decomposition active.
- Assert: wall-clock time with decomposition is at most 50% of baseline wall-clock time (i.e., at least 2× throughput improvement) under the mocked scenario where refresh takes 50 ms.
- Label: `integration`, performance

### Acceptance criteria

- AC-3.A: All T-3.x tests pass.
- AC-3.B: `rg 'await.*request_with_retry|await.*http' kiro/account_manager.py` shows no HTTP awaits inside any line that is within the `_coordination_lock` context manager block.
- AC-3.C: T-3.2 Hypothesis test finds no TOCTOU shrink case.
- AC-3.D: T-3.7 deadlock test passes with 0 timeouts.
- AC-3.E: Full pytest suite passes.
- AC-3.F: Lock acquisition order is documented in source code as required by FR-3.9.

---

## Non-functional requirements

**NFR-1 — External API contract frozen.** The OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) and Anthropic-compatible (`/v1/messages`) request and response shapes MUST NOT change across any of the three PRs. Verified by the full existing test suite.

**NFR-2 — No new dependencies.** `asyncio.to_thread` (stdlib), `asyncio.Lock`/`Semaphore` (stdlib), and the existing `httpx` are the only tools used. No `aiosqlite`, `anyio`, or other new packages may be added.

**NFR-3 — Backwards compatibility of internal interfaces.** Any module that calls `AccountManager.get_next_account()`, `report_success()`, or `report_failure()` MUST NOT need changes to its call sites. Method signatures are stable.

**NFR-4 — No event-loop blocking > 1 ms.** After PR #2, no save operation may block the event loop thread for more than 1 ms. Verified by T-2.7.

**NFR-5 — Each PR independently revertible.** Reverting PR #3 MUST leave the codebase in the PR #2 state (functional and test-passing). Reverting PR #2 MUST leave the codebase in the PR #1 state.

**NFR-6 — Test suite growth.** Each PR MUST add its own test scenarios (min: 2 for PR #1, 4 for PR #2, 6 for PR #3) without deleting existing tests.

**NFR-7 — Log levels preserved.** No existing `logger.debug`, `logger.info`, `logger.warning`, or `logger.error` call site MUST be removed; new log calls MUST use appropriate levels consistent with the surrounding context.

---

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

---

## Out of scope

The following are explicitly excluded and MUST NOT appear in any of the three PRs:

- Multi-worker uvicorn / process-level scaling
- Replacing `run_in_executor` with `aiosqlite` or any new async DB dependency
- Rewriting `AwsEventStreamParser` buffer strategy
- Moving `tiktoken` token counting off the event loop
- Connection pooling infrastructure beyond reusing existing `app.state.http_client`
- Any change to the public OpenAI or Anthropic-compatible API request/response contract
- Performance profiling or load testing against real Kiro API endpoints
