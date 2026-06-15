# Design: perf-async-improvements

- **Status:** design_complete
- **Change name:** `perf-async-improvements`
- **Type:** architecture / performance
- **Delivery:** Chained PRs, stacked to main (#1 → #2 → #3)
- **Next recommended phase:** tasks

---

## 1. Architecture overview

The change removes three classes of event-loop contention without altering the external API contract:

1. **Client reuse** — stop constructing a fresh `httpx.AsyncClient` per streaming request and per token refresh.
2. **Off-loop blocking I/O** — move file/SQLite save work into worker threads via `asyncio.to_thread`.
3. **Lock decomposition** — replace the single `AccountManager._lock` with a narrow in-memory coordination lock plus per-account locks, so no outbound HTTP runs inside a critical section.

### 1.1 Verified current state (read before designing)

| Claim | Verified at | Notes |
|-------|-------------|-------|
| Streaming uses `shared_client=None` | `routes_openai.py:351`, `routes_anthropic.py:414`, `routes_anthropic.py:726`, `routes_openai.py:603` | Non-streaming already uses `request.app.state.http_client` |
| Token refresh opens a client inline | `auth.py:708` (Kiro Desktop), `auth.py:825` (AWS SSO OIDC) | `async with httpx.AsyncClient(timeout=30) as client:` |
| `Connection: close` already present | `http_client.py:229` | Only set on `stream=True`; mitigates issue #38 |
| Shared client + lifespan exist | `main.py:351`, `main.py:530` | `app.state.http_client` created at startup, `aclose()` at shutdown |
| `_save_state` callers are async | `main.py:503` (startup), `main.py:525` (shutdown), `account_manager.py:429` (periodic) | All await-capable → safe to make `async` |
| `_load_credentials_from_sqlite` called from sync `__init__` AND async `get_access_token` | `auth.py:896` (async path), constructor path (sync) | Must stay `def`; async caller wraps inline |
| `_lock` held across HTTP | `account_manager.py:663-763` (`get_next_account`), via `_initialize_account` (2 HTTP) + `_refresh_account_models` (1 HTTP) | The core bottleneck |
| `_refresh_account_models` / `_initialize_account` build `shared_client=None` | `account_manager.py:516`, `account_manager.py:604` | These are also PR #1 client-reuse targets, indirectly |

### 1.2 Lock hierarchy (PR #3 target state)

```
                          AccountManager
  ┌──────────────────────────────────────────────────────────────┐
  │                                                                │
  │  _coordination_lock : asyncio.Lock      (LEVEL 1 — global)     │
  │  ──────────────────────────────────────                       │
  │  Protects ONLY in-memory state, held for microseconds:        │
  │    • _current_account_index (read/write)                      │
  │    • _accounts dict structure (membership, iteration snapshot)│
  │    • _model_to_accounts dict structure                        │
  │    • account.failures / account.stats counters                │
  │    • account.models_cached_at (commit after refresh)          │
  │  NEVER held across `await <http>`                             │
  │                                                                │
  │  _account_locks : Dict[str, asyncio.Lock]   (LEVEL 2)         │
  │  ────────────────────────────────────────                    │
  │  One lock per account_id. Serializes:                         │
  │    • lazy _initialize_account (HTTP) — one init per account   │
  │    • _refresh_account_models (HTTP) — dedups same-account     │
  │  Different accounts proceed concurrently.                     │
  │  HTTP awaits happen UNDER this lock, NOT under L1.            │
  │                                                                │
  └──────────────────────────────────────────────────────────────┘
                          │ (separate component)
                          ▼
                    KiroAuthManager
  ┌──────────────────────────────────────────────────────────────┐
  │  _lock : asyncio.Lock                       (LEVEL 3)         │
  │  Auth-object internal token state. Already exists.            │
  │  NEVER acquire L1 while holding L3.                           │
  └──────────────────────────────────────────────────────────────┘

ACQUISITION ORDER (must be documented in source — FR-3.9):
   L1 (_coordination_lock)  →  L2 (per-account lock)  →  L3 (Auth._lock)

INVARIANT: release ALL of L1 before any `await client.send/request`.
           HTTP is permitted only under L2 (or no lock at all).
```

`AccountStats` counter increments are covered by L1 (they are microsecond dict/int writes; a separate per-account lock would add overhead without benefit). The proposal text floated per-account locks for stats, but stats live on the same `Account` object the coordination lock already touches, so folding them into L1 keeps the hierarchy two-deep and avoids a third lock-acquire on every `report_success`.

---

## 2. Detailed design per PR

### PR #1 — Shared streaming client + auth singleton

**2.1.1 Streaming client reuse (FR-1.1, FR-1.2)**

Both streaming branches change from:

```python
if request_data.stream:
    http_client = KiroHttpClient(auth_manager, shared_client=None)
else:
    shared_client = request.app.state.http_client
    http_client = KiroHttpClient(auth_manager, shared_client=shared_client)
```

to a single resolution that always reuses the shared client, with a `None`-safe fallback (FR-1.7):

```python
shared_client = getattr(request.app.state, "http_client", None)
if shared_client is None:
    logger.warning("app.state.http_client missing; falling back to per-request client")
http_client = KiroHttpClient(auth_manager, shared_client=shared_client)
```

`KiroHttpClient` already handles `shared_client=None` by lazily creating an owned client in `_get_client` (`http_client.py:127`), and `close()` is a no-op for shared clients (`http_client.py:159`). The streaming timeout (`STREAMING_READ_TIMEOUT`) is already configured on `app.state.http_client` (`main.py:347`), so no per-request timeout override is lost. `Connection: close` is still applied in `request_with_retry` (`http_client.py:229`) — **unchanged** (FR-1.5).

Touch points: `routes_openai.py:351`, `routes_anthropic.py:414`, `routes_anthropic.py:726`, `routes_openai.py:603`. (Two streaming sites per file — the second pair is the failover/secondary path; both must be converted.)

**2.1.2 Auth refresh singleton (FR-1.3, FR-1.4) — chosen design: constructor injection (Option A)**

**Decision: Option A (constructor injection) over module-level singleton (B) or lazy AccountManager-owned (C).**

Rationale: A is explicit and testable — a test passes a `MockTransport`-backed client directly. B (module singleton) hides global state, is hard to reset between tests, and risks use-after-close across event loops. C couples client creation to AccountManager and still needs threading the client into auth, i.e. it is A plus indirection.

Design:

1. Add `refresh_client: Optional[httpx.AsyncClient] = None` to `KiroAuthManager.__init__` (`auth.py:119`). Store as `self._refresh_client`.
2. `_refresh_token_kiro_desktop` (`auth.py:708`) and `_refresh_token_aws_sso_oidc` (`auth.py:825`) replace the inline `async with httpx.AsyncClient(...)` with a resolved client:

```python
client = self._refresh_client
owns = client is None
if owns:
    logger.warning("No shared refresh client; creating a per-call client")
    client = httpx.AsyncClient(timeout=30)
try:
    response = await client.post(self._refresh_url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
finally:
    if owns:
        await client.aclose()
```

This preserves the `timeout=30` semantics (note: distinct from the streaming client's 300 s read timeout — token refresh should stay short, so the injected client must be configured with a 30 s timeout, see lifespan below).

3. **Lifespan wiring** (`main.py:351` block): create a dedicated short-timeout client for auth refresh and register it on `app.state`:

```python
app.state.auth_http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)
```

Closed at shutdown next to `app.state.http_client.aclose()` (`main.py:530`):

```python
await app.state.auth_http_client.aclose()
```

4. **Threading the client to auth managers.** `KiroAuthManager` instances are created inside `AccountManager._initialize_account` (`account_manager.py:473/480/487`). `AccountManager` must receive `app.state.auth_http_client` so it can pass it into each `KiroAuthManager(...)`. Add an optional `auth_http_client` parameter to `AccountManager.__init__` (stored as `self._auth_http_client`), set when the manager is constructed in `main.py:456`, and forwarded as `refresh_client=self._auth_http_client` in all three `KiroAuthManager(...)` constructions.

**Lifecycle summary:**

```
startup (lifespan)
  └─ app.state.auth_http_client = AsyncClient(timeout=30)
  └─ AccountManager(..., auth_http_client=app.state.auth_http_client)
       └─ _initialize_account → KiroAuthManager(..., refresh_client=self._auth_http_client)
                                    └─ _refresh_token_* uses self._refresh_client
shutdown (lifespan)
  └─ app.state.auth_http_client.aclose()
```

Use-after-close guard (R2): the client is closed only after `save_task` is cancelled and the final save completes, by which point no request handler is running. The `owns`/fallback branch above also means a `None` or closed injected client degrades to a per-call client rather than raising.

---

### PR #2 — Async file/SQLite I/O via asyncio.to_thread

**Pattern:** keep the cheap guards (path checks, `SQLITE_READONLY`, `self._creds_file` presence) on the event loop; move only the blocking body into `asyncio.to_thread`.

**2.2.1 `_save_state` (FR-2.1, account_manager.py:373)**

Stays `async def`. The whole tmp-write + `replace` is one closure passed to `to_thread`, preserving atomicity (R3). Building `state_data` reads in-memory dicts and must happen under `_coordination_lock` in PR #3, but the dict snapshot is cheap and stays on the loop; only the serialization+write goes to the thread:

```python
async def _save_state(self) -> None:
    state_data = { ... }            # build snapshot on loop (microseconds)
    state_path = Path(self._state_file)
    tmp_path = state_path.with_suffix('.json.tmp')

    def _write() -> None:
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(state_path)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            if tmp_path.exists():
                tmp_path.unlink()

    async with self._save_lock:          # new lock, see 2.2.4
        await asyncio.to_thread(_write)
```

`json.dump` is moved into the thread because for large state files serialization itself can block. Callers at `main.py:503`, `main.py:525`, and `account_manager.py:429` already `await` it — no signature change to callers.

**2.2.2 `_save_credentials_to_file` (FR-2.2, auth.py:489) → `async def`**

Move the read-existing + write to the thread as one closure (read-modify-write must be atomic w.r.t. the file). Caller sites at `auth.py:741` become `await self._save_credentials_to_file()`.

**2.2.3 `_save_credentials_to_sqlite` (FR-2.3, FR-2.8, auth.py:524) → `async def`**

`SQLITE_READONLY` and `self._sqlite_db` checks stay on the loop (return before entering the thread → T-2.8). The `sqlite3.connect` + read-merge-write + commit goes into one closure passed to `to_thread`. Caller at `auth.py:739` becomes `await self._save_credentials_to_sqlite()`.

**2.2.4 Save serialization lock (FR-2.5)**

Add `self._save_lock = asyncio.Lock()` to `KiroAuthManager.__init__` and a separate one to `AccountManager.__init__`. It serializes concurrent saves to the same file/DB from the same object. Because the save methods are now called from `force_refresh`/`get_access_token` (both already under `KiroAuthManager._lock`), the save lock is mostly defensive against future concurrent callers; it is cheap and prevents interleaved thread writes (R5). The save lock is **always** released before returning and is never held across L1/L2.

**2.2.5 `_load_credentials_from_sqlite` stays sync (FR-2.4)**

It is called from the synchronous `__init__` and from async `get_access_token` (`auth.py:896`). It MUST remain `def`. For the async call site, the load is short (single-row read) and already inside the `KiroAuthManager._lock` critical section of `get_access_token`; the spec does not require wrapping it (FR-2.4 explicitly forbids changing its signature). If profiling later shows it matters, the async caller can wrap it as `await asyncio.to_thread(self._load_credentials_from_sqlite, self._sqlite_db)` — noted as a future option, **out of scope** for this PR to keep `__init__` untouched.

---

### PR #3 — Lock decomposition

**2.3.1 New members on `AccountManager.__init__` (account_manager.py:210)**

```python
# Lock acquisition order (MUST hold): coordination → per-account → Auth._lock.
# Never hold _coordination_lock across an `await` of an HTTP call.
self._coordination_lock = asyncio.Lock()        # was self._lock
self._account_locks: Dict[str, asyncio.Lock] = {}
self._refresh_in_flight: set[str] = set()         # dedup marker (FR-3.6)
```

`self._lock` is renamed `_coordination_lock` everywhere (`save_state_periodically:428`, `report_success:773`, `report_failure:827`, `get_next_account:663`). NFR-3: external callers (`report_success`/`report_failure`/`get_next_account`) keep identical signatures.

**2.3.2 `_get_account_lock` helper**

```python
def _get_account_lock(self, account_id: str) -> asyncio.Lock:
    # Called only while holding _coordination_lock (dict mutation must be serialized).
    lock = self._account_locks.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        self._account_locks[account_id] = lock
    return lock
```

**2.3.3 `get_next_account` restructure (FR-3.1, FR-3.2, FR-3.4, FR-3.10)**

The current method does selection + lazy init (HTTP) + TTL refresh (HTTP) all under one lock. New flow splits selection (L1, fast) from init/refresh (L2, HTTP outside L1):

```python
async def get_next_account(self, model, exclude_accounts=None):
    # --- Phase A: SELECT candidate under L1 (no HTTP) ---
    async with self._coordination_lock:
        account_id, account = self._select_candidate(model, exclude_accounts)  # pure in-memory
        if account_id is None:
            return None
        needs_init = account.auth_manager is None
        needs_refresh = (not needs_init
                         and account.models_cached_at > 0
                         and (time.time() - account.models_cached_at) > ACCOUNT_CACHE_TTL)
    # L1 RELEASED here. No HTTP has run under L1.

    # --- Phase B: lazy init under L2 (HTTP, double-checked) ---
    if needs_init:
        async with self._account_lock_for(account_id):     # L2
            if account.auth_manager is None:                 # double-check (FR-3.4)
                ok = await self._initialize_account(account_id)  # HTTP under L2 only
                if not ok:
                    async with self._coordination_lock:      # commit failure under L1
                        account.failures += 1
                        self._dirty = True
                    return None
        needs_refresh = False  # fresh init means cache is current

    # --- Phase C: TTL refresh under L2, deduped, non-blocking stale serve ---
    if needs_refresh:
        await self._maybe_refresh(account_id)   # see 2.3.4

    return account
```

`_account_lock_for(account_id)` wraps `_get_account_lock` but briefly re-takes L1 to mutate `_account_locks` per the ordering rule:

```python
async def _account_lock_for(self, account_id):
    async with self._coordination_lock:
        return self._get_account_lock(account_id)
```

`_select_candidate` is the existing single-account and multi-account selection logic (lines 664–763) refactored into a pure in-memory function returning `(account_id, account)` or `(None, None)` — no `await`, no HTTP. The Circuit Breaker / sticky / probabilistic-retry logic is unchanged; it just no longer calls `_initialize_account` or `_refresh_account_models` inline.

**Double-checked locking (FR-3.4):** the fast `needs_init` read happens under L1; the slow path re-checks `account.auth_manager is None` under L2. Ten concurrent callers → first wins the L2 lock and initializes, the other nine re-check under L2, see a non-`None` `auth_manager`, and skip (→ T-3.2, exactly one `_initialize_account`).

**2.3.4 TTL refresh dedup + stale-serve (FR-3.5, FR-3.6, FR-3.8)**

```python
async def _maybe_refresh(self, account_id):
    async with self._coordination_lock:               # L1, microseconds
        if account_id in self._refresh_in_flight:
            return                                     # someone else is refreshing → serve stale
        self._refresh_in_flight.add(account_id)
        lock = self._get_account_lock(account_id)
    try:
        async with lock:                              # L2, HTTP under here only
            await self._refresh_account_models(account_id)   # commit results under L1 inside
    finally:
        async with self._coordination_lock:
            self._refresh_in_flight.discard(account_id)
```

Design note on FR-3.8 ("requests MUST NOT block waiting for refresh"): the *second* concurrent caller for the same account observes `account_id in _refresh_in_flight` and returns immediately, serving the stale cache. The *first* caller awaits the refresh (it triggered it). This satisfies "no second HTTP call" (FR-3.6) and "stale served without blocking" for all-but-the-triggering request (FR-3.8). The triggering request waiting for its own refresh matches current behavior and is acceptable; if even the first request must not block, refresh can be moved to `asyncio.create_task` (fire-and-forget) — documented as an alternative, but the await-under-L2 form is chosen because it keeps error handling and `_dirty` commit deterministic and testable (T-3.4, T-3.5).

**2.3.5 `_refresh_account_models` commit under L1 (FR-3.3)**

The HTTP GET stays outside L1 (it already builds its own `KiroHttpClient`; in PR #1 chain it should reuse `app.state.http_client` — see note below). After the response is parsed, the in-memory mutation (`model_cache.update`, `models_cached_at`, `_model_to_accounts` append, `_dirty`) is committed under a brief L1 re-acquire:

```python
# ... HTTP done (outside L1) ...
if response.status_code == 200:
    models_list = response.json().get("models", [])
    await account.model_cache.update(models_list)        # cache is its own structure
    async with self._coordination_lock:
        account.models_cached_at = time.time()
        for m in account.model_resolver.get_available_models():
            self._model_to_accounts.setdefault(m, ModelAccountList())
            if account_id not in self._model_to_accounts[m].accounts:
                self._model_to_accounts[m].accounts.append(account_id)
        self._dirty = True
```

`_initialize_account` gets the same treatment: HTTP (token fetch + ListAvailableModels) runs under L2, and the registration of `account.auth_manager`/`model_cache`/`_model_to_accounts` (lines 560–574) is committed under a brief L1 re-acquire. Note `_initialize_account` and `_refresh_account_models` currently build `KiroHttpClient(..., shared_client=None)` (`account_manager.py:516`, `:604`); PR #1's reuse principle suggests passing the shared client here too, but these run inside AccountManager which has no `request` object. Threading `app.state.http_client` into `AccountManager` (same mechanism as the auth client in PR #1) lets these reuse the pool. **Scope note:** the spec's PR #1 FRs target the route handlers and auth refresh only; reusing the shared client in these two AccountManager call sites is a natural extension and SHOULD be done in PR #3 when these methods are already being edited, but is not a hard PR #1 requirement.

**2.3.6 `report_success` / `report_failure` (FR-3.7)**

Swap `self._lock` → `self._coordination_lock`. Bodies are already pure in-memory counter mutation (no HTTP, no I/O) — they satisfy FR-3.7 unchanged. They do NOT call `_save_state` synchronously; persistence happens via the periodic `save_state_periodically` task (which after PR #2 awaits the off-loop save). This matches T-3.6.

**2.3.7 Lock ordering documentation (FR-3.9)** — the comment block in 2.3.1 sits at the lock declarations; T-3.8 greps for `# Lock acquisition order:`.

---

## 3. Data flow — new `get_next_account()`

```
Request arrives ──► get_next_account(model)
        │
        ▼
  ┌─────────────────────────── L1 (coordination_lock) ───────────────────────────┐
  │  _select_candidate: sticky index, circuit breaker, exclude set  (pure mem)    │
  │  read account.auth_manager is None  → needs_init                               │
  │  read models_cached_at age          → needs_refresh                            │
  └───────────────────────────────── release L1 ─────────────────────────────────┘
        │
        ├── needs_init? ──► L2 (per-account lock) ──► double-check ──► _initialize_account
        │                        │                                       (token fetch + HTTP)
        │                        │                                  commit under brief L1
        │                        ▼
        │                   release L2
        │
        ├── needs_refresh? ──► L1: check _refresh_in_flight
        │                         ├─ in flight ──► return (serve STALE, no block)  ◄── 2nd caller
        │                         └─ not in flight ──► mark + get L2 lock, release L1
        │                                  └─ L2: _refresh_account_models (HTTP)
        │                                          commit results under brief L1
        │                                  finally: L1 clear _refresh_in_flight
        │
        ▼
   return account   (object reference; caller does the upstream Kiro request)
```

Concurrency property: while account A holds its L2 lock across a 100 ms refresh, account B's request acquires L1 (microseconds), finds B's candidate, takes B's *separate* L2 lock, and proceeds — no cross-account blocking (T-3.3). L1 is never held during any HTTP await (T-3.1, AC-3.B).

---

## 4. Dependency graph between PRs

```
        ┌─────────┐
        │  PR #1  │  shared streaming client + auth singleton (Low risk)
        └────┬────┘
             │  provides: app.state.auth_http_client, shared-client habit
             ▼
        ┌─────────┐
        │  PR #2  │  async file/SQLite I/O (Medium risk)
        └────┬────┘   provides: off-loop saves → safe to commit refresh+save under brief lock
             │
             ▼
        ┌─────────┐
        │  PR #3  │  lock decomposition (High risk)
        └─────────┘   depends on #1 (client to reuse in extracted refresh)
                       depends on #2 (saves no longer block under any lock)
```

- PR #2 is technically independent of PR #1 but stacks after it for linear history (proposal §"Dependencies between PRs").
- PR #3 hard-depends on both: it relies on PR #1's shared/auth client being available to the extracted refresh path, and on PR #2 ensuring the `_save_state` it may trigger does not re-block under the brief L1 re-acquire.
- Each PR is independently revertible (NFR-5): reverting #3 leaves #2 state; reverting #2 leaves #1 state.

---

## 5. Testing approach per PR

**Shared concurrency fixture (spec §"Concurrency baseline"):** `httpx.MockTransport` / `respx`-backed `app.state.http_client`; `asyncio.gather()` of N requests over M accounts; metric = max observed parallelism + wall-clock for N=10, M=3.

### PR #1
- **Reference identity** (T-1.1, T-1.2): spy on `KiroHttpClient.__init__` and assert the `shared_client` arg `is request.app.state.http_client`; assert no `httpx.AsyncClient(` constructed during the request (patch the constructor to count).
- **Singleton refresh** (T-1.3): inject a `MockTransport` client as `refresh_client`, call `force_refresh()`, assert `.post` called on the injected client, no new client built.
- **Connection: close regression** (T-1.4, T-1.6): `MockTransport` captures headers → assert `Connection: close`; 5-way `gather` with a connection-counter transport → assert active connections return to 0 (issue #38).
- **Lifecycle** (T-1.5): boot app via `httpx.ASGITransport`; assert `app.state.auth_http_client` not None after startup, `.is_closed` after shutdown.
- **Static gate** (AC-1.B): `rg 'httpx.AsyncClient\(' kiro/auth.py kiro/routes_*.py` → no matches in hot-path handlers.

### PR #2
- **Off-loop assertion** (T-2.1, T-2.3, T-2.4): patch `asyncio.to_thread` to record the callable; assert it was called and the blocking primitive (`open`, `sqlite3.connect`) is invoked *inside* the thread closure, not on the calling frame.
- **Event-loop liveness** (T-2.7, NFR-4): background heartbeat task appending timestamps; trigger a save whose thread body `time.sleep(0.02)`; assert heartbeat advanced during the save (loop not blocked > 1 ms).
- **Atomic write** (T-2.2, R3): patch `os.replace`/`Path.replace` to raise after `json.dump`; assert original state file intact.
- **Sync load preserved** (T-2.5): `not asyncio.iscoroutinefunction(_load_credentials_from_sqlite)`; call from sync context with no `RuntimeWarning`.
- **Serialization** (T-2.6, R5): 5 concurrent `_save_credentials_to_sqlite` via `gather`; assert no two thread closures overlap (timestamp ranges disjoint) — proves `_save_lock`.
- **Readonly skip** (T-2.8): `SQLITE_READONLY=true` → `asyncio.to_thread` NOT called.

### PR #3
- **No HTTP under L1** (T-3.1, key): patch `_refresh_account_models` to assert `self._coordination_lock.locked() is False` at HTTP-call time.
- **No TOCTOU** (T-3.2, Hypothesis over N∈[2,20]): N concurrent `get_next_account` for an uninitialized account → `_initialize_account` called exactly once.
- **Per-account isolation** (T-3.3): account A refresh sleeps 100 ms; B completes < 50 ms.
- **Refresh dedup** (T-3.4): 5 concurrent same-account calls → `_refresh_account_models` HTTP called once.
- **Stale serve** (T-3.5): 200 ms refresh; second request served stale, no deadlock.
- **report_success no HTTP** (T-3.6): assert no HTTP await in `report_success`.
- **No deadlock** (T-3.7, Hypothesis accounts∈[2,5], requests∈[10,50]): `gather` with 5 s timeout, 0 timeouts.
- **Order documented** (T-3.8): grep for `# Lock acquisition order:`.
- **Throughput** (T-3.9): decomposed wall-clock ≤ 50% of single-lock baseline at 50 ms refresh.

**How to deterministically test "lock not held across await":** wrap the candidate HTTP method with a spy that reads `self._coordination_lock.locked()` synchronously at entry. Because asyncio is single-threaded, `locked()` reflects the exact loop state at the await boundary — no flakiness.

---

## 6. Migration notes

**Callers that DO NOT change (NFR-3):**
- `get_next_account(model, exclude_accounts)` — same signature, same return type (`Optional[Account]`).
- `report_success(account_id, model)`, `report_failure(account_id, model, error_type, status_code, reason)` — unchanged.
- `_load_credentials_from_sqlite` — stays `def`; `__init__` path untouched.
- The OpenAI/Anthropic route handlers' control flow is unchanged except the streaming-branch client selection (mechanical).

**Callers that DO change:**
- `KiroAuthManager(...)` constructions in `account_manager.py:473/480/487` gain `refresh_client=self._auth_http_client`.
- `AccountManager(...)` in `main.py:456` gains `auth_http_client=app.state.auth_http_client` (and optionally `http_client=app.state.http_client` for §2.3.5 reuse).
- Lifespan (`main.py`) gains creation + `aclose()` of `app.state.auth_http_client`.
- Internal `auth.py` refresh sites and the three save methods become `async` / use injected client — all their call sites are already async and gain `await`.
- `account_manager.py`: `self._lock` → `self._coordination_lock` (rename, all references), plus new `_account_locks`, `_refresh_in_flight`, `_save_lock`.

**Behavior frozen (NFR-1):** no OpenAI/Anthropic request or response shape changes. Circuit-breaker, sticky-index, probabilistic-retry, and fallback-model semantics are preserved exactly — only the locking around them changes. Stale-cache-on-failure tolerance (R8) is already current behavior.

**Reversibility (NFR-5):** each PR is a clean superset of the prior; reverting the top of the stack restores the lower state with a passing suite.
