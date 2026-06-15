# Spec: lock-decomposition

- **Capability:** lock-decomposition
- **Source change:** perf-async-improvements (PR #3)
- **Status:** merged

## Purpose

Decompose the single global `AccountManager._lock` so the critical section covers only in-memory state reads/writes and never network I/O. Add per-account concurrency control so a single account's TTL refresh does not block unrelated accounts or unrelated requests. Add double-checked locking for lazy account initialization. Concurrent refresh attempts for the same account MUST be deduplicated. External API contract is unchanged.

## Context

- `account_manager.py:210`: `self._lock = asyncio.Lock()` — single global lock.
- `get_next_account()`: acquires `_lock`, may call `_refresh_account_models()` (outbound HTTP) while lock is held.
- `_refresh_account_models()` at `account_manager.py:604`: creates a new `KiroHttpClient(auth_manager, shared_client=None)` and makes an HTTP GET — this is the HTTP-under-lock violation.
- `report_success()` / `report_failure()`: acquire `_lock` for in-memory counter updates.
- Depends on PR #1 (shared client available for refresh) and PR #2 (save-after-refresh no longer blocks).

## Lock acquisition order (MUST be documented and enforced)

To prevent deadlock, locks MUST always be acquired in this order when multiple are needed:

1. `AccountManager._coordination_lock` (global, in-memory mutations only)
2. Per-account `asyncio.Lock` or `asyncio.Semaphore` (for TTL refresh serialization)
3. `Auth._lock` (auth-object internal state — never acquire `_coordination_lock` while holding `Auth._lock`)

No coroutine MAY hold two cross-component locks across an `await` of an HTTP call. The rule is: release all locks before any `await client.request(...)` or `await client.send(...)`.

## Requirements

### Requirement: Global lock renamed and restricted to in-memory state

The global `AccountManager._lock` MUST be renamed `_coordination_lock` and its scope restricted to in-memory state reads and writes only. It MUST NOT be held while any `await` of an outbound HTTP call is pending.

#### Scenario: _coordination_lock never held across an HTTP await

- GIVEN an `AccountManager` with `_refresh_account_models` patched to record whether `_coordination_lock.locked()` is True at the moment of the HTTP call, and an account with an expired model TTL
- WHEN `await account_manager.get_next_account(model="test-model")` is called
- THEN `_coordination_lock.locked()` is `False` at the moment `_refresh_account_models` began its HTTP work.

### Requirement: get_next_account does not perform HTTP under coordination lock

`get_next_account()` MUST NOT perform HTTP (call `_refresh_account_models`) while holding `_coordination_lock`. The decision to refresh (check TTL) MUST happen under the lock; the actual HTTP call MUST happen after the lock is released.

#### Scenario: Refresh decision is in-memory; HTTP runs after lock release

- GIVEN an account with expired model TTL and `_refresh_account_models` patched to record the lock state at call time
- WHEN `get_next_account()` is invoked
- THEN the TTL check happens under `_coordination_lock`
- AND the HTTP call in `_refresh_account_models` runs after `_coordination_lock` is released.

### Requirement: Refresh results committed under coordination lock

After `_refresh_account_models()` completes outside the lock, the results (updated model list and `models_cached_at`) MUST be committed to in-memory state under a brief re-acquisition of `_coordination_lock`.

#### Scenario: Models cache and timestamp committed atomically

- GIVEN an account whose model cache is expired and `_refresh_account_models` returning a new model list
- WHEN the refresh completes
- THEN `account.models_cached_at` and the model list are updated under a brief `_coordination_lock` re-acquisition
- AND no concurrent reader observes a partially-updated cache.

> **Implementation note**: The pre-init sentinel guard `models_cached_at > 0` was intentionally dropped per the PR #3 design deviation. The implementation now treats `0.0` as "infinitely expired → must refresh" rather than as a pre-init sentinel. See SUGGESTION in `verify-report.md` (a code comment in `account_manager.py` explaining this contract would help future readers).

### Requirement: Double-checked locking for lazy account initialization

A **double-checked locking** pattern MUST guard lazy account initialization in `get_next_account()` to prevent TOCTOU races introduced by the lock split:

1. Check initialized state under `_coordination_lock`; if not initialized, release lock.
2. Acquire per-account lock, re-check initialized state under per-account lock.
3. Perform initialization; release per-account lock.
4. Re-acquire `_coordination_lock` to register the account.

#### Scenario: Concurrent initializers do not race on first call

- GIVEN 10 concurrent coroutines calling `get_next_account()` for a model with an uninitialized account, and `_initialize_account` patched to track call count
- WHEN `asyncio.gather(*[get_next_account() for _ in range(10)])` is run (Hypothesis property test over N in range [2, 20])
- THEN `_initialize_account` is called exactly once despite 10 concurrent callers.

### Requirement: Per-account locks isolate account-level operations

Each account MUST have a dedicated `asyncio.Lock` (or `asyncio.Semaphore(1)`) stored in a dict keyed by `account_id` (e.g. `self._account_locks: Dict[str, asyncio.Lock]`). A TTL refresh for account A MUST NOT block requests for account B.

#### Scenario: Account B is not blocked by account A's slow refresh

- GIVEN 2 accounts (A, B) with HTTP for account A patched to take 100 ms (simulate slow refresh), and both accounts' model caches expired
- WHEN concurrent requests for both accounts are issued
- THEN account B's request completes without waiting for account A's refresh
- AND wall-clock time for B is < 50 ms.

### Requirement: Concurrent refresh attempts for the same account are deduplicated

Concurrent TTL refresh attempts for the same account MUST be deduplicated: the second coroutine to arrive MUST wait on the per-account lock and then observe the already-updated cache (not trigger a second HTTP call). An in-flight marker (e.g. `self._refresh_in_flight: Set[str]`) MAY be used to short-circuit the second call.

#### Scenario: Five concurrent same-account requests cause one refresh

- GIVEN 1 account with expired TTL and `_refresh_account_models` patched to count HTTP call invocations and take 50 ms each
- WHEN 5 concurrent `get_next_account()` calls for that account are issued via `asyncio.gather()`
- THEN `_refresh_account_models` HTTP is called exactly once (not 5 times)
- AND all 5 callers receive a valid account.

### Requirement: report_success and report_failure are in-memory only

`report_success()` and `report_failure()` MUST acquire only `_coordination_lock` (in-memory counter mutation) and MUST NOT trigger any HTTP call or file I/O while the lock is held.

#### Scenario: report_success performs no HTTP call

- GIVEN `report_success()` is inspected or wrapped with a spy
- WHEN `report_success()` is called
- THEN it does not trigger any `await` of an HTTP call
- AND it only mutates in-memory counters and schedules `_save_state` (which is now off-loop per PR #2).

### Requirement: Stale model cache is served during in-flight refresh

Serving a stale model cache during an in-flight refresh for the same account is acceptable. Requests MUST NOT be blocked waiting for the refresh to complete; they MUST use the cached (possibly stale) model list and proceed.

#### Scenario: Second concurrent request is served from stale cache

- GIVEN 1 account with expired TTL and slow HTTP mock (200 ms), with the model list served to the first request captured
- WHEN a request is issued and, while refresh is in flight, a second request is issued
- THEN the second request is served (not blocked) using the stale model list
- AND no `TimeoutError` or deadlock occurs.

### Requirement: Lock acquisition order documented in source

The lock acquisition order defined above (coordination → per-account → auth) MUST be documented in a code comment at the point where the locks are declared. Violating this order in any code path is a spec violation.

#### Scenario: Source comment marks the lock order

- GIVEN the source file `account_manager.py`
- WHEN a grep for `# Lock acquisition order:` (or equivalent marker) is performed near the lock declarations
- THEN the marker is present.

### Requirement: No HTTP call inside the coordination lock window

`get_next_account()` MUST never make an HTTP call while holding `_coordination_lock`. This constraint MUST be statically verifiable by code inspection (no `await` inside the lock window except for the per-account lock acquisition).

#### Scenario: Static gate — no HTTP await inside _coordination_lock block

- GIVEN a search over `kiro/account_manager.py`
- WHEN `rg 'await.*request_with_retry|await.*http'` is run
- THEN no HTTP awaits are found inside any line within the `_coordination_lock` context manager block.
