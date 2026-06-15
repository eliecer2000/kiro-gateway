# Spec: shared-http-client

- **Capability:** shared-http-client
- **PR:** #1 — Shared streaming client + auth singleton
- **Change:** perf-async-improvements
- **Status:** spec_complete
- **Risk:** Low

## Purpose

Reuse the existing `request.app.state.http_client` for streaming code paths (OpenAI and Anthropic) and add a dedicated long-lived `httpx.AsyncClient` for token refresh, so that no streaming request or token refresh constructs a new `httpx.AsyncClient` on the hot path. Connection reuse is restored, TCP/TLS handshakes are avoided per request, and lifecycle is owned by the FastAPI lifespan. External API contract is unchanged.

## Context

- `kiro/routes_openai.py:351` and `kiro/routes_anthropic.py:603` currently create `KiroHttpClient(auth_manager, shared_client=None)` for streaming requests, discarding TCP/TLS connection reuse.
- Non-streaming branches already pass `shared_client=request.app.state.http_client`.
- `kiro/auth.py:708` and `kiro/auth.py:825` each open `async with httpx.AsyncClient(...)` per token-refresh call, constructing and destroying a client on every refresh.
- `kiro/http_client.py:229` sets `Connection: close` on streaming requests to prevent CLOSE_WAIT socket leaks (issue #38). This behavior MUST be preserved.

## Requirements

### Requirement: Streaming OpenAI requests reuse the shared client

The streaming branch in `routes_openai.py` MUST pass `shared_client=request.app.state.http_client` to `KiroHttpClient`, matching the non-streaming branch.

#### Scenario: Streaming OpenAI request reuses shared client

- GIVEN a FastAPI app with `app.state.http_client` configured
- WHEN a streaming OpenAI chat completion request is processed
- THEN `KiroHttpClient.__init__` receives the same object reference as `app.state.http_client`
- AND no new `httpx.AsyncClient()` is constructed during the request

### Requirement: Streaming Anthropic requests reuse the shared client

The streaming branch in `routes_anthropic.py` MUST pass `shared_client=request.app.state.http_client` to `KiroHttpClient`, matching the non-streaming branch.

#### Scenario: Streaming Anthropic request reuses shared client

- GIVEN a FastAPI app with `app.state.http_client` configured
- WHEN a streaming Anthropic messages request is processed
- THEN `KiroHttpClient.__init__` receives the same object reference as `app.state.http_client`
- AND no new `httpx.AsyncClient()` is constructed during the request

### Requirement: Module-level singleton auth client for token refresh

A module-level singleton `httpx.AsyncClient` MUST be created at application startup and registered on `app.state` (e.g. `app.state.auth_http_client`). Token-refresh code in `auth.py` (both `_refresh_kiro_desktop_token` and `_refresh_aws_sso_oidc_token`) MUST use this singleton instead of constructing a new client per call.

#### Scenario: Token refresh uses the singleton auth client

- GIVEN `app.state.auth_http_client` is configured with a mock transport
- WHEN `force_refresh()` is triggered
- THEN the singleton client's `post` method is called
- AND no new `httpx.AsyncClient()` is constructed inside the refresh path

### Requirement: Auth client lifecycle tied to app lifespan

The singleton auth client MUST be closed at application shutdown (lifespan or shutdown event). No use-after-close MUST occur.

#### Scenario: Auth singleton created at startup and closed at shutdown

- GIVEN a FastAPI app started via `httpx.AsyncClient(app=app, base_url=...)`
- WHEN startup completes
- THEN `app.state.auth_http_client` is not None
- WHEN shutdown completes
- THEN `app.state.auth_http_client.is_closed == True`
- AND no request handler holds a reference to the closed client

### Requirement: Connection: close header preserved on streaming

Streaming requests MUST continue to send `Connection: close` in the request headers (the existing line at `http_client.py:229` MUST be preserved and covered by a regression test).

#### Scenario: Connection: close header present on streaming request

- GIVEN a mock transport that captures outgoing request headers
- WHEN `http_client.request_with_retry(..., stream=True)` is called
- THEN the captured request headers contain `Connection: close`

### Requirement: No AsyncClient construction in hot path

No `httpx.AsyncClient` constructor call MAY remain inside the hot path of a streaming request or a token-refresh call after this PR.

#### Scenario: Static gate — no AsyncClient constructor in hot path

- GIVEN a search over `kiro/auth.py`, `kiro/routes_openai.py`, `kiro/routes_anthropic.py`
- WHEN `rg 'httpx.AsyncClient('` is run
- THEN no matches are returned inside hot-path request handlers
- AND only module-level or startup wiring is permitted

### Requirement: Graceful fallback when shared client is unavailable

The fallback behavior when `app.state.http_client` is `None` (e.g. in unit tests that do not configure the app) MUST not raise an `AttributeError`; it MUST fall back to a locally-scoped client with a warning log.

#### Scenario: Missing app.state.http_client falls back with warning

- GIVEN a request handler where `app.state.http_client` is `None`
- WHEN the streaming client is resolved
- THEN no `AttributeError` is raised
- AND a warning is logged
- AND a locally-scoped client is used for the request

## Test scenarios

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

## Acceptance criteria

- AC-1.A: All T-1.x tests pass.
- AC-1.B: `rg 'httpx.AsyncClient(' kiro/auth.py kiro/routes_openai.py kiro/routes_anthropic.py` returns no matches inside hot-path request handlers (only module-level or startup wiring is permitted).
- AC-1.C: Full pytest suite (1673 baseline + new tests) passes.
- AC-1.D: No `CLOSE_WAIT` socket leak observed under T-1.6 scenario.
