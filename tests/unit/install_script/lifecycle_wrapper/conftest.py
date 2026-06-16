# -*- coding: utf-8 -*-

"""
Shared fixtures for the lifecycle-wrapper unit tests.

The conftest provides:
- `installed_env`: writes a fully-laid-out install dir at INSTALL_DIR so the
  wrapper finds install.env, the bin/kiro-gateway script, the app/ tree,
  the state files, and the plist/unit path. Tests that drive the wrapper
  point the wrapper at this fake root.
- `mock_health_server`: starts a tiny HTTP server on a free port that
  returns a configurable response on /health (200 healthy, 500 unhealthy,
  or refused/no response). Tests use the server's URL in the wrapper's
  HEALTH_URL env var so the probe can be controlled end-to-end.
"""

from __future__ import annotations

import os
import hashlib
import shutil
import socket
import textwrap
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
WRAPPER_PATH = SCRIPTS_DIR / "kiro-gateway"
INSTALL_COMMON_SH = SCRIPTS_DIR / "lib" / "install-common.sh"


@pytest.fixture
def installed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Lay out a fake install root so the wrapper can resolve INSTALL_DIR,
    find install.env, and source the shared lib. Returns the install root
    Path.

    The fixture also writes scripts/kiro-gateway into the install root
    (${INSTALL_DIR}/bin/kiro-gateway) — but the wrapper under test is the
    real one at REPO_ROOT/scripts/kiro-gateway, so the fixture also sets
    KIRO_GATEWAY_WRAPPER env to point the test at the real script.
    """
    install_dir = tmp_path / "install-root"
    install_dir.mkdir(parents=True, exist_ok=True)

    (install_dir / "bin").mkdir(parents=True, exist_ok=True)
    (install_dir / "state").mkdir(parents=True, exist_ok=True)
    (install_dir / "logs").mkdir(parents=True, exist_ok=True)
    (install_dir / "app").mkdir(parents=True, exist_ok=True)
    (install_dir / "app.prev").mkdir(parents=True, exist_ok=True)
    (install_dir / "venv" / "bin").mkdir(parents=True, exist_ok=True)

    # install.env — the wrapper reads this to discover INSTALL_DIR and PLATFORM.
    platform = os.environ.get("UNAME_S", "Darwin")
    (install_dir / "state" / "install.env").write_text(
        textwrap.dedent(
            f"""\
            INSTALL_DIR={install_dir}
            VERSION=2.5.0
            PLATFORM={platform}
            INSTALLED_AT=2026-06-15T00:00:00Z
            """
        )
    )
    # Touch the credential and state files so lay_out_state assertions hold.
    (install_dir / "state" / "credentials.json").write_text("{}")
    (install_dir / "state" / "state.json").write_text("{}")

    # A fake app/ sentinel so update/rollback can assert file changes.
    for app_dir, version in (
        (install_dir / "app", "2.5.0"),
        (install_dir / "app.prev", "2.4.0"),
    ):
        (app_dir / "VERSION").write_text(f"{version}\n")
        (app_dir / "requirements.txt").write_text("fastapi\nuvicorn\n")
        shutil.copytree(SCRIPTS_DIR, app_dir / "scripts")

    requirements = b"fastapi\nuvicorn\n"
    (install_dir / "state" / "requirements.sha256").write_text(
        hashlib.sha256(requirements).hexdigest() + "\n"
    )
    pip = install_dir / "venv" / "bin" / "pip"
    pip.write_text("#!/usr/bin/env bash\nexit 0\n")
    pip.chmod(0o755)

    # Place the wrapper script at ${INSTALL_DIR}/bin/kiro-gateway so
    # symlink resolution works. We COPY (not symlink) the real wrapper
    # into the install dir so that real_path("$0") resolves to the
    # install dir's bin/ — which is what production does (the canonical
    # path is the install dir's bin/kiro-gateway, regardless of how
    # the wrapper was invoked).
    wrapper_shim = install_dir / "bin" / "kiro-gateway"
    real_wrapper = WRAPPER_PATH
    if real_wrapper.exists():
        wrapper_shim.write_text(real_wrapper.read_text())
        wrapper_shim.chmod(0o755)
    else:
        wrapper_shim.write_text("#!/usr/bin/env bash\necho shim\n")
        wrapper_shim.chmod(0o755)

    # Also place the shared lib so the wrapper can source it.
    install_lib = install_dir / "lib" / "install-common.sh"
    if not install_lib.parent.exists():
        install_lib.parent.mkdir(parents=True, exist_ok=True)
    if INSTALL_COMMON_SH.exists() and not install_lib.exists():
        install_lib.write_text(INSTALL_COMMON_SH.read_text())

    monkeypatch.setenv("KIRO_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    return install_dir


def _free_port() -> int:
    """Find a free TCP port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _HealthHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler that returns a configurable status for /health."""

    # Class-level configurable. Tests set these via the fixture's setter.
    status_code = 200
    body = b'{"status":"healthy"}'

    def log_message(self, format, *args):  # noqa: A002
        # Silence stderr noise during tests.
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(self.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.body)))
            self.end_headers()
            self.wfile.write(self.body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def mock_health_server(monkeypatch: pytest.MonkeyPatch):
    """
    Start an HTTP server on a free port. Tests can:
      - server.set_status(200) / 500
      - server.url  -> the full URL the wrapper should probe
      - server.set_unreachable()  -> stop the server before the probe runs
    """
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class _Server:
        def __init__(self, port_, server_, thread_):
            self.url = f"http://127.0.0.1:{port_}/health"
            self.port = port_
            self._server = server_
            self._thread = thread_

        def set_status(self, code, body=b'{"status":"x"}'):
            _HealthHandler.status_code = code
            _HealthHandler.body = body

        def set_unreachable(self):
            # Stop the server so curl fails to connect.
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)

    # Default: 200 healthy.
    _HealthHandler.status_code = 200
    _HealthHandler.body = b'{"status":"healthy"}'

    yield _Server(port, server, thread)

    # Teardown — make sure the server is stopped even if test forgot.
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    thread.join(timeout=2)


# stub_curl_health removed; tests use mock_health_server (real HTTP) instead.
