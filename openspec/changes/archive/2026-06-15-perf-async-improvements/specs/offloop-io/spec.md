# Spec: offloop-io

- **Capability:** offloop-io
- **PR:** #2 — Async file/SQLite I/O via run_in_executor
- **Change:** perf-async-improvements
- **Status:** spec_complete
- **Risk:** Medium

## Purpose

Move all synchronous file and SQLite I/O off the event loop by delegating blocking bodies to a thread via `asyncio.to_thread`. Atomic write semantics MUST be preserved. The sync `__init__` load path MUST remain synchronous. No new dependencies are introduced. External API contract is unchanged.

## Context

- `account_manager.py:373` `_save_state`: synchronous `open(tmp_path, 'w') + json.dump + os.replace` runs on the event loop; uses atomic tmp+rename.
- `auth.py:489` `_save_credentials_to_file`: synchronous `open` + `json.dump` on the event loop.
- `auth.py:524` `_save_credentials_to_sqlite`: synchronous `sqlite3` operations on the event loop.
- `auth.py:248` `_load_credentials_from_sqlite`: synchronous, called from `Auth.__init__` (sync context). The sync load path MUST remain sync. Only async call sites (if any) get the executor wrapper.

No new dependencies are permitted. `asyncio.to_thread` (Python 3.9+, available on 3.14) is the preferred spelling over `loop.run_in_executor(None, ...)`.

## Requirements

### Requirement: _save_state delegates blocking body to a thread

`_save_state` MUST delegate its blocking body (the `json.dump` + `os.replace` sequence) to a thread via `asyncio.to_thread`. The full tmp-write + atomic-rename sequence MUST execute as a single callable inside the thread (atomicity preserved).

#### Scenario: _save_state runs the write off the event loop

- GIVEN an `AccountManager` instance with a temp state file and `asyncio.to_thread` patched to record calls
- WHEN `await account_manager._save_state()` is called
- THEN `asyncio.to_thread` is called with a callable (the blocking body)
- AND a concurrent `asyncio.sleep(0)` task completes before the save callable finishes (proving the loop was not blocked).

#### Scenario: _save_state atomic-write semantics preserved

- GIVEN a temp directory and an `AccountManager` with real files
- WHEN `await account_manager._save_state()` is called with a simulated crash injected mid-write (patch `os.replace` to raise after `json.dump`)
- THEN the original state file is intact (not corrupted)
- AND the `.tmp` file may or may not exist.

### Requirement: _save_credentials_to_file becomes async and off-loop

`_save_credentials_to_file` MUST delegate its blocking body to a thread via `asyncio.to_thread`. The method signature MUST become `async def`.

#### Scenario: _save_credentials_to_file runs off the event loop

- GIVEN an `Auth` instance with a temp credentials file and `asyncio.to_thread` patched
- WHEN `await auth._save_credentials_to_file()` is called
- THEN `asyncio.to_thread` is called
- AND no synchronous `open()` call occurs on the calling coroutine's frame.

### Requirement: _save_credentials_to_sqlite becomes async and off-loop

`_save_credentials_to_sqlite` MUST delegate its blocking SQLite read-merge-write body to a thread via `asyncio.to_thread`. The method signature MUST become `async def`. The `SQLITE_READONLY` guard MUST be checked before entering the thread (cheap in-memory check stays on the loop).

#### Scenario: _save_credentials_to_sqlite runs off the event loop

- GIVEN an `Auth` instance with a temp SQLite database and `asyncio.to_thread` patched
- WHEN `await auth._save_credentials_to_sqlite()` is called
- THEN `asyncio.to_thread` is called
- AND `sqlite3.connect` is not called from the event loop thread.

### Requirement: _load_credentials_from_sqlite remains synchronous

`_load_credentials_from_sqlite` MUST remain a synchronous method (`def`, not `async def`) because it is called from `Auth.__init__` which is a synchronous constructor. No change to call signature.

#### Scenario: _load_credentials_from_sqlite is callable from sync context

- GIVEN `auth._load_credentials_from_sqlite`
- WHEN it is called directly from a non-async context without `await`
- THEN no `RuntimeWarning` is raised
- AND `asyncio.iscoroutinefunction(auth._load_credentials_from_sqlite)` is False.

### Requirement: Concurrent saves serialized per auth object

A dedicated in-memory `asyncio.Lock` (e.g. `self._save_lock`) MUST serialize concurrent save operations for the same auth object, preventing interleaved writes to the same file or SQLite row.

#### Scenario: Concurrent saves do not interleave

- GIVEN an `Auth` instance with `asyncio.to_thread` patched to record call order with timestamps
- WHEN 5 concurrent `_save_credentials_to_sqlite()` calls are issued via `asyncio.gather()`
- THEN no two save callables overlap in execution (the `_save_lock` serializes them)
- AND the final state is one of the 5 valid states, not a corrupt merge.

### Requirement: All callers of newly-async save methods must await them

All callers of the newly-async save methods MUST `await` them. All call sites in `auth.py` that call `_save_credentials_to_file` or `_save_credentials_to_sqlite` MUST be in async context and use `await`.

#### Scenario: All save call sites in auth.py use await

- GIVEN a search over `kiro/auth.py`
- WHEN the call sites of `_save_credentials_to_file` and `_save_credentials_to_sqlite` are inspected
- THEN every call site is in an async context
- AND every call site is prefixed with `await`.

### Requirement: Event loop unblocked during save operations

The event loop MUST NOT block for more than 1 ms during any save operation. A concurrent coroutine (e.g. a no-op async heartbeat task) MUST remain schedulable while a save is in progress.

#### Scenario: Heartbeat task advances during a save

- GIVEN a background task that appends a timestamp every `asyncio.sleep(0)` iteration
- WHEN a `_save_state()` call is triggered whose body takes at least 20 ms (e.g. `asyncio.to_thread` with a real `time.sleep(0.02)` inside)
- THEN the background task is scheduled at least once during the save (it appended a timestamp), proving the event loop was not blocked.

### Requirement: SQLITE_READONLY flag short-circuits writes

The `SQLITE_READONLY` environment flag behavior in `_save_credentials_to_sqlite` MUST be preserved: when set, the method returns immediately without entering the thread.

#### Scenario: SQLITE_READONLY=true skips the write

- GIVEN `SQLITE_READONLY=true` set in the environment
- WHEN `await auth._save_credentials_to_sqlite()` is called
- THEN `asyncio.to_thread` is NOT called (no write attempted)
- AND the database is unchanged.

## Test scenarios

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

## Acceptance criteria

- AC-2.A: All T-2.x tests pass.
- AC-2.B: `_save_state`, `_save_credentials_to_file`, `_save_credentials_to_sqlite` are all `async def` and delegate blocking work to `asyncio.to_thread`.
- AC-2.C: `_load_credentials_from_sqlite` remains `def` (synchronous).
- AC-2.D: `rg 'sqlite3\.connect|open\(' kiro/account_manager.py kiro/auth.py` shows no blocking I/O calls in async functions outside of `asyncio.to_thread` wrappers.
- AC-2.E: Full pytest suite passes.
