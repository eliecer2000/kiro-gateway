# Proposal: perf-async-improvements

- **Status:** proposal_complete
- **Change name:** `perf-async-improvements`
- **Type:** architecture / performance
- **Delivery:** Chained PRs, stacked to main (PR #1 -> PR #2 -> PR #3, each merges to main in order)
- **Next recommended phase:** spec

## Executive summary

kiro-gateway currently serializes effectively all request handling behind a single global `asyncio.Lock` in `AccountManager`, and performs synchronous file/SQLite I/O directly on the event loop, defeating the concurrency benefits of FastAPI + httpx async. Under concurrent load this turns a multi-account async gateway into a near-sequential pipeline, with HTTP calls (TTL model refresh) executing while the global lock is held. This change removes the worst offenders in three independently shippable, stacked PRs — starting with zero-risk client reuse, then moving blocking I/O off the loop, and finally decomposing the global lock so the critical section never spans network I/O. The result is meaningfully higher concurrency and lower tail latency with no change to external API behavior.

## Intent

**Problem.** The gateway is async end-to-end on paper, but three structural issues serialize and block the event loop:

1. A process-wide `asyncio.Lock` (`AccountManager._lock`, `kiro/account_manager.py:210`) is held across `get_next_account()`, `report_success()`, and `report_failure()` — i.e. on every request boundary — and the `get_next_account()` critical section can trigger `_refresh_account_models()`, which performs outbound HTTP. While that HTTP call is in flight, every other request is blocked on the same lock.
2. Synchronous file and SQLite operations (`_save_state`, `_save_credentials_to_file`, `_save_credentials_to_sqlite`, `_load_credentials_from_sqlite`) run inline inside async code paths, blocking the event loop thread for the duration of disk/DB I/O.
3. New `httpx.AsyncClient` instances are created per streaming request and per token refresh, discarding TCP/TLS connection reuse.

**Why now.** These are the verified top bottlenecks from the exploration pass. They compound: the lock serializes requests, and the I/O blocking happens *inside* that serialized window, so latency stacks. The fixes are well-bounded and can be delivered as low-risk stacked PRs without an architectural rewrite (multi-worker uvicorn is explicitly deferred).

## Scope

Included in this change:

- **Reuse a shared `httpx.AsyncClient` for streaming requests** (`kiro/routes_openai.py:351`, `kiro/routes_anthropic.py:603`), matching the non-streaming path that already uses `request.app.state.http_client`.
- **Reuse a singleton `httpx.AsyncClient` for token refresh** (`kiro/auth.py:708`, `kiro/auth.py:825`).
- **Move synchronous file/SQLite I/O off the event loop** via `run_in_executor` / `asyncio.to_thread`: `_save_state` (`account_manager.py:373`), `_save_credentials_to_file` (`auth.py:489`), `_save_credentials_to_sqlite` (`auth.py:524`), and the async-context call sites of `_load_credentials_from_sqlite` (`auth.py:248`).
- **Decompose the global `AccountManager._lock`**: shrink the critical section so it covers only in-memory state mutation, extract HTTP-bound TTL model refresh (`_refresh_account_models`, `account_manager.py:580`) out of the lock, add double-checked locking for lazy account initialization (TOCTOU guard), and introduce per-account concurrency control (semaphore/lock) so a single account's TTL refresh does not block unrelated accounts or unrelated requests.

## Non-goals

Explicitly NOT included:

- **Multi-worker uvicorn / process scaling** — architectural change, deferred (finding #10).
- **Replacing `run_in_executor` with `aiosqlite` or any new async-DB dependency** — we deliberately avoid adding a dependency; `run_in_executor` keeps the change dependency-free.
- **Connection pooling infrastructure / proxy-level tuning** beyond reusing the existing `app.state.http_client` and an auth singleton.
- **Rewriting `AwsEventStreamParser` buffer strategy** (finding #8, LOW) — out of scope for this performance pass.
- **Moving `tiktoken` token counting off the loop** (finding #7, LOW) — out of scope; revisit only if profiling shows it matters.
- Any change to public OpenAI/Anthropic-compatible request or response contracts.

## Approach (per PR slice)

### PR #1 — Easy wins: shared streaming client + auth singleton

Reuse the already-existing `request.app.state.http_client` for streaming code paths instead of constructing `KiroHttpClient(auth_manager, shared_client=None)`. The non-streaming branch already passes `shared_client=request.app.state.http_client`, so the pattern is in place; PR #1 extends it to the streaming branch. Add a module-level singleton `httpx.AsyncClient` (created at startup, closed at shutdown) for the two token-refresh call sites in `auth.py`. The `Connection: close` header already present is expected to keep the original VPN CLOSE_WAIT issue mitigated; PR #1 validates this assumption before relying on it. Zero architectural risk, no lock or I/O-model changes.

### PR #2 — Async I/O: move blocking file/SQLite work off the event loop

Wrap the synchronous body of `_save_state`, `_save_credentials_to_file`, and `_save_credentials_to_sqlite` so the blocking disk/DB work executes in a thread pool via `loop.run_in_executor` (or `asyncio.to_thread`). `_load_credentials_from_sqlite` is currently called from `__init__` (a synchronous context), so the load path is restructured: keep a sync load for the `__init__` path, and ensure any async call sites use the executor wrapper. No new dependencies. Medium complexity — primary care is preserving atomic-write semantics (tmp file + rename in `_save_state`) and not introducing races between concurrent saves.

### PR #3 — Lock decomposition

Split the monolithic `AccountManager._lock` so the critical section protects only in-memory state reads/writes, never network I/O:

- Extract `_refresh_account_models()` (HTTP-bound) out of the `get_next_account()` lock window. Decide refresh-needed under the lock, release, perform HTTP outside, then re-acquire briefly to commit results.
- Add **double-checked locking** for lazy account initialization to close the TOCTOU window the lock split opens.
- Introduce **per-account concurrency control** (e.g. a per-account `asyncio.Lock`/semaphore) so a single account's TTL refresh serializes only that account, not the whole gateway, and concurrent refreshes of the same account are deduplicated.
- Keep `report_success`/`report_failure` mutations under a short in-memory lock only.

Highest complexity and highest concurrency payoff. Depends on PR #1 (shared client available for refresh) and PR #2 (state saves no longer block under any lock).

## PR breakdown

| PR | Title | Files touched | Risk | Est. test changes |
|----|-------|---------------|------|-------------------|
| #1 | Shared streaming client + auth singleton | `kiro/routes_openai.py`, `kiro/routes_anthropic.py`, `kiro/auth.py`, app startup/shutdown wiring | Low | New: streaming reuses shared client; auth refresh uses singleton; regression test for `Connection: close` / CLOSE_WAIT behavior. ~2-4 tests. |
| #2 | Async file/SQLite I/O via run_in_executor | `kiro/account_manager.py` (`_save_state`), `kiro/auth.py` (`_save_credentials_to_file`, `_save_credentials_to_sqlite`, `_load_credentials_from_sqlite` call sites) | Medium | Tests asserting saves run off-loop (no event-loop block), atomic-write preserved, concurrent-save safety. ~4-6 tests. |
| #3 | Global lock decomposition + per-account semaphores | `kiro/account_manager.py` (`get_next_account`, `report_success`, `report_failure`, `_refresh_account_models`, lock structure) | High | Concurrency tests: no HTTP under global lock, double-checked init has no TOCTOU, per-account refresh isolation, dedup of concurrent same-account refresh. Hypothesis property tests for interleavings. ~8-12 tests. |

PRs stack to main in order: #1 -> #2 -> #3. Each is independently mergeable and reverts cleanly.

## Risk matrix

| # | Risk | Likelihood | Impact | Mitigation | PR |
|---|------|-----------|--------|------------|-----|
| R1 | Shared streaming client reintroduces VPN CLOSE_WAIT socket leak | Low | Medium | `Connection: close` header already in place; validate explicitly before merge; keep per-request client fallback path behind a flag if regression observed | #1 |
| R2 | Auth singleton client lifecycle (created/closed at wrong time) leaks or uses a closed client | Low | Medium | Create at app startup, close at shutdown; guard against use-after-close | #1 |
| R3 | `run_in_executor` breaks atomic write (tmp+rename) of `_save_state` | Low | High | Keep the full write+rename inside one executor call; test atomicity | #2 |
| R4 | `_load_credentials_from_sqlite` restructuring breaks sync `__init__` startup path | Medium | High | Preserve a sync load for `__init__`; only wrap async call sites; startup smoke test | #2 |
| R5 | Concurrent saves from thread pool race on the same file/DB | Medium | Medium | Serialize saves with a dedicated in-memory save lock; thread-pool work is short | #2 |
| R6 | Lock split introduces TOCTOU on lazy account initialization | High (if unguarded) | High | Double-checked locking; property tests over interleavings | #3 |
| R7 | Extracting HTTP refresh from lock causes duplicate concurrent refreshes of same account | Medium | Low | Per-account lock/semaphore + in-flight dedup | #3 |
| R8 | Stale model cache served during the unlocked refresh window | Medium | Low | Acceptable: serve stale cache while refresh in flight (current behavior already tolerates stale on failure) | #3 |
| R9 | Nested-lock ordering (`AccountManager._lock` + `auth._lock` + per-account) deadlock | Low | High | Define and document a strict lock acquisition order; never hold two cross-component locks across `await` of HTTP | #3 |

## Success criteria

Measurable outcomes:

1. **No HTTP under the global lock.** Static/runtime assertion: no outbound HTTP call (`_refresh_account_models`, any `httpx` request) executes while `AccountManager._lock` is held. Verified by test that fails if a refresh occurs inside the critical section.
2. **No synchronous file/SQLite I/O on the event loop.** `_save_state`, `_save_credentials_to_file`, `_save_credentials_to_sqlite` execute their blocking work via the executor; verified by test asserting the event loop is not blocked (e.g. a concurrent heartbeat task continues advancing during a save).
3. **Connection reuse for streaming + token refresh.** No new `httpx.AsyncClient` is constructed per streaming request or per token refresh; verified by test/inspection that the shared/singleton client is reused.
4. **Concurrency throughput improvement.** Under a concurrent-request benchmark (N simultaneous requests across M accounts), p50 and p95 latency improve measurably versus the pre-change baseline, and effective concurrency is no longer pinned to ~1 by the global lock. Target: p95 latency reduction under concurrent load and request serialization eliminated (concrete thresholds set in the spec phase against a captured baseline).
5. **No behavioral regression.** Full existing test suite (pytest + hypothesis) passes; OpenAI/Anthropic-compatible request/response contracts unchanged; no CLOSE_WAIT socket-leak regression observed.
6. **Each PR independently shippable and revertible**, stacked to main in order #1 -> #2 -> #3.

## Dependencies between PRs

- PR #3 depends on PR #1 (shared client available for extracted refresh) and PR #2 (saves no longer block, so committing refresh results under a short lock is safe).
- PR #2 is independent of PR #1 but stacks after it for clean linear history.
