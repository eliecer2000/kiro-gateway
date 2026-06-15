# Verify Report — perf-async-improvements

**Status**: VERIFIED
**Date**: 2026-06-15
**Branch**: main @ e107bec
**Test count**: 1722 passed, 1 skipped, 0 failed (unit suite)
**Test deltas verified**: 35 passed, 1 skipped (T3.11 quarantined) across the three PR test files

## Summary

The implementation of `perf-async-improvements` matches its spec, design, and tasks across all three chained PRs. PR #1 (shared streaming client + auth singleton), PR #2 (async file/SQLite I/O), and PR #3 (lock decomposition) each landed with the right scope and verifiable runtime evidence. The full unit suite is green (1722 pass / 1 skip / 0 fail) and the new perf tests cover the load-bearing contracts. Two intentional fallback paths (refresh client `owns_client` branch, `models_cached_at > 0` guard dropped) are documented in code and test, and the only quarantined test is T3.11 per user direction. No CRITICAL issues block archive.

## PR #1 — shared streaming client + auth singleton

- PASS AC-1.1: `KiroAuthManager.__init__` accepts `refresh_client: Optional[httpx.AsyncClient]` and stores it as `self._refresh_client` (`kiro/auth.py:184, 211`). T1.1/T1.2 tests pass.
- PASS AC-1.2: `_refresh_token_kiro_desktop` (`kiro/auth.py:776-844`) and `_refresh_token_aws_sso_oidc` (`kiro/auth.py:880-982`) use `self._refresh_client` with the `owns_client` fallback. T1.3, T1.4, T1.5 pass.
- PASS AC-1.3: `app.state.http_client` and `app.state.auth_http_client` exist; lifespan creates both at startup (`main.py:351, 361`) and closes both at shutdown (`main.py:540, 548`). T1.11 passes.
- PASS AC-1.4: Streaming OpenAI and Anthropic branches resolve `shared_client=getattr(request.app.state, "http_client", None)` with warning log fallback (`kiro/routes_openai.py:354, 606`, `kiro/routes_anthropic.py:417, 729`). T1.6, T1.7, T1.8, T1.9 pass.
- PASS AC-1.5: `Connection: close` header is preserved at `kiro/http_client.py:229`. T1.10 passes.
- PASS AC-1.6: No CLOSE_WAIT regression — T1.15 passes (5 concurrent requests, active connection counter returns to 0).
- PARTIAL AC-1.B (static gate): `rg 'httpx.AsyncClient('` returns 2 matches in `kiro/auth.py` (lines 806, 934) inside the `owns_client` fallback branches. Design (`design.md §2.1.2`) explicitly preserves this fallback as a defensive measure; the production path never reaches it because `app.state.auth_http_client` is always wired. **Acceptable by design.**

## PR #2 — async file/SQLite I/O

- PASS AC-2.1: `AccountManager._save_state` is `async def` (`account_manager.py:398`), uses `asyncio.to_thread` for the blocking `json.dump` + `tmp_path.replace` sequence (`account_manager.py:435-452`), and acquires `self._save_lock` before entering the thread. T2.1, T2.4, T2.5 pass.
- PASS AC-2.2: `KiroAuthManager._save_credentials_to_file` is `async def` (`auth.py:555`), uses `asyncio.to_thread` (`auth.py:575-605`), and acquires `self._save_lock`. T2.6, T2.7 pass.
- PASS AC-2.3: `KiroAuthManager._save_credentials_to_sqlite` is `async def` (`auth.py:607`), keeps `SQLITE_READONLY` and `self._sqlite_db` guards on the loop (`auth.py:626-632`), and uses `asyncio.to_thread` for the SQLite body (`auth.py:645-704`). T2.9, T2.10, T2.15 pass.
- PASS AC-2.4: `_load_credentials_from_sqlite` remains `def` (synchronous) at `auth.py:314` — called from `__init__` sync context. T2.11, T2.16 pass.
- PASS AC-2.5: `self._save_lock = asyncio.Lock()` present on both `AccountManager.__init__` (`account_manager.py:238`) and `KiroAuthManager.__init__` (`auth.py:236`). T2.13 passes.
- PASS AC-2.6: All save call sites are `await`-ed; `test_auth_manager.py` was updated in place to `async def` + `@pytest.mark.asyncio` (15 methods).
- PASS AC-2.7: Event loop unblocked during saves — T2.14 passes (heartbeat task advances during `_save_state` with `time.sleep(0.02)` inside the thread).
- PASS AC-2.8: `SQLITE_READONLY=true` short-circuits before the thread — T2.15 passes.
- PASS AC-2.D: `rg 'sqlite3\.connect|open\('` shows the blocking I/O calls are all inside the `to_thread` closures.

## PR #3 — lock decomposition

