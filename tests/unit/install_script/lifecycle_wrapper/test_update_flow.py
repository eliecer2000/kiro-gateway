# -*- coding: utf-8 -*-

"""
Tests for the `update` flow (T-3.9).

The wrapper must:
- snapshot app/ to app.prev/
- fetch the new tarball, verify SHA256, extract atomically into app/
- reload the service
- health-poll up to 10s; on healthy -> remove app.prev/ and print success

This test stubs curl, sha256sum, and the service manager so the full
update flow is exercisable end-to-end.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import socket
import subprocess
import tarfile
import textwrap
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _build_tarball(root: str, members: dict) -> bytes:
    """Build a tarball with the given root dir and members."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, content in members.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _HealthHandler(BaseHTTPRequestHandler):
    status_code = 200

    def log_message(self, *a, **k): pass
    def do_GET(self):
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"healthy"}')


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def test_wrapper_update_fetches_and_swaps(tmp_path, monkeypatch, installed_env):
    """
    GIVEN an installed kiro-gateway v2.5.0 with app.prev/ = v2.4.0
    WHEN `kiro-gateway update` is invoked
    THEN the wrapper fetches a new tarball, swaps app/ with the new content,
    AND version is bumped to v2.6.0.
    """
    new_version = "2.6.0"
    # Build a fake tarball for v2.6.0.
    tarball = _build_tarball(
        f"kiro-gateway-{new_version}",
        {
            f"kiro-gateway-{new_version}/main.py": "print('v2.6.0')\n",
            f"kiro-gateway-{new_version}/VERSION": f"{new_version}\n",
            f"kiro-gateway-{new_version}/requirements.txt": "fastapi\nuvicorn\n",
            f"kiro-gateway-{new_version}/LICENSE": "MIT\n",
            f"kiro-gateway-{new_version}/scripts/kiro-gateway": (
                REPO_ROOT / "scripts" / "kiro-gateway"
            ).read_text(),
            f"kiro-gateway-{new_version}/scripts/lib/install-common.sh": (
                REPO_ROOT / "scripts" / "lib" / "install-common.sh"
            ).read_text(),
            f"kiro-gateway-{new_version}/scripts/system/kiro-gateway.service": (
                REPO_ROOT / "scripts" / "system" / "kiro-gateway.service"
            ).read_text(),
            f"kiro-gateway-{new_version}/scripts/system/kiro-gateway.plist": (
                REPO_ROOT / "scripts" / "system" / "kiro-gateway.plist"
            ).read_text(),
        },
    )
    sha = hashlib.sha256(tarball).hexdigest()

    # Place the tarball somewhere curl can serve it.
    tarball_path = tmp_path / "kiro-gateway.tar.gz"
    tarball_path.write_bytes(tarball)

    # Place a SHA256SUMS file that the wrapper will fetch. The wrapper
    sums = f"{sha}  kiro-gateway-{new_version}.tar.gz\n"
    sums_path = tmp_path / "SHA256SUMS"
    sums_path.write_text(sums)

    # Stub curl: serve the GitHub latest API, the SHA256SUMS, the tarball,
    # AND the local health probe.
    curl_log = tmp_path / "curl.log"
    _write_stub(
        tmp_path,
        "curl",
        f"""\
        #!/usr/bin/env bash
        URL=""
        OUT=""
        WRITE_OUT=0
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -o) OUT="$2"; shift 2 ;;
            -w) WRITE_OUT=1; shift 2 ;;
            --proto|--tlsv1.2|--max-time) shift 2 ;;
            -sSL|-fsSL|-sS|-sI|-I|-*|-) shift ;;
            http*://*) URL="$1"; shift ;;
            *) shift ;;
          esac
        done
        echo "URL=$URL OUT=$OUT WRITE=$WRITE_OUT" >> "{curl_log}"
        if [[ "$URL" == *"/releases/latest"* ]]; then
          printf '{{"tag_name":"v{new_version}","name":"v{new_version}"}}\\n'
          exit 0
        fi
        if [[ "$URL" == *"/SHA256SUMS"* ]]; then
          cat "{sums_path}"
          exit 0
        fi
        if [[ "$URL" == *".tar.gz" ]] && [[ -n "$OUT" ]]; then
          cp "{tarball_path}" "$OUT"
          exit 0
        fi
        # Health probe and network probe: emit 200.
        if [[ "$WRITE_OUT" == "1" ]]; then
          printf '200'
        fi
        exit 0
        """,
    )

    # Stub sha256sum.
    _write_stub(
        tmp_path,
        "sha256sum",
        f"""\
        #!/usr/bin/env bash
        shasum -a 256 "$@"
        """,
    )

    # Stub systemctl.
    sc_log = tmp_path / "systemctl.log"
    _write_stub(
        tmp_path,
        "systemctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{sc_log}"
        if [[ "$1" == "--user" ]] && [[ "$2" == "show-environment" ]]; then
          echo "PATH=/usr/bin"
          exit 0
        fi
        if [[ "$1" == "--user" ]] && [[ "$2" == "is-active" ]]; then
          echo "active"
          exit 0
        fi
        exit 0
        """,
    )

    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Linux")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    # Start a real health server on a free port.
    port = _free_port()
    health_srv = HTTPServer(("127.0.0.1", port), _HealthHandler)
    threading.Thread(target=health_srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HEALTH_URL", f"http://127.0.0.1:{port}/health")

        out = subprocess.run(
            ["bash", str(WRAPPER), "update"],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert out.returncode == 0, (
            f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}\n"
            f"curl.log={curl_log.read_text() if curl_log.exists() else '(missing)'}\n"
            f"systemctl.log={sc_log.read_text() if sc_log.exists() else '(missing)'}"
        )
    finally:
        health_srv.shutdown()
        health_srv.server_close()

    # The version in install.env was bumped to 2.6.0.
    install_env = (installed_env / "state" / "install.env").read_text()
    assert "VERSION=2.6.0" in install_env, f"install.env:\n{install_env}"

    # app/ now has the new main.py content.
    new_main = (installed_env / "app" / "main.py").read_text()
    assert "v2.6.0" in new_main, f"app/main.py:\n{new_main}"

    # app.prev/ was removed after the healthy start.
    assert not (installed_env / "app.prev").exists(), "app.prev/ should be removed after healthy update"
    assert (installed_env / "bin" / "kiro-gateway").read_text() == (
        installed_env / "app" / "scripts" / "kiro-gateway"
    ).read_text()
    service_calls = sc_log.read_text()
    assert "daemon-reload" in service_calls
    assert "start kiro-gateway" in service_calls
