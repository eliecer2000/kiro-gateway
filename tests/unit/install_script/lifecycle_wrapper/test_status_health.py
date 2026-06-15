# -*- coding: utf-8 -*-

"""
Tests for the `status` subcommand health probe (T-3.3).

The wrapper must:
- exit 0 with `running (healthy)` when /health returns 2xx and service is up.
- exit 1 with `running (unhealthy)` when service is up but /health returns 5xx.
- exit 1 with `stopped` (or equivalent) when the service is not running.

A real HTTP server fixture (`mock_health_server`) is used so the
probe path is end-to-end: a fresh `curl` invocation against a
loopback URL on a free port.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def _stub_launchctl_active(tmp_path: Path, log: Path) -> Path:
    """A launchctl stub that reports a real PID for the gateway (i.e. active)."""
    return _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        if [[ "$1" == "list" ]]; then
          printf '%s\n' "PID\tStatus\tLabel"
          printf '%s\n' "1234\t0\tcom.jwadow.kiro-gateway"
          exit 0
        fi
        exit 0
        """,
    )


def _stub_systemctl_active(tmp_path: Path, log: Path) -> Path:
    """A systemctl stub that reports the gateway as active."""
    return _write_stub(
        tmp_path,
        "systemctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        if [[ "$1" == "--user" ]] && [[ "$2" == "is-active" ]]; then
          echo "active"
          exit 0
        fi
        exit 0
        """,
    )


def _run_wrapper(monkeypatch, args):
    """Run the wrapper with the current monkeypatched env."""
    import subprocess
    # Merge monkeypatched env onto os.environ.
    env = dict(os.environ)
    # pytest's monkeypatch uses the standard setenv/delete; os.environ is
    # already updated for the test process. The monkeypatched env is what
    # `os.environ` reflects at this point. Pass a copy explicitly.
    return subprocess.run(
        ["bash", str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_wrapper_status_healthy_exits_zero(tmp_path, monkeypatch, installed_env, mock_health_server):
    """
    GIVEN the service is active and /health returns 200
    WHEN `kiro-gateway status` is invoked
    THEN exit 0 and `running (healthy)` is printed.
    """
    log = tmp_path / "svc.log"
    _stub_launchctl_active(tmp_path, log)
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))
    monkeypatch.setenv("HEALTH_URL", mock_health_server.url)

    out = _run_wrapper(monkeypatch, ["status"])
    assert out.returncode == 0, f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    assert "running (healthy)" in (out.stdout + out.stderr)


def test_wrapper_status_unhealthy_exits_one(tmp_path, monkeypatch, installed_env, mock_health_server):
    """
    GIVEN the service is active but /health returns 500
    WHEN `kiro-gateway status` is invoked
    THEN exit 1 and `running (unhealthy)` is printed.
    """
    mock_health_server.set_status(500, b'{"status":"oops"}')
    log = tmp_path / "svc.log"
    _stub_launchctl_active(tmp_path, log)
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))
    monkeypatch.setenv("HEALTH_URL", mock_health_server.url)

    out = _run_wrapper(monkeypatch, ["status"])
    assert out.returncode == 1, f"expected exit 1, got {out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    combined = out.stdout + out.stderr
    assert "running (unhealthy)" in combined or "unhealthy" in combined, (
        f"expected 'unhealthy' in output; got: {combined!r}"
    )


def test_wrapper_status_stopped_exits_one(tmp_path, monkeypatch, installed_env, mock_health_server):
    """
    GIVEN the service is NOT running
    WHEN `kiro-gateway status` is invoked
    THEN exit 1 and `stopped` (or equivalent) is printed.
    """
    # Stub launchctl that returns NO row for the gateway (so it's not loaded).
    log = tmp_path / "svc.log"
    _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        if [[ "$1" == "list" ]]; then
          printf '%s\n' "PID\tStatus\tLabel"
          # No row for com.jwadow.kiro-gateway.
          exit 0
        fi
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))
    monkeypatch.setenv("HEALTH_URL", mock_health_server.url)

    out = _run_wrapper(monkeypatch, ["status"])
    assert out.returncode == 1, f"expected exit 1, got {out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    combined = (out.stdout + out.stderr).lower()
    assert "stopped" in combined or "inactive" in combined or "not running" in combined, (
        f"expected stopped/inactive in output; got: {combined!r}"
    )