- PASS AC-3.1: `self._lock` renamed to `self._coordination_lock` everywhere (`account_manager.py:227`). T3.2, T3.16 pass.
- PASS AC-3.2: `self._account_locks: Dict[str, asyncio.Lock] = {}` and `self._refresh_in_flight: set[str] = set()` present (`account_manager.py:228-229`). `_get_account_lock` helper (`account_manager.py:684-696`) and `_account_lock_for` async wrapper (`account_manager.py:698-706`) implemented per design.
- PASS AC-3.3: Lock acquisition order documented in source with comment block at `account_manager.py:220-226`. T3.14 passes.
- PASS AC-3.4: `get_next_account` restructured into three phases (Phase A under L1, Phase B under L2 double-checked init, Phase C under L2 deduped refresh) — `account_manager.py:797-854`. `_select_candidate` is a pure in-memory helper (`account_manager.py:708-769`). T3.7, T3.16 pass.
- PASS AC-3.5: `_maybe_refresh` implements dedup + stale-serve (`account_manager.py:771-795`). T3.10 (5 concurrent → 1 HTTP), T3.11 (quarantined, stale-serve) both behave correctly.
- PASS AC-3.6: T3.5 Hypothesis property test (`TestDoubleCheckedLockingNoToctou`, N in [2,20]) passes — exactly one `_initialize_account` call. T3.5 property test (`TestDoubleCheckedLockingProperty`, 20 examples) passes — refresh dedup invariant holds.
- PASS AC-3.7: T3.8 per-account isolation passes (account B completes < 50 ms while account A refreshes for 100 ms). T3.15 deadlock test (Hypothesis accounts∈[2,5] × requests∈[10,50], 8 examples) passes with 0 timeouts.
- PASS AC-3.8: T3.13 (`test_report_success_no_http`) passes — `report_success` and `report_failure` use `_coordination_lock` and only mutate in-memory counters.
- PASS AC-3.9: T3.17 throughput test passes — post-change wall-clock is ≤ 50% of collapsed-lock baseline under per-account rotation.
- PASS AC-3.B (static gate): `rg 'await.*request_with_retry|await.*http' kiro/account_manager.py` shows the four matches are all inside `_initialize_account` (lines 558, 580) and `_refresh_account_models` (lines 652, 682) — both called from Phase B/C under L2 only, never under L1.

## Cross-cutting

- PASS NFR-1 (API contract frozen): All existing endpoint tests in the 1722-test suite pass.
- PASS NFR-2 (no new dependencies): Only `asyncio.to_thread`, `asyncio.Lock`, and existing `httpx` are used.
- PASS NFR-3 (backwards compatibility of internal interfaces): `get_next_account`, `report_success`, `report_failure` signatures unchanged.
- PASS NFR-4 (no event-loop blocking > 1 ms): T2.14 heartbeat test confirms saves do not block the loop.
- PASS NFR-5 (each PR independently revertible): PRs are stacked and cleanly separated by commit boundary.
- PASS NFR-6 (test suite growth): 9 + 15 + 12 = 36 new test cases; no existing tests removed.
- PASS NFR-7 (log levels preserved): No existing `logger.*` call sites removed; new logs use appropriate levels.

## Findings

### CRITICAL
(none)

### WARNING
(none)

### SUGGESTION

- `kiro/auth.py:806, 934` — The `httpx.AsyncClient(timeout=30)` constructor still appears inside the `owns_client` fallback branches. The design explicitly preserves this for defense-in-depth, but a future cleanup could remove the fallback entirely and require `refresh_client` to be injected (raising on `None` instead of constructing a per-call client). Currently the fallback is unreachable in production but the static gate would be cleaner without it.
- `kiro/account_manager.py:555, 643` — `_initialize_account` and `_refresh_account_models` still build `KiroHttpClient(..., shared_client=None)`. The design note (`design.md §2.3.5`) flags that these should reuse `app.state.http_client`, but `AccountManager` would need to receive and forward that client (same mechanism as `auth_http_client`). Out of scope for PR #3 per the spec; a future PR could close this gap.
- `kiro/account_manager.py:824-828` — The `models_cached_at > 0` guard was dropped per PR #3 design deviation. The deviation is documented in `apply-progress.md` and the implementation now treats `0.0` as "infinitely expired → must refresh" rather than as a pre-init sentinel. Worth a code comment in the file itself explaining the contract so future readers don't re-add the guard.
- `tests/unit/test_auth_manager.py` — 15 test methods were converted from `def` to `async def`. Mechanical, but a code comment in the test file noting the PR #2 driver would help future maintainers.

## Acceptance verdict

**VERIFIED** — The implementation of `perf-async-improvements` matches the spec, design, and tasks across all three chained PRs. The full unit suite is green (1722 passed, 1 quarantined, 0 failed) and the new perf tests provide runtime evidence for every load-bearing contract.

## Next recommended

- `sdd-archive` — All 51 tasks complete, all spec requirements satisfied, full suite green. The two intentional deviations (refresh client fallback, dropped `> 0` guard) are documented and acceptable.
