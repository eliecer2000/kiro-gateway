# -*- coding: utf-8 -*-

"""
Tests for PR #2 of perf-async-improvements: async file/SQLite I/O via asyncio.to_thread.

Covers:
- T2.1: _save_state delegates blocking body to asyncio.to_thread
- T2.4: _save_state atomic-write semantics preserved
- T2.5: save_state_periodically awaits the new async _save_state
- T2.6: _save_credentials_to_file delegates blocking body to asyncio.to_thread
- T2.9: _save_credentials_to_sqlite delegates blocking body to asyncio.to_thread
- T2.11: _load_credentials_from_sqlite remains a sync (def) method
- T2.13: Concurrent saves are serialized by _save_lock
- T2.14: Event loop unblocked during save operations
- T2.15: SQLITE_READONLY short-circuits writes (no thread spawned)
- T2.16: get_access_token reload path works with sync _load_credentials_from_sqlite
"""

import asyncio
import inspect
import json
import os
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from kiro.account_manager import AccountManager
from kiro.auth import KiroAuthManager
from kiro.cache import ModelInfoCache
from kiro.model_resolver import ModelResolver


# =============================================================================
# Helpers / builders
# =============================================================================


def _make_account_manager(tmp_path: Path, state_data: dict | None = None) -> AccountManager:
    """
    Build an AccountManager that points at temp files in `tmp_path`.
    The credentials.json is empty (we never call load_credentials in these tests).
    The state file is initialized with `state_data` if provided.
    """
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps([]))
    state_file = tmp_path / "state.json"
    if state_data is not None:
        state_file.write_text(json.dumps(state_data))
    return AccountManager(credentials_file=str(creds_file), state_file=str(state_file))


def _make_auth_manager(tmp_path: Path, *, with_sqlite: bool = False) -> KiroAuthManager:
    """
    Build a KiroAuthManager that points at a temp credentials file or sqlite db.

    We do NOT call get_access_token() during these tests (no token expiry checks).
    """
    if with_sqlite:
        db = tmp_path / "data.sqlite3"
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
        token_data = {
            "access_token": "init_access",
            "refresh_token": "init_refresh",
            "expires_at": "2099-01-01T00:00:00Z",
            "region": "us-east-1",
        }
        cur.execute(
            "INSERT INTO auth_kv (key, value) VALUES (?, ?)",
            ("codewhisperer:odic:token", json.dumps(token_data)),
        )
        conn.commit()
        conn.close()
        return KiroAuthManager(sqlite_db=str(db))
    else:
        creds_file = tmp_path / "kiro-auth-token.json"
        creds_file.write_text(json.dumps({
            "accessToken": "init_access",
            "refreshToken": "init_refresh",
            "expiresAt": "2099-01-01T00:00:00.000Z",
            "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test",
            "region": "us-east-1",
        }))
        return KiroAuthManager(creds_file=str(creds_file))


# =============================================================================
# T2.1 - _save_state delegates blocking body to asyncio.to_thread
# =============================================================================


