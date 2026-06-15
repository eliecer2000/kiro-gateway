# -*- coding: utf-8 -*-

"""
Tests for the snapshot cleanup on healthy start (T-3.11 + T-3.12).

T-3.11: After a successful update with /health returning 200 within 10s,
        the wrapper removes app.prev/ and prints "Update successful. Old version removed."
T-3.12: After a failed update where /health never returns 2xx, the wrapper
        preserves app.prev/ and prints a hint to run `update --rollback`.
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def _build_tarball(root: str, members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, content in members.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def _setup_update_stubs(tmp_path, monkeypatch, new_version, sums_filename_suffix="", health_url=None, health_should_fail=False):
    """Common helper: place tarball, sums, curl/sha256sum/systemctl stubs."""
    tarball = _build_tarball(
        f"kiro-gateway-{new_version}",
        {
            f"kiro-gateway-{new_version}/main.py": f"print('{new_version}')\n",
            f"kiro-gateway-{new_version}/requirements.txt": "fastapi\n",
            f"kiro-gateway-{new_version}/LICENSE": "MIT\n",
        },
    )
    sha = hashlib.sha256(tarball).hexdigest()

    tarball_path = tmp_path / "kiro-gateway.tar.gz"
    tarball_path.write_bytes(tarball)
    sums = f"{sha}  v{new_version}{sums_filename_suffix}.tar.gz\n"
    sums_path = tmp_path / "SHA256SUMS"
    sums_path.write_text(sums)

    curl_log = tmp_path / "curl.log"
    # If the test wants the health URL to be unreachable, the stub emits
    # '000' for any URL matching the health host/port.
    health_fail_pattern = "127.0.0.1:1" if health_should_fail else "__none__"
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
        # Health probe: emit 000 (connect failure) for the configured
        # unreachable host/port; 200 for everything else.
        if [[ "$URL" == *"{health_fail_pattern}"* ]]; then
          if [[ "$WRITE_OUT" == "1" ]]; then
            printf '000'
          fi
          exit 7
        fi
        if [[ "$WRITE_OUT" == "1" ]]; then
          printf '200'
        fi
        exit 0
        """,
    )
    _write_stub(
        tmp_path,
        "sha256sum",
        """\
        #!/usr/bin/env bash
        shasum -a 256 "$@"
        """,
    )
    _write_stub(
        tmp_path,
        "systemctl",
        """\
        #!/usr/bin/env bash
        if [[ "$1" == "--user" ]] && [[ "$2" == "show-environment" ]]; then
          echo "PATH=/usr/bin"
          exit 0
        fi
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Linux")
    if health_url:
        monkeypatch.setenv("HEALTH_URL", health_url)


def test_snapshot_removed_on_healthy_start(tmp_path, monkeypatch, installed_env, mock_health_server):
    """
    GIVEN /health returns 200 within 10s of the update
    WHEN `kiro-gateway update` completes
    THEN app.prev/ is removed and the success message is printed.
    """
    _setup_update_stubs(tmp_path, monkeypatch, "2.7.0", health_url=mock_health_server.url)
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    out = subprocess.run(
        ["bash", str(WRAPPER), "update"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, (
        f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    combined = out.stdout + out.stderr
    assert "Update successful" in combined, f"expected 'Update successful' in output; got: {combined!r}"
    assert not (installed_env / "app.prev").exists(), "app.prev/ should be removed on healthy start"


def test_snapshot_preserved_on_unhealthy_start(tmp_path, monkeypatch, installed_env):
    """
    GIVEN /health never returns 2xx within 10s
    WHEN `kiro-gateway update` completes
    THEN app.prev/ is preserved and the hint is printed.
    """
    # Use an unreachable URL so the health probe always fails.
    _setup_update_stubs(
        tmp_path, monkeypatch, "2.7.0",
        health_url="http://127.0.0.1:1/health",  # port 1 is always closed
        health_should_fail=True,
    )
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    out = subprocess.run(
        ["bash", str(WRAPPER), "update"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Exit 1 because the health probe never succeeded.
    assert out.returncode == 1, (
        f"expected exit 1, got {out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    combined = out.stdout + out.stderr
    assert "app.prev/" in combined or "preserved" in combined, (
        f"expected 'preserved' hint in output; got: {combined!r}"
    )
    # The previous snapshot is still there.
    assert (installed_env / "app.prev").exists(), "app.prev/ should be preserved on unhealthy start"