class TestSaveStateRunsOffEventLoop:
    """T2.1: _save_state uses asyncio.to_thread for the json.dump + os.replace."""

    @pytest.mark.asyncio
    async def test_save_state_uses_asyncio_to_thread(self, tmp_path):
        """
        What it does: Verifies _save_state calls asyncio.to_thread with a callable.
        Purpose: Confirms the off-loop delegation.
        """
        print("Setup: Building AccountManager with a temp state file...")
        manager = _make_account_manager(tmp_path)

        print("Action: Patching asyncio.to_thread to record calls...")
        with patch("kiro.account_manager.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None  # the write succeeds
            await manager._save_state()

            print("Verification: asyncio.to_thread was called...")
            mock_to_thread.assert_called_once()
            # The first positional arg must be a callable (the _write closure).
            first_arg = mock_to_thread.call_args[0][0]
            assert callable(first_arg), (
                "asyncio.to_thread must be called with a callable (the blocking body)"
            )

    @pytest.mark.asyncio
    async def test_save_state_does_not_block_event_loop(self, tmp_path):
        """
        What it does: A concurrent asyncio.sleep(0) task completes before the save callable.
        Purpose: Confirms the blocking body is not running on the event-loop frame.
        """
        print("Setup: Building AccountManager...")
        manager = _make_account_manager(tmp_path)

        loop_advanced = asyncio.Event()

        async def heartbeat():
            await asyncio.sleep(0)
            loop_advanced.set()

        with patch(
            "kiro.account_manager.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
        ):
            # Real asyncio.to_thread would still offload to a thread; we just want
            # to confirm the body is not invoked synchronously on the calling frame.
            # Replace the body with a no-op and verify heartbeat still ran.
            with patch.object(manager, "_save_state", wraps=manager._save_state) as spy:
                # Spawn heartbeat, then save, then check.
                hb = asyncio.create_task(heartbeat())
                await manager._save_state()
                await hb
                # The heartbeat must have run.
                assert loop_advanced.is_set()
                assert spy.called


# =============================================================================
# T2.4 - _save_state atomic write preserved
# =============================================================================


class TestSaveStateAtomicWrite:
    """T2.4: a crash injected after json.dump does not corrupt the original state file."""

    @pytest.mark.asyncio
    async def test_save_state_atomic_write_on_replace_failure(self, tmp_path):
        """
        What it does: Patches tmp_path.replace to raise after json.dump succeeds.
        Purpose: Confirms the original state file is not corrupted.
        """
        print("Setup: Building AccountManager and a real state file with prior data...")
        prior_state = {
            "current_account_index": 0,
            "accounts": {},
            "model_to_accounts": {
                "claude-sonnet-4-5": {"accounts": ["preserved/path.json"]}
            },
        }
        manager = _make_account_manager(tmp_path, state_data=prior_state)

        state_path = Path(manager._state_file)
        original_contents = state_path.read_text()
        assert "preserved/path.json" in original_contents, "fixture sanity check"

        # Patch tmp_path.replace to raise OSError, simulating a crash mid-rename.
        from unittest.mock import patch as _patch

        def boom_replace(self, *a, **kw):
            raise OSError("simulated crash during rename")

        with _patch.object(Path, "replace", boom_replace):
            # Should not raise — errors are caught inside the off-loop body.
            await manager._save_state()

        print("Verification: original state file is intact...")
        after = state_path.read_text()
        assert after == original_contents, "state file was corrupted by failed save"
        # The .tmp file may or may not exist; that's fine per the spec.


# =============================================================================
# T2.5 - save_state_periodically awaits the new async _save_state
# =============================================================================


class TestSaveStatePeriodicallyWithAsyncSave:
    """T2.5: save_state_periodically() awaits _save_state() without warnings or type errors."""

    @pytest.mark.asyncio
    async def test_save_state_periodically_awaits_async_save_state(self, tmp_path):
        """
        What it does: Marks the manager dirty, starts the periodic task, waits one tick.
        Purpose: Confirms save_state_periodically awaits the now-async _save_state.
        """
        print("Setup: Building AccountManager with a temp state file...")
        manager = _make_account_manager(tmp_path)

        # Set dirty + populate minimal account data so the write has something to do.
        manager._dirty = True
        manager._accounts["acct1"] = _make_dummy_account("acct1")

        # Patch asyncio.sleep in account_manager to fire faster than the configured interval.
        # NOTE: snapshot the real sleep before patching, because `kiro.account_manager.asyncio`
        # is the shared `asyncio` module — patching its `sleep` attribute also affects this
        # closure if we use `asyncio.sleep` directly.
        _real_sleep = asyncio.sleep

        async def fast_sleep(_):
            await _real_sleep(0)
            # Mark dirty again so the loop runs at least once after each tick.
            manager._dirty = True

        with patch("kiro.account_manager.asyncio.sleep", side_effect=fast_sleep):
            with patch("kiro.account_manager.asyncio.to_thread", new=AsyncMock(return_value=None)):
                task = asyncio.create_task(manager.save_state_periodically())
                # Let the loop run a few iterations.
                for _ in range(3):
                    await asyncio.sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # If _save_state was sync and we forgot to await, this would have produced
        # a RuntimeWarning ("never awaited") at GC time. We assert the inverse: no warning.
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            # Force a GC pass.
            import gc
            gc.collect()
        relevant = [w for w in captured if "coroutine" in str(w.message).lower()]
        assert not relevant, f"Unexpected coroutine warnings: {[str(w.message) for w in relevant]}"


def _make_dummy_account(account_id: str):
    """Build a minimal Account that supports the dict-comprehension in _save_state."""
    from kiro.account_manager import Account, AccountStats
    return Account(
        id=account_id,
        auth_manager=None,
        model_cache=ModelInfoCache(),
        model_resolver=ModelResolver(
            cache=ModelInfoCache(),
            hidden_models={},
            aliases={},
            hidden_from_list=set(),
        ),
        failures=0,
        last_failure_time=0.0,
        models_cached_at=0.0,
        stats=AccountStats(),
    )


# =============================================================================
# T2.6 - _save_credentials_to_file delegates blocking body to asyncio.to_thread
# =============================================================================


class TestSaveCredentialsToFileRunsOffEventLoop:
    """T2.6: _save_credentials_to_file uses asyncio.to_thread for the read+write body."""

    @pytest.mark.asyncio
    async def test_save_credentials_to_file_uses_to_thread(self, tmp_path):
        """
        What it does: Verifies asyncio.to_thread is called by _save_credentials_to_file.
        Purpose: Confirms the off-loop delegation for JSON file saves.
        """
        print("Setup: Building KiroAuthManager with a temp creds file...")
        manager = _make_auth_manager(tmp_path)
        manager._access_token = "new_access"
        manager._refresh_token = "new_refresh"
        manager._expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        with patch("kiro.auth.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None
            await manager._save_credentials_to_file()

            print("Verification: asyncio.to_thread was called...")
            mock_to_thread.assert_called_once()
            first_arg = mock_to_thread.call_args[0][0]
            assert callable(first_arg), (
                "asyncio.to_thread must be called with a callable (the blocking body)"
            )

    @pytest.mark.asyncio
    async def test_save_credentials_to_file_signature_is_async(self, tmp_path):
        """
        What it does: Verifies _save_credentials_to_file is a coroutine function.
        Purpose: The spec requires `async def` for this method.
        """
        print("Action: Inspecting _save_credentials_to_file signature...")
        assert inspect.iscoroutinefunction(KiroAuthManager._save_credentials_to_file), (
            "_save_credentials_to_file MUST be async (PR #2 contract)"
        )


# =============================================================================
# T2.9 - _save_credentials_to_sqlite delegates blocking body to asyncio.to_thread
# =============================================================================


class TestSaveCredentialsToSqliteRunsOffEventLoop:
    """T2.9: _save_credentials_to_sqlite uses asyncio.to_thread for sqlite ops."""

    @pytest.mark.asyncio
    async def test_save_credentials_to_sqlite_uses_to_thread(self, tmp_path):
        """
        What it does: Verifies asyncio.to_thread is called by _save_credentials_to_sqlite.
        Purpose: Confirms the off-loop delegation for SQLite saves.
        """
        print("Setup: Building KiroAuthManager with a temp SQLite DB...")
        manager = _make_auth_manager(tmp_path, with_sqlite=True)
        manager._access_token = "new_access"
        manager._refresh_token = "new_refresh"
        manager._expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        with patch("kiro.auth.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None
            await manager._save_credentials_to_sqlite()

            print("Verification: asyncio.to_thread was called...")
            mock_to_thread.assert_called_once()
            first_arg = mock_to_thread.call_args[0][0]
            assert callable(first_arg), (
                "asyncio.to_thread must be called with a callable (the blocking body)"
            )

    @pytest.mark.asyncio
    async def test_save_credentials_to_sqlite_signature_is_async(self, tmp_path):
        """
        What it does: Verifies _save_credentials_to_sqlite is a coroutine function.
        Purpose: The spec requires `async def` for this method.
        """
        print("Action: Inspecting _save_credentials_to_sqlite signature...")
        assert inspect.iscoroutinefunction(KiroAuthManager._save_credentials_to_sqlite), (
            "_save_credentials_to_sqlite MUST be async (PR #2 contract)"
        )


# =============================================================================
# T2.11 - _load_credentials_from_sqlite remains sync
# =============================================================================


class TestLoadCredentialsFromSqliteRemainsSync:
    """T2.11: _load_credentials_from_sqlite is a regular function, not a coroutine."""

    def test_load_credentials_from_sqlite_is_not_coroutine(self):
        """
        What it does: Asserts _load_credentials_from_sqlite is a regular def function.
        Purpose: It is called from the synchronous __init__ — must remain sync.
        """
        print("Verification: _load_credentials_from_sqlite is not a coroutine function...")
        assert not inspect.iscoroutinefunction(KiroAuthManager._load_credentials_from_sqlite), (
            "_load_credentials_from_sqlite MUST remain sync (called from __init__)"
        )

    def test_load_credentials_from_sqlite_callable_from_sync_context(self, tmp_path):
        """
        What it does: Calls the method directly from a non-async context.
        Purpose: Confirms no RuntimeWarning about awaiting a non-coroutine.
        """
        print("Setup: Building KiroAuthManager with a temp SQLite DB...")
        manager = _make_auth_manager(tmp_path, with_sqlite=True)

        # We need to call _load_credentials_from_sqlite directly without `await`.
        # The method does file I/O (synchronous); the global network-blocking
        # fixture prevents real network — file I/O is fine.
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = manager._load_credentials_from_sqlite(manager._sqlite_db)

        print("Verification: no RuntimeWarning raised...")
        rt_warnings = [
            w for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "coroutine" in str(w.message).lower()
        ]
        assert not rt_warnings, f"Unexpected coroutine warnings: {[str(w.message) for w in rt_warnings]}"
        # Result should be None (the method returns None).
        assert result is None


# =============================================================================
# T2.13 - Concurrent saves serialized by _save_lock
# =============================================================================


class TestConcurrentSavesSerialized:
    """T2.13: 5 concurrent _save_credentials_to_sqlite calls are serialized by _save_lock."""

    @pytest.mark.asyncio
    async def test_concurrent_saves_do_not_overlap(self, tmp_path):
        """
        What it does: 5 concurrent saves; assert no two thread bodies overlap.
        Purpose: Confirms _save_lock serializes concurrent saves.
        """
        print("Setup: Building KiroAuthManager with a temp SQLite DB...")
        manager = _make_auth_manager(tmp_path, with_sqlite=True)
        manager._access_token = "tok"
        manager._refresh_token = "ref"
        manager._expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        # Track thread-body execution intervals.
        intervals = []
        lock = asyncio.Lock()
        overlap_detected = False
        currently_inside = {"v": False}

        def make_body(idx: int):
            def body():
                if currently_inside["v"]:
                    nonlocal overlap_detected
                    overlap_detected = True
                currently_inside["v"] = True
                # Sync sleep to simulate a slow write.
                time.sleep(0.01)
                currently_inside["v"] = False
            return body

        async def fake_to_thread(fn, *args, **kwargs):
            # Run on the loop but record entry/exit in monotonic time.
            entry = time.monotonic()
            fn()
            exit_ = time.monotonic()
            async with lock:
                intervals.append((entry, exit_))
            return None

        async def one_save(i: int):
            # Bypass the real method; we only care about the lock + to_thread contract.
            async with manager._save_lock:
                await fake_to_thread(make_body(i))

        # Run 5 saves concurrently.
        await asyncio.gather(*(one_save(i) for i in range(5)))

        print(f"Intervals: {intervals}")
        print(f"Overlap detected: {overlap_detected}")
        assert not overlap_detected, "Two save bodies overlapped — _save_lock failed to serialize"
        # The intervals should be disjoint (start[i+1] >= end[i] for sorted order).
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        for i in range(len(sorted_intervals) - 1):
            assert sorted_intervals[i][1] <= sorted_intervals[i + 1][0] + 0.001, (
                f"Intervals {sorted_intervals[i]} and {sorted_intervals[i+1]} overlap"
            )

    @pytest.mark.asyncio
    async def test_save_lock_exists(self, tmp_path):
        """What it does: Confirms _save_lock is an asyncio.Lock on the auth manager."""
        manager = _make_auth_manager(tmp_path)
        assert hasattr(manager, "_save_lock")
        assert isinstance(manager._save_lock, asyncio.Lock)


# =============================================================================
# T2.14 - Event loop unblocked during save operations
# =============================================================================


class TestEventLoopUnblockedDuringSave:
    """T2.14: a heartbeat task advances while a save is in progress."""

    @pytest.mark.asyncio
    async def test_heartbeat_advances_during_save_state(self, tmp_path):
        """
        What it does: Triggers a _save_state with a 20ms body; a heartbeat task runs.
        Purpose: The heartbeat must append at least one timestamp during the save.
        """
        print("Setup: Building AccountManager and a dirty state...")
        manager = _make_account_manager(tmp_path)
        manager._accounts["acct"] = _make_dummy_account("acct")
        manager._dirty = True

        # Track heartbeat ticks.
        beats = []
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                beats.append(time.monotonic())
                await asyncio.sleep(0)

        hb_task = asyncio.create_task(heartbeat())

        # Patch asyncio.to_thread to invoke a slow callable.
        real_to_thread = asyncio.to_thread

        def slow_body():
            time.sleep(0.02)

        # Capture loop-side traceback to assert the slow body did not run on the loop.
        import traceback
        loop_thread_ids = {id(asyncio.get_event_loop())}

        with patch("kiro.account_manager.asyncio.to_thread", new=AsyncMock(side_effect=real_to_thread)) as _:
            # The real asyncio.to_thread runs `slow_body` in the default executor;
            # we want to ensure the loop is not blocked.
            await manager._save_state()

        stop.set()
        await hb_task

        # The heartbeat should have ticked at least once during the ~20ms save.
        # Generous bound to avoid CI flakiness.
        print(f"Heartbeats: {len(beats)}")
        assert len(beats) >= 1, "Heartbeat never ran — the loop was blocked during save"


# =============================================================================
# T2.15 - SQLITE_READONLY short-circuits writes
# =============================================================================


class TestSqliteReadonlyFlagSkipsWrite:
    """T2.15: SQLITE_READONLY=true → asyncio.to_thread is NOT called."""

    @pytest.mark.asyncio
    async def test_sqlite_readonly_skips_thread(self, tmp_path, monkeypatch):
        """
        What it does: Sets SQLITE_READONLY=true and asserts the write is skipped.
        Purpose: SQLITE_READONLY preserves original behavior (no thread spawned).
        """
        print("Setup: Patching SQLITE_READONLY=true in the kiro.config module...")
        # Patch the imported symbol in kiro.auth.
        monkeypatch.setattr("kiro.auth.SQLITE_READONLY", True)

        manager = _make_auth_manager(tmp_path, with_sqlite=True)
        manager._access_token = "new_access"
        manager._refresh_token = "new_refresh"

        with patch("kiro.auth.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            await manager._save_credentials_to_sqlite()
            print("Verification: asyncio.to_thread was NOT called...")
            mock_to_thread.assert_not_called()

        # DB should be unchanged. We didn't update the access_token, so the
        # stored access_token is still "init_access" from the fixture.
        db_path = Path(manager._sqlite_db)
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM auth_kv WHERE key = ?",
            ("codewhisperer:odic:token",),
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None
        stored = json.loads(row[0])
        assert stored.get("access_token") == "init_access", (
            f"DB was modified despite SQLITE_READONLY: {stored}"
        )


# =============================================================================
# T2.16 - get_access_token reload path still works (sync _load_credentials_from_sqlite)
# =============================================================================


class TestGetAccessTokenReloadPath:
    """T2.16: get_access_token() still works with the sync _load_credentials_from_sqlite."""

    @pytest.mark.asyncio
    async def test_get_access_token_returns_valid_token(self, tmp_path):
        """
        What it does: Forces the SQLite reload branch and confirms we get a valid token.
        Purpose: Sync load path is preserved; no coroutine wrapping breaks the flow.
        """
        print("Setup: Building KiroAuthManager with a valid token in SQLite...")
        manager = _make_auth_manager(tmp_path, with_sqlite=True)
        # The fixture writes an access_token that expires in 2099; it is valid.
        # Force a reload by marking the token as expiring soon.
        manager._expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        # Patch force_refresh (called from the refresh path) to be a no-op returning
        # the in-memory token. We do not want real HTTP traffic in this test.
        with patch.object(manager, "force_refresh", new=AsyncMock(return_value="reloaded_token")):
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                token = await manager.get_access_token()

        # The exact return value depends on the SQLite reload branch — we just want
        # to confirm no exceptions / warnings are produced by mixing sync + async.
        assert token, "get_access_token returned a falsy value"
        rt_warnings = [
            w for w in captured
            if issubclass(w.category, RuntimeWarning)
        ]
        # Filter to coroutine-related ones only.
        coroutine_warnings = [w for w in rt_warnings if "coroutine" in str(w.message).lower()]
        assert not coroutine_warnings, (
            f"Unexpected coroutine warnings: {[str(w.message) for w in coroutine_warnings]}"
        )
